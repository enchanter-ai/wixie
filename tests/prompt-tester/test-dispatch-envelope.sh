#!/usr/bin/env bash
# Regression tests for WIX-DISPATCH-001: the dispatch envelope must separate
# transport success from task outcome, and every terminal state must be distinguishable.
#
# Deterministic fake provider: subprocess.run is replaced, so no CLI is launched, no model is
# called and nothing is spent. Phase 4 requires these to pass before any further live call.
set -euo pipefail
REPO_ROOT="${1:-.}"

python - "$REPO_ROOT" <<'PY'
import importlib.util, pathlib, subprocess, sys, types

root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("dispatch", root / "shared" / "scripts" / "dispatch-via-cli.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

failures = []


class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def with_fake(stdout="", returncode=0, stderr="", raises=None):
    """Replace subprocess.run for both the capability probe and the dispatch call."""
    def fake_run(cmd, *a, **kw):
        if len(cmd) > 1 and cmd[1] == "--version":
            return FakeProc(0, "2.1.278 (Claude Code)", "")
        if raises is not None:
            raise raises
        return FakeProc(returncode, stdout, stderr)
    return fake_run


def run_case(name, *, stdout="", returncode=0, stderr="", raises=None, expect_status=None,
             expect_cause_contains=None, expect_result=None):
    orig = d.subprocess.run
    d.subprocess.run = with_fake(stdout, returncode, stderr, raises)
    try:
        env = d.dispatch_one(prompt="hello", model="haiku", timeout=5, max_retries=1)
    except Exception as exc:  # a terminal state must never escape as a traceback
        failures.append(f"{name}: raised {type(exc).__name__}: {exc}")
        return None
    finally:
        d.subprocess.run = orig

    if expect_status and env.get("status") != expect_status:
        failures.append(f"{name}: status={env.get('status')!r}, expected {expect_status!r} "
                        f"(cause={env.get('cause')!r})")
    if expect_cause_contains and expect_cause_contains.lower() not in str(env.get("cause", "")).lower():
        failures.append(f"{name}: cause {env.get('cause')!r} does not mention {expect_cause_contains!r}")
    if expect_result is not None and env.get("result") != expect_result:
        failures.append(f"{name}: result={env.get('result')!r}, expected {expect_result!r}")
    return env


# --- the defect: exit 0 + valid envelope + NO output was reported as a completed dispatch -------
run_case("missing result key", stdout='{"total_cost_usd":0.01}',
         expect_status="error", expect_cause_contains="empty model output")
run_case("null result", stdout='{"result":null}',
         expect_status="error", expect_cause_contains="empty model output")
run_case("empty string result", stdout='{"result":""}',
         expect_status="error", expect_cause_contains="empty model output")
run_case("whitespace-only result", stdout='{"result":"   \\n  "}',
         expect_status="error", expect_cause_contains="empty model output")

# --- genuine success still succeeds --------------------------------------------------------------
ok = run_case("real output", stdout='{"result":"the answer","total_cost_usd":0.02}',
              expect_status="ok", expect_result="the answer")

# --- a JSON scalar must not escape as AttributeError ---------------------------------------------
run_case("non-object JSON", stdout='"just a string"',
         expect_status="error", expect_cause_contains="parse failure")
run_case("JSON array", stdout='[]',
         expect_status="error", expect_cause_contains="parse failure")

# --- other terminal states stay distinguishable ---------------------------------------------------
run_case("unparseable stdout", stdout='not json at all',
         expect_status="error", expect_cause_contains="parse failure")
run_case("self-reported error", stdout='{"is_error":true,"result":"boom"}',
         expect_status="error")
run_case("wall-clock timeout", raises=subprocess.TimeoutExpired(cmd="claude", timeout=5),
         expect_status="error", expect_cause_contains="timeout")
run_case("spawn failure", raises=OSError("no such file"),
         expect_status="blocked")
run_case("auth failure", returncode=1, stderr="401 unauthorized",
         expect_status="blocked")

# --- transport success must be recorded separately from task outcome ------------------------------
#
# The first version of this asserted transport_ok is True on the two envelopes that had it. An
# independent reviewer showed the field was ABSENT from six of eight terminal returns, so a
# consumer got None for a timeout and None for is_error=true - indistinguishable between
# "transport failed" and "transport fine, task failed", which is the whole distinction the field
# exists to carry. Asserting only the True cases could never have caught that. Every envelope is
# now checked, and False is asserted where transport genuinely did not deliver an answer.
empty = run_case("transport_ok on empty output", stdout='{"result":null}', expect_status="error")
if empty is not None and empty.get("transport_ok") is not True:
    failures.append("empty output: transport_ok should be True - the CLI did answer; the TASK failed")
if ok is not None and ok.get("transport_ok") is not True:
    failures.append("real output: transport_ok should be True")

# transport genuinely failed: the CLI never delivered a model answer.
for label, kwargs in (
    ("wall-clock timeout", dict(raises=subprocess.TimeoutExpired(cmd="claude", timeout=5))),
    ("spawn failure", dict(raises=OSError("no such file"))),
    ("auth failure", dict(returncode=1, stderr="401 unauthorized")),
    ("provider error", dict(returncode=1, stderr="500 internal server error")),
    ("unparseable stdout", dict(stdout="not json at all")),
):
    env = run_case(f"transport_ok False on {label}", **kwargs)
    if env is None:
        continue
    if "transport_ok" not in env:
        failures.append(f"{label}: transport_ok is absent, so a consumer cannot tell a transport "
                        "failure from a task failure")
    elif env["transport_ok"] is not False:
        failures.append(f"{label}: transport_ok is {env['transport_ok']!r}, expected False - "
                        "the CLI never delivered a model answer")

# the task failed but the transport did not: is_error=true means the CLI answered.
task_err = run_case("transport_ok True on is_error", stdout='{"is_error":true,"result":"boom"}',
                    expect_status="error")
if task_err is not None and task_err.get("transport_ok") is not True:
    failures.append("is_error=true: transport_ok should be True - the CLI answered and the TASK "
                    "reported the error")

# exhaustive: no dispatch envelope may omit the field at all.
import ast as _ast
_src = (root / "shared" / "scripts" / "dispatch-via-cli.py").read_text(encoding="utf-8")
for _node in _ast.walk(_ast.parse(_src)):
    if not isinstance(_node, _ast.Dict):
        continue
    _keys = [k.value for k in _node.keys
             if isinstance(k, _ast.Constant) and isinstance(k.value, str)]
    if "status" in _keys and "result" in _keys and "transport_ok" not in _keys:
        failures.append(f"dispatch-via-cli.py:{_node.lineno}: an envelope returns status and "
                        "result but no transport_ok")

if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)
print("PASS: 13 dispatch terminal states distinguishable; empty output is not success; "
      "transport_ok is present on every envelope and False wherever transport failed")
PY
