#!/usr/bin/env python3
"""
WIX-EVAL-004 — the printed VERDICT line, the process exit code, and the --json
machine-readable payload must always agree, on every fixture shape (all axes/sigma/
assertions pass, an overall-score-only failure, a single-axis failure, a sigma-only
failure, a single failed SAT assertion, and an unexpected internal error).

Exercises the REAL decision path end to end: main() -> run() -> deploy_verdict() ->
_print_final() -> the exit(...) call. `score_prompt` and `run_assertions` are
monkeypatched so each scenario pins an EXACT (overall, per-axis, sigma, assertions)
shape regardless of what self-eval's heuristics currently compute for arbitrary text
-- convergence.py's own verdict/exit logic is never touched or reimplemented here, so
this cannot pass by tautology (unlike re-deriving "0 if deploy else 1" inside the test
itself, which would still pass even if the exit code reverted to the score-only gate).

Also runs the actual audited exit-gate-fixture prompt through convergence.py as a real
subprocess (no monkeypatching at all) and asserts it no longer reproduces the finding's
observed HOLD-printed/exit-0 combination.

Usage: python test_verdict_exit_agreement.py <REPO_ROOT>   (exit 0 = pass)
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

PLACEHOLDER_PROMPT = "You are a helpful assistant. Do the task. Respond in JSON format. Do not guess.\n"

BASE_ASSERTIONS = [
    ("has_role", True, "Prompt defines a role or persona"),
    ("has_task", True, "Prompt defines a clear task"),
    ("has_format", True, "Prompt specifies output format"),
    ("has_constraints", True, "Prompt has constraints/guardrails"),
    ("has_edge_cases", True, "Prompt handles edge cases"),
    ("no_hedge_words", True, "No hedge words (maybe, perhaps, possibly)"),
    ("no_filler", True, "No filler phrases"),
    ("has_structure", True, "Prompt has structural markup (headers or XML tags)"),
]

AXES = ["Clarity", "Completeness", "Efficiency", "Model Fit", "Failure Resilience"]

VERDICT_JSON_RE = re.compile(r"^VERDICT_JSON (\{.*\})$", re.MULTILINE)


def load_module(repo_root: Path):
    path = repo_root / "shared" / "scripts" / "convergence.py"
    spec = importlib.util.spec_from_file_location("convergence_uut", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def invoke_main(mod, argv):
    """Call the REAL main() with patched sys.argv; capture stdout and the SystemExit code."""
    old_argv = sys.argv
    sys.argv = ["convergence.py"] + argv
    exit_code = None
    out = io.StringIO()
    err = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                mod.main()
            except SystemExit as e:
                exit_code = e.code if e.code is not None else 0
    finally:
        sys.argv = old_argv
    return exit_code, out.getvalue(), err.getvalue()


def printed_verdict(stdout_text):
    if re.search(r"VERDICT: DEPLOY\b", stdout_text):
        return "DEPLOY"
    if re.search(r"VERDICT: HOLD\b", stdout_text):
        return "HOLD"
    return None  # no final report was ever printed (e.g. a crash)


def json_payload(stdout_text):
    m = VERDICT_JSON_RE.search(stdout_text)
    assert m, f"no VERDICT_JSON line found in stdout:\n{stdout_text}"
    return json.loads(m.group(1))


def run_scenario(mod, tmp_path, name, scores, assertions, expected_verdict, expected_deploy, expected_exit):
    """Patch score_prompt/run_assertions to a fixed shape, run the real main() on a
    throwaway prompt file, and assert the printed line, the exit code, and the JSON
    payload all agree with each other AND with the expected shape."""
    prompt_dir = tmp_path / name
    prompt_dir.mkdir()
    prompt_path = prompt_dir / "prompt.md"
    prompt_path.write_text(PLACEHOLDER_PROMPT, encoding="utf-8")

    fixed_scores = dict(scores)
    fixed_assertions = list(assertions)
    mod.score_prompt = lambda text, s=fixed_scores: dict(s)
    mod.run_assertions = lambda text, a=fixed_assertions: list(a)

    exit_code, out, err = invoke_main(mod, [str(prompt_path), "--max", "1", "--json"])

    seen_verdict = printed_verdict(out)
    payload = json_payload(out)

    assert exit_code == expected_exit, f"[{name}] exit_code={exit_code}, expected {expected_exit}"
    assert seen_verdict == expected_verdict, f"[{name}] printed VERDICT={seen_verdict}, expected {expected_verdict}"
    assert payload["verdict"] == expected_verdict, f"[{name}] json verdict={payload['verdict']}, expected {expected_verdict}"
    assert payload["deploy"] is expected_deploy, f"[{name}] json deploy={payload['deploy']}, expected {expected_deploy}"
    assert payload["exit_code"] == expected_exit, f"[{name}] json exit_code={payload['exit_code']}, expected {expected_exit}"
    assert payload["measured"] is False, f"[{name}] json 'measured' must be False (heuristic-only)"
    assert "not" in payload["note"].lower() and "measured deploy" in payload["note"].lower(), \
        f"[{name}] json note must state this is NOT a measured DEPLOY: {payload['note']!r}"
    # The core WIX-EVAL-004 invariant: exit 0 iff the printed line AND the json payload both say DEPLOY.
    assert (exit_code == 0) == (seen_verdict == "DEPLOY" == payload["verdict"]), \
        f"[{name}] exit code disagrees with the printed/json verdict — a consumer could read the wrong one"
    return exit_code, out, payload


def test_all_pass(mod, tmp_path):
    scores = {a: 9.5 for a in AXES}
    scores["overall"] = 9.5
    run_scenario(mod, tmp_path, "all_pass", scores, BASE_ASSERTIONS,
                 expected_verdict="DEPLOY", expected_deploy=True, expected_exit=0)


def test_score_fail(mod, tmp_path):
    # Every axis and sigma pass the bar; overall alone is below the 9.0 floor.
    scores = {a: 9.5 for a in AXES}
    scores["overall"] = 8.9
    run_scenario(mod, tmp_path, "score_fail", scores, BASE_ASSERTIONS,
                 expected_verdict="HOLD", expected_deploy=False, expected_exit=1)


def test_axis_fail(mod, tmp_path):
    # overall clears 9.0, but one axis is below the 7.0 floor.
    scores = {a: 9.5 for a in AXES}
    scores["Model Fit"] = 6.9
    scores["overall"] = 9.0
    run_scenario(mod, tmp_path, "axis_fail", scores, BASE_ASSERTIONS,
                 expected_verdict="HOLD", expected_deploy=False, expected_exit=1)


def test_sigma_fail(mod, tmp_path):
    # overall and every axis clear their floors, but the spread across axes exceeds
    # the dynamic sigma floor (0.45 for a short prompt) — the exact shape of the
    # audited exit-gate-fixture finding (9.5 overall, sigma 0.75, 8/8 assertions).
    scores = {"Clarity": 10.0, "Completeness": 9.5, "Efficiency": 10.0, "Model Fit": 8.0, "Failure Resilience": 10.0}
    scores["overall"] = 9.5
    run_scenario(mod, tmp_path, "sigma_fail", scores, BASE_ASSERTIONS,
                 expected_verdict="HOLD", expected_deploy=False, expected_exit=1)


def test_assertion_fail(mod, tmp_path):
    # overall, every axis and sigma all pass; exactly one SAT assertion fails.
    scores = {a: 9.5 for a in AXES}
    scores["overall"] = 9.5
    assertions = list(BASE_ASSERTIONS)
    assertions[2] = ("has_format", False, "Prompt specifies output format")
    run_scenario(mod, tmp_path, "assertion_fail", scores, assertions,
                 expected_verdict="HOLD", expected_deploy=False, expected_exit=1)


def test_crash(mod, tmp_path):
    """An unexpected exception during scoring must exit distinctly from BOTH DEPLOY (0)
    and HOLD (1) — a crash is not a scored HOLD, and must not be misread as one."""
    prompt_dir = tmp_path / "crash"
    prompt_dir.mkdir()
    prompt_path = prompt_dir / "prompt.md"
    prompt_path.write_text(PLACEHOLDER_PROMPT, encoding="utf-8")

    def boom(text):
        raise RuntimeError("simulated scorer crash")

    mod.score_prompt = boom
    mod.run_assertions = lambda text: list(BASE_ASSERTIONS)

    exit_code, out, err = invoke_main(mod, [str(prompt_path), "--max", "1", "--json"])

    assert exit_code == 3, f"[crash] exit_code={exit_code}, expected 3 (EXIT_INTERNAL_ERROR)"
    assert printed_verdict(out) is None, "[crash] must never print VERDICT: DEPLOY or VERDICT: HOLD"
    payload = json_payload(out)
    assert payload["verdict"] == "ERROR", payload
    assert payload["deploy"] is False, payload
    assert payload["exit_code"] == 3, payload
    assert "error" in payload and payload["error"], "[crash] json payload must carry the error message"
    assert exit_code not in (0, 1), "[crash] must not collide with DEPLOY(0) or HOLD(1)"


def test_bad_input(mod, tmp_path):
    """Missing file and empty file are controlled usage errors (exit 2) — distinct from
    both HOLD (1) and the internal-error path (3)."""
    missing = tmp_path / "bad_input" / "missing.md"
    exit_code, out, err = invoke_main(mod, [str(missing), "--json"])
    assert exit_code == 2, f"[missing_file] exit_code={exit_code}"
    payload = json_payload(out)
    assert payload["verdict"] == "ERROR" and payload["exit_code"] == 2, payload

    empty_dir = tmp_path / "bad_input"
    empty_dir.mkdir(exist_ok=True)
    empty = empty_dir / "empty.md"
    empty.write_text("", encoding="utf-8")
    exit_code, out, err = invoke_main(mod, [str(empty), "--json"])
    assert exit_code == 2, f"[empty_file] exit_code={exit_code}"
    payload = json_payload(out)
    assert payload["verdict"] == "ERROR" and payload["exit_code"] == 2, payload


def test_audit_fixture_real_subprocess(repo_root, tmp_path):
    """No monkeypatching: run the real, unpatched script as a subprocess against a
    writable copy of the audited challenge/exit-gate-fixture prompt (the finding's own
    repro). Before the fix: VERDICT: HOLD printed, process exit 0. Assert that
    combination is gone."""
    fixture_src = (repo_root / ".." / ".." / ".." / ".." / "audit-package-pinned" /
                    "extracted" / "challenge" / "exit-gate-fixture" / "prompt.md").resolve()
    if not fixture_src.is_file():
        # Fall back to the WIXIE_AUDIT_PACKAGE env var some hosts use, else skip gracefully —
        # the monkeypatched fixture matrix above already covers the same shape deterministically.
        env_path = os.environ.get("WIXIE_AUDIT_EXIT_GATE_FIXTURE")
        fixture_src = Path(env_path) if env_path else None
        if not fixture_src or not fixture_src.is_file():
            print("  (skip) audit exit-gate-fixture not found on this host; matrix scenarios already cover its shape")
            return

    work_dir = tmp_path / "audit_fixture"
    work_dir.mkdir()
    dest = work_dir / "prompt.md"
    dest.write_text(fixture_src.read_text(encoding="utf-8"), encoding="utf-8")
    os.chmod(dest, stat.S_IWRITE | stat.S_IREAD)  # the source is shipped read-only; convergence.py rewrites it in place

    proc = subprocess.run(
        [sys.executable, str(repo_root / "shared" / "scripts" / "convergence.py"), str(dest), "--max", "1"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    printed_hold = "VERDICT: HOLD" in proc.stdout
    assert not (printed_hold and proc.returncode == 0), (
        f"[audit_fixture] reproduced the finding: printed HOLD with exit 0 "
        f"(stdout tail: {proc.stdout[-400:]!r})"
    )
    # The fixture is known to score overall 9.5, sigma ~0.75 > floor 0.45, 8/8 assertions —
    # i.e. HOLD on sigma alone. Pin the now-correct behavior, not just "not the old bug".
    assert printed_hold and proc.returncode == 1, (
        f"[audit_fixture] expected VERDICT: HOLD with exit 1, got exit={proc.returncode}\n{proc.stdout[-600:]}"
    )


def main():
    repo_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(".").resolve()

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)

        # Each scenario gets a fresh module load so monkeypatches from one scenario
        # never leak into the next.
        for test_fn in (test_all_pass, test_score_fail, test_axis_fail, test_sigma_fail,
                         test_assertion_fail, test_crash, test_bad_input):
            mod = load_module(repo_root)
            test_fn(mod, tmp_path)

        test_audit_fixture_real_subprocess(repo_root, tmp_path)

    print("test_verdict_exit_agreement: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
