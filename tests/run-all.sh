#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PASS=0
FAIL=0

# Private test temp root (WIX-TEST-ENV-001; contract in tests/lib/test-root.sh). Unset:
# create a fresh per-run root under <repo>/.test-root/ (gitignored) and remove it at the end
# (keep it with WIXIE_TEST_KEEP_ROOT=1). Set: use it as given after validation. Either way every
# test inherits TMPDIR/TMP/TEMP inside the root; nothing falls back to a global temp dir.
OWNED_ROOT=""
if [[ -z "${WIXIE_TEST_ROOT:-}" ]]; then
  mkdir -p "$REPO_ROOT/.test-root"
  OWNED_ROOT="$(mktemp -d "$REPO_ROOT/.test-root/run.XXXXXX")"
  WIXIE_TEST_ROOT="$OWNED_ROOT"
fi
# shellcheck source=lib/test-root.sh
source "$SCRIPT_DIR/lib/test-root.sh"
if [[ -n "$OWNED_ROOT" && "${WIXIE_TEST_KEEP_ROOT:-0}" != 1 ]]; then
  trap 'rm -rf "$OWNED_ROOT"' EXIT
fi

# Preflight: Python children must resolve their temp dir inside the root too.
PY="$(command -v python || command -v python3 || true)"
[[ -n "$PY" ]] || { echo "run-all: no python/python3 on PATH -- cannot run the suite" >&2; exit 97; }
PY_TMP="$("$PY" -c 'import tempfile; print(tempfile.gettempdir())' | tr -d '\r')"
wixie__inside "$(wixie__native "$PY_TMP")" "$wixie__root_native" \
  || { echo "run-all: python tempdir '$PY_TMP' is outside WIXIE_TEST_ROOT '$WIXIE_TEST_ROOT'" >&2; exit 97; }

run_test() {
  local test_file="$1"
  local name
  name="$(basename "$test_file" .sh)"
  if bash "$test_file" "$REPO_ROOT" 2>/dev/null; then
    echo "  PASS  $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $name"
    FAIL=$((FAIL + 1))
  fi
}

echo ""
echo "================================================"
echo "  WIXIE TEST SUITE"
echo "  WIXIE_TEST_ROOT=$WIXIE_TEST_ROOT"
echo "================================================"
echo ""

for suite_dir in "$SCRIPT_DIR"/*/; do
  suite="$(basename "$suite_dir")"
  [[ "$suite" == lib ]] && continue
  echo "  [$suite]"
  for test_file in "$suite_dir"test-*.sh; do
    [[ -f "$test_file" ]] || continue
    run_test "$test_file"
  done
  echo ""
done

TOTAL=$((PASS + FAIL))
echo "================================================"
echo "  $PASS/$TOTAL passed"
# Machine-checkable evidence that the suite actually executed (CI asserts it; WIX-CI-001).
SUMMARY="WIXIE_SUITE_SUMMARY total=$TOTAL passed=$PASS failed=$FAIL"
echo "$SUMMARY"
if [[ -n "${WIXIE_SUITE_SUMMARY_FILE:-}" ]]; then
  printf '%s\n' "$SUMMARY" > "$WIXIE_SUITE_SUMMARY_FILE"
fi
if [[ $TOTAL -eq 0 ]]; then
  echo "  NO TESTS RAN"
  exit 1
fi
if [[ $FAIL -gt 0 ]]; then
  echo "  $FAIL FAILED"
  exit 1
fi
echo "  All tests passed."
echo "================================================"
