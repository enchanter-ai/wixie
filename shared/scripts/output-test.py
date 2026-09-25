#!/usr/bin/env python3
"""Wixie Hybrid Convergence Engine — orchestrate all 5 evaluation approaches into
a single smart pipeline that minimizes cost and maximizes output quality.

Pipeline phases:
  Phase 1: Pre-flight  (FREE — no API calls)
  Phase 2: Generate    (COSTS MONEY — only if Phase 1 passes)
  Phase 3: Evaluate    (CHEAP — mostly offline heuristics)
  Phase 4: Learn & Fix (CHEAP — offline regex or one Sonnet call)

Sub-engines (gracefully skipped if not yet available):
  1. output-eval.py       — heuristic output scoring, no API
  2. output-sim.py        — token budget / structural forecast
  3. output-schema.py     — structural schema generation & validation
  4. self-check-inject.py — model self-QA injection
  5. (built-in)           — API-based generation + Sonnet evaluation

Usage:
    python output-test.py <prompt-folder>
    python output-test.py <prompt-folder> --max 5
    python output-test.py <prompt-folder> --dry-run
    python output-test.py <prompt-folder> --skip-preflight
    python output-test.py <prompt-folder> --no-fix
    python output-test.py <prompt-folder> --verbose
    python output-test.py <prompt-folder> --evaluator-model <id> --fixer-model <id>

Environment:
    ANTHROPIC_API_KEY must be set (unless --dry-run).
    WIXIE_EVALUATOR_MODEL / WIXIE_FIXER_MODEL request other evaluator / fixer
    models (CLI flags take precedence). The fixer defaults to the evaluator.

Model identity:
    Every requested model (target from metadata.target_model, evaluator, fixer,
    including overrides) is resolved through shared/models-registry.json. Only
    entries declaring provider "anthropic" and an available api.model_id are
    sent; anything else stops the run before any API call. Requested, resolved
    and provider-observed (response.model) identities are saved per call and
    per role in output-test-results.json. Sampling parameters are only sent to
    models whose registry entry declares sampling "adjustable". Cost uses the
    resolved entry's registry price; with no price or no usage it is UNKNOWN.

Cost awareness:
    Phase 1 is always free. Phase 2 calls the target model (~$1.20 for Opus).
    Phase 3 is mostly offline. Phase 4 calls the evaluator/fixer model (~$0.10)
    only when needed. Default max 3 iterations = ~$3.90 worst case. Use --max
    to control.
"""
import sys, os, re, json, time, importlib, importlib.util
from datetime import datetime

# Fix Windows encoding issues with Unicode characters (checkmarks, arrows, etc.)
if sys.platform == "win32":
    for stream in [sys.stdout, sys.stderr]:
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Dynamic sub-engine imports ───────────────────────────────────────────────

def _try_import(filename, module_name):
    """Try to import a sibling script. Returns module or None."""
    path = os.path.join(SCRIPT_DIR, filename)
    if not os.path.isfile(path):
        return None
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        mod = importlib.util.module_from_spec(spec)
        # Suppress stdout during import (sub-modules may print during load)
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.stdout = old_stdout
        return mod
    except Exception:
        return None

# Import sub-engines — None if not yet built
_self_eval     = _try_import("self-eval.py", "self_eval")
_output_eval   = _try_import("output-eval.py", "output_eval")
_output_sim    = _try_import("output-sim.py", "output_sim")
_output_schema = _try_import("output-schema.py", "output_schema")
_self_check    = _try_import("self-check-inject.py", "self_check_inject")

# ─── Display helpers ──────────────────────────────────────────────────────────

RESET = ""
BOLD = ""
DIM = ""
GREEN = ""
RED = ""
YELLOW = ""
CYAN = ""
MAGENTA = ""

def _init_colors():
    global RESET, BOLD, DIM, GREEN, RED, YELLOW, CYAN, MAGENTA
    if sys.stdout.isatty():
        RESET   = "\033[0m"
        BOLD    = "\033[1m"
        DIM     = "\033[2m"
        GREEN   = "\033[32m"
        RED     = "\033[31m"
        YELLOW  = "\033[33m"
        CYAN    = "\033[36m"
        MAGENTA = "\033[35m"

def bar(val, mx=10, width=20):
    filled = min(round((val / mx) * width), width) if mx > 0 else 0
    return "#" * filled + "." * (width - filled)

def print_header(title, subtitle=""):
    w = 60
    print(f"\n{'=' * w}")
    print(f"  {BOLD}{title}{RESET}")
    if subtitle:
        print(f"  {DIM}{subtitle}{RESET}")
    print(f"{'=' * w}\n")

def print_phase(name):
    print(f"\n  {BOLD}{CYAN}{name}{RESET}")

def print_check(label, value, detail="", ok=True):
    icon = f"{GREEN}\u2713{RESET}" if ok else f"{RED}\u2717{RESET}"
    print(f"    {label.ljust(20)} {value}  {icon}  {DIM}{detail}{RESET}")

def print_score_line(label, val, mx=10, width=20):
    color = GREEN if val / mx >= 0.8 else YELLOW if val / mx >= 0.6 else RED
    print(f"    {label.ljust(20)} {color}{val:g}/{mx}{RESET}  {bar(val, mx, width)}")

def print_warn(msg):
    print(f"    {YELLOW}[skip]{RESET} {msg}")

# ─── Model resolution (WIX-EVAL-003) ─────────────────────────────────────────
#
# shared/models-registry.json is the single source of truth for which model a
# requested id is sent as. Registry membership alone is NOT enough: an entry is
# sendable only when it declares provider "anthropic" and an "api" block with
# availability "available" and a model_id. Everything else fails explicitly
# before any call. A fallback happens only when the unavailable entry declares
# one in api.fallback, and it is recorded with both identities.
#
# Per-entry api block (field additions on existing registry entries):
#   model_id               string sent as `model` to the Anthropic Messages API
#   availability           "available" | "unavailable" | "restricted"
#   sampling               "adjustable" (temperature/top_p/top_k may be set) |
#                          "default_only" (non-default values are rejected, so
#                          none are sent); anything else is treated as default_only
#   pricing_usd_per_mtok   {"input": x, "output": y} or null (cost then UNKNOWN)
#   fallback               optional registry id to use when not available
#   source, checked        where the facts came from and when

REGISTRY_PATH = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "models-registry.json"))
SENDABLE_PROVIDER = "anthropic"

DEFAULT_TARGET_MODEL = "claude-opus-4-6"
DEFAULT_EVALUATOR_MODEL = "claude-sonnet-4-6"
EVALUATOR_ENV = "WIXIE_EVALUATOR_MODEL"
FIXER_ENV = "WIXIE_FIXER_MODEL"

# Requested sampling for the evaluator and fixer. Applied through the resolved
# model's sampling capability, never sent blindly.
EVALUATOR_SAMPLING = {"temperature": 0.0}
FIXER_SAMPLING = {"temperature": 0.0}
EVALUATOR_MAX_TOKENS = 2048
FIXER_MAX_TOKENS = 1024


class ModelResolutionError(Exception):
    """A requested model cannot be sent to the provider. Never passed through."""


def load_registry(path=None):
    path = path or REGISTRY_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            models = json.load(f).get("models")
    except (OSError, ValueError) as e:
        raise ModelResolutionError(f"cannot read model registry {path}: {e}")
    if not isinstance(models, dict):
        raise ModelResolutionError(f"model registry {path} has no 'models' object")
    return models


def _sendable_entry(registry, registry_id, role):
    """Return the api block of a registry id that output-test may send, or raise."""
    entry = registry.get(registry_id)
    if not isinstance(entry, dict):
        raise ModelResolutionError(
            f"{role} model {registry_id!r} is not in models-registry.json; "
            f"add it (with provider and api fields) or pick a registered model")
    provider = entry.get("provider")
    if provider != SENDABLE_PROVIDER:
        raise ModelResolutionError(
            f"{role} model {registry_id!r}: registry provider is "
            f"{provider or 'undeclared'}; output-test only calls the Anthropic API")
    api = entry.get("api")
    if not isinstance(api, dict):
        raise ModelResolutionError(
            f"{role} model {registry_id!r}: registry declares no api block "
            f"(model_id / availability), so no provider identity is known")
    return api


def resolve_model(requested, role="target", requested_source="default"):
    """Resolve a requested registry id to the provider model id that will be sent.

    Returns a resolution record. Raises ModelResolutionError for unknown,
    non-Anthropic, undeclared or unavailable models (unless a fallback is declared).
    """
    if not isinstance(requested, str) or not requested.strip():
        raise ModelResolutionError(f"{role} model is empty or not a string: {requested!r}")
    registry = load_registry()
    api = _sendable_entry(registry, requested, role)
    registry_id = requested
    fallback = None
    availability = api.get("availability")
    if availability != "available":
        fb = api.get("fallback")
        if not fb:
            raise ModelResolutionError(
                f"{role} model {requested!r}: registry availability is {availability!r} "
                f"and no fallback is declared (source: {api.get('source', 'unstated')})")
        fb_api = _sendable_entry(registry, fb, role)
        if fb_api.get("availability") != "available":
            raise ModelResolutionError(
                f"{role} model {requested!r}: declared fallback {fb!r} is itself "
                f"{fb_api.get('availability')!r}; fallbacks do not chain")
        fallback = {
            "from_registry_id": requested,
            "from_availability": availability,
            "from_model_id": api.get("model_id"),
            "to_registry_id": fb,
            "to_model_id": fb_api.get("model_id"),
            "declared_in": f"models-registry.json models.{requested}.api.fallback",
        }
        registry_id, api = fb, fb_api
    model_id = api.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise ModelResolutionError(
            f"{role} model {registry_id!r}: registry api block has no model_id")
    return {
        "role": role,
        "requested": requested,
        "requested_source": requested_source,
        "resolved": model_id,
        "resolved_registry_id": registry_id,
        "provider": SENDABLE_PROVIDER,
        "availability": api.get("availability"),
        "sampling": api.get("sampling"),
        "pricing_usd_per_mtok": api.get("pricing_usd_per_mtok"),
        "api_source": api.get("source"),
        "api_checked": api.get("checked"),
        "fallback": fallback,
        "resolution_source": "models-registry.json",
    }


def select_requested_models(meta, evaluator_model=None, fixer_model=None, env=None):
    """Pick the requested id for each role and record where it came from.

    CLI arguments beat environment variables beat defaults. Every value, whatever
    its source, still goes through resolve_model; nothing here bypasses it.
    """
    env = os.environ if env is None else env
    if meta.get("target_model"):
        target = (meta["target_model"], "metadata.target_model")
    else:
        target = (DEFAULT_TARGET_MODEL, "default")
    if evaluator_model:
        evaluator = (evaluator_model, "cli:--evaluator-model")
    elif env.get(EVALUATOR_ENV):
        evaluator = (env[EVALUATOR_ENV], f"env:{EVALUATOR_ENV}")
    else:
        evaluator = (DEFAULT_EVALUATOR_MODEL, "default")
    if fixer_model:
        fixer = (fixer_model, "cli:--fixer-model")
    elif env.get(FIXER_ENV):
        fixer = (env[FIXER_ENV], f"env:{FIXER_ENV}")
    else:
        fixer = (evaluator[0], f"inherited:evaluator ({evaluator[1]})")
    return {"target": target, "evaluator": evaluator, "fixer": fixer}


def resolve_run_models(meta, evaluator_model=None, fixer_model=None):
    """Resolve all three roles. Returns (identity, errors); errors maps role -> message."""
    identity, errors = {}, {}
    for role, (requested, source) in select_requested_models(
            meta, evaluator_model, fixer_model).items():
        try:
            identity[role] = resolve_model(requested, role, source)
        except ModelResolutionError as e:
            errors[role] = str(e)
            identity[role] = {"role": role, "requested": requested,
                              "requested_source": source, "resolved": None,
                              "error": str(e)}
    return identity, errors


def apply_sampling_policy(resolution, requested_params):
    """Split requested sampling params into those sent and those withheld."""
    policy = resolution.get("sampling")
    requested_params = {k: v for k, v in (requested_params or {}).items() if v is not None}
    sent, omitted = {}, {}
    for k, v in requested_params.items():
        (sent if policy == "adjustable" else omitted)[k] = v
    record = {"policy": policy or "undeclared", "requested": requested_params,
              "sent": sent, "omitted": omitted}
    if omitted:
        record["reason"] = ("model accepts only provider-default sampling; parameters not sent"
                            if policy == "default_only" else
                            "sampling capability not declared as adjustable; parameters not sent")
    return sent, record

# ─── Cost tracking ────────────────────────────────────────────────────────────

def estimate_cost(resolution, usage):
    """Return (cost_usd or None, provenance). Priced by the RESOLVED registry entry."""
    rid = (resolution or {}).get("resolved_registry_id")
    if not usage or usage.get("input_tokens") is None or usage.get("output_tokens") is None:
        return None, "UNKNOWN: provider usage not reported"
    pricing = (resolution or {}).get("pricing_usd_per_mtok")
    if not isinstance(pricing, dict) or not all(
            isinstance(pricing.get(k), (int, float)) for k in ("input", "output")):
        return None, f"UNKNOWN: no price declared for {rid!r} in models-registry.json"
    cost = (usage["input_tokens"] / 1e6 * pricing["input"] +
            usage["output_tokens"] / 1e6 * pricing["output"])
    return round(cost, 6), (f"models-registry.json models.{rid}.api.pricing_usd_per_mtok "
                            f"(resolved {resolution.get('resolved')})")


def cost_summary(calls):
    """Cost of a group of calls. cost_usd is None (UNKNOWN) when any call in the group is
    unpriced or failed; known_cost_usd is then a partial sum, labelled by unknown_calls."""
    known, unknown = sum_known_costs(calls)
    return {"cost_usd": round(known, 6) if unknown == 0 else None,
            "known_cost_usd": round(known, 6), "unknown_calls": unknown}


def sum_known_costs(calls):
    """(known_cost_sum, unknown_count) over call records."""
    known, unknown = 0.0, 0
    for c in calls:
        if c.get("cost_usd") is None:
            unknown += 1
        else:
            known += c["cost_usd"]
    return known, unknown

# ─── API helpers ──────────────────────────────────────────────────────────────

def get_client():
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic SDK not installed. Run: pip install anthropic", file=sys.stderr)
        sys.exit(1)
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)
    return anthropic.Anthropic(api_key=key)


def _redact(text):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key and len(key) >= 8:
        text = text.replace(key, "[REDACTED]")
    return text


def _usage_of(response):
    u = getattr(response, "usage", None)
    if u is None:
        return None
    it = getattr(u, "input_tokens", None)
    ot = getattr(u, "output_tokens", None)
    if it is None and ot is None:
        return None
    return {"input_tokens": it, "output_tokens": ot}


def call_model(client, resolution, system_prompt, user_prompt, max_tokens=4096, sampling=None):
    """Call the Anthropic API with a resolved model. Returns (text or None, call_record).

    The record keeps requested, resolved and provider-observed identity apart.
    A provider error keeps its failure: text is None, usage is None (unknown,
    not zero) and cost is UNKNOWN.
    """
    sent_sampling, sampling_record = apply_sampling_policy(resolution, sampling)
    record = {
        "role": resolution.get("role"),
        "requested": resolution.get("requested"),
        "resolved": resolution.get("resolved"),
        "observed": None,
        # True when the provider reports a different model than the one sent (an alias
        # served as a snapshot, or a substitution); None when the provider did not say.
        "identity_mismatch": None,
        "fallback": resolution.get("fallback"),
        "ok": False,
        "usage": None,
        "cost_usd": None,
        "cost_provenance": None,
        "sampling": sampling_record,
        "max_tokens": max_tokens,
        "error": None,
    }
    kwargs = {
        "model": resolution["resolved"],
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    kwargs.update(sent_sampling)
    if system_prompt:
        kwargs["system"] = system_prompt
    try:
        response = client.messages.create(**kwargs)
    except Exception as e:
        record["error"] = {
            "type": type(e).__name__,
            "status_code": getattr(e, "status_code", None),
            "message": _redact(str(e))[:500],
        }
        record["cost_provenance"] = "UNKNOWN: provider call failed; usage not reported"
        return None, record
    text = ""
    for block in getattr(response, "content", None) or []:
        if hasattr(block, "text"):
            text += block.text
    observed = getattr(response, "model", None)
    record["observed"] = observed if isinstance(observed, str) and observed else None
    if record["observed"] is not None:
        record["identity_mismatch"] = record["observed"] != record["resolved"]
    record["stop_reason"] = getattr(response, "stop_reason", None)
    record["usage"] = _usage_of(response)
    record["cost_usd"], record["cost_provenance"] = estimate_cost(resolution, record["usage"])
    record["ok"] = True
    return text, record

# ─── Loaders ──────────────────────────────────────────────────────────────────

def load_prompt_folder(folder):
    """Load prompt, metadata, and tests from a prompt folder."""
    folder = os.path.abspath(folder)
    prompt_file = None
    for ext in ["xml", "md", "txt", "json"]:
        candidate = os.path.join(folder, f"prompt.{ext}")
        if os.path.isfile(candidate):
            prompt_file = candidate
            break
    if not prompt_file:
        print(f"ERROR: No prompt file found in {folder}", file=sys.stderr)
        sys.exit(1)

    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt_text = f.read()

    meta_path = os.path.join(folder, "metadata.json")
    meta = {}
    if os.path.isfile(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    tests_path = os.path.join(folder, "tests.json")
    tests = []
    if os.path.isfile(tests_path):
        with open(tests_path, "r", encoding="utf-8") as f:
            tests = json.load(f)

    return prompt_text, meta, tests, prompt_file, folder

# ─── Phase 1: Pre-flight (FREE) ──────────────────────────────────────────────

def run_preflight(prompt_text, meta, folder, verbose=False):
    """Run all free pre-flight checks. Returns (passed, results_dict)."""
    results = {
        "prompt_quality": None,
        "token_budget": None,
        "schema": None,
        "forecast": None,
        "passed": True,
        "warnings": [],
    }

    config = meta.get("config", {})
    max_tokens = config.get("max_tokens", 32768)

    # 1a. Prompt quality via self-eval
    if _self_eval:
        try:
            scores = {a: round(fn(prompt_text), 1)
                      for a, fn in zip(_self_eval.AXES, _self_eval.SCORERS)}
            overall = round(sum(scores.values()) / len(scores), 1)
            low_axes = [a for a, v in scores.items() if v < 6]
            verdict = "DEPLOY" if overall >= 9.0 and not low_axes else (
                "PASS" if overall >= 7.0 and not low_axes else "NEEDS WORK"
            )
            results["prompt_quality"] = {
                "scores": scores,
                "overall": overall,
                "verdict": verdict,
                "low_axes": low_axes,
            }
            ok = verdict != "NEEDS WORK"
            print_check("Prompt quality:", f"{overall}/10  {verdict}",
                        f"low: {', '.join(low_axes)}" if low_axes else "", ok=ok)
            if verbose and low_axes:
                for a in low_axes:
                    print(f"      {DIM}{a}: {scores[a]}/10{RESET}")
            if not ok:
                results["passed"] = False
        except Exception as e:
            print_warn(f"self-eval error: {e}")
            results["warnings"].append(f"self-eval error: {e}")
    else:
        print_warn("self-eval.py not found — skipping prompt quality check")
        results["warnings"].append("self-eval.py not available")

    # 1b. Token budget via output-sim
    if _output_sim:
        try:
            sim_result = _output_sim.simulate(prompt_text, max_tokens=max_tokens)
            prompt_tokens = sim_result.get("prompt_tokens", 0)
            budget_pct = round((prompt_tokens / max_tokens) * 100) if max_tokens > 0 else 0
            budget_ok = budget_pct < 80
            results["token_budget"] = {
                "prompt_tokens": prompt_tokens,
                "max_tokens": max_tokens,
                "budget_pct": budget_pct,
                "ok": budget_ok,
                "forecast": sim_result,
            }
            print_check("Token budget:", f"OK ({prompt_tokens} / {max_tokens} = {budget_pct}%)",
                        ok=budget_ok)
            if not budget_ok:
                results["passed"] = False
                print(f"      {RED}Prompt uses {budget_pct}% of token budget — output will be truncated{RESET}")
        except Exception as e:
            print_warn(f"output-sim error: {e}")
            results["warnings"].append(f"output-sim error: {e}")
    else:
        # Fallback: rough token estimate (4 chars per token)
        est_tokens = len(prompt_text) // 4
        budget_pct = round((est_tokens / max_tokens) * 100) if max_tokens > 0 else 0
        budget_ok = budget_pct < 80
        results["token_budget"] = {
            "prompt_tokens": est_tokens,
            "max_tokens": max_tokens,
            "budget_pct": budget_pct,
            "ok": budget_ok,
            "estimated": True,
        }
        print_check("Token budget:", f"~{est_tokens} / {max_tokens} = {budget_pct}% (estimated)",
                    ok=budget_ok)
        if not budget_ok:
            results["passed"] = False

    # 1c. Schema generation via output-schema
    if _output_schema:
        try:
            schema = _output_schema.generate_schema(prompt_text)
            sections = schema.get("sections", [])
            elements = sum(len(s.get("elements", [])) for s in sections)
            results["schema"] = {
                "sections": len(sections),
                "elements": elements,
                "schema": schema,
            }
            print_check("Schema generated:", f"{len(sections)} sections, {elements} elements",
                        ok=len(sections) > 0)
        except Exception as e:
            print_warn(f"output-schema error: {e}")
            results["warnings"].append(f"output-schema error: {e}")
    else:
        print_warn("output-schema.py not found — skipping schema generation")
        results["warnings"].append("output-schema.py not available")

    # 1d. Structural forecast via output-sim
    if _output_sim and results.get("schema"):
        try:
            forecast = _output_sim.forecast(prompt_text, results["schema"]["schema"])
            all_addressable = forecast.get("all_addressable", True)
            results["forecast"] = forecast
            print_check("Forecast:", "All sections addressable" if all_addressable else "Some sections may be missed",
                        ok=all_addressable)
            if not all_addressable:
                results["warnings"].append("Forecast: some sections may not be addressable within token budget")
        except Exception as e:
            print_warn(f"forecast error: {e}")
    elif not _output_sim:
        print_warn("output-sim.py not found — skipping forecast")

    return results["passed"], results

# ─── Phase 2: Generate (COSTS MONEY) ─────────────────────────────────────────

def run_generate(client, prompt_text, meta, folder, iteration, target=None):
    """Post prompt to the resolved target model. Returns (output or None, call_record, gen_info).

    `target` is a resolution record from resolve_model; when omitted it is
    resolved here from metadata (raising ModelResolutionError, never guessing).
    """
    if target is None:
        requested, source = select_requested_models(meta)["target"]
        target = resolve_model(requested, "target", source)
    config = meta.get("config", {})
    max_tokens = config.get("max_tokens", 16384)
    sampling = {"temperature": config.get("temperature", 1.0)}
    is_system = config.get("system_prompt", True)

    gen_info = {
        "self_check_injected": False,
        "model": target["requested"],
        "model_requested": target["requested"],
        "model_resolved": target["resolved"],
    }

    # Inject self-check if available
    active_prompt = prompt_text
    if _self_check:
        try:
            active_prompt = _self_check.inject(prompt_text)
            gen_info["self_check_injected"] = True
            print(f"    Self-check injected {GREEN}✓{RESET}")
        except Exception as e:
            print_warn(f"self-check-inject error: {e}")
    else:
        print_warn("self-check-inject.py not found — skipping self-check injection")

    # POST to target model
    print(f"    Posted to {target['resolved']} (requested {target['requested']})...",
          end="", flush=True)

    if is_system:
        output, call = call_model(
            client, target, active_prompt,
            "Execute the instructions in the system prompt. Produce the complete output as specified.",
            max_tokens=max_tokens, sampling=sampling
        )
    else:
        output, call = call_model(
            client, target, None, active_prompt,
            max_tokens=max_tokens, sampling=sampling
        )
    gen_info["model_observed"] = call["observed"]
    gen_info["sampling"] = call["sampling"]

    if output is None:
        print(f" {RED}API ERROR{RESET}")
        print(f"      {call['error']['type']}: {call['error']['message'][:200]}")
        return None, call, gen_info

    output_words = len(output.split())
    usage = call["usage"] or {}
    cost_txt = f"${call['cost_usd']:.4f}" if call["cost_usd"] is not None else "cost UNKNOWN"
    print(f" {GREEN}{output_words:,} words{RESET} "
          f"({usage.get('output_tokens')} tokens, {cost_txt}; observed {call['observed']})")
    if call["identity_mismatch"]:
        print(f"    {YELLOW}IDENTITY MISMATCH{RESET}: sent {call['resolved']}, provider reported {call['observed']}")

    # Save output as reference
    output_path = os.path.join(folder, "output-reference.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)

    gen_info["output_words"] = output_words
    gen_info["output_tokens"] = usage.get("output_tokens")

    return output, call, gen_info

# ─── Phase 3: Evaluate (CHEAP — mostly offline) ──────────────────────────────

def run_contains_tests(output, tests):
    """Run tests.json expected_contains assertions against the output."""
    results = []
    for test in tests:
        name = test.get("name", "unnamed")
        expected = test.get("expected_contains", [])
        passed_all = True
        missing = []
        for keyword in expected:
            if keyword.lower() not in output.lower():
                passed_all = False
                missing.append(keyword)
        results.append({
            "name": name,
            "passed": passed_all,
            "missing": missing,
            "tags": test.get("tags", []),
        })
    return results

def extract_self_check_results(output):
    """Extract self-check QA block from model output (if self-check was injected)."""
    # Look for self-check block patterns
    patterns = [
        r"<self[_-]check>(.*?)</self[_-]check>",
        r"## Self[- ]Check(.*?)(?=\n## |\Z)",
        r"\*\*Self[- ]Check\*\*(.*?)(?=\n\*\*|\Z)",
    ]
    for pattern in patterns:
        match = re.search(pattern, output, re.S | re.I)
        if match:
            block = match.group(1).strip()
            # Count pass/fail lines
            passes = len(re.findall(r'(?:PASS|\u2713|YES|pass)', block, re.I))
            fails = len(re.findall(r'(?:FAIL|\u2717|NO|fail)', block, re.I))
            total = passes + fails if (passes + fails) > 0 else 1
            return {
                "found": True,
                "passed": passes,
                "total": total,
                "score": round(passes / total * 10, 1) if total > 0 else 0,
                "raw": block[:500],
            }
    return {"found": False, "passed": 0, "total": 0, "score": 0}

def run_evaluate(output, prompt_text, tests, meta, preflight_results, verbose=False):
    """Run all offline evaluation checks. Returns (scores_dict, details_dict)."""
    scores = {}
    details = {}

    # 3a. Heuristic output scoring via output-eval
    if _output_eval:
        try:
            eval_result = _output_eval.evaluate(output, prompt_text)
            for key in ["structural", "specificity", "prior_art"]:
                if key in eval_result:
                    scores[key] = eval_result[key]
            details["output_eval"] = eval_result
            if "structural" in scores:
                print_score_line("Structural:", scores["structural"])
            if "specificity" in scores:
                print_score_line("Specificity:", scores["specificity"])
            if "prior_art" in scores:
                print_score_line("Prior Art:", scores["prior_art"])
        except Exception as e:
            print_warn(f"output-eval error: {e}")
    else:
        print_warn("output-eval.py not found — skipping heuristic scoring")

    # 3b. tests.json assertions
    test_results = run_contains_tests(output, tests)
    tests_passed = sum(1 for t in test_results if t["passed"])
    tests_total = len(test_results)
    if tests_total > 0:
        scores["assertions"] = round(tests_passed / tests_total * 10, 1)
        print_score_line("Assertions:", tests_passed, mx=tests_total)
        if verbose:
            for t in test_results:
                icon = f"{GREEN}PASS{RESET}" if t["passed"] else f"{RED}FAIL{RESET}"
                detail = f"missing: {t['missing']}" if t["missing"] else ""
                print(f"      {icon}  {t['name']}  {DIM}{detail}{RESET}")
    else:
        print_warn("No tests.json found — skipping assertion checks")
    details["test_results"] = test_results

    # 3c. Self-check extraction
    self_check = extract_self_check_results(output)
    if self_check["found"]:
        scores["self_check"] = self_check["score"]
        print_score_line("Self-check:", self_check["passed"], mx=self_check["total"])
    else:
        if verbose:
            print_warn("No self-check block found in output")
    details["self_check"] = self_check

    # 3d. Schema validation via output-schema
    schema = (preflight_results or {}).get("schema", {}).get("schema")
    if _output_schema and schema:
        try:
            validation = _output_schema.validate(output, schema)
            matched = validation.get("matched", 0)
            total_sections = validation.get("total", 1)
            scores["schema"] = round(matched / total_sections * 10, 1) if total_sections > 0 else 10
            print_score_line("Schema:", matched, mx=total_sections)
            details["schema_validation"] = validation
        except Exception as e:
            print_warn(f"output-schema validation error: {e}")
    elif not _output_schema:
        if verbose:
            print_warn("output-schema.py not found — skipping schema validation")

    # Compute overall score
    if scores:
        overall = round(sum(scores.values()) / len(scores), 1)
    else:
        overall = 0
    scores["overall"] = overall

    # Determine verdict
    if overall >= 8.0 and all(v >= 6.0 for k, v in scores.items() if k != "overall"):
        verdict = "PASS"
    elif overall >= 6.0:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"
    scores["verdict"] = verdict

    print()
    color = GREEN if verdict == "PASS" else YELLOW if verdict == "MARGINAL" else RED
    print(f"    {'OVERALL:'.ljust(20)} {color}{BOLD}{overall}/10{RESET}")
    print(f"    {'VERDICT:'.ljust(20)} {color}{BOLD}{verdict}{RESET}")

    return scores, details

# ─── Phase 4: Learn & Fix (CHEAP) ────────────────────────────────────────────

def run_llm_evaluation(client, prompt_text, output, meta, evaluator):
    """Use the resolved evaluator model to judge the output against the prompt's
    success criteria. Returns (eval_result or None, call_record); None means the
    provider call failed and there is no evaluation to use."""
    criteria_match = re.search(r"<success_criteria>(.*?)</success_criteria>", prompt_text, re.S)
    criteria_text = criteria_match.group(1).strip() if criteria_match else "No success criteria found."

    eval_prompt = f"""You are evaluating the output of a prompt. Score each criterion as PASS or FAIL.

## Success Criteria
{criteria_text}

## Output to Evaluate (first 12000 characters)
{output[:12000]}

## Instructions
For each numbered criterion:
1. State PASS or FAIL.
2. Give a 1-sentence reason.
3. If FAIL, describe specifically what is missing or wrong.

After all criteria, give:
- **Overall verdict**: PASS (all criteria met) or FAIL (any criterion not met).
- **Weakest area**: Which criterion is closest to failing, even if it passed.
- **Top fix**: The single most impactful change to the PROMPT (not the output) that would improve the output.

Respond in this exact JSON format:
```json
{{
  "criteria": [
    {{"id": 1, "verdict": "PASS|FAIL", "reason": "...", "fix": "...or null"}},
    ...
  ],
  "overall": "PASS|FAIL",
  "weakest_area": "...",
  "top_fix": "...",
  "output_quality_score": 8.5
}}
```"""

    response_text, call = call_model(
        client, evaluator, None, eval_prompt,
        max_tokens=EVALUATOR_MAX_TOKENS, sampling=EVALUATOR_SAMPLING
    )
    if response_text is None:
        return None, call
    try:
        json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.S)
        if json_match:
            return json.loads(json_match.group(1)), call
        return json.loads(response_text), call
    except json.JSONDecodeError:
        # The call succeeded but produced no usable verdict: no score, not a zero.
        return {
            "criteria": [],
            "overall": "UNPARSEABLE",
            "weakest_area": "Could not parse evaluator response",
            "top_fix": response_text[:500],
            "output_quality_score": None,
            "raw_response": response_text[:1000],
        }, call

def generate_fix(client, prompt_text, eval_result, test_results, scores, prompt_file, fixer):
    """Use the resolved fixer model to generate a specific prompt fix based on failures.
    Returns (fix or None, call_record or None); no record means no call was made."""
    failures = []
    for c in eval_result.get("criteria", []):
        if c.get("verdict") == "FAIL":
            failures.append(f"- Criterion {c['id']}: {c.get('reason', '')}. Fix: {c.get('fix', 'none')}")
    for t in test_results:
        if not t["passed"]:
            failures.append(f"- Test '{t['name']}' failed: missing keywords {t['missing']}")

    if not failures:
        return None, None

    top_fix = eval_result.get("top_fix", "No suggestion")

    fix_prompt = f"""You are a prompt engineer fixing a prompt based on test failures.

## Current Prompt (in {os.path.basename(prompt_file)})
{prompt_text[:8000]}

## Failures Found
{chr(10).join(failures)}

## Evaluator's Top Fix Suggestion
{top_fix}

## Instructions
Generate a SPECIFIC edit to fix the most impactful failure. Return JSON:
```json
{{
  "target": "the exact string in the prompt to replace (20-200 chars, must exist in the prompt)",
  "replacement": "the new string to replace it with",
  "reason": "1-sentence explanation of why this fix addresses the failure"
}}
```

Rules:
- The target string MUST exist verbatim in the prompt. Copy it exactly.
- Make the smallest change that fixes the most impactful failure.
- Do not rewrite the entire prompt. Fix ONE thing.
- If the failure is about missing content, add to an existing section rather than creating new sections."""

    response_text, call = call_model(
        client, fixer, None, fix_prompt,
        max_tokens=FIXER_MAX_TOKENS, sampling=FIXER_SAMPLING
    )
    if response_text is None:
        return None, call
    try:
        json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.S)
        if json_match:
            return json.loads(json_match.group(1)), call
        return json.loads(response_text), call
    except json.JSONDecodeError:
        return {"error": response_text[:500]}, call

def apply_fix(prompt_text, fix):
    """Apply a fix to the prompt text. Returns (new_text, applied_bool)."""
    target = fix.get("target", "")
    replacement = fix.get("replacement", "")
    if not target or not replacement:
        return prompt_text, False
    if target not in prompt_text:
        return prompt_text, False
    new_text = prompt_text.replace(target, replacement, 1)
    return new_text, True

def try_offline_fix(prompt_text, scores, details):
    """Attempt convergence.py-style regex fixes for structural failures.
    Returns (new_text, applied_bool, description) or (prompt_text, False, None)."""
    # Import convergence fixers if available
    try:
        convergence = _try_import("convergence.py", "convergence")
        if not convergence:
            return prompt_text, False, None
    except Exception:
        return prompt_text, False, None

    # Identify what kind of failure we have
    test_results = details.get("test_results", [])
    failed_tests = [t for t in test_results if not t["passed"]]

    # If assertion tests failed with missing keywords, try to inject them
    # (this is a structural fix — no API needed)
    if failed_tests and hasattr(convergence, 'FIXERS'):
        # Run convergence-style fixes on the prompt
        pre_text = prompt_text

        # Score the prompt to find weakest axis
        if _self_eval:
            prompt_scores = {a: round(fn(prompt_text), 1)
                           for a, fn in zip(_self_eval.AXES, _self_eval.SCORERS)}
            weakest = min(_self_eval.AXES, key=lambda a: prompt_scores[a])
            if weakest in convergence.FIXERS and prompt_scores[weakest] < 9.0:
                candidate_text = convergence.FIXERS[weakest](prompt_text)
                if candidate_text != pre_text:
                    # WIX-CONV-001 item 4: this path applies convergence.py's fixers with
                    # no gate of its own. Share the same structural gate convergence.py's
                    # own accept/revert loop uses (protected_regions_equal), so a candidate
                    # that changed a fenced code block / table / blockquote / <example>
                    # block is refused here too, regardless of score.
                    gate = getattr(convergence, "protected_regions_equal", None)
                    if gate is not None and not gate(pre_text, candidate_text):
                        return prompt_text, False, None
                    return candidate_text, True, f"Offline fix: improved {weakest} ({prompt_scores[weakest]}/10)"

    return prompt_text, False, None

def diagnose_and_fix(client, prompt_text, output, scores, details, meta, prompt_file,
                     evaluator, fixer, verbose=False):
    """Phase 4: Diagnose failures and apply fixes.

    Returns (new_prompt, fix_info, calls) where calls are the provider call records
    (evaluator and fixer) made in this phase, each with its own identity and cost.
    """
    fix_info = {"method": None, "applied": False, "description": None}
    calls = []

    # Strategy 1: Try offline regex fix first (FREE)
    new_text, applied, desc = try_offline_fix(prompt_text, scores, details)
    if applied:
        fix_info = {"method": "offline_regex", "applied": True, "description": desc}
        print(f"    {GREEN}Offline fix applied{RESET}: {desc}")
        return new_text, fix_info, calls

    # Strategy 2: Use the evaluator model for content-level diagnosis (CHEAP)
    print(f"    {CYAN}Diagnosing with {evaluator['resolved']}...{RESET}", end="", flush=True)
    eval_result, eval_call = run_llm_evaluation(client, prompt_text, output, meta, evaluator)
    calls.append(eval_call)

    if eval_result is None:
        # Provider failure: record it, do not score it, do not fix from it.
        err = eval_call["error"]
        print(f" {RED}EVALUATOR PROVIDER ERROR{RESET}: {err['type']}: {err['message'][:120]}")
        fix_info = {"method": "llm_evaluation", "applied": False,
                    "description": "evaluator provider call failed; no evaluation, no fix attempted",
                    "evaluation_failed": True, "error": err}
        return prompt_text, fix_info, calls

    overall_verdict = eval_result.get("overall", "UNPARSEABLE")
    quality_score = eval_result.get("output_quality_score")
    fix_info["llm_evaluation"] = {"overall": overall_verdict, "output_quality_score": quality_score}

    if overall_verdict == "PASS":
        print(f" {GREEN}PASS{RESET} (quality: {quality_score}/10)")
    else:
        print(f" {RED}{overall_verdict}{RESET} (quality: {quality_score}/10)")

    if verbose:
        for c in eval_result.get("criteria", []):
            cv = c.get("verdict", "?")
            cr = c.get("reason", "")
            icon = f"{GREEN}PASS{RESET}" if cv == "PASS" else f"{RED}FAIL{RESET}"
            print(f"      {icon}  Criterion {c.get('id', '?')}: {cr[:80]}")

    # If LLM says PASS and offline scores are decent, we're good
    llm_eval = fix_info["llm_evaluation"]
    if overall_verdict == "PASS" and scores.get("overall", 0) >= 7.0:
        fix_info = {"method": "none_needed", "applied": False, "description": "LLM evaluation passed",
                    "llm_evaluation": llm_eval}
        return prompt_text, fix_info, calls

    # Generate and apply a targeted fix with the resolved fixer model
    print(f"    {CYAN}Generating fix with {fixer['resolved']}...{RESET}", end="", flush=True)
    test_results = details.get("test_results", [])
    fix, fix_call = generate_fix(client, prompt_text, eval_result, test_results, scores,
                                 prompt_file, fixer)
    if fix_call is not None:
        calls.append(fix_call)

    if fix_call is not None and not fix_call["ok"]:
        err = fix_call["error"]
        print(f" {RED}FIXER PROVIDER ERROR{RESET}: {err['type']}: {err['message'][:120]}")
        fix_info = {"method": "llm_fix", "applied": False,
                    "description": "fixer provider call failed", "fix_failed": True,
                    "error": err, "llm_evaluation": llm_eval}
    elif fix and "error" not in fix:
        new_text, applied = apply_fix(prompt_text, fix)
        if applied:
            reason = fix.get("reason", "no reason")
            print(f" {GREEN}Applied{RESET}: {reason[:80]}")
            fix_info = {"method": "llm_fix", "applied": True, "description": reason,
                        "llm_evaluation": llm_eval}
            # Save fixed prompt
            with open(prompt_file, "w", encoding="utf-8") as f:
                f.write(new_text)
            return new_text, fix_info, calls
        else:
            print(f" {YELLOW}Could not apply{RESET} (target string not found)")
            fix_info = {"method": "llm_fix", "applied": False, "description": "target not found",
                        "llm_evaluation": llm_eval}
    else:
        err = fix.get("error", "unknown") if fix else "no fix generated"
        print(f" {RED}Fix failed{RESET}: {str(err)[:80]}")
        fix_info = {"method": "llm_fix", "applied": False, "description": str(err)[:200],
                    "llm_evaluation": llm_eval}

    return prompt_text, fix_info, calls

# ─── Results persistence ──────────────────────────────────────────────────────

def _identity_with_observed(identity, calls):
    """Per role: requested and resolved from resolution, observed from provider responses."""
    out = {}
    for role, rec in (identity or {}).items():
        role_calls = [c for c in calls if c.get("role") == role]
        observed = [c.get("observed") for c in role_calls]
        out[role] = dict(rec)
        out[role]["observed"] = sorted({o for o in observed if o})
        out[role]["observed_unknown_calls"] = sum(1 for o in observed if not o)
        out[role]["identity_mismatch_calls"] = sum(1 for c in role_calls if c.get("identity_mismatch"))
        out[role]["calls"] = len(role_calls)
    return out


def save_results(folder, run_data):
    """Save comprehensive results to output-test-results.json."""
    path = os.path.join(folder, "output-test-results.json")
    calls = run_data.get("calls", [])
    known, unknown = sum_known_costs(calls)
    if not calls:
        cost_status = "no_calls"
    else:
        cost_status = "complete" if unknown == 0 else "partial"
    data = {
        "engine": "hybrid-convergence",
        "version": "2.0",
        "last_run": datetime.now().isoformat(),
        "prompt_folder": folder,
        "model": run_data.get("model", "unknown"),
        "model_identity": _identity_with_observed(run_data.get("model_identity"), calls),
        "model_resolution_errors": run_data.get("model_resolution_errors", {}),
        "fallback_events": run_data.get("fallback_events", []),
        "iterations": run_data.get("total_iterations", 0),
        "final_verdict": run_data.get("final_verdict", "NO_RUNS"),
        "final_score": run_data.get("final_score", 0),
        # None when any call's cost is unknown: a partial sum is not a total.
        "total_cost_usd": round(known, 6) if unknown == 0 else None,
        "known_cost_usd": round(known, 6),
        "cost_unknown_calls": unknown,
        "cost_status": cost_status,
        "total_duration_sec": round(run_data.get("total_duration", 0), 1),
        # Each bucket: cost_usd (None when UNKNOWN), known_cost_usd and unknown_calls.
        "cost_breakdown": run_data.get("cost_breakdown", {}),
        "provider_failures": [c for c in calls if not c.get("ok")],
        "preflight": run_data.get("preflight", {}),
        "iterations_detail": run_data.get("iterations_detail", []),
        "available_engines": run_data.get("available_engines", []),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path

# ─── Main engine ──────────────────────────────────────────────────────────────

def _close_iteration(iter_data, calls, iter_start):
    iter_data["calls"] = calls
    summary = cost_summary(calls)
    iter_data["cost_usd"] = summary["cost_usd"]          # None when any call is unpriced/failed
    iter_data["known_cost_usd"] = summary["known_cost_usd"]
    iter_data["cost_unknown_calls"] = summary["unknown_calls"]
    iter_data["cost_complete"] = summary["unknown_calls"] == 0
    iter_data["duration_sec"] = round(time.time() - iter_start, 1)
    return iter_data


def run(folder, max_iterations=3, dry_run=False, skip_preflight=False,
        no_fix=False, verbose=False, evaluator_model=None, fixer_model=None, client=None):
    _init_colors()
    prompt_text, meta, tests, prompt_file, folder = load_prompt_folder(folder)

    # Resolve every role up front, through the registry, before any call.
    identity, model_errors = resolve_run_models(meta, evaluator_model, fixer_model)
    fallback_events = [rec["fallback"] for rec in identity.values() if rec.get("fallback")]
    target_model_id = identity["target"]["requested"]
    prompt_name = os.path.basename(folder)

    # Track available engines
    available = []
    if _self_eval:     available.append("self-eval")
    if _output_eval:   available.append("output-eval")
    if _output_sim:    available.append("output-sim")
    if _output_schema: available.append("output-schema")
    if _self_check:    available.append("self-check-inject")
    available.append("api-eval (built-in)")

    print_header(
        "WIXIE OUTPUT TEST ENGINE (Hybrid)",
        f"Prompt: {prompt_name} | Model: {target_model_id}"
    )

    if not available:
        print(f"  {DIM}Engines: built-in only{RESET}")
    else:
        print(f"  {DIM}Engines: {', '.join(available)}{RESET}")

    for role, rec in identity.items():
        if rec.get("resolved"):
            print(f"  {DIM}{role.capitalize()}: {rec['requested']} -> {rec['resolved']} "
                  f"({rec['requested_source']}; sampling {rec.get('sampling') or 'undeclared'}){RESET}")
        else:
            print(f"  {RED}{role.capitalize()}: {rec['requested']} UNRESOLVED{RESET} "
                  f"({rec['requested_source']})")
    for fb in fallback_events:
        print(f"  {YELLOW}FALLBACK{RESET}: {fb['from_registry_id']} ({fb['from_availability']}) "
              f"-> {fb['to_registry_id']} = {fb['to_model_id']} (declared in registry)")

    run_start = time.time()
    # Calls per cost bucket; preflight and evaluate (Phase 3) make no provider calls.
    bucket_calls = {"preflight": [], "generate": [], "evaluate": [], "fix": []}
    iterations_detail = []
    all_calls = []
    preflight_results = None
    final_verdict = "NO_RUNS"
    final_score = 0

    def _run_data(**kw):
        data = {
            "model": target_model_id,
            "model_identity": identity,
            "model_resolution_errors": model_errors,
            "fallback_events": fallback_events,
            "calls": all_calls,
            "total_iterations": 0,
            "final_score": 0,
            "total_duration": round(time.time() - run_start, 1),
            "cost_breakdown": {k: cost_summary(v) for k, v in bucket_calls.items()},
            "preflight": preflight_results,
            "iterations_detail": [],
            "available_engines": available,
        }
        data.update(kw)
        return data

    # ═══════════════════════════════════════════════════════════════════════════
    # Phase 1: Pre-flight (FREE)
    # ═══════════════════════════════════════════════════════════════════════════
    if not skip_preflight:
        print_phase("Phase 1: Pre-flight (free)")
        preflight_ok, preflight_results = run_preflight(prompt_text, meta, folder, verbose=verbose)

        if not preflight_ok and not dry_run:
            print(f"\n    {RED}{BOLD}Pre-flight FAILED{RESET} — fix prompt before spending API credits")
            print(f"    {DIM}Use convergence.py to auto-fix, or --skip-preflight to override{RESET}")
            # Still save results
            results_path = save_results(folder, _run_data(
                final_verdict="PREFLIGHT_FAIL", preflight=preflight_results))
            print(f"\n  Results saved: {os.path.basename(results_path)}")
            _print_summary(0, 0, round(time.time() - run_start, 1), 0, "PREFLIGHT_FAIL")
            return []
    else:
        print(f"\n  {DIM}(--skip-preflight: Phase 1 skipped){RESET}")

    if dry_run:
        print(f"\n  {DIM}(--dry-run: stopping after Phase 1){RESET}")
        results_path = save_results(folder, _run_data(
            final_verdict="DRY_RUN",
            final_score=preflight_results.get("prompt_quality", {}).get("overall", 0) if preflight_results else 0,
            preflight=preflight_results))
        print(f"\n  Results saved: {os.path.basename(results_path)}")
        _print_summary(0, 0, round(time.time() - run_start, 1), 0,
                       preflight_results.get("prompt_quality", {}).get("verdict", "DRY_RUN") if preflight_results else "DRY_RUN")
        return []

    # No call is made unless every role resolved to a sendable provider model.
    if model_errors:
        print(f"\n  {RED}{BOLD}MODEL RESOLUTION FAILED{RESET} — no API call made")
        for role, err in model_errors.items():
            print(f"    {role}: {err}", file=sys.stderr)
        results_path = save_results(folder, _run_data(final_verdict="MODEL_RESOLUTION_FAILED"))
        print(f"\n  Results saved: {os.path.basename(results_path)}")
        _print_summary(0, 0, round(time.time() - run_start, 1), 0, "MODEL_RESOLUTION_FAILED")
        return []

    # ═══════════════════════════════════════════════════════════════════════════
    # Iteration loop: Phase 2 -> Phase 3 -> Phase 4 -> repeat
    # ═══════════════════════════════════════════════════════════════════════════
    if client is None:
        client = get_client()

    for iteration in range(1, max_iterations + 1):
        iter_start = time.time()
        calls = []

        # ───────────────────────────────────────────────────────────────────────
        # Phase 2: Generate (COSTS MONEY)
        # ───────────────────────────────────────────────────────────────────────
        print_phase(f"Phase 2: Generate (iter {iteration})")
        output, gen_call, gen_info = run_generate(
            client, prompt_text, meta, folder, iteration, target=identity["target"]
        )
        calls.append(gen_call)
        all_calls.append(gen_call)
        bucket_calls["generate"].append(gen_call)

        if output is None:
            # Provider error — record it with its provenance and stop
            iterations_detail.append(_close_iteration({
                "iteration": iteration,
                "verdict": "API_ERROR",
                "gen_info": gen_info,
                "error": gen_call["error"],
            }, calls, iter_start))
            final_verdict = "API_ERROR"
            break

        # ───────────────────────────────────────────────────────────────────────
        # Phase 3: Evaluate (CHEAP — mostly offline)
        # ───────────────────────────────────────────────────────────────────────
        print_phase("Phase 3: Evaluate")
        scores, details = run_evaluate(
            output, prompt_text, tests, meta, preflight_results, verbose=verbose
        )

        final_score = scores.get("overall", 0)
        final_verdict = scores.get("verdict", "FAIL")

        iter_data = {
            "iteration": iteration,
            "verdict": final_verdict,
            "scores": {k: v for k, v in scores.items() if k != "verdict"},
            "gen_info": gen_info,
        }

        # ───────────────────────────────────────────────────────────────────────
        # Check exit: PASS
        # ───────────────────────────────────────────────────────────────────────
        if final_verdict == "PASS":
            iterations_detail.append(_close_iteration(iter_data, calls, iter_start))

            print(f"\n  {'=' * 50}")
            print(f"  {GREEN}{BOLD}ALL CHECKS PASSED{RESET}")
            print(f"  {'=' * 50}")
            break

        # ───────────────────────────────────────────────────────────────────────
        # Phase 4: Learn & Fix (CHEAP)
        # ───────────────────────────────────────────────────────────────────────
        if no_fix:
            print(f"\n    {DIM}(--no-fix: skipping auto-fix){RESET}")
            iterations_detail.append(_close_iteration(iter_data, calls, iter_start))
            continue

        if iteration < max_iterations:
            print_phase("Phase 4: Learn & Fix")
            new_prompt, fix_info, fix_calls = diagnose_and_fix(
                client, prompt_text, output, scores, details, meta, prompt_file,
                identity["evaluator"], identity["fixer"], verbose=verbose
            )
            calls.extend(fix_calls)
            all_calls.extend(fix_calls)
            bucket_calls["fix"].extend(fix_calls)
            iter_data["fix"] = fix_info

            if fix_info["applied"]:
                prompt_text = new_prompt

        iterations_detail.append(_close_iteration(iter_data, calls, iter_start))
        iter_cost_txt = (f"${iter_data['cost_usd']:.3f}" if iter_data["cost_complete"]
                         else f"UNKNOWN (${iter_data['known_cost_usd']:.3f} known + "
                              f"{iter_data['cost_unknown_calls']} unpriced/failed call(s))")
        print(f"\n  {DIM}--- Iteration {iteration} done ({iter_cost_txt}) ---{RESET}")

    else:
        # Max iterations reached without PASS
        if iterations_detail:
            best = max(iterations_detail, key=lambda x: x.get("scores", {}).get("overall", 0))
            final_score = best.get("scores", {}).get("overall", 0)
            final_verdict = best.get("verdict", "FAIL")

        print(f"\n  {'=' * 50}")
        print(f"  {YELLOW}{BOLD}MAX ITERATIONS REACHED{RESET}")
        print(f"  Best score: {final_score}/10")
        print(f"  {'=' * 50}")

    # ═══════════════════════════════════════════════════════════════════════════
    # Save results & print summary
    # ═══════════════════════════════════════════════════════════════════════════
    total_duration = round(time.time() - run_start, 1)
    total_iterations = len(iterations_detail)
    total_cost, unknown_cost_calls = sum_known_costs(all_calls)

    results_path = save_results(folder, _run_data(
        total_iterations=total_iterations,
        final_verdict=final_verdict,
        final_score=final_score,
        total_duration=total_duration,
        iterations_detail=iterations_detail,
    ))
    print(f"\n  Results saved: {os.path.basename(results_path)}")

    _print_summary(total_cost, total_iterations, total_duration, final_score, final_verdict,
                   unknown_cost_calls)

    # Summary table for multi-iteration runs
    if len(iterations_detail) > 1:
        print(f"\n  {'─' * 55}")
        print(f"  {'Iter':>4}  {'Score':>7}  {'Verdict':>10}  {'Cost':>8}  {'Time':>6}")
        print(f"  {'─' * 55}")
        for it in iterations_detail:
            s = f"{it.get('scores', {}).get('overall', 0)}/10"
            v = it.get("verdict", "?")
            c = (f"${it['cost_usd']:.3f}" if it.get("cost_usd") is not None
                 else f"${it.get('known_cost_usd', 0):.3f}+?")
            t = f"{it.get('duration_sec', 0):.0f}s"
            color = GREEN if v == "PASS" else RED if v == "FAIL" else YELLOW
            print(f"  {it['iteration']:>4}  {s:>7}  {color}{v:>10}{RESET}  {c:>8}  {t:>6}")
        print(f"  {'─' * 55}")
        print(f"  {'Total':>4}  {'':>7}  {'':>10}  ${total_cost:>7.3f}  {total_duration:>5.0f}s")
        print()

    return iterations_detail

def _print_summary(cost, iterations, duration, score, verdict, unknown_cost_calls=0):
    color = GREEN if verdict == "PASS" else YELLOW if verdict in ("MARGINAL", "DRY_RUN") else RED
    cost_txt = (f"${cost:.2f}" if not unknown_cost_calls else
                f"UNKNOWN (${cost:.2f} known; {unknown_cost_calls} call(s) unpriced or failed)")
    print(f"\n  Cost: {cost_txt} | Duration: {duration:.0f}s | Iterations: {iterations}")
    if score:
        print(f"  Score: {score}/10 | Verdict: {color}{BOLD}{verdict}{RESET}")
    else:
        print(f"  Verdict: {color}{BOLD}{verdict}{RESET}")
    print(f"{'=' * 60}\n")

# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    folder = args[0]
    max_iter = 3
    dry_run = False
    skip_preflight = False
    no_fix = False
    verbose = False
    evaluator_model = None
    fixer_model = None

    i = 1
    while i < len(args):
        arg = args[i]
        if arg == "--max" and i + 1 < len(args):
            max_iter = int(args[i + 1])
            i += 2
        elif arg.startswith("--max="):
            max_iter = int(arg.split("=")[1])
            i += 1
        elif arg == "--evaluator-model" and i + 1 < len(args):
            evaluator_model = args[i + 1]
            i += 2
        elif arg.startswith("--evaluator-model="):
            evaluator_model = arg.split("=", 1)[1]
            i += 1
        elif arg == "--fixer-model" and i + 1 < len(args):
            fixer_model = args[i + 1]
            i += 2
        elif arg.startswith("--fixer-model="):
            fixer_model = arg.split("=", 1)[1]
            i += 1
        elif arg == "--dry-run":
            dry_run = True
            i += 1
        elif arg == "--skip-preflight":
            skip_preflight = True
            i += 1
        elif arg == "--no-fix":
            no_fix = True
            i += 1
        elif arg == "--verbose":
            verbose = True
            i += 1
        elif arg == "--eval-only":
            # Backward compatibility: --eval-only = --no-fix
            no_fix = True
            i += 1
        elif arg == "--fix":
            # Backward compatibility: --fix is now the default (use --no-fix to disable)
            i += 1
        else:
            i += 1

    if not os.path.isdir(folder):
        print(f"ERROR: {folder} is not a directory.", file=sys.stderr)
        sys.exit(1)

    results = run(
        folder,
        max_iterations=max_iter,
        dry_run=dry_run,
        skip_preflight=skip_preflight,
        no_fix=no_fix,
        verbose=verbose,
        evaluator_model=evaluator_model,
        fixer_model=fixer_model,
    )

    # Exit code: 0 if any iteration passed, 1 otherwise
    if any(r.get("verdict") == "PASS" for r in results):
        sys.exit(0)
    else:
        sys.exit(1)
