#!/usr/bin/env bash
# Regression test for WIX-EFF-001 fix round 1 (independent verifier REJECT on 3770fab, blocking
# issue C5): the per-trial timeout must be bounded through a .cmd/.bat shim, not just a direct
# executable. NO MOCKING — this spawns a REAL process tree shaped exactly like the reported bug:
# a .cmd wrapper (the same OS mechanism as npm's `claude.CMD` on Windows) whose outer process
# blocks on a foreground child that holds the inherited stdout/stderr pipes open well past the
# trial timeout. Before the fix, subprocess.run's built-in timeout killed only the direct child
# (the implicit cmd.exe), leaving the grandchild alive and the pipes open, so a 3s timeout took
# 120.8s end to end for two trials. After the fix, _kill_process_tree kills the whole tree and
# _run_trial_subprocess returns within TRIAL_TIMEOUT + TREE_KILL_DRAIN_TIMEOUT + a small margin.
set -euo pipefail
REPO_ROOT="${1:-.}"

PYTHONIOENCODING=utf-8 python - "$REPO_ROOT" <<'PY'
import importlib.util, os, pathlib, sys, tempfile, time

root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("efficacy_replay", root / "shared" / "scripts" / "efficacy-replay.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

failures = []
def check(name, cond, detail=""):
    if not cond:
        failures.append(f"{name}: {detail}")

tmp = pathlib.Path(tempfile.mkdtemp(prefix="wix-eff001-treekill-"))
mod.TRIAL_TIMEOUT = 2  # keep the test fast; the pre-fix bug multiplies whatever this is set to

if sys.platform == "win32":
    # The outer process (what Popen actually launches — Windows implicitly runs this .cmd
    # through its own cmd.exe, exactly like resolving `claude` to npm's claude.CMD) blocks in
    # the foreground on a NESTED cmd.exe running `ping`, which inherits the same stdout/stderr
    # pipe handles. Killing only the outer process leaves that nested cmd.exe + ping.exe alive,
    # still holding the pipes open — reproducing the reported grandchild-holds-stdout bug without
    # needing a real npm/claude install.
    wrapper = tmp / "wrapper.cmd"
    wrapper.write_text(
        "@echo off\r\n"
        "echo hanging\r\n"
        "%COMSPEC% /c \"ping -n 30 127.0.0.1 >nul\"\r\n",
        encoding="utf-8")
    cmd = [str(wrapper)]
elif shutil_which := __import__("shutil").which("sh"):
    # POSIX analogue: `sh` backgrounds a long sleep sharing the same process group (created by
    # start_new_session in _run_trial_subprocess), then waits on it in the foreground.
    wrapper = tmp / "wrapper.sh"
    wrapper.write_text("#!/bin/sh\nsleep 30 &\nwait\n", encoding="utf-8")
    wrapper.chmod(0o755)
    cmd = [shutil_which, str(wrapper)]
else:
    print("SKIP test-efficacy-timeout-tree-kill: no usable shell on this platform")
    sys.exit(0)

env = dict(os.environ)
t0 = time.monotonic()
proc, transport = mod._run_trial_subprocess(cmd, env, str(tmp))
elapsed = time.monotonic() - t0

# Bound: TRIAL_TIMEOUT (2s) + TREE_KILL_DRAIN_TIMEOUT (5s, module default) + generous margin for
# taskkill/killpg overhead and CI/host slowness. The pre-fix bug produced ~120s for a 3s timeout
# (40x); this bound (well under 5x TRIAL_TIMEOUT) would fail loudly if the regression came back.
budget = mod.TRIAL_TIMEOUT + mod.TREE_KILL_DRAIN_TIMEOUT + 15
check("real tree-kill: proc is None", proc is None, proc)
check("real tree-kill: reason is timeout", transport.get("reason") == "timeout", transport)
check("real tree-kill: bounded wall time",
      elapsed < budget,
      f"elapsed={elapsed:.1f}s budget={budget}s (pre-fix this reproduced as ~120s for a 3s timeout)")

if failures:
    print("FAIL test-efficacy-timeout-tree-kill")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print(f"PASS test-efficacy-timeout-tree-kill (elapsed {elapsed:.1f}s, budget {budget}s)")
PY
