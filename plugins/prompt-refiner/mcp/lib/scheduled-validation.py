#!/usr/bin/env python3
"""
scheduled-validation.py — F4.3 in the deep-research foundations roadmap.

Runs a single canary `/deep-research <slug> --depth quick` dispatch, parses
the produced `claims.json`, checks against the canary's documented baselines
(τ, sources_count, wall-clock, verdict), and writes:

  - a one-line status to `shared/state/scheduled-validation.log`
  - on drift detected, a fuller report to
    `state/roadmaps/scheduled-validation-drift-YYYY-MM-DD.md`

This script is the *scaffold*. It does NOT install itself as a cron/systemd
job — that wiring is intentionally left to the operator, so the rollout
decision is a human one. See `state/roadmaps/bg23-scheduled-validation-report.md`
§ "Operator wiring" for the cron/systemd templates.

Cost envelope (honest numbers, per run):
  --depth quick → ~6 Haiku fetcher calls + 1 Sonnet triangulator + 1 Haiku verifier
  ≈ $1-3 per run via the dispatch-via-cli shim
  Full depth would be ~$5-15; this script will refuse anything other than `quick`.

Authorship: Enchanter Labs.

Usage:
    python scheduled-validation.py                 # pick next canary, run it
    python scheduled-validation.py --canary <slug> # run a specific canary
    python scheduled-validation.py --dry-run       # show next canary, do not dispatch
    python scheduled-validation.py --probe-only    # capability probe (no dispatch)

Tool-scope requirement: the invoking environment must have `Bash(claude:*)`
on its allowlist so `dispatch-via-cli.py` can spawn the `/deep-research`
sub-worker. See `dispatch-via-cli.py` § "Tool-scope requirement".
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time
from typing import Any

# ---------------------------------------------------------------------------
# Path constants. Anchor everything to the repo root via this script's
# location so the routine works under any worktree.
# ---------------------------------------------------------------------------
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent          # shared/scripts
SHARED_DIR = SCRIPT_DIR.parent                                 # shared
REPO_ROOT = SHARED_DIR.parent                                  # wixie/

CANARY_CONFIG = SHARED_DIR / "scheduled-validation-canaries.json"
INDEX_FILE = SHARED_DIR / "state" / "scheduled-validation-index.txt"
LOG_FILE = SHARED_DIR / "state" / "scheduled-validation.log"
DRIFT_REPORT_DIR = REPO_ROOT / "state" / "roadmaps"
BRIEFS_DIR = REPO_ROOT / "state" / "briefs"

# Quick-depth wall-clock floor (ms). The full-depth floor is 15 min; quick
# can legitimately finish in 1-3 min. Under 1 min strongly suggests a phase
# short-circuited (fetchers returned errored without retrying, etc).
QUICK_DEPTH_WALL_CLOCK_FLOOR_MS = 60_000

# Drift tolerances. Documented in the canary config too; redeclared here so
# the script's drift logic is self-contained for auditability.
TAU_DRIFT_TOLERANCE = 0.15  # absolute drift from baseline_tau

# Sub-worker dispatch budget. /deep-research --depth quick should finish in
# a few minutes; we give it 25 min headroom because dispatch-via-cli is
# subject to rate-limit retries.
SUBWORKER_TIMEOUT_S = 25 * 60

# Resolve the dispatch shim. It lives next to this script.
sys.path.insert(0, str(SCRIPT_DIR))
try:
    # The shim's filename contains hyphens, so use importlib for safety.
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "dispatch_via_cli",
        SCRIPT_DIR / "dispatch-via-cli.py",
    )
    if _spec is None or _spec.loader is None:
        raise ImportError("dispatch-via-cli.py spec resolution failed")
    _dispatch_mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_dispatch_mod)
    dispatch_one = _dispatch_mod.dispatch_one
    _capability_probe = _dispatch_mod._capability_probe
except Exception as _exc:  # noqa: BLE001 — surface the real cause honestly
    print(
        json.dumps(
            {
                "status": "blocked",
                "cause": f"dispatch-via-cli.py import failed: {_exc!r}",
            },
            indent=2,
        ),
        file=sys.stderr,
    )
    # Allow --probe-only / --dry-run to still report the blockage clearly.
    dispatch_one = None
    _capability_probe = None


# ---------------------------------------------------------------------------
# Canary list + rotation
# ---------------------------------------------------------------------------
def load_canaries() -> list[dict[str, Any]]:
    """Load and minimally validate the canary config."""
    if not CANARY_CONFIG.is_file():
        raise FileNotFoundError(f"canary config missing: {CANARY_CONFIG}")
    blob = json.loads(CANARY_CONFIG.read_text(encoding="utf-8"))
    canaries = blob.get("canaries", [])
    if not canaries:
        raise ValueError(f"canary config has no canaries: {CANARY_CONFIG}")
    required = {"slug", "topic", "baseline_tau", "baseline_sources_count_min",
                "baseline_claims_min", "expected_verdict"}
    for c in canaries:
        missing = required - set(c)
        if missing:
            raise ValueError(f"canary {c.get('slug', '?')} missing fields: {missing}")
    return canaries


def next_canary_index(num_canaries: int) -> int:
    """Round-robin: read INDEX_FILE, return that value mod num_canaries.
    Caller increments + persists *after* the dispatch attempt so a crash
    mid-run doesn't skip a canary."""
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not INDEX_FILE.is_file():
        return 0
    try:
        return int(INDEX_FILE.read_text(encoding="utf-8").strip()) % num_canaries
    except (ValueError, OSError):
        # Corrupt index — restart from 0 rather than crash. Log it.
        return 0


def advance_index(current: int, num_canaries: int) -> None:
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(str((current + 1) % num_canaries), encoding="utf-8")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def build_subworker_prompt(canary: dict[str, Any]) -> str:
    """The sub-worker is asked to invoke `/deep-research` at quick depth.

    Honest-numbers caveat: the sub-worker is a *fresh* Claude session via
    `claude -p`, so it has no knowledge of why it's being asked. The prompt
    has to be self-contained and explicit about depth.
    """
    return (
        f"Run the /deep-research skill on the topic below at --depth quick.\n"
        f"\n"
        f"Topic: {canary['topic']}\n"
        f"\n"
        f"Use slug: {canary['slug']}\n"
        f"\n"
        f"Constraints (do not negotiate):\n"
        f"- --depth quick (NOT full). This is a scheduled validation run; "
        f"full depth is reserved for principal-initiated work.\n"
        f"- Persist artifacts to state/briefs/{canary['slug']}/ as the skill "
        f"normally would (claims.json, sources.jsonl, trace.json).\n"
        f"- On completion, print a one-line summary: "
        f"`VALIDATION_DONE slug=<slug> verdict=<verdict> tau=<float> "
        f"sources=<int> claims=<int> wall_ms=<int>`\n"
        f"- If you cannot run /deep-research (skill missing, capability gap, "
        f"etc.), print `VALIDATION_BLOCKED cause=<short>` and exit. Do not "
        f"silently degrade.\n"
    )


def dispatch_canary(canary: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a sub-worker to run /deep-research at quick depth."""
    if dispatch_one is None:
        return {
            "status": "blocked",
            "cause": "dispatch-via-cli.py not importable (see startup error)",
        }
    prompt = build_subworker_prompt(canary)
    # The sub-worker needs WebSearch + WebFetch + Read + Write + Bash + Glob
    # to run the /deep-research skill end-to-end. We deliberately do NOT
    # whitelist `Agent` — quick depth doesn't need recursive dispatch, and
    # forbidding it makes the run cheaper and more deterministic.
    allowed_tools = "WebSearch,WebFetch,Read,Write,Edit,Bash,Glob,Grep"
    started = time.time()
    result = dispatch_one(
        model="opus",  # /deep-research orchestrator is Opus per CLAUDE.md
        prompt=prompt,
        allowed_tools=allowed_tools,
        timeout=SUBWORKER_TIMEOUT_S,
        max_retries=2,  # rate-limit retries only; cheaper than 3 for a long-running call
    )
    result["dispatched_at"] = dt.datetime.utcnow().isoformat() + "Z"
    result["wall_clock_ms"] = int((time.time() - started) * 1000)
    return result


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------
def parse_claims_artifact(slug: str) -> dict[str, Any]:
    """Read state/briefs/<slug>/claims.json. Return a normalised summary.

    Honest-numbers note: this script does *not* re-run the verifier. It
    only inspects the artifact the sub-worker wrote. If the sub-worker
    fabricated the artifact (extremely unlikely under quick depth), the
    drift check won't catch it — that's the verifier's job, not ours.
    """
    brief_dir = BRIEFS_DIR / slug
    claims_path = brief_dir / "claims.json"
    trace_path = brief_dir / "trace.json"
    sources_path = brief_dir / "sources.jsonl"

    summary: dict[str, Any] = {
        "claims_path_exists": claims_path.is_file(),
        "trace_path_exists": trace_path.is_file(),
        "sources_path_exists": sources_path.is_file(),
        "claims_count": 0,
        "sources_count": 0,
        "verdict": None,
        "tau": None,
        "verify_passed": None,
        "parse_errors": [],
    }

    if not claims_path.is_file():
        summary["parse_errors"].append(f"claims.json missing at {claims_path}")
        return summary

    # claims.json may be JSONL or a single JSON document depending on schema
    # version (the deep-research skill writes JSONL for the claim list).
    # Tolerate both — count claims either way.
    try:
        raw = claims_path.read_text(encoding="utf-8").strip()
        if not raw:
            summary["parse_errors"].append("claims.json empty")
        elif raw.startswith("["):
            arr = json.loads(raw)
            summary["claims_count"] = len(arr) if isinstance(arr, list) else 0
        else:
            # JSONL
            lines = [ln for ln in raw.splitlines() if ln.strip()]
            valid_lines = 0
            for ln in lines:
                try:
                    json.loads(ln)
                    valid_lines += 1
                except json.JSONDecodeError:
                    summary["parse_errors"].append(
                        f"claims.json line parse error: {ln[:80]!r}"
                    )
            summary["claims_count"] = valid_lines
    except (OSError, json.JSONDecodeError) as exc:
        summary["parse_errors"].append(f"claims.json read failure: {exc}")

    if sources_path.is_file():
        try:
            raw = sources_path.read_text(encoding="utf-8").strip()
            if raw:
                lines = [ln for ln in raw.splitlines() if ln.strip()]
                # Count parseable lines only
                count = 0
                for ln in lines:
                    try:
                        json.loads(ln)
                        count += 1
                    except json.JSONDecodeError:
                        pass
                summary["sources_count"] = count
        except OSError as exc:
            summary["parse_errors"].append(f"sources.jsonl read failure: {exc}")

    if trace_path.is_file():
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            summary["verdict"] = trace.get("verdict") or trace.get("status")
            summary["tau"] = trace.get("tau") or trace.get("final_tau")
            summary["verify_passed"] = trace.get("verify_passed")
            # Some trace schemas nest the verdict under a key.
            if summary["verdict"] is None and "stop_conditions" in trace:
                summary["verdict"] = trace["stop_conditions"].get("verdict")
            if summary["tau"] is None:
                # Walk one level for a tau anywhere
                for k, v in trace.items():
                    if isinstance(v, dict) and "tau" in v:
                        summary["tau"] = v["tau"]
                        break
        except (OSError, json.JSONDecodeError) as exc:
            summary["parse_errors"].append(f"trace.json read failure: {exc}")

    return summary


def detect_drift(
    canary: dict[str, Any],
    dispatch_result: dict[str, Any],
    artifact_summary: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Return (drift_detected, reasons). Each reason is a single sentence."""
    reasons: list[str] = []

    if dispatch_result.get("status") != "ok":
        reasons.append(
            f"dispatch status={dispatch_result.get('status')!r}; "
            f"cause={dispatch_result.get('cause')!r}"
        )
        # If dispatch itself failed, no point in scoring the artifact —
        # but we still flag this as drift so the operator notices.
        return True, reasons

    # Wall-clock floor: dispatch's reported wall_clock_ms is the outer
    # measurement. If the sub-worker returned in under one minute, a phase
    # short-circuited (no real fetching happened).
    wall_ms = dispatch_result.get("wall_clock_ms", 0)
    if wall_ms < QUICK_DEPTH_WALL_CLOCK_FLOOR_MS:
        reasons.append(
            f"wall_clock_ms={wall_ms} below quick-depth floor "
            f"({QUICK_DEPTH_WALL_CLOCK_FLOOR_MS}) — phase likely short-circuited"
        )

    if artifact_summary["parse_errors"]:
        reasons.append(
            f"artifact parse errors: {artifact_summary['parse_errors'][:3]}"
        )

    if not artifact_summary["claims_path_exists"]:
        reasons.append("claims.json was not produced")
        return True, reasons

    verdict = artifact_summary.get("verdict")
    expected = canary["expected_verdict"]
    if verdict and verdict != expected:
        reasons.append(
            f"verdict={verdict!r} expected={expected!r}"
        )
    elif verdict is None:
        reasons.append(
            "verdict not found in trace.json (schema may have changed)"
        )

    tau = artifact_summary.get("tau")
    baseline_tau = canary["baseline_tau"]
    if tau is None:
        reasons.append("tau not found in trace.json")
    else:
        try:
            tau_f = float(tau)
            if abs(tau_f - baseline_tau) > TAU_DRIFT_TOLERANCE:
                reasons.append(
                    f"tau={tau_f:.3f} drifted from baseline {baseline_tau:.3f} "
                    f"by > {TAU_DRIFT_TOLERANCE} (absolute)"
                )
        except (TypeError, ValueError):
            reasons.append(f"tau not numeric: {tau!r}")

    sources_count = artifact_summary.get("sources_count", 0)
    min_sources = canary["baseline_sources_count_min"]
    if sources_count < min_sources:
        reasons.append(
            f"sources_count={sources_count} below baseline_min={min_sources}"
        )

    claims_count = artifact_summary.get("claims_count", 0)
    min_claims = canary["baseline_claims_min"]
    if claims_count < min_claims:
        reasons.append(
            f"claims_count={claims_count} below baseline_min={min_claims}"
        )

    return bool(reasons), reasons


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def append_log(line: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def write_drift_report(
    canary: dict[str, Any],
    dispatch_result: dict[str, Any],
    artifact_summary: dict[str, Any],
    reasons: list[str],
) -> pathlib.Path:
    today = dt.date.today().isoformat()
    DRIFT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = DRIFT_REPORT_DIR / f"scheduled-validation-drift-{today}.md"
    body = (
        f"# Scheduled-Validation Drift Report — {today}\n"
        f"\n"
        f"**Canary**: `{canary['slug']}`\n"
        f"**Topic**: {canary['topic']}\n"
        f"**Sub-question shape**: {canary.get('sub_question_shape', 'unknown')}\n"
        f"**Run timestamp (UTC)**: {dispatch_result.get('dispatched_at', 'unknown')}\n"
        f"\n"
        f"## Drift reasons\n"
        f"\n"
        + "".join(f"- {r}\n" for r in reasons)
        + f"\n## Baseline vs observed\n"
        f"\n"
        f"| Metric | Baseline | Observed |\n"
        f"|---|---|---|\n"
        f"| verdict | {canary['expected_verdict']} | {artifact_summary.get('verdict')} |\n"
        f"| tau | {canary['baseline_tau']} (± {TAU_DRIFT_TOLERANCE}) | {artifact_summary.get('tau')} |\n"
        f"| sources_count | ≥ {canary['baseline_sources_count_min']} | {artifact_summary.get('sources_count')} |\n"
        f"| claims_count | ≥ {canary['baseline_claims_min']} | {artifact_summary.get('claims_count')} |\n"
        f"| wall_clock_ms | ≥ {QUICK_DEPTH_WALL_CLOCK_FLOOR_MS} | {dispatch_result.get('wall_clock_ms')} |\n"
        f"| dispatch status | ok | {dispatch_result.get('status')} |\n"
        f"\n"
        f"## Sub-worker dispatch envelope\n"
        f"\n"
        f"```json\n"
        f"{json.dumps({k: v for k, v in dispatch_result.items() if k != 'raw'}, indent=2, default=str)}\n"
        f"```\n"
        f"\n"
        f"## Artifact summary\n"
        f"\n"
        f"```json\n"
        f"{json.dumps(artifact_summary, indent=2, default=str)}\n"
        f"```\n"
        f"\n"
        f"## Operator next steps\n"
        f"\n"
        f"1. Re-run this canary manually in foreground:\n"
        f"   `python shared/scripts/scheduled-validation.py --canary {canary['slug']}`\n"
        f"2. If the regression reproduces, diff `state/briefs/{canary['slug']}/claims.json` "
        f"against the previous run (git history is the audit trail).\n"
        f"3. Identify the offending phase (Decompose / Cast / Triangulate / Synthesize / Verify) "
        f"by reading `state/briefs/{canary['slug']}/trace.json`.\n"
        f"4. Open a P1 against the offending phase. The deep-research foundations roadmap "
        f"is in `state/roadmaps/2026-05-16-deep-research-foundations-roadmap.md`.\n"
        f"\n"
        f"_Authored automatically by `shared/scripts/scheduled-validation.py` (F4.3). "
        f"Authorship: Enchanter Labs._\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli() -> int:
    ap = argparse.ArgumentParser(
        description="Run one canary /deep-research validation run (quick depth).",
    )
    ap.add_argument("--canary", help="run a specific canary slug (default: next in rotation)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show which canary would run; do not dispatch")
    ap.add_argument("--probe-only", action="store_true",
                    help="run the claude CLI capability probe and exit")
    args = ap.parse_args()

    if args.probe_only:
        if _capability_probe is None:
            print(json.dumps({"status": "blocked",
                              "cause": "dispatch-via-cli.py not importable"},
                             indent=2))
            return 2
        ok, info = _capability_probe()
        print(json.dumps({"status": "ok" if ok else "blocked", "info": info},
                         indent=2))
        return 0 if ok else 2

    try:
        canaries = load_canaries()
    except (FileNotFoundError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "cause": str(exc)}, indent=2),
              file=sys.stderr)
        return 2

    if args.canary:
        matching = [c for c in canaries if c["slug"] == args.canary]
        if not matching:
            print(json.dumps({
                "status": "blocked",
                "cause": f"no canary with slug {args.canary!r}; available: "
                         f"{[c['slug'] for c in canaries]}",
            }, indent=2), file=sys.stderr)
            return 2
        canary = matching[0]
        idx = canaries.index(canary)
    else:
        idx = next_canary_index(len(canaries))
        canary = canaries[idx]

    if args.dry_run:
        print(json.dumps({
            "status": "dry-run",
            "next_canary": canary["slug"],
            "topic": canary["topic"],
            "index": idx,
            "expected_verdict": canary["expected_verdict"],
            "baseline_tau": canary["baseline_tau"],
        }, indent=2))
        return 0

    # Real dispatch.
    dispatch_result = dispatch_canary(canary)
    artifact_summary = parse_claims_artifact(canary["slug"])
    drift, reasons = detect_drift(canary, dispatch_result, artifact_summary)

    # One-line log entry — operator-readable, grep-friendly.
    ts = dt.datetime.utcnow().isoformat() + "Z"
    log_line = (
        f"{ts} canary={canary['slug']} "
        f"dispatch={dispatch_result.get('status', 'unknown')} "
        f"verdict={artifact_summary.get('verdict')} "
        f"tau={artifact_summary.get('tau')} "
        f"sources={artifact_summary.get('sources_count')} "
        f"claims={artifact_summary.get('claims_count')} "
        f"wall_ms={dispatch_result.get('wall_clock_ms')} "
        f"drift={'true' if drift else 'false'}"
    )
    append_log(log_line)

    drift_report_path: pathlib.Path | None = None
    if drift:
        drift_report_path = write_drift_report(
            canary, dispatch_result, artifact_summary, reasons
        )

    # Advance the round-robin index only on a non-blocked dispatch attempt.
    # On blocked (e.g. CLI not on PATH), we want the *next* invocation to
    # retry the same canary rather than skip it.
    if dispatch_result.get("status") != "blocked":
        advance_index(idx, len(canaries))

    # stdout: a one-line summary + the JSON payload for piping into a
    # downstream alert tool.
    print(log_line)
    print(json.dumps({
        "canary": canary["slug"],
        "dispatch_status": dispatch_result.get("status"),
        "dispatch_cause": dispatch_result.get("cause"),
        "verdict": artifact_summary.get("verdict"),
        "tau": artifact_summary.get("tau"),
        "sources_count": artifact_summary.get("sources_count"),
        "claims_count": artifact_summary.get("claims_count"),
        "wall_clock_ms": dispatch_result.get("wall_clock_ms"),
        "drift_detected": drift,
        "drift_reasons": reasons,
        "drift_report": str(drift_report_path) if drift_report_path else None,
    }, indent=2))

    # Exit codes mirror dispatch-via-cli's contract:
    #   0 = ok, no drift
    #   1 = drift detected (regression — alert)
    #   2 = blocked (capability/config — fix infra)
    if dispatch_result.get("status") == "blocked":
        return 2
    if drift:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
