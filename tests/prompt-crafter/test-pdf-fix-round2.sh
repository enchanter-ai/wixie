#!/usr/bin/env bash
# Regression test for WIX-PDF-001 fix round 2.
#
# The defect the independent verifier found in round 1's fix: real Edge on this host exits 0
# roughly 1.6-1.9s BEFORE its own (detached) writer process actually finishes creating the PDF.
# convert_one saw the empty output file, reported "wrote nothing", and deleted it -- but that
# file lived directly in the shared OS temp root (round 1's fix moved the *profile* into a
# private directory, but not the output file), so Edge's late write then recreated it there as a
# loose, unswept wixie-pdf-out-*.pdf. This happened in 8/8 real Edge attempts.
#
# Fix round 2: (1) every attempt's profile AND output now live inside ONE private
# wixie-pdf-attempt-* directory, never the shared temp root; (2) convert_one polls for a late
# write (LATE_WRITE_POLL_S, size-stable + %PDF--validated) before declaring failure; (3) the
# startup sweep now also covers wixie-pdf-attempt-* dirs and legacy wixie-pdf-out-* files.
#
# No real browser is needed for any scenario here. Per the coordinator's explicit instruction,
# this test points TMP/TEMP at an isolated directory inside the work dir for its own duration and
# never touches the user's real %TEMP% (see the export block below); it does not delete anything
# outside that isolated directory.
set -uo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
# Private temp root (WIX-TEST-ENV-001): every scratch path below derives from WIXIE_TEST_ROOT.
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"
SCRIPT="$REPO_ROOT/shared/scripts/html-to-pdf.py"

WORK="$(wixie_mktemp_d pdf-fix-round2)" || exit 97
trap 'rm -rf "$WORK"' EXIT

# See test-pdf-browser-fallback.sh's matching comment for the empirical confirmation that Git
# Bash/MSYS auto-translates TMP/TEMP so a plain forward-slash export here is seen correctly by
# native Windows Python's tempfile.gettempdir(), both directly and through a nested subprocess.
mkdir -p "$WORK/systmp"
export TMP="$WORK/systmp"
export TEMP="$WORK/systmp"

FAILED=0
fail() { echo "FAIL: $1"; FAILED=1; }

# A stub "browser" .bat wrapper forwarding to a companion Python script (see
# test-pdf-browser-fallback.sh for why a .bat wrapper is the right shape on Windows).
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

# Exits 0 immediately, writing NOTHING itself -- but spawns a DETACHED process that writes a
# valid PDF to the requested --print-to-pdf= path after WIXIE_TEST_DELAY seconds. This is the
# exact shape of the real Edge defect: subprocess exit is not proof the file is finished, or
# even started.
STUB_DELAYED_WRITER='
import sys, os, subprocess

target = None
for a in sys.argv[1:]:
    if a.startswith("--print-to-pdf="):
        target = a.split("=", 1)[1]

delay = os.environ.get("WIXIE_TEST_DELAY", "2")
code = (
    "import sys, time\n"
    "time.sleep(float(sys.argv[1]))\n"
    "with open(sys.argv[2], \"wb\") as fh:\n"
    "    fh.write(b\"%PDF-1.4\\n% late detached write\\n\")\n"
)
kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
if sys.platform == "win32":
    kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
else:
    kwargs["start_new_session"] = True
subprocess.Popen([sys.executable, "-c", code, delay, target], **kwargs)
sys.exit(0)
'

# Exits 0 immediately and never writes anything, ever (no detached child at all).
STUB_NEVER_WRITES='
import sys
sys.exit(0)
'

write_html() {
  printf '<!DOCTYPE html><html><body>report</body></html>' > "$1"
}

# Every wixie-pdf-* item found directly inside the isolated temp root (systmp), one per line.
list_isolated_temp_wixie_items() {
  find "$WORK/systmp" -maxdepth 1 -iname 'wixie-pdf-*' 2>/dev/null
}

# ── Driver: calls convert_one() directly (importlib), no CLI, so the exact boolean/timing/
# leftover-state can be asserted precisely. ─────────────────────────────────────────────────
cat > "$WORK/probe_convert_one.py" <<'PY'
# argv: <html_to_pdf_script> <work_dir> <stub_bat> <delay_seconds_or_empty>
import importlib.util, os, sys, time

script, work_dir, stub_bat = sys.argv[1], sys.argv[2], sys.argv[3]
if len(sys.argv) > 4 and sys.argv[4]:
    os.environ["WIXIE_TEST_DELAY"] = sys.argv[4]

spec = importlib.util.spec_from_file_location("m", script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

html = os.path.join(work_dir, "report.html")
with open(html, "w") as f:
    f.write("<html></html>")
pdf = os.path.join(work_dir, "report.pdf")

start = time.time()
ok, detail = mod.convert_one(html, pdf, "Delayed", stub_bat, "chromium")
elapsed = time.time() - start

print("OK", ok)
print("DETAIL", detail)
print("ELAPSED", round(elapsed, 2))
print("DEST_PDF_EXISTS", os.path.isfile(pdf))
if os.path.isfile(pdf):
    with open(pdf, "rb") as fh:
        print("DEST_PDF_VALID", fh.read(5) == b"%PDF-")
print("LATE_WRITE_POLL_S", mod.LATE_WRITE_POLL_S)
print("PROBE_DONE")
PY

# ── Scenario (a): late write arrives WITHIN the bound -- must succeed, leave nothing behind ──
scenario_late_write_within_bound_succeeds() {
  local d="$WORK/a"
  mkdir -p "$d"
  write_stub "$d/bin" "delayed" "$STUB_DELAYED_WRITER"

  local before after out
  before="$(list_isolated_temp_wixie_items)"
  out="$(python "$WORK/probe_convert_one.py" "$SCRIPT" "$d" "$d/bin/delayed.bat" "2" 2>&1)"
  echo "$out"
  echo "$out" | grep -q "PROBE_DONE" || { fail "(a) probe did not complete"; return; }

  echo "$out" | grep -q "^OK True" || fail "(a) a write that lands 2s after exit (within the 5s bound) must be accepted as success"
  echo "$out" | grep -q "^DEST_PDF_EXISTS True" || fail "(a) report.pdf was not produced"
  echo "$out" | grep -q "^DEST_PDF_VALID True" || fail "(a) report.pdf is not a valid PDF"

  # Give any trailing cleanup a brief moment, then confirm nothing wixie-pdf-* related is left
  # anywhere directly in the isolated temp root -- this is the actual fix under test: round 1
  # would have left a loose wixie-pdf-out-*.pdf here once the late write landed.
  sleep 1
  after="$(list_isolated_temp_wixie_items)"
  [ -z "$after" ] || fail "(a) leftover wixie-pdf-* item(s) in the isolated temp root after a successful late write: $after"
}

# ── Scenario (b): a writer that never writes at all -- must fall through, leave nothing ──────
scenario_never_writes_falls_through() {
  local d="$WORK/b"
  mkdir -p "$d"
  write_stub "$d/bin" "never" "$STUB_NEVER_WRITES"

  local out
  out="$(python "$WORK/probe_convert_one.py" "$SCRIPT" "$d" "$d/bin/never.bat" "" 2>&1)"
  echo "$out"
  echo "$out" | grep -q "PROBE_DONE" || { fail "(b) probe did not complete"; return; }

  echo "$out" | grep -q "^OK False" || fail "(b) a browser that never writes anything must not be reported as success"
  echo "$out" | grep -qi "wrote nothing" || fail "(b) failure reason should say the browser wrote nothing"
  echo "$out" | grep -q "^DEST_PDF_EXISTS False" || fail "(b) no report.pdf should exist"

  local after
  after="$(list_isolated_temp_wixie_items)"
  [ -z "$after" ] || fail "(b) leftover wixie-pdf-* item(s) in the isolated temp root after a writer that never wrote anything: $after"
}

# ── Scenario (c): the late write arrives AFTER the bound -- confined to the private dir,
# never loose in the shared temp root, and eventually removed or swept ──────────────────────
scenario_late_write_after_bound_confined() {
  local d="$WORK/c"
  mkdir -p "$d"
  write_stub "$d/bin" "verylate" "$STUB_DELAYED_WRITER"

  local out
  out="$(python "$WORK/probe_convert_one.py" "$SCRIPT" "$d" "$d/bin/verylate.bat" "8" 2>&1)"
  echo "$out"
  echo "$out" | grep -q "PROBE_DONE" || { fail "(c) probe did not complete"; return; }

  echo "$out" | grep -q "^OK False" || fail "(c) a write that lands after the poll bound must not be reported as success"
  local elapsed
  elapsed="$(echo "$out" | grep "^ELAPSED" | awk '{print $2}')"
  # Must have actually waited close to the 5s bound (not given up instantly) but must NOT have
  # waited anywhere near the full 8s delay -- that is the bound actually being honoured.
  python -c "
e = $elapsed
assert 4.0 <= e <= 7.5, f'expected convert_one to give up around the {5.0}s bound, took {e}s'
print('ELAPSED_BOUND_OK')
" || fail "(c) convert_one did not respect LATE_WRITE_POLL_S (elapsed=${elapsed}s)"

  # The critical assertion: even while the detached writer is still pending (it lands at ~8s,
  # well after convert_one already gave up around ~5s), nothing must ever be directly inside the
  # isolated temp ROOT -- only, at most, still inside a wixie-pdf-attempt-* directory. This is
  # exactly what round 1 got wrong (it wrote straight into the shared root).
  local loose
  loose="$(find "$WORK/systmp" -maxdepth 1 -iname 'wixie-pdf-out-*' 2>/dev/null)"
  [ -z "$loose" ] || fail "(c) a wixie-pdf-out-* file is loose directly in the isolated temp root: $loose"

  # Wait past the 8s delayed write, then past a chunk of the bounded cleanup retry, and check
  # again -- confined to a subdirectory throughout is fine; loose in the root is the failure.
  sleep 6
  loose="$(find "$WORK/systmp" -maxdepth 1 -iname 'wixie-pdf-out-*' 2>/dev/null)"
  [ -z "$loose" ] || fail "(c) a wixie-pdf-out-* file is loose directly in the isolated temp root after the late write landed: $loose"

  # Finally, prove full reclamation: whatever wixie-pdf-attempt-* directory might still remain
  # (the retry inside convert_one may or may not have already won the race) is picked up by the
  # sweep once it is old enough -- back-date it and sweep for real, rather than waiting out the
  # full 600s in this test.
  local remaining
  remaining="$(list_isolated_temp_wixie_items)"
  if [ -n "$remaining" ]; then
    python -c "
import importlib.util, os, time
spec = importlib.util.spec_from_file_location('m', r'$SCRIPT')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
tmp = r'$WORK/systmp'
old = time.time() - mod.STALE_PDF_TEMP_MAX_AGE_S - 60
for name in os.listdir(tmp):
    if name.startswith('wixie-pdf-'):
        os.utime(os.path.join(tmp, name), (old, old))
mod.tempfile.gettempdir = lambda: tmp
mod._sweep_stale_pdf_temp_items()
print('SWEPT')
" || fail "(c) sweep-backstop probe failed to run"
    remaining="$(list_isolated_temp_wixie_items)"
  fi
  [ -z "$remaining" ] || fail "(c) a wixie-pdf-* item survives both the bounded retry and the sweep: $remaining"
}

scenario_late_write_within_bound_succeeds
scenario_never_writes_falls_through
scenario_late_write_after_bound_confined

if [ "$FAILED" -ne 0 ]; then
  exit 1
fi
echo "PASS: a browser whose write lands within LATE_WRITE_POLL_S is accepted as success with nothing left behind, a browser that never writes falls through cleanly with nothing left behind, and a write that lands after the bound is confined to the private per-attempt directory (never loose in the shared/isolated temp root) and is fully reclaimed by the bounded retry and/or the sweep"
