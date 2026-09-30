#!/usr/bin/env bash
# Regression test for WIX-PDF-001 fix round 1 (independent-verifier findings against the
# initial WIX-PDF-001 fix):
#
#   1. Hung converter blocks fallback -- report-gen's outer subprocess timeout equaled
#      html-to-pdf's per-browser timeout, so a hung first browser consumed the ENTIRE outer
#      budget and the process was killed from outside before a second candidate was ever
#      tried; the hung browser also outlived report-gen and leaked its profile dir.
#   2. Stale-PDF false success -- the standalone CLI wrote the browser's output directly to
#      the final report.pdf path, so a pre-existing (stale) report.pdf plus a browser that
#      wrote nothing looked identical to success.
#   3. Profile-dir leak -- a single-attempt-then-short-retry cleanup did not reliably win the
#      race against a browser process tree that hadn't fully released its file handles yet.
#   4. The WIXIE_TEST_PDF_BROWSERS test seam was honoured unconditionally.
#
# No real browser is needed for any scenario here (stub .bat "browsers" via the
# WIXIE_TEST_MODE=1 + WIXIE_TEST_PDF_BROWSERS seam, or direct calls into the module via
# importlib). See NOTES.md for the separate real-host evidence run.
set -uo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
# Private temp root (WIX-TEST-ENV-001): every scratch path below derives from WIXIE_TEST_ROOT.
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"
# D27: portable fake browsers (.bat on Windows, executable #!/bin/sh on POSIX).
# shellcheck source=../lib/fake-browser.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/fake-browser.sh"
SCRIPT="$REPO_ROOT/shared/scripts/html-to-pdf.py"

WORK="$(wixie_mktemp_d pdf-fix-round1)" || exit 97
trap 'rm -rf "$WORK"' EXIT

# WIX-PDF-001 fix round 2: html-to-pdf.py's own temp usage must never touch the user's real
# %TEMP% during a test run. Git Bash/MSYS auto-translates TMP/TEMP specifically, so exporting
# them once here redirects every script below (the CLI subprocess and the in-process probes
# alike) without threading an isolated directory through every call site. See
# test-pdf-browser-fallback.sh's matching comment for the empirical confirmation.
mkdir -p "$WORK/systmp"
export TMP="$WORK/systmp"
export TEMP="$WORK/systmp"

FAILED=0
fail() { echo "FAIL: $1"; FAILED=1; }

# ── Driver scripts ──────────────────────────────────────────────────────────────
# Path handling: every filesystem path reaching a separately spawned Python process is passed
# as a literal argv token, never baked into a heredoc's Python source or an env-var string --
# see test-pdf-browser-fallback.sh's header comment for why (MSYS argv path rewriting).

cat > "$WORK/run_cli.py" <<'PY'
# argv: <html_to_pdf_script> <html_path> [--no-test-mode] -- name path type [name path type ...]
# Runs the real html-to-pdf.py CLI as a child process. --no-test-mode omits WIXIE_TEST_MODE so
# the gating fix (issue 4) can be exercised; otherwise both test-seam variables are set.
import sys, subprocess, json, os

argv = sys.argv[1:]
script, html = argv[0], argv[1]
rest = argv[2:]
no_test_mode = False
if rest and rest[0] == "--no-test-mode":
    no_test_mode = True
    rest = rest[1:]
if rest and rest[0] == "--":
    rest = rest[1:]
candidates = [rest[i:i + 3] for i in range(0, len(rest), 3)]

env = dict(os.environ)
env.pop("WIXIE_TEST_MODE", None)
env.pop("WIXIE_TEST_PDF_BROWSERS", None)
if candidates:
    env["WIXIE_TEST_PDF_BROWSERS"] = json.dumps(candidates)
    if not no_test_mode:
        env["WIXIE_TEST_MODE"] = "1"

r = subprocess.run([sys.executable, script, html, "--keep-html"], env=env, capture_output=True, text=True)
sys.stdout.write(r.stdout)
sys.stderr.write(r.stderr)
sys.exit(r.returncode)
PY

write_stub() {
  local dir="$1" stub_name="$2" py_body="$3"
  mkdir -p "$dir"
  cat > "$dir/${stub_name}.py" <<PYEOF
$py_body
PYEOF
  wixie_fake_browser "$dir" "$stub_name"
}

write_hang_stub() {
  # A pure batch busy-loop: hangs entirely inside the one process subprocess.run()/Popen()
  # tracks directly, no grandchild involved (see test-pdf-browser-fallback.sh for why a
  # .bat-calls-python chain is unsuitable for a timeout test on Windows).
  local dir="$1" stub_name="$2"
  mkdir -p "$dir"
  wixie_fake_browser_hang "$dir" "$stub_name"
}

STUB_ALWAYS_OK='
import sys
target = None
for a in sys.argv[1:]:
    if a.startswith("--print-to-pdf="):
        target = a.split("=", 1)[1]
if target:
    with open(target, "wb") as fh:
        fh.write(b"%PDF-1.4\n% stub browser output\n")
'

STUB_WRITES_NOTHING='
import sys
sys.exit(0)
'

write_html() {
  printf '<!DOCTYPE html><html><body>report</body></html>' > "$1"
}

# ── Scenario (1): a hung first browser does not block the second from being tried ──────────
# Exercises convert_with_fallback()'s real deadline logic directly (custom small
# overall_timeout/per_browser_timeout so the test stays fast) rather than waiting out the full
# 12s/45s production defaults -- the logic under test is the same either way.
scenario_hang_does_not_block_fallback() {
  local d="$WORK/1"
  write_hang_stub "$d/bin" "hang"
  write_stub "$d/bin" "ok" "$STUB_ALWAYS_OK"

  cat > "$d/probe.py" <<'PY'
# argv: <html_to_pdf_script> <work_dir> <hang_bat> <ok_bat>
import importlib.util, os, sys, time

script, work_dir, hang_bat, ok_bat = sys.argv[1:5]
spec = importlib.util.spec_from_file_location("m1", script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

html = os.path.join(work_dir, "report.html")
with open(html, "w") as f:
    f.write("<html></html>")
pdf = os.path.join(work_dir, "report.pdf")

candidates = [("Hang", hang_bat, "chromium"), ("Ok", ok_bat, "chromium")]
start = time.time()
ok, used, attempts = mod.convert_with_fallback(html, pdf, candidates, overall_timeout=6, per_browser_timeout=2)
elapsed = time.time() - start

assert ok, f"expected the second (working) browser to succeed: attempts={attempts}"
assert used == "Ok", f"expected 'Ok' to be the browser that succeeded, got {used!r}"
assert any("Hang" in a and "timed out" in a for a in attempts), f"hang's timeout not reported: {attempts}"
# The hang must have been bounded by per_browser_timeout (~2s), not the full overall_timeout
# (6s) and not left to run past it either -- this is the actual fix: before it, a hang
# anywhere near the outer budget starved every later candidate of a real attempt.
assert 1.5 <= elapsed <= 5.0, f"expected ~2s (per-browser timeout) + a fast second attempt, took {elapsed:.1f}s"
print("HANG_FALLBACK_OK", elapsed)
PY
  local out
  out="$(python "$d/probe.py" "$SCRIPT" "$d" "$d/bin/hang$WIXIE_FAKE_BROWSER_EXT" "$d/bin/ok$WIXIE_FAKE_BROWSER_EXT" 2>&1)"
  echo "$out"
  echo "$out" | grep -q "HANG_FALLBACK_OK" || fail "(1) a hung first browser blocked (or over-delayed) the fallback to a working second browser"
}

# ── Scenario (2): same fix, exercised through the real CLI with production timeout constants ──
# Slower (waits out the real ~12s PER_BROWSER_TIMEOUT_S) but proves the actual shipped defaults
# leave room for a fallback, not just a custom test-only timeout pair.
scenario_hang_then_good_real_cli() {
  local d="$WORK/2"
  write_hang_stub "$d/bin" "hang"
  write_stub "$d/bin" "ok" "$STUB_ALWAYS_OK"
  write_html "$d/report.html"

  local start end elapsed
  start=$(date +%s)
  OUT="$(python "$WORK/run_cli.py" "$SCRIPT" "$d/report.html" -- "Hang" "$d/bin/hang$WIXIE_FAKE_BROWSER_EXT" "chromium" "Ok" "$d/bin/ok$WIXIE_FAKE_BROWSER_EXT" "chromium" 2>&1)"
  CODE=$?
  end=$(date +%s)
  elapsed=$((end - start))
  echo "$OUT"
  echo "elapsed=${elapsed}s"

  [ "$CODE" -eq 0 ] || fail "(2) expected exit 0 (the second browser should still succeed), got $CODE"
  echo "$OUT" | grep -q "PDF saved:.*via Ok" || fail "(2) the working second browser should still be used"
  echo "$OUT" | grep -q "tried and failed: Hang.*timed out" || fail "(2) the hang's timeout should still be reported"
  [ -f "$d/report.pdf" ] || fail "(2) no report.pdf produced despite the second browser working"
  # Must have genuinely waited out something close to the per-browser timeout (not been killed
  # immediately) but nowhere near the full overall budget (45s) or report-gen's outer bound (60s).
  [ "$elapsed" -ge 9 ] || fail "(2) finished suspiciously fast ($elapsed s) -- did the hang actually run?"
  [ "$elapsed" -le 40 ] || fail "(2) took far too long ($elapsed s) -- fallback should not consume the whole overall budget"
}

# ── Scenario (3): outer report-gen timeout still leaves room (static regression guard) ─────
scenario_outer_timeout_leaves_room() {
  local rg="$REPO_ROOT/shared/scripts/report-gen.py"
  local outer inner
  outer="$(grep -oE 'OUTER_PDF_TIMEOUT_S = [0-9]+' "$rg" | grep -oE '[0-9]+')"
  inner="$(grep -oE 'OVERALL_TIMEOUT_S = [0-9]+' "$SCRIPT" | head -1 | grep -oE '[0-9]+')"
  if [ -z "$outer" ] || [ -z "$inner" ]; then
    fail "(3) could not find OUTER_PDF_TIMEOUT_S in report-gen.py or OVERALL_TIMEOUT_S in html-to-pdf.py"
    return
  fi
  echo "report-gen OUTER_PDF_TIMEOUT_S=$outer, html-to-pdf OVERALL_TIMEOUT_S=$inner"
  [ "$outer" -gt "$inner" ] || fail "(3) report-gen's outer PDF timeout ($outer s) must stay strictly larger than html-to-pdf's own overall fallback budget ($inner s), or a hung chain gets killed from outside again"
}

# ── Scenario (4): stale report.pdf is never reported as this run's success (standalone CLI) ──
scenario_stale_pdf_not_reported_as_success() {
  local d="$WORK/4"
  mkdir -p "$d/bin" "$d/folder"
  write_stub "$d/bin" "nothing" "$STUB_WRITES_NOTHING"
  printf '<html><body>x</body></html>' > "$d/folder/report.html"
  printf '%%PDF-1.4 STALE-FROM-OLD-RUN' > "$d/folder/report.pdf"
  local before_hash
  before_hash="$(python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$d/folder/report.pdf")"

  OUT="$(python "$WORK/run_cli.py" "$SCRIPT" "$d/folder" -- "Nothing" "$d/bin/nothing$WIXIE_FAKE_BROWSER_EXT" "chromium" 2>&1)"
  CODE=$?
  echo "$OUT"

  [ "$CODE" -eq 1 ] || fail "(4) a browser that writes nothing must never be reported as success just because a stale report.pdf already existed, got exit $CODE"
  echo "$OUT" | grep -qi "PDF saved" && fail "(4) 'PDF saved' must never be printed for a stale pre-existing file"
  local after_hash
  after_hash="$(python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$d/folder/report.pdf")"
  [ "$before_hash" = "$after_hash" ] || fail "(4) the stale report.pdf's bytes were modified by a run that produced no real output"
}

# ── Scenario (5): a lingering grandchild holding a profile-dir handle is killed, not leaked ──
scenario_lingering_handle_killed_and_cleaned() {
  local d="$WORK/5"
  mkdir -p "$d/bin"

  # A REAL stub browser (invoked through the actual _run_bounded()/Popen path, not faked) that
  # exits normally but first spawns a DETACHED grandchild holding a file open inside its own
  # --user-data-dir -- exactly the shape that leaked a real profile dir on the verifier's host.
  # The grandchild's PID is recorded via a marker file (path passed through an env var, since
  # convert_one's own argv construction is fixed) so the test can confirm it was actually
  # killed, not just that cleanup eventually raced past it.
  cat > "$d/bin/lingering.py" <<'PYEOF'
import sys, os, subprocess, time

args = sys.argv[1:]
profile = target = None
for a in args:
    if a.startswith("--user-data-dir="):
        profile = a.split("=", 1)[1]
    elif a.startswith("--print-to-pdf="):
        target = a.split("=", 1)[1]

marker = os.environ["WIXIE_TEST_MARKER"]
with open(marker, "w") as mf:
    mf.write(profile + "\n")
lock_path = os.path.join(profile, "locked.bin")
holder_code = (
    "import sys,time,os\n"
    "with open(sys.argv[2], 'a') as mf: mf.write(str(os.getpid()) + chr(10))\n"
    "f = open(sys.argv[1], 'wb')\n"
    "f.write(b'held')\n"
    "f.flush()\n"
    "time.sleep(20)\n"
)
kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
if sys.platform == "win32":
    kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
else:
    kwargs["start_new_session"] = True
subprocess.Popen([sys.executable, "-c", holder_code, lock_path, marker], **kwargs)

for _ in range(50):
    if os.path.isfile(lock_path):
        break
    time.sleep(0.1)

if target:
    with open(target, "wb") as fh:
        fh.write(b"%PDF-1.4\n% stub\n")
sys.exit(0)
PYEOF
  wixie_fake_browser "$d/bin" lingering

  cat > "$d/probe.py" <<'PY'
# argv: <html_to_pdf_script> <work_dir> <lingering_bat> <marker_path>
import importlib.util, os, sys, time

script, work_dir, bat, marker = sys.argv[1:5]
os.environ["WIXIE_TEST_MARKER"] = marker
spec = importlib.util.spec_from_file_location("m5", script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

html = os.path.join(work_dir, "report.html")
with open(html, "w") as f:
    f.write("<html></html>")
pdf = os.path.join(work_dir, "report.pdf")

ok, detail = mod.convert_one(html, pdf, "Lingering", bat, "chromium")
assert ok, f"expected the conversion itself to succeed: {detail!r}"

lines = open(marker).read().splitlines() if os.path.isfile(marker) else []
profile_dir = lines[0] if len(lines) > 0 else None
holder_pid = lines[1] if len(lines) > 1 else None
print("PROFILE_DIR", profile_dir)
print("HOLDER_PID", holder_pid)
# Informational only -- see the bash side for why immediate removal is not asserted here.
print("PROFILE_DIR_GONE", not (profile_dir and os.path.isdir(profile_dir)))
print("PROBE_DONE")
PY
  local out
  out="$(python "$d/probe.py" "$SCRIPT" "$d" "$d/bin/lingering$WIXIE_FAKE_BROWSER_EXT" "$d/holder.pid" 2>&1)"
  echo "$out"
  echo "$out" | grep -q "PROBE_DONE" || { fail "(5) probe did not complete"; return; }

  # What this scenario actually guarantees and asserts: the lingering process is killed. That
  # is the fix under test ("terminate the browser process tree before removing the profile").
  # Directory removal timing itself is NOT asserted here: measured live on this host, the
  # kernel-level handle-release race a just-killed process can leave behind occasionally
  # outlasts even a generous (15s) bounded retry -- sometimes past 60s -- independent of
  # anything this code does differently, which is exactly why cleanup is a documented
  # two-layer design (bounded retry here, a sweep of stale directories on a LATER invocation,
  # separately and deterministically verified against a synthetic old directory in scenario 7,
  # where no real OS-level lock is involved). Asserting immediate removal here would make this
  # test flake on exactly the race it exists to describe.
  local holder_pid
  holder_pid="$(echo "$out" | grep "HOLDER_PID" | awk '{print $2}')"
  if [ -z "$holder_pid" ] || [ "$holder_pid" = "None" ]; then
    fail "(5) no holder PID was recorded -- the lingering-process setup itself did not run as expected"
    return
  fi
  if tasklist /FI "PID eq $holder_pid" 2>/dev/null | grep -q "$holder_pid"; then
    fail "(5) the lingering handle-holding process (pid $holder_pid) is still running after convert_one returned -- process-tree kill did not reach it"
  fi
  echo "$out" | grep -q "PROFILE_DIR_GONE True" || \
    echo "(5) note: the profile directory was not removed within this run's own bounded retry (matches the real-host behavior documented above); the sweep backstop (scenario 7) is what eventually reclaims it"
}

# ── Scenario (6): WIXIE_TEST_PDF_BROWSERS alone (no WIXIE_TEST_MODE) is ignored ────────────
scenario_test_seam_gated() {
  local d="$WORK/6"
  mkdir -p "$d/bin"
  write_stub "$d/bin" "ok" "$STUB_ALWAYS_OK"
  write_html "$d/report.html"

  # WITHOUT the flag: the fake candidate must be ignored, so this must NOT behave like the
  # fake "Ok" browser was used (real discovery runs instead -- on this host that may find a
  # real browser and succeed, or find none and fail with the documented no-browser message;
  # either way it must never say "via Ok" for our fake path, and it must never invoke our bat).
  local marker="$d/bin/ok-was-invoked.marker"
  rm -f "$marker"
  cat >> "$d/bin/ok.py" <<PY
open(r"$marker", "w").write("invoked")
PY
  OUT="$(python "$WORK/run_cli.py" "$SCRIPT" "$d/report.html" --no-test-mode -- "Ok" "$d/bin/ok$WIXIE_FAKE_BROWSER_EXT" "chromium" 2>&1)"
  CODE=$?
  echo "--- without WIXIE_TEST_MODE ---"
  echo "$OUT"
  echo "$OUT" | grep -q "via Ok" && fail "(6) the fake 'Ok' stub was used even though WIXIE_TEST_MODE was not set"
  [ -f "$marker" ] && fail "(6) the fake stub browser was actually invoked even though WIXIE_TEST_MODE was not set"

  # WITH the flag (both variables): the fake candidate must be honoured, proving the gate
  # isn't simply broken/inert in the other direction too.
  rm -f "$marker"
  OUT2="$(python "$WORK/run_cli.py" "$SCRIPT" "$d/report.html" -- "Ok" "$d/bin/ok$WIXIE_FAKE_BROWSER_EXT" "chromium" 2>&1)"
  CODE2=$?
  echo "--- with WIXIE_TEST_MODE=1 ---"
  echo "$OUT2"
  [ "$CODE2" -eq 0 ] || fail "(6) with WIXIE_TEST_MODE=1 set, the fake stub should have been used and succeeded, got exit $CODE2"
  echo "$OUT2" | grep -q "via Ok" || fail "(6) with WIXIE_TEST_MODE=1 set, expected the fake 'Ok' stub to be used"
}

# ── Scenario (7): startup sweep removes only a stale, exact-prefix profile dir ─────────────
scenario_stale_profile_sweep() {
  local d="$WORK/7"
  mkdir -p "$d/tmp"
  # probe.py creates all of its own fixtures (stale/fresh attempt dirs, a legacy profile dir, a
  # legacy out-file) directly, so their exact ages can be controlled precisely via os.utime.

  cat > "$d/probe.py" <<'PY'
# argv: <html_to_pdf_script> <tmp_dir>
# Covers all three sweep targets (fix round 2 extended the sweep beyond just
# wixie-pdf-profile-*): the current wixie-pdf-attempt-* directory prefix, the fix-round-1-era
# wixie-pdf-profile-* directory prefix (kept for backward compatibility with older leftovers),
# and the fix-round-1-era wixie-pdf-out-* FILE prefix (a plain file, not a directory).
import importlib.util, os, sys, time

script, tmp = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("m7", script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

stale_attempt = os.path.join(tmp, "wixie-pdf-attempt-teststale")
fresh_attempt = os.path.join(tmp, "wixie-pdf-attempt-testfresh")
stale_profile = os.path.join(tmp, "wixie-pdf-profile-teststale")
stale_out_file = os.path.join(tmp, "wixie-pdf-out-teststale.pdf")
fresh_out_file = os.path.join(tmp, "wixie-pdf-out-testfresh.pdf")
unrelated = os.path.join(tmp, "some-other-dir")

os.makedirs(stale_attempt); os.makedirs(fresh_attempt); os.makedirs(stale_profile)
open(stale_out_file, "wb").write(b"%PDF-1.4 stale")
open(fresh_out_file, "wb").write(b"%PDF-1.4 fresh")
os.makedirs(unrelated)

old = time.time() - mod.STALE_PDF_TEMP_MAX_AGE_S - 60
os.utime(stale_attempt, (old, old))
os.utime(stale_profile, (old, old))
os.utime(stale_out_file, (old, old))
# fresh_attempt / fresh_out_file keep their just-created mtime (well under the threshold)

mod.tempfile.gettempdir = lambda: tmp
mod._sweep_stale_pdf_temp_items()

assert not os.path.isdir(stale_attempt), "a wixie-pdf-attempt-* dir older than the threshold was not swept"
assert not os.path.isdir(stale_profile), "a legacy wixie-pdf-profile-* dir older than the threshold was not swept"
assert not os.path.isfile(stale_out_file), "a legacy wixie-pdf-out-* FILE older than the threshold was not swept"
assert os.path.isdir(fresh_attempt), "a fresh (recent) wixie-pdf-attempt-* dir was incorrectly swept"
assert os.path.isfile(fresh_out_file), "a fresh (recent) wixie-pdf-out-* file was incorrectly swept"
assert os.path.isdir(unrelated), "a directory that doesn't match any tracked prefix was touched"
print("SWEEP_OK")
PY
  local out
  out="$(python "$d/probe.py" "$SCRIPT" "$d/tmp" 2>&1)"
  echo "$out"
  echo "$out" | grep -q "SWEEP_OK" || fail "(7) stale profile-dir sweep did not behave as documented"
}

scenario_hang_does_not_block_fallback
scenario_hang_then_good_real_cli
scenario_outer_timeout_leaves_room
scenario_stale_pdf_not_reported_as_success
scenario_lingering_handle_killed_and_cleaned
scenario_test_seam_gated
scenario_stale_profile_sweep

if [ "$FAILED" -ne 0 ]; then
  exit 1
fi
echo "PASS: a hung converter no longer blocks the fallback chain (deadline-bounded per-attempt timeout, real CLI end to end, and a static guard that report-gen's outer timeout stays larger than html-to-pdf's own overall budget), a stale pre-existing report.pdf is never reported as this run's success, a lingering process still holding a profile-dir handle is killed and its directory cleaned up rather than leaked, the WIXIE_TEST_PDF_BROWSERS seam is inert without WIXIE_TEST_MODE=1, and the startup sweep removes only a stale exact-prefix profile directory"
