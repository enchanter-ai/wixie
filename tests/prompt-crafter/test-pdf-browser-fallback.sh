#!/usr/bin/env bash
# Regression test for WIX-PDF-001.
#
# The defect: html-to-pdf.py launched headless Edge without an isolated --user-data-dir; while
# the user's Edge was already running, the launch handed the print job off to that running
# instance, subprocess.run() returned (often exit 0) before any PDF existed, convert() reported
# it as success on nothing more than "the process exited", and find_browser() (singular) only
# ever tried ONE browser -- a failing browser never fell through to the next available converter,
# and subprocess stdout/stderr was captured and then discarded on every path.
#
# This test drives html-to-pdf.py's real CLI (python html-to-pdf.py <html> --keep-html) end to
# end, with WIXIE_TEST_PDF_BROWSERS substituting a deterministic list of stub "browser"
# executables for real browser discovery -- no real browser, model, or network is needed for any
# of these scenarios. A real-browser run against the actual installed Edge/Chrome on this host is
# separate, documented evidence (see NOTES.md), not a dependency of this test.
#
# Path handling note: every filesystem path that must reach a *separately spawned* native Windows
# Python process is passed as a literal argv token (never baked as a string constant into a
# heredoc's Python source, and never hand-assembled into JSON in bash). Git Bash/MSYS only
# rewrites POSIX-style paths to native Windows paths for literal argv tokens of a directly
# exec'd process; a path embedded inside an environment variable's value or a heredoc's Python
# source text is NOT rewritten and breaks native Python's own path resolution. All three helper
# drivers below (run_cli.py, probe_profile.py, probe_timeout.py) therefore take every path as
# sys.argv, never as an interpolated string literal.
set -uo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
# Private temp root (WIX-TEST-ENV-001): every scratch path below derives from WIXIE_TEST_ROOT.
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"
SCRIPT="$REPO_ROOT/shared/scripts/html-to-pdf.py"

WORK="$(wixie_mktemp_d pdf-browser-fallback)" || exit 97
trap 'rm -rf "$WORK"' EXIT

# WIX-PDF-001 fix round 2: html-to-pdf.py's own temp usage (mkdtemp/mkstemp, and the sweep) must
# never touch the user's real %TEMP% during a test run. Git Bash/MSYS auto-translates the TMP/
# TEMP environment variables specifically (confirmed empirically: a plain forward-slash
# export TMP=... is seen by native Windows Python's tempfile.gettempdir() as the correct
# backslash path, both directly and through a nested subprocess's env=), so exporting these once
# here is enough to redirect every script below -- the CLI subprocess (via env=dict(os.environ))
# and the in-process probe scripts (via plain os.environ) alike -- without threading an isolated
# directory through every call site's argv. $WORK itself is not touched by html-to-pdf.py; only
# its own wixie-pdf-* items would be, and those now land in $WORK/systmp, cleaned up by the trap
# above, never in the real %TEMP%.
mkdir -p "$WORK/systmp"
export TMP="$WORK/systmp"
export TEMP="$WORK/systmp"

FAILED=0
fail() { echo "FAIL: $1"; FAILED=1; }

# ── Driver scripts (written once, reused by every scenario) ────────────────────

cat > "$WORK/run_cli.py" <<'PY'
# argv: <html_to_pdf_script> <html_path> [name path type]...
# Builds WIXIE_TEST_PDF_BROWSERS from argv-supplied (MSYS-translated) paths and runs the real
# html-to-pdf.py CLI as a child process, relaying its exit code, stdout and stderr.
import sys, subprocess, json, os

script, html = sys.argv[1], sys.argv[2]
rest = sys.argv[3:]
candidates = [rest[i:i + 3] for i in range(0, len(rest), 3)]

env = dict(os.environ)
env["WIXIE_TEST_MODE"] = "1"
env["WIXIE_TEST_PDF_BROWSERS"] = json.dumps(candidates)

r = subprocess.run([sys.executable, script, html, "--keep-html"], env=env, capture_output=True, text=True)
sys.stdout.write(r.stdout)
sys.stderr.write(r.stderr)
sys.exit(r.returncode)
PY

cat > "$WORK/probe_profile.py" <<'PY'
# argv: <html_to_pdf_script> <work_dir>
# Directly exercises convert_one()'s isolated-profile lifecycle with _run_bounded() (the
# tree-kill-aware launcher convert_one actually calls) faked out, so the profile path and its
# lifecycle can be asserted precisely instead of scraped from stdout. This also stands in for
# "browser already open" vs "browser closed": a fresh --user-data-dir behaves like a brand-new
# instance either way -- there is no separate code path for either case.
import importlib.util, os, sys, types

script, work_dir = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("html_to_pdf_mod", script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

profiles_seen = []
profile_exists_at_invoke = []


def fake_run_bounded(cmd, timeout):
    profile = None
    target = None
    for a in cmd:
        if a.startswith("--user-data-dir="):
            profile = a.split("=", 1)[1]
        elif a.startswith("--print-to-pdf="):
            target = a.split("=", 1)[1]
    profiles_seen.append(profile)
    profile_exists_at_invoke.append(bool(profile) and os.path.isdir(profile))
    if target:
        with open(target, "wb") as fh:
            fh.write(b"%PDF-1.4\n% fake\n")
    return types.SimpleNamespace(returncode=0, stdout="", stderr=""), False


mod._run_bounded = fake_run_bounded

html = os.path.join(work_dir, "report.html")
with open(html, "w") as f:
    f.write("<html></html>")

ok1, detail1 = mod.convert_one(html, os.path.join(work_dir, "out1.pdf"), "Fake", "fake-browser-exe", "chromium")
ok2, detail2 = mod.convert_one(html, os.path.join(work_dir, "out2.pdf"), "Fake", "fake-browser-exe", "chromium")

assert ok1 and ok2, f"expected both conversions to succeed: {detail1!r} {detail2!r}"
assert len(profiles_seen) == 2, profiles_seen
assert all(profiles_seen), "profile dir was never passed to the browser command"
assert profiles_seen[0] != profiles_seen[1], f"two invocations reused the same profile dir: {profiles_seen}"
assert all(profile_exists_at_invoke), "the profile dir did not exist yet when the browser was invoked"
assert not os.path.isdir(profiles_seen[0]), "first invocation's profile dir was not cleaned up afterward"
assert not os.path.isdir(profiles_seen[1]), "second invocation's profile dir was not cleaned up afterward"
print("PROFILE_TEST_OK")
PY

cat > "$WORK/probe_timeout.py" <<'PY'
# argv: <html_to_pdf_script> <work_dir> <hang_bat_path>
# Calls convert_one() against a genuinely hanging stub process with a short timeout, so the
# assertion is on real wall-clock behavior, not a mock.
import importlib.util, os, sys, time

script, work_dir, hang_bat = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location("html_to_pdf_mod2", script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

html = os.path.join(work_dir, "report.html")
with open(html, "w") as f:
    f.write("<html></html>")

start = time.time()
ok, detail = mod.convert_one(html, os.path.join(work_dir, "out.pdf"), "Hang", hang_bat, "chromium", timeout=1)
elapsed = time.time() - start

assert not ok, "a hung browser must not be reported as success"
assert "timed out" in detail, detail
assert elapsed < 4, f"convert_one did not respect the short timeout, took {elapsed:.1f}s"
print("TIMEOUT_TEST_OK")
PY

# A stub "browser": a .bat wrapper (directly CreateProcess-able on Windows, and what
# find_browsers() would hand subprocess.run in real use) that forwards argv to a companion
# Python script, where the actual stub behavior is easy to express.
write_stub() {
  local dir="$1" stub_name="$2" py_body="$3"
  mkdir -p "$dir"
  cat > "$dir/${stub_name}.py" <<PYEOF
$py_body
PYEOF
  cat > "$dir/${stub_name}.bat" <<'BATEOF'
@echo off
python "%~dp0STUBNAME.py" %*
BATEOF
  sed -i "s/STUBNAME/${stub_name}/" "$dir/${stub_name}.bat"
}

STUB_ALWAYS_FAIL='
import sys
sys.stderr.write("simulated browser crash: no window available\n")
sys.exit(7)
'

STUB_ALWAYS_OK='
import sys
target = None
for a in sys.argv[1:]:
    if a.startswith("--print-to-pdf="):
        target = a.split("=", 1)[1]
if target:
    with open(target, "wb") as fh:
        fh.write(b"%PDF-1.4\n% stub browser output\n")
print("stub-ok: wrote", target)
'

STUB_BAD_PDF='
import sys
target = None
for a in sys.argv[1:]:
    if a.startswith("--print-to-pdf="):
        target = a.split("=", 1)[1]
if target:
    with open(target, "wb") as fh:
        fh.write(b"NOT-A-PDF, just garbage bytes that happen to be non-empty\n")
'

# The timeout scenario needs a stub that hangs WITHOUT spawning any child process of its own.
# Windows' subprocess timeout only reliably bounds the *direct* child it tracks: a .bat that
# shells out to `python hang.py` makes python.exe a grandchild holding the inherited stdout/
# stderr pipes open, and Popen.communicate(timeout=...) then blocks on those pipes for the
# grandchild's full runtime regardless of the requested timeout (confirmed empirically while
# writing this test: killing the .bat/cmd.exe direct child did not shorten the observed wait). A
# pure batch busy-loop hangs entirely inside the one process subprocess.run() actually tracks, so
# the timeout enforces promptly -- this is a test-harness constraint, not a statement about how
# real browser processes behave.
write_hang_stub() {
  local dir="$1" stub_name="$2"
  mkdir -p "$dir"
  printf '@echo off\r\nfor /L %%%%i in (1,1,2000000000) do rem\r\n' > "$dir/${stub_name}.bat"
}

write_html() {
  printf '<!DOCTYPE html><html><body>report</body></html>' > "$1"
}

# ── Scenario (a): first browser fails, second succeeds -- fallback works ───────
scenario_fallback_to_next() {
  local d="$WORK/a"
  write_stub "$d/bin" "fail1" "$STUB_ALWAYS_FAIL"
  write_stub "$d/bin" "ok2" "$STUB_ALWAYS_OK"
  write_html "$d/report.html"

  OUT="$(python "$WORK/run_cli.py" "$SCRIPT" "$d/report.html" \
    "StubFail" "$d/bin/fail1.bat" "chromium" \
    "StubOk" "$d/bin/ok2.bat" "chromium" 2>&1)"
  CODE=$?
  echo "$OUT"

  [ "$CODE" -eq 0 ] || fail "(a) expected exit 0 once a later browser succeeds, got $CODE"
  echo "$OUT" | grep -q "PDF saved:.*via StubOk" || fail "(a) success message should name the browser that actually worked (StubOk)"
  echo "$OUT" | grep -q "tried and failed: StubFail" || fail "(a) the earlier failure should still be reported, not silently swallowed"
  [ -f "$d/report.pdf" ] || fail "(a) no report.pdf produced despite a working fallback browser"
  head -c5 "$d/report.pdf" 2>/dev/null | grep -q '%PDF-' || fail "(a) report.pdf missing %PDF- header"
}

# ── Scenario (b): every available browser fails ─────────────────────────────────
scenario_all_fail() {
  local d="$WORK/b"
  write_stub "$d/bin" "fail1" "$STUB_ALWAYS_FAIL"
  write_stub "$d/bin" "fail2" "$STUB_ALWAYS_FAIL"
  write_html "$d/report.html"

  OUT="$(python "$WORK/run_cli.py" "$SCRIPT" "$d/report.html" \
    "StubFail1" "$d/bin/fail1.bat" "chromium" \
    "StubFail2" "$d/bin/fail2.bat" "chromium" 2>&1)"
  CODE=$?
  echo "$OUT"

  [ "$CODE" -eq 1 ] || fail "(b) expected documented exit 1 when every browser fails, got $CODE"
  echo "$OUT" | grep -qi "all 2 available browser(s) failed" || fail "(b) missing clear all-failed summary message"
  echo "$OUT" | grep -q "tried and failed: StubFail1" || fail "(b) first failure not reported"
  echo "$OUT" | grep -q "tried and failed: StubFail2" || fail "(b) second failure not reported"
  [ -f "$d/report.pdf" ] && fail "(b) no report.pdf should exist when every browser failed"
  [ -f "$d/report.html" ] || fail "(b) --keep-html was passed; report.html must still be present"
}

# ── Scenario (c): subprocess stderr is surfaced, not silently discarded ────────
scenario_output_surfaced() {
  local d="$WORK/c"
  write_stub "$d/bin" "fail1" "$STUB_ALWAYS_FAIL"
  write_html "$d/report.html"

  OUT="$(python "$WORK/run_cli.py" "$SCRIPT" "$d/report.html" \
    "StubFail" "$d/bin/fail1.bat" "chromium" 2>&1)"
  CODE=$?
  echo "$OUT"

  [ "$CODE" -eq 1 ] || fail "(c) expected exit 1, got $CODE"
  echo "$OUT" | grep -q "simulated browser crash: no window available" || \
    fail "(c) the failing browser's own stderr must be surfaced, not discarded"
}

# ── Scenario (d): a browser reports success but writes a non-PDF file ──────────
scenario_bad_pdf_rejected() {
  local d="$WORK/d"
  write_stub "$d/bin" "badpdf" "$STUB_BAD_PDF"
  write_html "$d/report.html"

  OUT="$(python "$WORK/run_cli.py" "$SCRIPT" "$d/report.html" \
    "StubBadPdf" "$d/bin/badpdf.bat" "chromium" 2>&1)"
  CODE=$?
  echo "$OUT"

  [ "$CODE" -eq 1 ] || fail "(d) a non-PDF file must never be reported as a successful conversion, got exit $CODE"
  echo "$OUT" | grep -qi "non-PDF" || fail "(d) failure reason should say the output wasn't a real PDF"
  [ -f "$d/report.pdf" ] && fail "(d) the bogus non-PDF file must not be left behind at report.pdf"
}

# ── Scenario (e): no candidate browsers at all ──────────────────────────────────
scenario_no_browsers() {
  local d="$WORK/e"
  mkdir -p "$d"
  write_html "$d/report.html"

  OUT="$(python "$WORK/run_cli.py" "$SCRIPT" "$d/report.html" 2>&1)"
  CODE=$?
  echo "$OUT"

  [ "$CODE" -eq 1 ] || fail "(e) expected documented exit 1 when no browser is available, got $CODE"
  echo "$OUT" | grep -qi "No browser found" || fail "(e) missing documented no-browser message"
  echo "$OUT" | grep -q "HTML report available at" || fail "(e) missing HTML-fallback pointer"
}

# ── Scenario (f): isolated per-invocation profile -- created, unique, cleaned up ─
scenario_isolated_profile() {
  local d="$WORK/f"
  mkdir -p "$d"
  local probe_out
  probe_out="$(python "$WORK/probe_profile.py" "$SCRIPT" "$d" 2>&1)"
  echo "$probe_out"
  echo "$probe_out" | grep -q "PROFILE_TEST_OK" || fail "(f) isolated per-invocation profile assertions failed"
}

# ── Scenario (g): a hung browser is bounded by timeout, not left to hang ───────
scenario_timeout_bounded() {
  local d="$WORK/g"
  write_hang_stub "$d/bin" "hang"
  local probe_out
  probe_out="$(python "$WORK/probe_timeout.py" "$SCRIPT" "$d" "$d/bin/hang.bat" 2>&1)"
  echo "$probe_out"
  echo "$probe_out" | grep -q "TIMEOUT_TEST_OK" || fail "(g) timeout-bounded conversion assertions failed"
}

scenario_fallback_to_next
scenario_all_fail
scenario_output_surfaced
scenario_bad_pdf_rejected
scenario_no_browsers
scenario_isolated_profile
scenario_timeout_bounded

if [ "$FAILED" -ne 0 ]; then
  exit 1
fi
echo "PASS: a failing browser falls through to the next available converter, subprocess output is surfaced (not discarded), a non-PDF output is rejected and not left behind, no-browser is reported deterministically, each invocation gets its own fresh --user-data-dir profile that exists at launch and is cleaned up afterward (uniqueness across invocations stands in for 'browser closed' vs 'already running'), and a hung browser is bounded by its timeout"
