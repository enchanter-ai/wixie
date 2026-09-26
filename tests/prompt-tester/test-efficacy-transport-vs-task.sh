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
# Fix round 1 (independent verifier REJECT on 3770fab) adds: a REAL process-tree timeout test
# (no mock — a genuine .cmd shim on Windows spawning a grandchild that holds stdout open, the
# exact shape that made a 3s timeout take 120.8s) and secret-redaction tests (a planted fake key
# must appear nowhere in stdout, verdict.json or runs/*.json).
#
# MOCKS THE MODEL CALL (sections 1-8): monkeypatches the module's `subprocess.Popen` — the seam
# _run_trial_subprocess now uses (fix round 1 switched from subprocess.run to Popen+communicate
# so a timeout can kill the whole process tree instead of just the direct child; subprocess.run's
# built-in timeout handling cannot do that). No real `claude -p` invocation in those sections, no
# tokens, no network. Runs hermetically against a temp corpus dir.
set -euo pipefail
REPO_ROOT="${1:-.}"
# Private temp root (WIX-TEST-ENV-001): every scratch path below derives from WIXIE_TEST_ROOT.
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"

PYTHONIOENCODING=utf-8 python - "$REPO_ROOT" <<'PY'
import importlib.util, io, json, contextlib, os, pathlib, subprocess, sys, tempfile, time
from types import SimpleNamespace

# Safety net: every section below mocks subprocess.Popen, but set this BEFORE the module loads
# too, so a mock gap can never silently fall through to the real `claude` CLI on PATH (this host
# resolves one — WIXIE_EFFICACY_CLAUDE_BIN forces resolve_claude_bin() to a path that cannot
# exist instead).
os.environ["WIXIE_EFFICACY_CLAUDE_BIN"] = "__wix_eff001_test_no_such_binary_do_not_create__"

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

# ── fake-Popen factories: each simulates one transport shape ─────────────────
# _run_trial_subprocess calls subprocess.Popen(...) then proc.communicate(timeout=...), then
# reads proc.returncode — a FakePopen instance stands in for the real Popen object.
class FakePopen:
    def __init__(self, returncode=0, stdout="", stderr="", timeout_first=False, pid=4242):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._timeout_first = timeout_first
        self._communicate_calls = 0
        self.pid = pid
        self.killed = False

    def communicate(self, timeout=None):
        self._communicate_calls += 1
        if self._timeout_first and self._communicate_calls == 1:
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

def fake_popen(returncode=0, stdout="", stderr="", timeout_first=False):
    """A `subprocess.Popen`-shaped constructor: cmd, *a, **kw -> FakePopen instance."""
    def ctor(cmd, *a, **kw):
        return FakePopen(returncode=returncode, stdout=stdout, stderr=stderr, timeout_first=timeout_first)
    return ctor

def fake_ok(response_text):
    return fake_popen(returncode=0, stdout=stream_json_for(response_text), stderr="")

fake_auth_failure = fake_popen(returncode=1, stdout="", stderr="Error: 401 Unauthorized - Not logged in")
fake_rate_limited = fake_popen(returncode=1, stdout="", stderr="429 Too Many Requests: rate limit exceeded")
fake_provider_error = fake_popen(returncode=1, stdout="", stderr="500 Internal Server Error")
fake_empty_output = fake_popen(returncode=0, stdout="   \n  ", stderr="")
fake_invalid_envelope = fake_popen(returncode=0, stdout="<html>Service Unavailable</html>\nnot json at all\n", stderr="")
fake_hang = fake_popen(returncode=-9, stdout="", stderr="", timeout_first=True)

def fake_spawn_failure(cmd, *a, **kw):
    raise FileNotFoundError("[Errno 2] No such file or directory: 'claude'")

# alternates ok/auth-failure by call count, to prove a mixed run separates transport from task
def fake_mixed(ok_response):
    calls = {"n": 0}
    def ctor(cmd, *a, **kw):
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            return FakePopen(returncode=1, stdout="", stderr="Error: 401 Unauthorized - Not logged in")
        return FakePopen(returncode=0, stdout=stream_json_for(ok_response), stderr="")
    return ctor

def run_corpus_with(fake, n=2, with_control=False):
    mod.subprocess.Popen = fake
    return mod.run_corpus("deploy-bar", prompt, n=n, model="fake-model", with_control=with_control)

# ── 1. _run_trial_subprocess: unit-level transport classification ────────────
mod.subprocess.Popen = fake_hang
t0 = time.monotonic()
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 timeout: proc None", proc is None, proc)
check("1 timeout: reason", transport["ok"] is False and transport["reason"] == "timeout", transport)
check("1 timeout: bounded (mocked, should be near-instant)", time.monotonic() - t0 < 15,
      time.monotonic() - t0)

mod.subprocess.Popen = fake_spawn_failure
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 spawn-failure: proc None", proc is None, proc)
check("1 spawn-failure: reason", transport["ok"] is False and transport["reason"] == "spawn-failure", transport)

mod.subprocess.Popen = fake_auth_failure
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 auth-failure: reason", transport["ok"] is False and transport["reason"] == "auth-failure", transport)

mod.subprocess.Popen = fake_rate_limited
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 rate-limited: reason", transport["ok"] is False and transport["reason"] == "rate-limited", transport)

mod.subprocess.Popen = fake_provider_error
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 provider-error: reason", transport["ok"] is False and transport["reason"] == "provider-error", transport)

mod.subprocess.Popen = fake_empty_output
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 empty-output: reason", transport["ok"] is False and transport["reason"] == "empty-output", transport)

mod.subprocess.Popen = fake_ok(GOOD_RESPONSE)
proc, transport = mod._run_trial_subprocess(["claude"], {}, ".")
check("1 ok: transport ok", transport["ok"] is True and transport["reason"] is None, transport)

# ── 2. run_corpus_trial: invalid envelope detected only when NOTHING parses ──
mod.subprocess.Popen = fake_invalid_envelope
trace, meta = mod.run_corpus_trial("sys", "hi", "fake-model", 0)
check("2 invalid-envelope trace empty", trace == [], trace)
check("2 invalid-envelope transport", meta["transport"]["ok"] is False
      and meta["transport"]["reason"] == "invalid-envelope", meta["transport"])

# structurally valid stream-json with no assistant/user turns is NOT a transport failure —
# it is a genuine (if unusual) empty task outcome.
fake_system_only = fake_popen(returncode=0, stdout=json.dumps({"type": "system", "subtype": "init"}), stderr="")
mod.subprocess.Popen = fake_system_only
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
        return FakePopen(returncode=0, stdout=stream_json_for(GOOD_RESPONSE), stderr="")
    return FakePopen(returncode=1, stdout="", stderr="Error: 401 Unauthorized - Not logged in")
v_ctrl = run_corpus_with(fake_control_fails, n=3, with_control=True)
check("7 control transport failure -> NO_MEASUREMENT overall", v_ctrl["decision"]["verdict"] == "NO_MEASUREMENT",
      v_ctrl["decision"])
check("7 treatment measured fine, control did not", v_ctrl["treatment"]["measurement_valid"] is True
      and v_ctrl["control"]["measurement_valid"] is False, (v_ctrl["treatment"], v_ctrl["control"]))

# ── 8. main() exit-code integration (WIX-EFF-001 residual: the test must exercise main()) ──
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

mod.subprocess.Popen = fake_auth_failure
rc, _ = call_main(["corpus", "deploy-bar", "--prompt", str(prompt), "-n", "1"])
check("8 main() NO_MEASUREMENT exit code", rc == mod.EXIT_NO_MEASUREMENT == 3, rc)

mod.subprocess.Popen = fake_ok(GOOD_RESPONSE)
rc, _ = call_main(["corpus", "deploy-bar", "--prompt", str(prompt), "-n", "10"])
check("8 main() ACCEPT exit code", rc == 0, rc)

mod.subprocess.Popen = fake_ok(BAD_RESPONSE)
rc, _ = call_main(["corpus", "deploy-bar", "--prompt", str(prompt), "-n", "10"])
check("8 main() REJECT exit code", rc == 1, rc)

# ── 9. secret redaction (WIX-EFF-001 fix round 1, C9) ─────────────────────────
# A fake CLI that echoes a planted credential-shaped string in BOTH stderr (transport-failure
# detail) and stdout (as if it leaked into the model's own response). Must appear nowhere in
# the printed summary, the persisted verdict.json, or the per-trial runs/*.json artifacts.
FAKE_KEY = "sk-ant-api03-THIS-IS-A-PLANTED-FAKE-TEST-KEY-1234567890abcdef"
fake_leaky_auth_failure = fake_popen(
    returncode=1, stdout="",
    stderr=f"Error: 401 Unauthorized - Not logged in. ANTHROPIC_API_KEY={FAKE_KEY} Authorization: Bearer {FAKE_KEY}")
mod.subprocess.Popen = fake_leaky_auth_failure
rc9, out9 = call_main(["corpus", "deploy-bar", "--prompt", str(prompt), "-n", "1"])
check("9 secret not in stdout", FAKE_KEY not in out9, out9)
persisted9 = (tmp / "deploy-bar" / "verdict.json").read_text(encoding="utf-8")
check("9 secret not in verdict.json", FAKE_KEY not in persisted9, persisted9)
runs9 = list((tmp / "deploy-bar" / "runs").glob("*.json"))
check("9 runs/*.json exist", len(runs9) > 0, runs9)
leaked = [p.name for p in runs9 if FAKE_KEY in p.read_text(encoding="utf-8")]
check("9 secret not in any runs/*.json", leaked == [], leaked)

# same planted key inside a well-formed assistant response (stdout, not stderr): still redacted
# wherever it is persisted, without breaking classification of the surrounding real text.
fake_leaky_ok = fake_popen(returncode=0, stdout=stream_json_for(f"{GOOD_RESPONSE} token={FAKE_KEY}"), stderr="")
mod.subprocess.Popen = fake_leaky_ok
rc9b, out9b = call_main(["corpus", "deploy-bar", "--prompt", str(prompt), "-n", "5"])
check("9b leaky-ok still ACCEPTs on the real content", rc9b == 0, rc9b)
check("9b secret not in stdout", FAKE_KEY not in out9b, out9b)
persisted9b = (tmp / "deploy-bar" / "verdict.json").read_text(encoding="utf-8")
check("9b secret not in verdict.json", FAKE_KEY not in persisted9b, persisted9b)
runs9b = list((tmp / "deploy-bar" / "runs").glob("*.json"))
leaked9b = [p.name for p in runs9b if FAKE_KEY in p.read_text(encoding="utf-8")]
check("9b secret not in any runs/*.json", leaked9b == [], leaked9b)

if failures:
    print("FAIL test-efficacy-transport-vs-task")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("PASS test-efficacy-transport-vs-task (mocked sections 1-9)")
PY
