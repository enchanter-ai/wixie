#!/usr/bin/env python3
"""The one canonical DEPLOY bar (WIX-SEC-REPORT-VERDICT-001, D17). Stdlib only.

Every Wixie surface that states a DEPLOY/HOLD verdict derives it here: convergence.py
(deploy_verdict, the printed VERDICT line, the exit code, --json/--json-out) and report-gen.py
(the report's verdict block, header badge and machine-readable status). No surface may keep a
second, weaker rule of its own.

The bar (all must hold, otherwise HOLD):
    overall >= 9.0
    every one of the 5 axes >= 7.0
    sigma <= sigma floor      sigma = population stdev of the 5 axis scores;
                              floor = self-eval.dynamic_sigma_floor(text): 0.45 for prompts of
                              <= 1000 words (the CLAUDE.md figure), 0.60 above 1000, 0.75 above
                              2000. CLAUDE.md writes "sigma < 0.45"; the implementation has always
                              used "<= dynamic floor". That rule is kept here unchanged.
    all 8 SAT assertions present and passing (run_assertions below; exactly 8, no fewer)

Missing or malformed evidence (an absent or non-numeric axis/overall/floor, an assertion set
that is not the 8 canonical results) is never DEPLOY: evaluate() returns UNVERIFIED.

This is a heuristic verdict (regex/structure scorers, zero model API calls), never a measured
one -- see convergence.py MACHINE_VERDICT_NOTE and efficacy-replay.py.

CLI (read-only; for agents and skills that must state a verdict, e.g. the translate adapter):
    python -B deploy_bar.py <prompt-file>
prints one JSON object (the evaluate() result plus "prompt_file") and exits
    0 DEPLOY, 1 HOLD, 2 usage error, 3 UNVERIFIED (no scorable evidence).
Copy its "verdict" field; never restate the bar.
"""
import os
import re
import statistics
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEPLOY = "DEPLOY"
HOLD = "HOLD"
UNVERIFIED = "UNVERIFIED"

OVERALL_MIN = 9.0
AXIS_MIN = 7.0
ASSERTION_NAMES = ("has_role", "has_task", "has_format", "has_constraints",
                   "has_edge_cases", "no_hedge_words", "no_filler", "has_structure")


def _load(name, filename):
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPT_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_eval = _load("wixie_self_eval", "self-eval.py")
AXES = list(_eval.AXES)
SCORERS = list(_eval.SCORERS)
# metadata.json axis keys (prompt-creator / prompt-improver schema) -> canonical axis names.
METADATA_AXIS_KEYS = {"clarity": "Clarity", "completeness": "Completeness", "efficiency": "Efficiency",
                      "model_fit": "Model Fit", "failure_resilience": "Failure Resilience"}


def score(text):
    """The canonical 5-axis scores (self-eval scorers, rounded to 0.1) and their rounded mean."""
    scores = {a: round(fn(text), 1) for a, fn in zip(AXES, SCORERS)}
    scores["overall"] = round(sum(scores[a] for a in AXES) / len(AXES), 1)
    return scores


def sigma_floor(text):
    return _eval.dynamic_sigma_floor(text)


def run_assertions(text):
    """The 8 SAT assertions: binary pass/fail checks. Returns [(name, passed, description)]."""
    results = []
    tl = text.lower()

    results.append(("has_role", bool(re.search(r'\b(you are|act as|role:|your role|your job)\b', tl)),
                     "Prompt defines a role or persona"))
    results.append(("has_task", bool(re.search(r'\b(task:|objective:|goal:|your job|you will|you should|analyze|generate|create|build|extract|classify|summari[sz]e|translate|rewrite|convert|parse|identify|detect|evaluate|score|rank|label|produce|write|compose|answer|respond)\b', tl)),
                     "Prompt defines a clear task"))
    results.append(("has_format", bool(re.search(r'\b(output format|respond in|format:|json|xml|markdown)\b|<output|<format', tl)),
                     "Prompt specifies output format"))
    results.append(("has_constraints", bool(re.search(r"\b(do not|don't|never|avoid|constraint|must not)\b", tl)),
                     "Prompt has constraints/guardrails"))
    results.append(("has_edge_cases", bool(re.search(r'\b(if.{0,20}(empty|invalid|error|missing)|edge case|fallback|if unsure)\b', tl)),
                     "Prompt handles edge cases"))
    results.append(("no_hedge_words", not bool(re.search(r'\b(maybe|perhaps|possibly|somewhat|might want to)\b', tl)),
                     "No hedge words (maybe, perhaps, possibly)"))
    results.append(("no_filler", not bool(re.search(r"(it's worth noting|please note that|keep in mind|in order to)", tl)),
                     "No filler phrases"))
    results.append(("has_structure", bool(re.search(r'(^#{1,3}\s|\n#{1,3}\s|<\w+>)', text)),
                     "Prompt has structural markup (headers or XML tags)"))

    return results


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def evaluate(scores, assertions, floor):
    """Apply the bar. scores: {axis name: number, ..., "overall": number}; assertions: the
    run_assertions() result ((name, passed, desc) tuples; bare bools accepted); floor: the sigma
    floor. Returns a dict: verdict (DEPLOY | HOLD | UNVERIFIED), deploy, the inputs used, and
    `failed` (why it is not DEPLOY). Never raises on malformed input."""
    scores = scores if isinstance(scores, dict) else {}
    missing = []
    axes = {a: scores.get(a) for a in AXES}
    overall = scores.get("overall")
    missing += [f"axis {a}" for a, v in axes.items() if not _num(v)]
    if not _num(overall):
        missing.append("overall")
    if not _num(floor):
        missing.append("sigma floor")
    results = []
    for a in (assertions if isinstance(assertions, (list, tuple)) else []):
        results.append(bool(a[1]) if isinstance(a, (list, tuple)) and len(a) > 1 else a is True)
    if len(results) != len(ASSERTION_NAMES):
        missing.append(f"SAT assertions ({len(results)} of {len(ASSERTION_NAMES)} results)")

    sigma = statistics.pstdev([axes[a] for a in AXES]) if all(_num(v) for v in axes.values()) else None
    out = {"overall": overall, "axes": axes, "sigma": sigma, "sigma_floor": floor,
           "assertions_passed": sum(results), "assertions_total": len(results)}
    if missing:
        out.update(verdict=UNVERIFIED, deploy=False, sigma_pass=None,
                   failed=["missing evidence: " + ", ".join(missing)])
        return out

    failed = []
    if not overall >= OVERALL_MIN:
        failed.append(f"overall {overall} < {OVERALL_MIN}")
    failed += [f"{a} {v} < {AXIS_MIN}" for a, v in axes.items() if not v >= AXIS_MIN]
    if not sigma <= floor:
        failed.append(f"sigma {sigma:.2f} > floor {floor:.2f}")
    if not all(results):
        failed.append(f"SAT {sum(results)}/{len(results)}")
    deploy = not failed
    out.update(verdict=DEPLOY if deploy else HOLD, deploy=deploy, sigma_pass=sigma <= floor,
               failed=failed)
    return out


def evaluate_text(text):
    """Score `text` (the scorer view of a prompt) and apply the bar."""
    if not isinstance(text, str) or not text.strip():
        return evaluate({}, [], None)
    assertions = run_assertions(text)
    result = evaluate(score(text), assertions, sigma_floor(text))
    result["assertions"] = {name: bool(ok) for name, ok, _ in assertions}
    return result


def evaluate_file(path):
    """Evaluate a prompt file as the scorers see it (prompt_regions view, newlines normalised,
    exactly like self-eval.py). An unreadable, undecodable or malformed file is UNVERIFIED."""
    try:
        pr = _load("prompt_regions", "prompt_regions.py")
        text = pr.read_view(path, normalize_newlines=True)
    except (OSError, ValueError) as e:  # RegionError and UnicodeDecodeError are ValueErrors
        result = evaluate({}, [], None)
        result["failed"] = [f"prompt not scorable: {type(e).__name__}: {e}"]
        return result
    return evaluate_text(text)


def main(argv):
    import json
    if len(argv) != 1:
        print("Usage: python -B deploy_bar.py <prompt-file>", file=sys.stderr)
        return 2
    result = evaluate_file(argv[0])
    result["prompt_file"] = argv[0]
    print(json.dumps(result, sort_keys=True))
    return {DEPLOY: 0, HOLD: 1}.get(result["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
