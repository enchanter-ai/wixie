#!/usr/bin/env bash
# Regression test for OBS-14 (opportunistic, not one of the 12 audited findings or a new-findings
# entry -- found by the WIX-PDF-001 fix-round-1 independent verifier while re-checking
# WIX-SEC-REPORT-001, same file already under remediation).
#
# The defect: metadata.json's target_model given as a JSON list or dict (a malformed but
# perfectly valid JSON value) is unhashable, and estimate_cost()'s
# pricing_per_1k_input.get(model_id, 0) raises an uncaught TypeError before build_html() ever
# finishes -- so unlike every other malformed-field case report-gen.py already handles, this one
# crashes report generation outright with NO HTML fallback written at all, at both base and head.
set -uo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
# Private temp root (WIX-TEST-ENV-001): every scratch path below derives from WIXIE_TEST_ROOT.
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"

WORK="$(wixie_mktemp_d report-obs14-unhashable-model)" || exit 97
trap 'rm -rf "$WORK"' EXIT

FAILED=0
fail() { echo "FAIL: $1"; FAILED=1; }

new_bin() {
  local bin_dir="$1"
  mkdir -p "$bin_dir"
  cp "$REPO_ROOT/shared/scripts/report-gen.py" "$bin_dir/report-gen.py"
  # Deterministic, no real browser needed: PDF conversion always fails synchronously, so every
  # scenario is driven down the HTML-fallback path and the fallback HTML itself is inspected.
  cat > "$bin_dir/html-to-pdf.py" <<'PY'
import sys
sys.stderr.write("no usable browser found on this host\n")
sys.exit(1)
PY
}

run_report_gen() {
  local bin_dir="$1" prompt_dir="$2"
  OUT="$(cd "$bin_dir" && python "$bin_dir/report-gen.py" "$prompt_dir" 2>&1)"
  CODE=$?
}

assert_no_crash() {
  local out="$1" label="$2"
  echo "$out" | grep -q "Traceback" && fail "$label: unhandled exception (Traceback)"
  echo "$out" | grep -qi "TypeError\|unhashable" && fail "$label: TypeError/unhashable leaked into output"
}

scenario_list_target_model() {
  local d="$WORK/a"
  mkdir -p "$d/prompt" "$d/bin"
  new_bin "$d/bin"
  cat > "$d/prompt/metadata.json" <<'JSON'
{"target_model": ["claude-sonnet-5", "backup-model"], "scores": {"overall": 8}}
JSON
  run_report_gen "$d/bin" "$d/prompt"
  echo "$OUT"
  assert_no_crash "$OUT" "(a) list target_model"
  [ "$CODE" -eq 1 ] || fail "(a) expected documented exit 1 (HTML fallback), got $CODE"
  [ -s "$d/prompt/report.html" ] || fail "(a) no report.html fallback was written for a list target_model"
  grep -qi "</html>" "$d/prompt/report.html" || fail "(a) report.html fallback is truncated"
}

scenario_dict_target_model() {
  local d="$WORK/b"
  mkdir -p "$d/prompt" "$d/bin"
  new_bin "$d/bin"
  cat > "$d/prompt/metadata.json" <<'JSON'
{"target_model": {"weird": "dict"}, "tokens": {"estimated": 500}, "scores": {"overall": 6}}
JSON
  run_report_gen "$d/bin" "$d/prompt"
  echo "$OUT"
  assert_no_crash "$OUT" "(b) dict target_model"
  [ "$CODE" -eq 1 ] || fail "(b) expected documented exit 1 (HTML fallback), got $CODE"
  [ -s "$d/prompt/report.html" ] || fail "(b) no report.html fallback was written for a dict target_model"
}

scenario_list_target_model_with_tokens_estimated() {
  # estimate_cost is also called from build_html directly with the raw target_model, not just
  # from analyze_prompt -- cover that call site too.
  local d="$WORK/c"
  mkdir -p "$d/prompt" "$d/bin"
  new_bin "$d/bin"
  cat > "$d/prompt/metadata.json" <<'JSON'
{"target_model": [1, 2, 3], "tokens": {"estimated": 1200, "context_window": 200000}}
JSON
  run_report_gen "$d/bin" "$d/prompt"
  echo "$OUT"
  assert_no_crash "$OUT" "(c) list target_model with numeric tokens"
  [ "$CODE" -eq 1 ] || fail "(c) expected documented exit 1 (HTML fallback), got $CODE"
  [ -s "$d/prompt/report.html" ] || fail "(c) no report.html fallback was written"
}

scenario_list_target_model
scenario_dict_target_model
scenario_list_target_model_with_tokens_estimated

if [ "$FAILED" -ne 0 ]; then
  exit 1
fi
echo "PASS: a target_model given as a JSON list or dict no longer crashes report generation (estimate_cost degrades to no cost estimate instead of raising on an unhashable dict key); a complete HTML fallback is written in every case"
