#!/usr/bin/env bash
# Regression tests for WIX-EFF-001: efficacy-replay.py must never record a transport/runtime
# failure (auth failure, empty output, invalid/garbled envelope, a hung trial, a provider error)
# as a measured task rejection. A trial whose transport failed contributes zero Wilson-count
# evidence; a run with zero valid measurements reports a distinct NO_MEASUREMENT verdict in
# stdout AND verdict.json, never REJECT/ACCEPT, with its own documented exit code (3). Genuine
# task rejection (a well-formed run that fails the corpus's expect/reject patterns) must still
# be scored as REJECT, and a mixed run (some trials transport-fail, others measure) must compute
# its verdict only over the trials that actually measured something.
#
# MOCKS THE MODEL CALL: monkeypatches the module's `subprocess.run`, exactly like
# tests/convergence-engine/test_corpus_measure.py does — no real `claude -p` invocation, no
# tokens, no network. Runs hermetically against a temp corpus dir.
set -euo pipefail
REPO_ROOT="${1:-.}"

PYTHONIOENCODING=utf-8 python - "$REPO_ROOT" <<'PY'
import importlib.util, io, json, contextlib, pathlib, subprocess, sys, tempfile
from types import SimpleNamespace

root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("efficacy_replay", root / "shared" / "scripts" / "efficacy-replay.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

failures = []
def check(name, cond, detail=""):
    if not cond:
        failures.append(f"{name}: {detail}")

def stream_json_for(text: str) -> str:
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})

GOOD_RESPONSE = (
    "- Recommendation: I recommend option A because skipping caching is invalid.\n"
    "- You should ship behind a flag.\n"
    "- The input is empty or invalid, so there is no date to return.\n"
)
BAD_RESPONSE = "As an AI, it depends. I'm not sure. The date is 2024-01-01."

def make_temp_corpus(tmp: pathlib.Path) -> pathlib.Path:
    cdir = tmp / "deploy-bar"
    cdir.mkdir(parents=True)
    corpus = {
        "name": "deploy-bar",
        "control_system": "You are a helpful assistant.",
        "accept": {"rate_floor": 0.75},
        "cases": [
            {"id": "structure", "input": "Compare approaches and recommend one.",
             "expect_patterns": ["(^|\\n)\\s*(-|\\d+[.)])", "(recommend|should)"],
             "reject_patterns": ["\\bas an AI\\b"]},
            {"id": "decisive", "input": "Flag or wait?",
             "expect_patterns": ["\\b(flag|wait|ship)\\b"],
             "reject_patterns": ["\\bI'?m not sure\\b"]},
            {"id": "edge", "input": "Parse '' into a date.",
             "expect_patterns": ["(empty|invalid)"],
             "reject_patterns": ["\\b2\\d{3}-\\d{2}-\\d{2}\\b"]},
        ],
    }
    (cdir / "corpus.json").write_text(json.dumps(corpus), encoding="utf-8")
    return cdir

tmp = pathlib.Path(tempfile.mkdtemp(prefix="wix-eff001-"))
mod.CORPUS_ROOT = tmp
make_temp_corpus(tmp)
prompt = tmp / "prompt.xml"
prompt.write_text("<role>disciplined engineer</role>", encoding="utf-8")

# ── fake-CLI factories: each simulates one transport shape ───────────────────
def fake_ok(response_text):
    def f(cmd, *a, **kw):
        return SimpleNamespace(returncode=0, stdout=stream_json_for(response_text), stderr="")
    return f

def fake_auth_failure(cmd, *a, **kw):
    return SimpleNamespace(returncode=1, stdout="", stderr="Error: 401 Unauthorized - Not logged in")

def fake_rate_limited(cmd, *a, **kw):
    return SimpleNamespace(returncode=1, stdout="", stderr="429 Too Many Requests: rate limit exceeded")

def fake_provider_error(cmd, *a, **kw):
    return SimpleNamespace(returncode=1, stdout="", stderr="500 Internal Server Error")

def fake_empty_output(cmd, *a, **kw):
    return SimpleNamespace(returncode=0, stdout="   \n  ", stderr="")

def fake_invalid_envelope(cmd, *a, **kw):
    return SimpleNamespace(returncode=0, stdout="<html>Service Unavailable</html>\nnot json at all\n", stderr="")

def fake_hang(cmd, *a, **kw):
    raise subprocess.TimeoutExpired(cmd=cmd, timeout=kw.get("timeout", mod.TRIAL_TIMEOUT))

def fake_spawn_failure(cmd, *a, **kw):
    raise FileNotFoundError("[Errno 2] No such file or directory: 'claude'")

# alternates ok/auth-failure by call count, to prove a mixed run separates transport from task
def fake_mixed(ok_response):
    calls = {"n": 0}
    def f(cmd, *a, **kw):
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            return fake_auth_failure(cmd, *a, **kw)
        return fake_ok(ok_response)(cmd, *a, **kw)
    return f

def run_corpus_with(fake, n=2, with_control=False):
    mod.subprocess.run = fake
    return mod.run_corpus("deploy-bar", prompt, n=n, model="fake-model", with_control=with_control)

# ── 1. _run_trial_subprocess: unit-level transport classification ────────────
mod.subprocess.run = fake_hang
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 timeout: proc None", proc is None, proc)
check("1 timeout: reason", transport["ok"] is False and transport["reason"] == "timeout", transport)

mod.subprocess.run = fake_spawn_failure
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 spawn-failure: proc None", proc is None, proc)
check("1 spawn-failure: reason", transport["ok"] is False and transport["reason"] == "spawn-failure", transport)

mod.subprocess.run = fake_auth_failure
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 auth-failure: reason", transport["ok"] is False and transport["reason"] == "auth-failure", transport)

mod.subprocess.run = fake_rate_limited
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 rate-limited: reason", transport["ok"] is False and transport["reason"] == "rate-limited", transport)

mod.subprocess.run = fake_provider_error
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 provider-error: reason", transport["ok"] is False and transport["reason"] == "provider-error", transport)

mod.subprocess.run = fake_empty_output
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 empty-output: reason", transport["ok"] is False and transport["reason"] == "empty-output", transport)

mod.subprocess.run = fake_ok(GOOD_RESPONSE)
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 ok: transport ok", transport["ok"] is True and transport["reason"] is None, transport)

# ── 2. run_corpus_trial: invalid envelope detected only when NOTHING parses ──
mod.subprocess.run = fake_invalid_envelope
trace, meta = mod.run_corpus_trial("sys", "hi", "fake-model", 0)
check("2 invalid-envelope trace empty", trace == [], trace)
check("2 invalid-envelope transport", meta["transport"]["ok"] is False
      and meta["transport"]["reason"] == "invalid-envelope", meta["transport"])

# structurally valid stream-json with no assistant/user turns is NOT a transport failure —
# it is a genuine (if unusual) empty task outcome.
def fake_system_only(cmd, *a, **kw):
    return SimpleNamespace(returncode=0, stdout=json.dumps({"type": "system", "subtype": "init"}), stderr="")
mod.subprocess.run = fake_system_only
trace, meta = mod.run_corpus_trial("sys", "hi", "fake-model", 0)
check("2 system-only event is NOT invalid-envelope", meta["transport"]["ok"] is True, meta["transport"])
check("2 system-only event yields empty trace", trace == [], trace)

# ── 3. corpus mode: pure transport failure -> NO_MEASUREMENT, never REJECT/ACCEPT ────
for label, fake in (("auth", fake_auth_failure), ("empty", fake_empty_output),
                    ("invalid-envelope", fake_invalid_envelope), ("hang", fake_hang),
                    ("rate-limited", fake_rate_limited)):
    v = run_corpus_with(fake, n=2, with_control=False)
    check(f"3 {label} decision is NO_MEASUREMENT", v["decision"]["verdict"] == "NO_MEASUREMENT",
          v["decision"])
    check(f"3 {label} decision is never REJECT/ACCEPT", v["decision"]["verdict"] not in ("REJECT", "ACCEPT"),
          v["decision"])
    check(f"3 {label} treatment not measurement_valid", v["treatment"]["measurement_valid"] is False,
          v["treatment"])
    check(f"3 {label} zero Wilson-count evidence", v["treatment"]["total"] == 0 and v["treatment"]["passes"] == 0,
          v["treatment"])
    check(f"3 {label} transport_failures recorded with cause", len(v["treatment"]["transport_failures"]) == 6
          and all(tf.get("reason") for tf in v["treatment"]["transport_failures"]), v["treatment"]["transport_failures"])
    # verdict.json on disk carries the same NO_MEASUREMENT verdict, not a stale REJECT.
    persisted = json.loads((tmp / "deploy-bar" / "verdict.json").read_text(encoding="utf-8"))
    check(f"3 {label} verdict.json decision", persisted["decision"]["verdict"] == "NO_MEASUREMENT", persisted["decision"])

# ── 4. corpus mode: genuine task rejection is still REJECT (not NO_MEASUREMENT) ──
v_bad = run_corpus_with(fake_ok(BAD_RESPONSE), n=10, with_control=False)
check("4 genuine rejection decision", v_bad["decision"]["verdict"] == "REJECT", v_bad["decision"])
check("4 genuine rejection measurement_valid True", v_bad["treatment"]["measurement_valid"] is True, v_bad["treatment"])
check("4 genuine rejection full Wilson count", v_bad["treatment"]["total"] == 30, v_bad["treatment"])

# ── 5. corpus mode: genuine task success is still ACCEPT ─────────────────────
v_good = run_corpus_with(fake_ok(GOOD_RESPONSE), n=10, with_control=False)
check("5 genuine success decision", v_good["decision"]["verdict"] == "ACCEPT", v_good["decision"])

# ── 6. mixed run: some trials transport-fail, others measure ─────────────────
v_mixed = run_corpus_with(fake_mixed(GOOD_RESPONSE), n=10, with_control=False)
check("6 mixed measurement_valid True (some trials measured)", v_mixed["treatment"]["measurement_valid"] is True,
      v_mixed["treatment"])
check("6 mixed decision is not NO_MEASUREMENT", v_mixed["decision"]["verdict"] != "NO_MEASUREMENT", v_mixed["decision"])
check("6 mixed excludes half the trials from Wilson count", v_mixed["treatment"]["attempted"] == 30
      and v_mixed["treatment"]["total"] == 15 and len(v_mixed["treatment"]["transport_failures"]) == 15,
      v_mixed["treatment"])
check("6 mixed rate computed only over measured trials", v_mixed["treatment"]["rate"] == 1.0, v_mixed["treatment"])

# ── 7. with_control: control arm transport failure also forces NO_MEASUREMENT ────
# run_corpus calls _measure_arm for "treatment" fully, then for "control" fully (deterministic
# order), so a counter that flips after the treatment arm's call count reliably fails only control.
n_cases = len(json.loads((tmp / "deploy-bar" / "corpus.json").read_text())["cases"])
call_state = {"n": 0, "total_treatment_calls": n_cases * 3}
def fake_control_fails(cmd, *a, **kw):
    call_state["n"] += 1
    if call_state["n"] <= call_state["total_treatment_calls"]:
        return fake_ok(GOOD_RESPONSE)(cmd, *a, **kw)
    return fake_auth_failure(cmd, *a, **kw)
v_ctrl = run_corpus_with(fake_control_fails, n=3, with_control=True)
check("7 control transport failure -> NO_MEASUREMENT overall", v_ctrl["decision"]["verdict"] == "NO_MEASUREMENT",
      v_ctrl["decision"])
check("7 treatment measured fine, control did not", v_ctrl["treatment"]["measurement_valid"] is True
      and v_ctrl["control"]["measurement_valid"] is False, (v_ctrl["treatment"], v_ctrl["control"]))

# ── 8. main() exit-code integration (WIX-EFF-001 residual: the test must exercise main()) ──
import argparse
def call_main(argv):
    old_argv = sys.argv
    sys.argv = ["efficacy-replay.py"] + argv
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = mod.main()
    finally:
        sys.argv = old_argv
    return rc, out.getvalue()

mod.subprocess.run = fake_auth_failure
rc, _ = call_main(["corpus", "deploy-bar", "--prompt", str(prompt), "-n", "1"])
check("8 main() NO_MEASUREMENT exit code", rc == mod.EXIT_NO_MEASUREMENT == 3, rc)

mod.subprocess.run = fake_ok(GOOD_RESPONSE)
rc, _ = call_main(["corpus", "deploy-bar", "--prompt", str(prompt), "-n", "10"])
check("8 main() ACCEPT exit code", rc == 0, rc)

mod.subprocess.run = fake_ok(BAD_RESPONSE)
rc, _ = call_main(["corpus", "deploy-bar", "--prompt", str(prompt), "-n", "10"])
check("8 main() REJECT exit code", rc == 1, rc)

if failures:
    print("FAIL test-efficacy-transport-vs-task")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("PASS test-efficacy-transport-vs-task")
PY
