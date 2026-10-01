#!/usr/bin/env bash
# Regression test for WIX-G0-REPORT-001.
#
# The defect: report-gen.py's PDF-failure branch printed an f-string referencing `theme`, a name
# never assigned anywhere in the file. The fallback report.html was written and the very next
# statement raised NameError, so a handled degradation became an unhandled crash and no final
# status line ever printed. The child's exit code was also captured and never read, so a stale or
# truncated PDF could be reported as success.
#
# Also covers the async-handoff leak this cluster's independent review demonstrated live:
# WIX-PDF-001 is a host defect (headless Edge launched without --user-data-dir can hand its print
# job off to an already-running Edge instance instead of executing it in the subprocess
# report-gen.py spawned). When that happens, report-gen.py can decide "failed" and exit before the
# real, detached browser instance finishes writing a PDF seconds later — and because report-gen.py
# used a unique-per-run temp name inside the user's prompt folder, that late write left a stray
# "_tmp_report_<id>.pdf" behind, unbounded across repeated runs. report-gen.py is NOT responsible
# for fixing WIX-PDF-001 itself (html-to-pdf.py is untouched); it is responsible for never letting
# that host defect deposit a file into the prompt folder after this process has already returned.
#
# All four scenarios are deterministic: PDF conversion is always driven by a stub
# html-to-pdf.py placed next to a throwaway copy of report-gen.py. No browser, no model, no
# network, no sleeps except the test's own explicit wait for the async scenario's delayed writer.
set -uo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
# Private temp root (WIX-TEST-ENV-001): every scratch path below derives from WIXIE_TEST_ROOT.
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"

WORK="$(wixie_mktemp_d report-pdf-fallback)" || exit 97
trap 'rm -rf "$WORK"' EXIT

FAILED=0
fail() { echo "FAIL: $1"; FAILED=1; }

write_metadata() {
  cat > "$1/metadata.json" <<'JSON'
{
  "name": "fallback-probe",
  "target_model": "claude-sonnet-5",
  "version": 1,
  "scores": {"overall": 8.0},
  "techniques": ["xml-structure"]
}
JSON
}

# A fresh bin/ dir with a throwaway copy of report-gen.py and the given stub html-to-pdf.py, so
# report-gen.py's own script_dir (used to locate html-to-pdf.py) resolves to our stub instead of
# the real converter.
new_bin() {
  local bin_dir="$1"
  mkdir -p "$bin_dir"
  cp "$REPO_ROOT/shared/scripts/report-gen.py" "$bin_dir/report-gen.py"
}

run_report_gen() {
  local bin_dir="$1" prompt_dir="$2"
  OUT="$(cd "$bin_dir" && python "$bin_dir/report-gen.py" "$prompt_dir" 2>&1)"
  CODE=$?
}

# ── Scenario (a): synchronous conversion failure ───────────────────────────────
scenario_sync_failure() {
  local d="$WORK/a"
  mkdir -p "$d/prompt" "$d/bin"
  write_metadata "$d/prompt"
  new_bin "$d/bin"

  cat > "$d/bin/html-to-pdf.py" <<'PY'
import sys
sys.stderr.write("no usable browser found on this host\n")
sys.exit(1)
PY

  run_report_gen "$d/bin" "$d/prompt"
  echo "$OUT"

  if echo "$OUT" | grep -q "NameError"; then fail "(a) failure path raised NameError (the uninitialized 'theme' defect)"; fi
  if echo "$OUT" | grep -q "Traceback"; then fail "(a) failure path raised an unhandled exception"; fi
  [ -s "$d/prompt/report.html" ] || fail "(a) no report.html fallback was written"
  grep -qi "</html>" "$d/prompt/report.html" || fail "(a) report.html fallback is truncated"
  if [ -f "$d/prompt/report.pdf" ]; then fail "(a) a report.pdf was left behind even though conversion failed"; fi
  if find "$d/prompt" -maxdepth 1 -name '_tmp_report*' | grep -q .; then
    fail "(a) temporary intermediate leaked into the prompt folder"
  fi
  [ "$CODE" -eq 1 ] || fail "(a) expected documented exit 1 on PDF failure, got $CODE"
  echo "$OUT" | grep -q "Done (HTML fallback)\." || fail "(a) missing documented fallback status line"
}

# ── Scenario (b): asynchronous browser write (WIX-PDF-001 interaction) ─────────
scenario_async_leak() {
  local d="$WORK/b"
  mkdir -p "$d/prompt" "$d/bin"
  write_metadata "$d/prompt"
  new_bin "$d/bin"

  # The delayed writer stands in for the detached, already-running Edge instance that
  # WIX-PDF-001 hands the print job off to: it wakes up well after the stub (and therefore
  # report-gen.py) has already returned, and only then writes a PDF-named file next to the HTML
  # file it was told about — exactly where the real converter would have written it.
  cat > "$d/bin/_delayed_writer.py" <<'PY'
import sys, time
time.sleep(1.5)
with open(sys.argv[1], "wb") as fh:
    fh.write(b"%PDF-1.4\n% stray asynchronous write from a detached browser instance\n")
PY

  cat > "$d/bin/html-to-pdf.py" <<'PY'
import os, subprocess, sys
args = [a for a in sys.argv[1:] if not a.startswith("--")]
html_path = args[0]
produced_pdf = os.path.splitext(html_path)[0] + ".pdf"
writer = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_delayed_writer.py")
kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
if sys.platform == "win32":
    kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
else:
    kwargs["start_new_session"] = True
subprocess.Popen([sys.executable, writer, produced_pdf], **kwargs)
# This process (standing in for the msedge.exe launcher) reports failure/nothing-yet and exits
# immediately, exactly like the real WIX-PDF-001 handoff: report-gen.py never blocks on the
# detached writer above.
sys.stderr.write("browser handed off to an already-running instance\n")
sys.exit(1)
PY

  run_report_gen "$d/bin" "$d/prompt"
  echo "$OUT"

  if echo "$OUT" | grep -q "Traceback"; then fail "(b) unhandled exception on the async-handoff path"; fi
  [ -s "$d/prompt/report.html" ] || fail "(b) no report.html fallback was written"
  [ "$CODE" -eq 1 ] || fail "(b) expected documented exit 1, got $CODE"
  echo "$OUT" | grep -q "Done (HTML fallback)\." || fail "(b) reported status did not stay 'failed / HTML fallback'"

  # Snapshot the prompt folder right after report-gen.py has already returned (its own report.html
  # fallback is expected to be there) — the thing under test is whether anything changes AFTER
  # this point, once the detached writer fires.
  right_after="$(ls -A "$d/prompt")"

  # Give the detached writer time to fire (it sleeps 1.5s) *after* report-gen.py has already
  # returned and its own process has exited.
  sleep 3

  after="$(ls -A "$d/prompt")"
  if [ "$right_after" != "$after" ]; then
    fail "(b) prompt folder contents changed after report-gen.py returned: right_after=[$right_after] after=[$after]"
  fi
  if [ -f "$d/prompt/report.pdf" ]; then fail "(b) the async browser write leaked report.pdf into the prompt folder"; fi
  if find "$d/prompt" -maxdepth 1 \( -name '_tmp_report*' -o -name '*.pdf' \) | grep -q .; then
    fail "(b) the async browser write leaked a stray PDF/intermediate into the prompt folder"
  fi
}

# ── Scenario (c): stale report.pdf already present ─────────────────────────────
scenario_stale_pdf() {
  local d="$WORK/c"
  mkdir -p "$d/prompt" "$d/bin"
  write_metadata "$d/prompt"
  new_bin "$d/bin"

  printf '%%PDF-1.4\nstale prior-run output\n' > "$d/prompt/report.pdf"
  # Back-date it so a same-second overwrite could never be mistaken for "unchanged".
  touch -d "2000-01-01" "$d/prompt/report.pdf" 2>/dev/null || touch -t 200001010000 "$d/prompt/report.pdf"
  before_hash="$(python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$d/prompt/report.pdf")"
  before_mtime="$(python -c "import os,sys; print(os.path.getmtime(sys.argv[1]))" "$d/prompt/report.pdf")"

  cat > "$d/bin/html-to-pdf.py" <<'PY'
import sys
sys.stderr.write("no usable browser found on this host\n")
sys.exit(1)
PY

  run_report_gen "$d/bin" "$d/prompt"
  echo "$OUT"

  if echo "$OUT" | grep -q "Traceback"; then fail "(c) unhandled exception with a stale report.pdf present"; fi
  [ "$CODE" -eq 1 ] || fail "(c) expected documented exit 1, got $CODE"
  echo "$OUT" | grep -q "Done (HTML fallback)\." || fail "(c) stale report.pdf was reported as fresh (status was not 'failed / HTML fallback')"

  after_hash="$(python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$d/prompt/report.pdf")"
  after_mtime="$(python -c "import os,sys; print(os.path.getmtime(sys.argv[1]))" "$d/prompt/report.pdf")"
  [ "$before_hash" = "$after_hash" ] || fail "(c) the stale report.pdf's content was modified by a failed run"
  [ "$before_mtime" = "$after_mtime" ] || fail "(c) the stale report.pdf's mtime changed on a failed run (it was reported as fresh)"
}

# ── Scenario (d): successful conversion still produces report.pdf ──────────────
scenario_success() {
  local d="$WORK/d"
  mkdir -p "$d/prompt" "$d/bin"
  write_metadata "$d/prompt"
  new_bin "$d/bin"

  cat > "$d/bin/html-to-pdf.py" <<'PY'
import os, sys
args = [a for a in sys.argv[1:] if not a.startswith("--")]
html_path = args[0]
produced_pdf = os.path.splitext(html_path)[0] + ".pdf"
with open(produced_pdf, "wb") as fh:
    fh.write(b"%PDF-1.4\n% deterministic stub output, not a real render\n")
print(f"PDF saved: {produced_pdf} (via stub)")
PY

  run_report_gen "$d/bin" "$d/prompt"
  echo "$OUT"

  if echo "$OUT" | grep -q "Traceback"; then fail "(d) unhandled exception on the success path"; fi
  [ "$CODE" -eq 0 ] || fail "(d) expected documented exit 0 on successful conversion, got $CODE"
  echo "$OUT" | grep -qx "Done\." || fail "(d) missing documented success status line"
  [ -f "$d/prompt/report.pdf" ] || fail "(d) successful conversion did not produce report.pdf"
  head -c5 "$d/prompt/report.pdf" | grep -q '%PDF-' || fail "(d) report.pdf is missing its %PDF- header"
  if [ -f "$d/prompt/report.html" ]; then fail "(d) an HTML fallback was written even though conversion succeeded"; fi
  if find "$d/prompt" -maxdepth 1 -name '_tmp_report*' | grep -q .; then
    fail "(d) temporary intermediate leaked into the prompt folder"
  fi
}

scenario_sync_failure
scenario_async_leak
scenario_stale_pdf
scenario_success

if [ "$FAILED" -ne 0 ]; then
  exit 1
fi
echo "PASS: PDF failure degrades to a complete HTML fallback with no crash and no leaked artifacts (sync + async), a stale report.pdf is never reported as fresh, and successful conversion still produces report.pdf"
