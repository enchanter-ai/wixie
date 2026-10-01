#!/usr/bin/env bash
# Regression test for WIX-SEC-REPORT-001.
#
# The defect: report-gen.py interpolated metadata.json / tests.json values into the generated
# HTML report without any escaping. A malicious value in metadata.json (target_model, task,
# techniques, config, scores, ...) or tests.json (test name, tags) could break out of a text
# node or a double/single-quoted attribute and inject markup or an event handler into a report a
# human is expected to open (file:// origin). Separately, a non-numeric or missing "numeric"
# field (tokens.estimated, a score axis, tokens.context_window, ...) reached an f-string numeric
# format spec ({x:,}) or an arithmetic comparison and raised, crashing report generation instead
# of degrading to a placeholder.
#
# This test drives report-gen.py end to end (real metadata.json/tests.json/prompt.md on disk,
# real generate_report() invocation) with a stub html-to-pdf.py that fails synchronously, so no
# browser/model/network is needed and the HTML fallback path (report.html) is always exercised
# and inspected directly. It never inspects analyze_prompt()/build_html() in isolation -- only
# the actual file report-gen.py writes.
set -uo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
# Private temp root (WIX-TEST-ENV-001): every scratch path below derives from WIXIE_TEST_ROOT.
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"

WORK="$(wixie_mktemp_d report-html-escaping)" || exit 97
trap 'rm -rf "$WORK"' EXIT

FAILED=0
fail() { echo "FAIL: $1"; FAILED=1; }

# A fresh bin/ dir with a throwaway copy of report-gen.py and a synchronously-failing stub
# html-to-pdf.py, so every scenario exercises report.html without needing a real browser.
new_bin() {
  local bin_dir="$1"
  mkdir -p "$bin_dir"
  cp "$REPO_ROOT/shared/scripts/report-gen.py" "$bin_dir/report-gen.py"
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

# Fails on any raw (unescaped) occurrence of a literal HTML tag opener that this template never
# legitimately emits -- report-gen.py's template has no <script>, <img> or <svg> anywhere in its
# static markup, so any occurrence proves an untrusted value broke out into real markup.
assert_no_raw_tag() {
  local file="$1" tag="$2" label="$3"
  if grep -qF "<${tag}" "$file"; then
    fail "$label: a raw, unescaped <${tag} tag reached report.html"
  fi
}

assert_contains() {
  local file="$1" needle="$2" label="$3"
  grep -qF -- "$needle" "$file" || fail "$label: expected escaped marker not found: $needle"
}

assert_not_contains() {
  local file="$1" needle="$2" label="$3"
  grep -qF -- "$needle" "$file" && fail "$label: unexpected raw marker present: $needle"
  return 0
}

assert_no_crash() {
  local out="$1" label="$2"
  if echo "$out" | grep -q "Traceback"; then fail "$label: unhandled exception (Traceback)"; fi
  if echo "$out" | grep -qi "NameError\|TypeError\|ValueError\|AttributeError\|KeyError"; then
    fail "$label: an unhandled Python exception name leaked into output: $(echo "$out" | grep -i 'NameError\|TypeError\|ValueError\|AttributeError\|KeyError' | head -1)"
  fi
}

# ── Scenario (a): hostile payloads, single-score-block metadata ────────────────
scenario_hostile_single_scores() {
  local d="$WORK/a"
  mkdir -p "$d/prompt" "$d/bin"
  new_bin "$d/bin"

  cat > "$d/prompt/metadata.json" <<'JSON'
{
  "mode": "create",
  "status": "pass",
  "target_model": "<script>alert('target_model')</script>",
  "task_domain": "\" onmouseover=\"alert(1)",
  "format": "javascript:alert(1)",
  "task": "<img src=x onerror=alert('task')> and data:text/html,<script>alert(2)</script>",
  "version": "<b>2</b>",
  "created": "<b>&\"'</b>xxxxxxxxxxx",
  "refined": "<i>\"'&</i>xxxxxxxxxxx",
  "tokens": {
    "estimated": "<script>alert('tokens')</script>",
    "context_window": "not-a-number",
    "usage_percent": "100%<script>x</script>"
  },
  "techniques": ["<script>alert('t1')</script>", "\">​<svg onload=alert(2)>‮", 42, null],
  "techniques_avoided": ["javascript:alert('avoided')", true],
  "scores": {
    "clarity": "<script>bad</script>",
    "completeness": 10,
    "efficiency": "high",
    "model_fit": 9,
    "failure_resilience": 10,
    "overall": "critical<script>x</script>"
  },
  "config": {
    "<script>badkey</script>": "<script>badval</script>",
    "temperature": "0.5\" onmouseover=\"alert(1)"
  }
}
JSON

  cat > "$d/prompt/tests.json" <<'JSON'
[
  {"name": "<script>alert('test1')</script>", "input": "x", "expected_contains": [], "tags": ["<script>tag</script>", "normal-tag"]},
  {"name": 12345, "input": "y", "expected_contains": [], "tags": [true, "another\" onmouseover=\"alert(1)"]},
  {"name": "javascript:alert('name')", "input": "z", "expected_contains": [], "tags": []}
]
JSON

  printf '# Prompt\n\n<script>alert("prompt-body")</script>\n\nBe helpful.\n' > "$d/prompt/prompt.md"

  run_report_gen "$d/bin" "$d/prompt"
  echo "$OUT"
  assert_no_crash "$OUT" "(a)"
  [ "$CODE" -eq 1 ] || fail "(a) expected documented exit 1 (stub PDF converter fails), got $CODE"
  echo "$OUT" | grep -q "Done (HTML fallback)\." || fail "(a) missing documented fallback status line"

  local html="$d/prompt/report.html"
  [ -s "$html" ] || { fail "(a) no report.html written"; return; }
  grep -qi "</html>" "$html" || fail "(a) report.html is truncated"

  # No payload ever reaches the page as live, executable markup.
  assert_no_raw_tag "$html" "script" "(a)"
  assert_no_raw_tag "$html" "img" "(a)"
  assert_no_raw_tag "$html" "svg" "(a)"

  # Every payload demonstrably reached the template and came out escaped rather than dropped.
  assert_contains "$html" "&lt;script&gt;alert(&#x27;target_model&#x27;)&lt;/script&gt;" "(a) target_model"
  assert_contains "$html" "&quot; onmouseover=&quot;alert(1)" "(a) task_domain attribute breakout"
  assert_contains "$html" "&lt;img src=x onerror=alert(&#x27;task&#x27;)&gt;" "(a) task"
  assert_contains "$html" "data:text/html,&lt;script&gt;alert(2)&lt;/script&gt;" "(a) task data: URL payload rendered as inert escaped text"
  assert_contains "$html" "javascript:alert(1)" "(a) format field (javascript: URL renders as plain escaped text, never a href)"
  assert_not_contains "$html" 'href="javascript:alert(1)"' "(a) format field must never become a clickable javascript: link"
  assert_contains "$html" "&lt;b&gt;2&lt;/b&gt;" "(a) version"
  # created/refined are truncated to the first 10 characters (date-length convention, unrelated
  # to this fix) before rendering, so the payload is front-loaded within that window.
  assert_contains "$html" "&lt;b&gt;&amp;&quot;&#x27;&lt;/b&gt;" "(a) created (within the first-10-chars date window)"
  assert_contains "$html" "&lt;i&gt;&quot;&#x27;&amp;&lt;/i&gt;" "(a) refined (within the first-10-chars date window)"
  assert_contains "$html" "&lt;script&gt;alert(&#x27;t1&#x27;)&lt;/script&gt;" "(a) techniques[0]"
  assert_contains "$html" "&lt;svg onload=alert(2)&gt;" "(a) techniques[1] survives unicode zero-width/RLO padding and still escapes"
  assert_contains "$html" "javascript:alert(&#x27;avoided&#x27;)" "(a) techniques_avoided[0]"
  assert_contains "$html" "&lt;script&gt;badkey&lt;/script&gt;" "(a) config key"
  assert_contains "$html" "&lt;script&gt;badval&lt;/script&gt;" "(a) config value"
  assert_contains "$html" "0.5&quot; onmouseover=&quot;alert(1)" "(a) config temperature attribute breakout"
  assert_contains "$html" "&lt;script&gt;alert(&#x27;test1&#x27;)&lt;/script&gt;" "(a) tests.json test name"
  assert_contains "$html" "&lt;script&gt;tag&lt;/script&gt;" "(a) tests.json tag"
  assert_contains "$html" "another&quot; onmouseover=&quot;alert(1)" "(a) tests.json second tag attribute breakout"

  # Non-numeric "numeric" fields degrade to escaped placeholder text, not a crash, and are not
  # silently dropped either.
  assert_contains "$html" "&lt;script&gt;alert(&#x27;tokens&#x27;)&lt;/script&gt;" "(a) non-numeric tokens.estimated placeholder"
  assert_contains "$html" "not-a-number" "(a) non-numeric tokens.context_window placeholder"
  assert_contains "$html" "&lt;script&gt;bad&lt;/script&gt;" "(a) non-numeric scores.clarity placeholder"
  assert_contains "$html" "critical&lt;script&gt;x&lt;/script&gt;" "(a) non-numeric scores.overall placeholder"

  # A malformed (non-string) techniques entry (42, null) is dropped, not stringified into a pill
  # or allowed to crash the join.
  assert_not_contains "$html" '<span class="pill-green">42</span>' "(a) non-string techniques entry must not render as a pill"
}

# ── Scenario (b): hostile payloads, before/after score-block metadata ──────────
scenario_hostile_before_after_scores() {
  local d="$WORK/b"
  mkdir -p "$d/prompt" "$d/bin"
  new_bin "$d/bin"

  cat > "$d/prompt/metadata.json" <<'JSON'
{
  "mode": "refine",
  "target_model": "claude-sonnet-5",
  "task": "Refine the onboarding prompt.",
  "scores": {
    "before": {"clarity": 5, "completeness": "n/a<script>x</script>", "efficiency": 6, "model_fit": 6, "failure_resilience": 6, "overall": 5.8},
    "after": {"clarity": 8, "completeness": 9, "efficiency": "<script>after</script>", "model_fit": 9, "failure_resilience": 9, "overall": "<script>overall</script>"}
  }
}
JSON
  cat > "$d/prompt/tests.json" <<'JSON'
[{"name": "happy-path", "input": "x", "expected_contains": [], "tags": []}]
JSON
  printf 'Be helpful and concise.\n' > "$d/prompt/prompt.md"

  run_report_gen "$d/bin" "$d/prompt"
  echo "$OUT"
  assert_no_crash "$OUT" "(b)"
  [ "$CODE" -eq 1 ] || fail "(b) expected documented exit 1, got $CODE"

  local html="$d/prompt/report.html"
  [ -s "$html" ] || { fail "(b) no report.html written"; return; }
  assert_no_raw_tag "$html" "script" "(b)"
  assert_contains "$html" "n/a&lt;script&gt;x&lt;/script&gt;" "(b) before.completeness placeholder"
  assert_contains "$html" "&lt;script&gt;after&lt;/script&gt;" "(b) after.efficiency placeholder"
  assert_contains "$html" "&lt;script&gt;overall&lt;/script&gt;" "(b) after.overall placeholder"
  # A before/after pair where either side is non-numeric can't compute a numeric delta; it must
  # show the documented "?" placeholder, not raise and not show a fabricated number.
  grep -q '>?</td>' "$html" || fail "(b) non-numeric before/after pair should show a '?' delta placeholder"
}

# ── Scenario (c): malformed structural fields (wrong JSON types, no payloads) ──
scenario_malformed_structures() {
  local d="$WORK/c"
  mkdir -p "$d/prompt" "$d/bin"
  new_bin "$d/bin"

  cat > "$d/prompt/metadata.json" <<'JSON'
{
  "target_model": 42,
  "scores": [1, 2, 3],
  "tokens": "not-an-object",
  "config": "not-an-object",
  "techniques": "not-a-list",
  "techniques_avoided": {"weird": true},
  "created": 20260101,
  "refined": true,
  "version": ["v2"]
}
JSON

  run_report_gen "$d/bin" "$d/prompt"
  echo "$OUT"
  assert_no_crash "$OUT" "(c)"
  [ "$CODE" -eq 1 ] || fail "(c) expected documented exit 1, got $CODE"
  local html="$d/prompt/report.html"
  [ -s "$html" ] || fail "(c) no report.html written despite malformed structural fields"
  grep -qi "</html>" "$html" || fail "(c) report.html is truncated"
}

# ── Scenario (d): metadata.json is not valid JSON at all ───────────────────────
scenario_invalid_json() {
  local d="$WORK/d"
  mkdir -p "$d/prompt" "$d/bin"
  new_bin "$d/bin"
  printf '{ this is not valid json' > "$d/prompt/metadata.json"

  run_report_gen "$d/bin" "$d/prompt"
  echo "$OUT"
  assert_no_crash "$OUT" "(d)"
  [ "$CODE" -eq 2 ] || fail "(d) expected documented exit 2 (usage/data error) for invalid JSON, got $CODE"
  [ -f "$d/prompt/report.html" ] && fail "(d) invalid JSON must not produce a report.html either"
  return 0
}

# ── Scenario (e): metadata.json is valid JSON but not an object ────────────────
scenario_nonobject_json() {
  local d="$WORK/e"
  mkdir -p "$d/prompt" "$d/bin"
  new_bin "$d/bin"
  printf '[1, 2, 3]' > "$d/prompt/metadata.json"

  run_report_gen "$d/bin" "$d/prompt"
  echo "$OUT"
  assert_no_crash "$OUT" "(e)"
  [ "$CODE" -eq 1 ] || fail "(e) expected documented exit 1 (degrades to an empty-defaults report), got $CODE"
  local html="$d/prompt/report.html"
  [ -s "$html" ] || fail "(e) no report.html written for a non-object metadata.json"
  grep -qi "</html>" "$html" || fail "(e) report.html is truncated"
}

# ── Scenario (f): benign content must not be double-escaped or mangled ─────────
scenario_benign_no_overescape() {
  local d="$WORK/f"
  mkdir -p "$d/prompt" "$d/bin"
  new_bin "$d/bin"

  cat > "$d/prompt/metadata.json" <<'JSON'
{
  "mode": "create",
  "target_model": "claude-sonnet-5",
  "task_domain": "coding",
  "format": "xml",
  "task": "Summarize the quarterly report for the finance team.",
  "version": 3,
  "tokens": {"estimated": 1200, "context_window": 200000, "usage_percent": 0.6},
  "techniques": ["Few-Shot", "Structured Output"],
  "scores": {"clarity": 8, "completeness": 9, "efficiency": 8, "model_fit": 9, "failure_resilience": 8, "overall": 8.4}
}
JSON
  cat > "$d/prompt/tests.json" <<'JSON'
[{"name": "happy-path", "input": "x", "expected_contains": [], "tags": ["core"]},
 {"name": "edge-empty-input", "input": "", "expected_contains": [], "tags": ["edge-case"]},
 {"name": "failure-timeout", "input": "y", "expected_contains": [], "tags": ["failure"]}]
JSON
  printf 'You are a data analyst. Summarize the report in three bullet points.\n' > "$d/prompt/prompt.md"

  run_report_gen "$d/bin" "$d/prompt"
  echo "$OUT"
  assert_no_crash "$OUT" "(f)"
  [ "$CODE" -eq 1 ] || fail "(f) expected documented exit 1 (stub PDF converter always fails), got $CODE"

  local html="$d/prompt/report.html"
  [ -s "$html" ] || { fail "(f) no report.html written"; return; }
  assert_contains "$html" "claude-sonnet-5" "(f) plain model id must render verbatim, unescaped"
  assert_contains "$html" "Summarize the quarterly report for the finance team." "(f) plain task text must render verbatim"
  assert_not_contains "$html" "&amp;amp;" "(f) no double-escaping artifact"
  assert_not_contains "$html" "&amp;lt;" "(f) no double-escaping artifact"
}

scenario_hostile_single_scores
scenario_hostile_before_after_scores
scenario_malformed_structures
scenario_invalid_json
scenario_nonobject_json
scenario_benign_no_overescape

if [ "$FAILED" -ne 0 ]; then
  exit 1
fi
echo "PASS: metadata.json/tests.json values are contextually escaped (text nodes and quoted attributes), javascript:/data: payloads and unicode-padded payloads never become live markup, malformed numeric/structural fields degrade to escaped placeholders instead of raising, invalid/non-object JSON is handled deterministically, and benign content is not double-escaped"
