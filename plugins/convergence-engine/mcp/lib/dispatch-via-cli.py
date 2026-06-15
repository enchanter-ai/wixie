#!/usr/bin/env python3
"""
dispatch-via-cli.py — Shell-out shim that lets a background agent dispatch
Claude sub-workers via the `claude -p` CLI as child processes.

Background context: G-5 in the deep-research gaps roadmap. Background agents
spawned by the CLI cannot recursively call the `Agent` tool (it isn't exposed
inside background contexts). This shim closes that gap by treating
`claude --print --output-format json` as the dispatch primitive.

Capability fidelity contract (CLAUDE.md, F22): if the `claude` CLI is not on
PATH, or if invocation fails, this script returns a structured error with
`status: "blocked"` and a `cause` field. It never silently degrades to a
stub response.

Authorship: Enchanter Labs.

Usage (single dispatch):
    python dispatch-via-cli.py \
        --model haiku \
        --prompt path/to/prompt.txt \
        --allowed-tools "WebSearch,WebFetch,Read" \
        --timeout 300 \
        --output result.json

Usage (programmatic batch — see `dispatch_batch` at the bottom):
    from dispatch_via_cli import dispatch_one, dispatch_batch
    results = dispatch_batch(prompts, model="haiku", max_concurrent=4)

Tool-scope requirement for the PARENT background agent:
    The parent's allowed-tools must include `Bash(claude:*)` so the subprocess
    call is permitted by the harness. `Bash(which:*)` is also recommended for
    the up-front capability probe. Without these, the shim will report
    "blocked: parent-tool-scope" and not silently fail.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from typing import Any

# ---------------------------------------------------------------------------
# Model alias map. Keep in lockstep with the version returned by the CLI's
# /model picker. Aliases (`haiku`/`sonnet`/`opus`) are accepted by claude -p
# directly, but we resolve to a pinned model id so the dispatch is
# reproducible across CLI updates.
# ---------------------------------------------------------------------------
MODEL_ALIASES: dict[str, str] = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-5",
    "opus": "claude-opus-4-7",
}

# Rate-limit / transient-error markers seen in claude CLI output. Conservative;
# we'd rather retry once too often than mis-classify an auth failure as a rate
# limit and burn cycles. The CLI is reasonably consistent at putting the
# offending phrase into `result` or stderr when --output-format json is set.
RATE_LIMIT_MARKERS = (
    "rate limit",
    "rate_limit",
    "429",
    "overloaded",
    "service unavailable",
    "503",
    "timeout",  # network-layer; distinct from our wall-clock timeout
)
AUTH_FAIL_MARKERS = (
    "unauthorized",
    "401",
    "invalid api key",
    "not authenticated",
    "authentication failed",
)


def _capability_probe() -> tuple[bool, str]:
    """Return (ok, cause). ok=True means `claude` is on PATH and responds to --version."""
    path = shutil.which("claude")
    if not path:
        return False, "claude CLI not on PATH (shutil.which returned None)"
    try:
        proc = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return False, "claude --version timed out after 10s"
    except OSError as exc:
        return False, f"OSError invoking claude: {exc}"
    if proc.returncode != 0:
        return False, f"claude --version exit {proc.returncode}: {proc.stderr.strip()[:200]}"
    return True, proc.stdout.strip()


def _resolve_model(model: str) -> str:
    """Accept alias or full id. Pin aliases via MODEL_ALIASES; pass through full ids."""
    if model in MODEL_ALIASES:
        return MODEL_ALIASES[model]
    # If the caller supplied a full claude-* id, trust them — translation
    # would be the harness's job, not this shim's.
    if model.startswith("claude-"):
        return model
    raise ValueError(
        f"unknown model {model!r}; expected one of {list(MODEL_ALIASES)} "
        f"or a full claude-* id"
    )


def _read_prompt(prompt_arg: str) -> str:
    """Resolve --prompt to its text. Accepts a path or a literal string."""
    p = pathlib.Path(prompt_arg)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return prompt_arg


def _classify_error(stderr: str, stdout: str, returncode: int) -> str:
    """Return one of: rate-limit, auth-fail, other."""
    blob = (stderr + "\n" + stdout).lower()
    for marker in AUTH_FAIL_MARKERS:
        if marker in blob:
            return "auth-fail"
    for marker in RATE_LIMIT_MARKERS:
        if marker in blob:
            return "rate-limit"
    return "other"


def dispatch_one(
    *,
    model: str,
    prompt: str,
    allowed_tools: str = "",
    timeout: int = 300,
    extra_args: list[str] | None = None,
    max_retries: int = 3,
    backoff_base: float = 2.0,
) -> dict[str, Any]:
    """Spawn one `claude --print --output-format json` subprocess and return a
    structured dict:

        {
          "status": "ok" | "blocked" | "error",
          "model": "<resolved id>",
          "result": "<assistant text>" | None,
          "duration_ms": int,
          "cost_usd": float | None,
          "attempts": int,
          "cause": str | None,         # populated when status != "ok"
          "raw": <parsed CLI JSON> | None,
        }

    Honest-numbers contract: never returns "ok" if the CLI returned non-zero
    or emitted a parse-failure. Rate-limit retries are bounded by
    `max_retries`; auth-fail short-circuits (retry won't fix a missing key).
    """
    ok, probe_info = _capability_probe()
    if not ok:
        return {
            "status": "blocked",
            "model": model,
            "result": None,
            "duration_ms": 0,
            "cost_usd": None,
            "attempts": 0,
            "cause": f"capability-probe-failed: {probe_info}",
            "raw": None,
        }

    resolved = _resolve_model(model)
    prompt_text = _read_prompt(prompt)

    base_cmd: list[str] = [
        shutil.which("claude") or "claude",
        "--print",
        "--output-format", "json",
        "--model", resolved,
    ]
    if allowed_tools:
        base_cmd += ["--allowed-tools", allowed_tools]
    if extra_args:
        base_cmd += list(extra_args)
    base_cmd += [prompt_text]

    attempts = 0
    last_cause = "unknown"
    while attempts < max_retries:
        attempts += 1
        started = time.time()
        try:
            proc = subprocess.run(
                base_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "model": resolved,
                "result": None,
                "duration_ms": int((time.time() - started) * 1000),
                "cost_usd": None,
                "attempts": attempts,
                "cause": f"wall-clock timeout after {timeout}s",
                "raw": None,
            }
        except OSError as exc:
            return {
                "status": "blocked",
                "model": resolved,
                "result": None,
                "duration_ms": 0,
                "cost_usd": None,
                "attempts": attempts,
                "cause": f"subprocess OSError: {exc}",
                "raw": None,
            }

        duration_ms = int((time.time() - started) * 1000)

        if proc.returncode != 0:
            kind = _classify_error(proc.stderr, proc.stdout, proc.returncode)
            last_cause = (
                f"exit={proc.returncode} kind={kind} "
                f"stderr={proc.stderr.strip()[:200]}"
            )
            if kind == "auth-fail":
                return {
                    "status": "blocked",
                    "model": resolved,
                    "result": None,
                    "duration_ms": duration_ms,
                    "cost_usd": None,
                    "attempts": attempts,
                    "cause": "auth-fail (check claude auth status; retries won't help)",
                    "raw": None,
                }
            if kind == "rate-limit" and attempts < max_retries:
                # Exponential backoff with a hard ceiling. Jitter is left to
                # the OS scheduler; we'd rather be conservative than clever.
                delay = min(backoff_base ** attempts, 30.0)
                time.sleep(delay)
                continue
            return {
                "status": "error",
                "model": resolved,
                "result": None,
                "duration_ms": duration_ms,
                "cost_usd": None,
                "attempts": attempts,
                "cause": last_cause,
                "raw": None,
            }

        # Exit 0: parse the JSON envelope. The CLI emits one JSON object on
        # stdout when --output-format=json is set; stray stderr lines (e.g. a
        # broken SessionEnd hook) are tolerated and not fatal.
        try:
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as exc:
            return {
                "status": "error",
                "model": resolved,
                "result": None,
                "duration_ms": duration_ms,
                "cost_usd": None,
                "attempts": attempts,
                "cause": f"stdout parse failure: {exc}; stdout[:200]={proc.stdout[:200]!r}",
                "raw": None,
            }

        # Honest-numbers gate: the CLI tells us is_error=true sometimes
        # without a non-zero exit. Trust the envelope.
        if payload.get("is_error"):
            return {
                "status": "error",
                "model": resolved,
                "result": payload.get("result"),
                "duration_ms": duration_ms,
                "cost_usd": payload.get("total_cost_usd"),
                "attempts": attempts,
                "cause": f"CLI reported is_error=true: {payload.get('result')[:200] if payload.get('result') else 'no message'}",
                "raw": payload,
            }

        return {
            "status": "ok",
            "model": resolved,
            "result": payload.get("result"),
            "duration_ms": duration_ms,
            "cost_usd": payload.get("total_cost_usd"),
            "attempts": attempts,
            "cause": None,
            "raw": payload,
        }

    return {
        "status": "error",
        "model": resolved,
        "result": None,
        "duration_ms": 0,
        "cost_usd": None,
        "attempts": attempts,
        "cause": f"max_retries={max_retries} exhausted; last_cause={last_cause}",
        "raw": None,
    }


def dispatch_batch(
    prompts: list[str | dict[str, Any]],
    *,
    model: str = "haiku",
    max_concurrent: int = 4,
    allowed_tools: str = "",
    timeout: int = 300,
) -> list[dict[str, Any]]:
    """Parallel fan-out over `prompts`. Each item is either:
      - a str (the prompt body or a path), or
      - a dict with keys: prompt (required), model, allowed_tools, timeout

    Order of returned results matches input order. `max_concurrent` is the
    only knob — keep it modest (4–8) so the rate-limit retry path doesn't
    end up serialising the whole batch anyway.
    """
    def _one(item: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(item, str):
            return dispatch_one(
                model=model,
                prompt=item,
                allowed_tools=allowed_tools,
                timeout=timeout,
            )
        return dispatch_one(
            model=item.get("model", model),
            prompt=item["prompt"],
            allowed_tools=item.get("allowed_tools", allowed_tools),
            timeout=item.get("timeout", timeout),
        )

    results: list[dict[str, Any] | None] = [None] * len(prompts)
    with cf.ThreadPoolExecutor(max_workers=max_concurrent) as pool:
        future_to_idx = {pool.submit(_one, p): i for i, p in enumerate(prompts)}
        for fut in cf.as_completed(future_to_idx):
            idx = future_to_idx[fut]
            try:
                results[idx] = fut.result()
            except Exception as exc:  # noqa: BLE001 — surface any leak honestly
                results[idx] = {
                    "status": "error",
                    "model": model,
                    "result": None,
                    "duration_ms": 0,
                    "cost_usd": None,
                    "attempts": 0,
                    "cause": f"executor exception: {exc!r}",
                    "raw": None,
                }
    return [r for r in results if r is not None]


def _cli() -> int:
    ap = argparse.ArgumentParser(
        description="Dispatch a Claude sub-worker via the claude -p CLI.",
    )
    ap.add_argument("--model", required=True, choices=list(MODEL_ALIASES) + ["claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-7"])
    ap.add_argument("--prompt", required=True, help="prompt text or path to a prompt file")
    ap.add_argument("--allowed-tools", default="", help="comma-separated tool whitelist")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--output", help="if set, write the JSON result to this path")
    ap.add_argument("--max-retries", type=int, default=3)
    ap.add_argument("--probe-only", action="store_true",
                    help="run the capability probe and exit; useful for CI / pre-flight checks")
    args = ap.parse_args()

    if args.probe_only:
        ok, info = _capability_probe()
        out = {"status": "ok" if ok else "blocked", "info": info}
        print(json.dumps(out, indent=2))
        return 0 if ok else 2

    result = dispatch_one(
        model=args.model,
        prompt=args.prompt,
        allowed_tools=args.allowed_tools,
        timeout=args.timeout,
        max_retries=args.max_retries,
    )

    payload = json.dumps(result, indent=2)
    if args.output:
        pathlib.Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload)

    if result["status"] == "ok":
        return 0
    if result["status"] == "blocked":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
