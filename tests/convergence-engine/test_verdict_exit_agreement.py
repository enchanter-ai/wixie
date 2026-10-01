#!/usr/bin/env python3
"""
WIX-EVAL-004 — the printed VERDICT line, the process exit code, and the --json /
--json-out machine-readable payload must always agree, on every fixture shape (all
axes/sigma/assertions pass, an overall-score-only failure, a single-axis failure, a
sigma-only failure, a single failed SAT assertion, an unexpected internal error, and
bad CLI input) — and the machine verdict must be emitted exactly once per run (N1).

Exercises the REAL decision path end to end: main() -> run() -> deploy_verdict() ->
_print_final() -> the exit(...) call. `score_prompt` and `run_assertions` are
monkeypatched so each scenario pins an EXACT (overall, per-axis, sigma, assertions)
shape regardless of what self-eval's heuristics currently compute for arbitrary text
-- convergence.py's own verdict/exit logic is never touched or reimplemented here, so
this cannot pass by tautology (unlike re-deriving "0 if deploy else 1" inside the test
itself, which would still pass even if the exit code reverted to the score-only gate).

Also runs a real subprocess of the (unpatched) script against an in-repo copy of the
audited challenge/exit-gate-fixture prompt and asserts it no longer reproduces the
finding's observed HOLD-printed/exit-0 combination. The fixture is carried inside this
test directory (fixtures/exit-gate-fixture-prompt.md) rather than located via a
host-relative path outside the repo, so this case runs — and cannot silently skip — in
any checkout, including the canonical repo without the wixie-remediation harness
alongside it.

Covers the independent verifier's follow-up notes (tranche1/verify/conv/VERIFICATION.md):
  N1 — a save_learnings() failure after the verdict is printed used to emit a second,
       contradictory VERDICT_JSON (see test_n1_single_machine_verdict_on_save_failure).
  N2 — `--max abc` / bare `--max` / bare `--json-out` used to raise uncaught and exit 1,
       the documented HOLD code (see test_n2_bad_cli_arguments).
  test gaps — test_axis_fail now isolates the axis clause (sigma passes in that fixture);
       the audit-fixture case no longer depends on a host-relative path; every scenario
       below also exercises --json-out, not just --json.

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

# Private temp root (WIX-TEST-ENV-001, tests/_test_root.py): scratch never lands in shared temp.
_root_spec = importlib.util.spec_from_file_location(
    "wixie_test_root", Path(__file__).resolve().parents[1] / "_test_root.py")
_root_mod = importlib.util.module_from_spec(_root_spec)
_root_spec.loader.exec_module(_root_mod)
_root_mod.ensure_test_root()

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

THIS_DIR = Path(__file__).resolve().parent
AUDIT_FIXTURE_COPY = THIS_DIR / "fixtures" / "exit-gate-fixture-prompt.md"


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


def single_json_payload(stdout_text, label):
    """Find the VERDICT_JSON line(s) and require EXACTLY one (N1)."""
    matches = VERDICT_JSON_RE.findall(stdout_text)
    assert len(matches) == 1, (
        f"[{label}] expected exactly ONE VERDICT_JSON line, found {len(matches)}:\n"
        f"{matches}\nfull stdout:\n{stdout_text}"
    )
    return json.loads(matches[0])


def make_prompt(tmp_path, name, content=PLACEHOLDER_PROMPT):
    prompt_dir = tmp_path / name
    prompt_dir.mkdir()
    prompt_path = prompt_dir / "prompt.md"
    prompt_path.write_text(content, encoding="utf-8")
    return prompt_dir, prompt_path


def run_scenario(mod, tmp_path, name, scores, assertions, expected_verdict, expected_deploy, expected_exit):
    """Patch score_prompt/run_assertions to a fixed shape, run the real main() on a
    throwaway prompt file with BOTH --json and --json-out, and assert the printed line,
    the process exit code, the stdout JSON payload, and the --json-out file all agree
    with each other AND with the expected shape."""
    prompt_dir, prompt_path = make_prompt(tmp_path, name)
    json_out_path = prompt_dir / "verdict.json"

    fixed_scores = dict(scores)
    fixed_assertions = list(assertions)
    mod.score_prompt = lambda text, s=fixed_scores: dict(s)
    mod.run_assertions = lambda text, a=fixed_assertions: list(a)

    exit_code, out, err = invoke_main(
        mod, [str(prompt_path), "--max", "1", "--json", "--json-out", str(json_out_path)])

    seen_verdict = printed_verdict(out)
    payload = single_json_payload(out, name)

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

    # --json-out coverage (test gap): the file must exist and match stdout's payload exactly.
    assert json_out_path.is_file(), f"[{name}] --json-out file was not written"
    file_payload = json.loads(json_out_path.read_text(encoding="utf-8"))
    assert file_payload == payload, (
        f"[{name}] --json-out file disagrees with stdout VERDICT_JSON:\n{file_payload}\nvs\n{payload}"
    )
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
    """overall clears 9.0 and ONLY one axis is below the 7.0 floor — sigma must PASS in
    this fixture (verifier note: axis_fail previously also failed sigma, so it could not
    prove the axis clause alone forces HOLD). Axes are kept tight around the 7.0
    boundary (7.0 x4, 6.9 x1) so their spread stays far under the 0.45 floor."""
    scores = {a: 7.0 for a in AXES}
    scores["Model Fit"] = 6.9
    scores["overall"] = 9.5
    _, _, payload = run_scenario(mod, tmp_path, "axis_fail", scores, BASE_ASSERTIONS,
                                  expected_verdict="HOLD", expected_deploy=False, expected_exit=1)
    assert payload["sigma_pass"] is True, (
        f"[axis_fail] sigma must PASS so this fixture isolates the axis clause, got {payload}"
    )
    assert payload["axes"]["Model Fit"] < 7.0 and all(
        payload["axes"][a] >= 7.0 for a in AXES if a != "Model Fit"
    ), f"[axis_fail] exactly one axis should be below 7.0: {payload['axes']}"


def test_sigma_fail(mod, tmp_path):
    # overall and every axis clear their floors, but the spread across axes exceeds
    # the dynamic sigma floor (0.45 for a short prompt) — the exact shape of the
    # audited exit-gate-fixture finding (9.5 overall, sigma 0.75, 8/8 assertions).
    scores = {"Clarity": 10.0, "Completeness": 9.5, "Efficiency": 10.0, "Model Fit": 8.0, "Failure Resilience": 10.0}
    scores["overall"] = 9.5
    _, _, payload = run_scenario(mod, tmp_path, "sigma_fail", scores, BASE_ASSERTIONS,
                                  expected_verdict="HOLD", expected_deploy=False, expected_exit=1)
    assert payload["sigma_pass"] is False, f"[sigma_fail] sigma must FAIL to isolate this clause: {payload}"
    assert all(payload["axes"][a] >= 7.0 for a in AXES) and payload["overall"] >= 9.0, (
        f"[sigma_fail] every axis and overall should otherwise pass: {payload}"
    )


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
    prompt_dir, prompt_path = make_prompt(tmp_path, "crash")
    json_out_path = prompt_dir / "verdict.json"

    def boom(text):
        raise RuntimeError("simulated scorer crash")

    mod.score_prompt = boom
    mod.run_assertions = lambda text: list(BASE_ASSERTIONS)

    exit_code, out, err = invoke_main(
        mod, [str(prompt_path), "--max", "1", "--json", "--json-out", str(json_out_path)])

    assert exit_code == 3, f"[crash] exit_code={exit_code}, expected 3 (EXIT_INTERNAL_ERROR)"
    assert printed_verdict(out) is None, "[crash] must never print VERDICT: DEPLOY or VERDICT: HOLD"
    payload = single_json_payload(out, "crash")
    assert payload["verdict"] == "ERROR", payload
    assert payload["deploy"] is False, payload
    assert payload["exit_code"] == 3, payload
    assert "error" in payload and payload["error"], "[crash] json payload must carry the error message"
    assert exit_code not in (0, 1), "[crash] must not collide with DEPLOY(0) or HOLD(1)"

    assert json_out_path.is_file(), "[crash] --json-out file was not written for the error path"
    file_payload = json.loads(json_out_path.read_text(encoding="utf-8"))
    assert file_payload == payload, f"[crash] --json-out disagrees with stdout: {file_payload} vs {payload}"


def test_bad_input(mod, tmp_path):
    """Missing file and empty file are controlled usage errors (exit 2) — distinct from
    both HOLD (1) and the internal-error path (3)."""
    bad_input_dir = tmp_path / "bad_input"
    bad_input_dir.mkdir()  # exists up front so --json-out's target directory is always valid
    missing = bad_input_dir / "missing.md"
    json_out_missing = bad_input_dir / "verdict-missing.json"
    exit_code, out, err = invoke_main(mod, [str(missing), "--json", "--json-out", str(json_out_missing)])
    assert exit_code == 2, f"[missing_file] exit_code={exit_code}"
    payload = single_json_payload(out, "missing_file")
    assert payload["verdict"] == "ERROR" and payload["exit_code"] == 2, payload
    assert json.loads(json_out_missing.read_text(encoding="utf-8")) == payload

    empty_dir = bad_input_dir
    empty = empty_dir / "empty.md"
    empty.write_text("", encoding="utf-8")
    json_out_empty = empty_dir / "verdict-empty.json"
    exit_code, out, err = invoke_main(mod, [str(empty), "--json", "--json-out", str(json_out_empty)])
    assert exit_code == 2, f"[empty_file] exit_code={exit_code}"
    payload = single_json_payload(out, "empty_file")
    assert payload["verdict"] == "ERROR" and payload["exit_code"] == 2, payload
    assert json.loads(json_out_empty.read_text(encoding="utf-8")) == payload


def test_n1_single_machine_verdict_on_save_failure(mod, tmp_path):
    """N1 (verifier note): if save_learnings() fails AFTER _print_final() has already
    printed a scored verdict, the process must still emit exactly one VERDICT_JSON line —
    matching the ACTUAL exit code (3, internal error) — not a first scored line (e.g.
    DEPLOY/exit_code 0) followed by a second, contradictory ERROR/exit_code 3 line.

    Reproduced the same way the verifier did: no monkeypatching of save_learnings itself,
    just a pre-existing learnings.json made read-only so its real `open(path, "w")` raises
    PermissionError. The content is deliberately invalid JSON so load_learnings() takes its
    except-branch and returns the full default schema (avoiding an unrelated KeyError from
    a schema-incomplete prior file, which would also crash but for the wrong reason)."""
    prompt_dir, prompt_path = make_prompt(tmp_path, "n1_save_failure")
    learnings_path = prompt_dir / "learnings.json"
    learnings_path.write_text("not valid json", encoding="utf-8")
    os.chmod(learnings_path, stat.S_IREAD)
    try:
        # A shape that reaches DEPLOY on iteration 1, so _print_final() runs (and, pre-fix,
        # would have already emitted VERDICT_JSON) before save_learnings() is even reached.
        scores = {a: 9.5 for a in AXES}
        scores["overall"] = 9.5
        mod.score_prompt = lambda text, s=scores: dict(s)
        mod.run_assertions = lambda text: list(BASE_ASSERTIONS)

        json_out_path = prompt_dir / "verdict.json"
        exit_code, out, err = invoke_main(
            mod, [str(prompt_path), "--max", "1", "--json", "--json-out", str(json_out_path)])

        assert exit_code == 3, f"[N1] expected exit 3 (save_learnings failure is an internal error), got {exit_code}"
        payload = single_json_payload(out, "N1")
        assert payload["exit_code"] == exit_code == 3, f"[N1] payload/exit disagree: {payload}"
        assert payload["verdict"] == "ERROR", f"[N1] must not report the pre-crash scored verdict: {payload}"
        assert payload["deploy"] is False, payload
        # The human report WAS printed (scoring itself succeeded) — only the machine verdict
        # must not duplicate/contradict itself.
        assert printed_verdict(out) == "DEPLOY", "[N1] scoring should have completed and printed DEPLOY before the crash"
        if json_out_path.is_file():
            assert json.loads(json_out_path.read_text(encoding="utf-8")) == payload
    finally:
        os.chmod(learnings_path, stat.S_IWRITE | stat.S_IREAD)


def test_n2_bad_cli_arguments(mod, tmp_path):
    """N2 (verifier note): `--max abc`, a bare trailing `--max`, and a bare trailing
    `--json-out` used to raise an uncaught ValueError/IndexError and exit 1 — the
    documented HOLD code. All three must instead exit 2 (EXIT_USAGE_ERROR) with an
    ERROR machine verdict, same as any other bad-input case."""
    _, prompt_path = make_prompt(tmp_path, "n2_bad_args")

    cases = {
        "max_non_integer": ["--json", str(prompt_path), "--max", "abc"],
        "max_missing_value": ["--json", str(prompt_path), "--max"],          # --max is the last token
        "json_out_missing_value": ["--json", str(prompt_path), "--json-out"],  # --json-out is the last token
    }
    for label, argv in cases.items():
        exit_code, out, err = invoke_main(mod, argv)
        assert exit_code == 2, f"[N2:{label}] exit_code={exit_code}, expected 2 (EXIT_USAGE_ERROR), not 1 (HOLD)"
        payload = single_json_payload(out, f"N2:{label}")
        assert payload["verdict"] == "ERROR" and payload["exit_code"] == 2, f"[N2:{label}] {payload}"
        assert "error" in payload and payload["error"], f"[N2:{label}] payload must carry the error message"


def test_audit_fixture_real_subprocess(repo_root, tmp_path):
    """No monkeypatching: run the real, unpatched script as a subprocess against a
    writable copy of the audited challenge/exit-gate-fixture prompt (the finding's own
    repro). The fixture text is carried in-repo (fixtures/exit-gate-fixture-prompt.md),
    not located via a path relative to the wixie-remediation harness, so this assertion
    always runs and never silently skips. Before the fix: VERDICT: HOLD printed, process
    exit 0. Assert that combination is gone and pin the now-correct HOLD/exit-1 shape."""
    assert AUDIT_FIXTURE_COPY.is_file(), f"missing in-repo audit fixture copy: {AUDIT_FIXTURE_COPY}"

    work_dir = tmp_path / "audit_fixture"
    work_dir.mkdir()
    dest = work_dir / "prompt.md"
    dest.write_text(AUDIT_FIXTURE_COPY.read_text(encoding="utf-8"), encoding="utf-8")
    os.chmod(dest, stat.S_IWRITE | stat.S_IREAD)  # convergence.py rewrites the prompt file in place

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
                         test_assertion_fail, test_crash, test_bad_input,
                         test_n1_single_machine_verdict_on_save_failure,
                         test_n2_bad_cli_arguments):
            mod = load_module(repo_root)
            test_fn(mod, tmp_path)

        test_audit_fixture_real_subprocess(repo_root, tmp_path)

    print("test_verdict_exit_agreement: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
