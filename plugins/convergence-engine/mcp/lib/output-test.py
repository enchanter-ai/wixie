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

Environment:
    ANTHROPIC_API_KEY must be set (unless --dry-run).

Cost awareness:
    Phase 1 is always free. Phase 2 calls the target model (~$1.20 for Opus).
    Phase 3 is mostly offline. Phase 4 uses Sonnet (~$0.10) only when needed.
    Default max 3 iterations = ~$3.90 worst case. Use --max to control.
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

def call_model(client, model, system_prompt, user_prompt, max_tokens=4096, temperature=1.0):
    """Call the Anthropic API and return (text, usage_dict)."""
    messages = [{"role": "user", "content": user_prompt}]
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "temperature": temperature,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    try:
        response = client.messages.create(**kwargs)
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
        return text, usage
    except Exception as e:
        return f"API_ERROR: {e}", {"input_tokens": 0, "output_tokens": 0}

# ─── Model ID mapping ────────────────────────────────────────────────────────

MODEL_MAP = {
    "claude-opus-4-6": "claude-opus-4-20250514",
    "claude-sonnet-4-6": "claude-sonnet-4-20250514",
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
}

EVAL_MODEL = "claude-sonnet-4-20250514"

def resolve_model(model_id):
    return MODEL_MAP.get(model_id, model_id)

# ─── Cost tracking ────────────────────────────────────────────────────────────

COST_PER_1K = {
    "claude-opus-4-20250514":   {"input": 0.015, "output": 0.075},
    "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    "claude-haiku-4-5-20251001": {"input": 0.0008, "output": 0.004},
}

def estimate_cost(model, usage):
    rates = COST_PER_1K.get(model, {"input": 0.01, "output": 0.05})
    return round(
        (usage["input_tokens"] / 1000 * rates["input"]) +
        (usage["output_tokens"] / 1000 * rates["output"]),
        4
    )

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

def run_generate(client, prompt_text, meta, folder, iteration):
    """Post prompt to target model. Returns (output, usage, cost, gen_info)."""
    target_model_id = meta.get("target_model", "claude-opus-4-6")
    target_model = resolve_model(target_model_id)
    config = meta.get("config", {})
    max_tokens = config.get("max_tokens", 16384)
    temperature = config.get("temperature", 1.0)
    is_system = config.get("system_prompt", True)

    gen_info = {
        "self_check_injected": False,
        "model": target_model_id,
    }

    # Inject self-check if available
    active_prompt = prompt_text
    if _self_check:
        try:
            active_prompt = _self_check.inject(prompt_text)
            gen_info["self_check_injected"] = True
            print(f"    Self-check injected {GREEN}\u2713{RESET}")
        except Exception as e:
            print_warn(f"self-check-inject error: {e}")
    else:
        print_warn("self-check-inject.py not found — skipping self-check injection")

    # POST to target model
    print(f"    Posted to {target_model_id}...", end="", flush=True)

    if is_system:
        output, usage = call_model(
            client, target_model, active_prompt,
            "Execute the instructions in the system prompt. Produce the complete output as specified.",
            max_tokens=max_tokens, temperature=temperature
        )
    else:
        output, usage = call_model(
            client, target_model, None, active_prompt,
            max_tokens=max_tokens, temperature=temperature
        )

    cost = estimate_cost(target_model, usage)
    output_words = len(output.split())

    if output.startswith("API_ERROR"):
        print(f" {RED}API ERROR{RESET}")
        print(f"      {output[:200]}")
        return None, usage, cost, gen_info

    print(f" {GREEN}{output_words:,} words{RESET} ({usage['output_tokens']:,} tokens, ${cost:.3f})")

    # Save output as reference
    output_path = os.path.join(folder, "output-reference.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)

    gen_info["output_words"] = output_words
    gen_info["output_tokens"] = usage["output_tokens"]

    return output, usage, cost, gen_info

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

def run_llm_evaluation(client, prompt_text, output, meta):
    """Use Sonnet to evaluate the output against the prompt's success criteria."""
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

    response_text, usage = call_model(
        client, EVAL_MODEL, None, eval_prompt,
        max_tokens=2048, temperature=0.0
    )
    try:
        json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.S)
        if json_match:
            return json.loads(json_match.group(1)), usage
        return json.loads(response_text), usage
    except json.JSONDecodeError:
        return {
            "criteria": [],
            "overall": "ERROR",
            "weakest_area": "Could not parse evaluator response",
            "top_fix": response_text[:500],
            "output_quality_score": 0,
            "raw_response": response_text[:1000],
        }, usage

def generate_fix(client, prompt_text, eval_result, test_results, scores, prompt_file):
    """Use Sonnet to generate a specific prompt fix based on failures."""
    failures = []
    for c in eval_result.get("criteria", []):
        if c.get("verdict") == "FAIL":
            failures.append(f"- Criterion {c['id']}: {c.get('reason', '')}. Fix: {c.get('fix', 'none')}")
    for t in test_results:
        if not t["passed"]:
            failures.append(f"- Test '{t['name']}' failed: missing keywords {t['missing']}")

    if not failures:
        return None, {"input_tokens": 0, "output_tokens": 0}

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

    response_text, usage = call_model(
        client, EVAL_MODEL, None, fix_prompt,
        max_tokens=1024, temperature=0.0
    )
    try:
        json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.S)
        if json_match:
            return json.loads(json_match.group(1)), usage
        return json.loads(response_text), usage
    except json.JSONDecodeError:
        return {"error": response_text[:500]}, usage

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
        from collections import OrderedDict

        # Score the prompt to find weakest axis
        if _self_eval:
            prompt_scores = {a: round(fn(prompt_text), 1)
                           for a, fn in zip(_self_eval.AXES, _self_eval.SCORERS)}
            weakest = min(_self_eval.AXES, key=lambda a: prompt_scores[a])
            if weakest in convergence.FIXERS and prompt_scores[weakest] < 9.0:
                prompt_text = convergence.FIXERS[weakest](prompt_text)
                if prompt_text != pre_text:
                    return prompt_text, True, f"Offline fix: improved {weakest} ({prompt_scores[weakest]}/10)"

    return prompt_text, False, None

def diagnose_and_fix(client, prompt_text, output, scores, details, meta, prompt_file, verbose=False):
    """Phase 4: Diagnose failures and apply fixes. Returns (new_prompt, fix_info, cost)."""
    fix_info = {"method": None, "applied": False, "description": None}
    cost = 0

    # Strategy 1: Try offline regex fix first (FREE)
    new_text, applied, desc = try_offline_fix(prompt_text, scores, details)
    if applied:
        fix_info = {"method": "offline_regex", "applied": True, "description": desc}
        print(f"    {GREEN}Offline fix applied{RESET}: {desc}")
        return new_text, fix_info, 0

    # Strategy 2: Use Sonnet for content-level diagnosis (CHEAP)
    print(f"    {CYAN}Diagnosing with Sonnet...{RESET}", end="", flush=True)
    eval_result, eval_usage = run_llm_evaluation(client, prompt_text, output, meta)
    eval_cost = estimate_cost(EVAL_MODEL, eval_usage)
    cost += eval_cost

    overall_verdict = eval_result.get("overall", "ERROR")
    quality_score = eval_result.get("output_quality_score", 0)

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
    if overall_verdict == "PASS" and scores.get("overall", 0) >= 7.0:
        fix_info = {"method": "none_needed", "applied": False, "description": "LLM evaluation passed"}
        return prompt_text, fix_info, cost

    # Phase 2: Sonnet API fallback for auto-fix — currently stub; manual-fix only
    # Generate and apply a targeted fix
    print(f"    {CYAN}Generating fix...{RESET}", end="", flush=True)
    test_results = details.get("test_results", [])
    fix, fix_usage = generate_fix(client, prompt_text, eval_result, test_results, scores, prompt_file)
    fix_cost = estimate_cost(EVAL_MODEL, fix_usage)
    cost += fix_cost

    if fix and "error" not in fix:
        new_text, applied = apply_fix(prompt_text, fix)
        if applied:
            reason = fix.get("reason", "no reason")
            print(f" {GREEN}Applied{RESET}: {reason[:80]}")
            fix_info = {"method": "sonnet_fix", "applied": True, "description": reason}
            # Save fixed prompt
            with open(prompt_file, "w", encoding="utf-8") as f:
                f.write(new_text)
            return new_text, fix_info, cost
        else:
            print(f" {YELLOW}Could not apply{RESET} (target string not found)")
            fix_info = {"method": "sonnet_fix", "applied": False, "description": "target not found"}
    else:
        err = fix.get("error", "unknown") if fix else "no fix generated"
        print(f" {RED}Fix failed{RESET}: {str(err)[:80]}")
        fix_info = {"method": "sonnet_fix", "applied": False, "description": str(err)[:200]}

    return prompt_text, fix_info, cost

# ─── Results persistence ──────────────────────────────────────────────────────

def save_results(folder, run_data):
    """Save comprehensive results to output-test-results.json."""
    path = os.path.join(folder, "output-test-results.json")
    data = {
        "engine": "hybrid-convergence",
        "version": "2.0",
        "last_run": datetime.now().isoformat(),
        "prompt_folder": folder,
        "model": run_data.get("model", "unknown"),
        "iterations": run_data.get("total_iterations", 0),
        "final_verdict": run_data.get("final_verdict", "NO_RUNS"),
        "final_score": run_data.get("final_score", 0),
        "total_cost_usd": round(run_data.get("total_cost", 0), 4),
        "total_duration_sec": round(run_data.get("total_duration", 0), 1),
        "cost_breakdown": run_data.get("cost_breakdown", {}),
        "preflight": run_data.get("preflight", {}),
        "iterations_detail": run_data.get("iterations_detail", []),
        "available_engines": run_data.get("available_engines", []),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path

# ─── Main engine ──────────────────────────────────────────────────────────────

def run(folder, max_iterations=3, dry_run=False, skip_preflight=False,
        no_fix=False, verbose=False):
    _init_colors()
    prompt_text, meta, tests, prompt_file, folder = load_prompt_folder(folder)

    target_model_id = meta.get("target_model", "claude-opus-4-6")
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

    run_start = time.time()
    total_cost = 0
    cost_breakdown = {"preflight": 0, "generate": 0, "evaluate": 0, "fix": 0}
    iterations_detail = []
    preflight_results = None
    final_verdict = "NO_RUNS"
    final_score = 0

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
            run_data = {
                "model": target_model_id,
                "total_iterations": 0,
                "final_verdict": "PREFLIGHT_FAIL",
                "final_score": 0,
                "total_cost": 0,
                "total_duration": round(time.time() - run_start, 1),
                "cost_breakdown": cost_breakdown,
                "preflight": preflight_results,
                "iterations_detail": [],
                "available_engines": available,
            }
            results_path = save_results(folder, run_data)
            print(f"\n  Results saved: {os.path.basename(results_path)}")
            _print_summary(0, 0, round(time.time() - run_start, 1), 0, "PREFLIGHT_FAIL")
            return []
    else:
        print(f"\n  {DIM}(--skip-preflight: Phase 1 skipped){RESET}")

    if dry_run:
        print(f"\n  {DIM}(--dry-run: stopping after Phase 1){RESET}")
        run_data = {
            "model": target_model_id,
            "total_iterations": 0,
            "final_verdict": "DRY_RUN",
            "final_score": preflight_results.get("prompt_quality", {}).get("overall", 0) if preflight_results else 0,
            "total_cost": 0,
            "total_duration": round(time.time() - run_start, 1),
            "cost_breakdown": cost_breakdown,
            "preflight": preflight_results,
            "iterations_detail": [],
            "available_engines": available,
        }
        results_path = save_results(folder, run_data)
        print(f"\n  Results saved: {os.path.basename(results_path)}")
        _print_summary(0, 0, round(time.time() - run_start, 1), 0,
                       preflight_results.get("prompt_quality", {}).get("verdict", "DRY_RUN") if preflight_results else "DRY_RUN")
        return []

    # ═══════════════════════════════════════════════════════════════════════════
    # Iteration loop: Phase 2 -> Phase 3 -> Phase 4 -> repeat
    # ═══════════════════════════════════════════════════════════════════════════
    client = get_client()

    for iteration in range(1, max_iterations + 1):
        iter_start = time.time()
        iter_cost = 0

        # ───────────────────────────────────────────────────────────────────────
        # Phase 2: Generate (COSTS MONEY)
        # ───────────────────────────────────────────────────────────────────────
        print_phase(f"Phase 2: Generate (iter {iteration})")
        output, usage, gen_cost, gen_info = run_generate(
            client, prompt_text, meta, folder, iteration
        )
        iter_cost += gen_cost
        cost_breakdown["generate"] += gen_cost

        if output is None:
            # API error — record and break
            iterations_detail.append({
                "iteration": iteration,
                "verdict": "API_ERROR",
                "cost_usd": round(iter_cost, 4),
                "duration_sec": round(time.time() - iter_start, 1),
            })
            final_verdict = "API_ERROR"
            total_cost += iter_cost
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
            "cost_usd": round(iter_cost, 4),
            "duration_sec": round(time.time() - iter_start, 1),
        }

        # ───────────────────────────────────────────────────────────────────────
        # Check exit: PASS
        # ───────────────────────────────────────────────────────────────────────
        if final_verdict == "PASS":
            iter_data["cost_usd"] = round(iter_cost, 4)
            iter_data["duration_sec"] = round(time.time() - iter_start, 1)
            iterations_detail.append(iter_data)
            total_cost += iter_cost

            print(f"\n  {'=' * 50}")
            print(f"  {GREEN}{BOLD}ALL CHECKS PASSED{RESET}")
            print(f"  {'=' * 50}")
            break

        # ───────────────────────────────────────────────────────────────────────
        # Phase 4: Learn & Fix (CHEAP)
        # ───────────────────────────────────────────────────────────────────────
        if no_fix:
            print(f"\n    {DIM}(--no-fix: skipping auto-fix){RESET}")
            iter_data["cost_usd"] = round(iter_cost, 4)
            iter_data["duration_sec"] = round(time.time() - iter_start, 1)
            iterations_detail.append(iter_data)
            total_cost += iter_cost
            continue

        if iteration < max_iterations:
            print_phase("Phase 4: Learn & Fix")
            new_prompt, fix_info, fix_cost = diagnose_and_fix(
                client, prompt_text, output, scores, details, meta, prompt_file,
                verbose=verbose
            )
            iter_cost += fix_cost
            cost_breakdown["fix"] += fix_cost
            iter_data["fix"] = fix_info

            if fix_info["applied"]:
                prompt_text = new_prompt

        iter_data["cost_usd"] = round(iter_cost, 4)
        iter_data["duration_sec"] = round(time.time() - iter_start, 1)
        iterations_detail.append(iter_data)
        total_cost += iter_cost

        print(f"\n  {DIM}--- Iteration {iteration} done (${iter_cost:.3f}) ---{RESET}")

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

    run_data = {
        "model": target_model_id,
        "total_iterations": total_iterations,
        "final_verdict": final_verdict,
        "final_score": final_score,
        "total_cost": total_cost,
        "total_duration": total_duration,
        "cost_breakdown": cost_breakdown,
        "preflight": preflight_results,
        "iterations_detail": iterations_detail,
        "available_engines": available,
    }
    results_path = save_results(folder, run_data)
    print(f"\n  Results saved: {os.path.basename(results_path)}")

    _print_summary(total_cost, total_iterations, total_duration, final_score, final_verdict)

    # Summary table for multi-iteration runs
    if len(iterations_detail) > 1:
        print(f"\n  {'─' * 55}")
        print(f"  {'Iter':>4}  {'Score':>7}  {'Verdict':>10}  {'Cost':>8}  {'Time':>6}")
        print(f"  {'─' * 55}")
        for it in iterations_detail:
            s = f"{it.get('scores', {}).get('overall', 0)}/10"
            v = it.get("verdict", "?")
            c = f"${it.get('cost_usd', 0):.3f}"
            t = f"{it.get('duration_sec', 0):.0f}s"
            color = GREEN if v == "PASS" else RED if v == "FAIL" else YELLOW
            print(f"  {it['iteration']:>4}  {s:>7}  {color}{v:>10}{RESET}  {c:>8}  {t:>6}")
        print(f"  {'─' * 55}")
        print(f"  {'Total':>4}  {'':>7}  {'':>10}  ${total_cost:>7.3f}  {total_duration:>5.0f}s")
        print()

    return iterations_detail

def _print_summary(cost, iterations, duration, score, verdict):
    color = GREEN if verdict == "PASS" else YELLOW if verdict in ("MARGINAL", "DRY_RUN") else RED
    print(f"\n  Cost: ${cost:.2f} | Duration: {duration:.0f}s | Iterations: {iterations}")
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

    i = 1
    while i < len(args):
        arg = args[i]
        if arg == "--max" and i + 1 < len(args):
            max_iter = int(args[i + 1])
            i += 2
        elif arg.startswith("--max="):
            max_iter = int(arg.split("=")[1])
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
    )

    # Exit code: 0 if any iteration passed, 1 otherwise
    if any(r.get("verdict") == "PASS" for r in results):
        sys.exit(0)
    else:
        sys.exit(1)
