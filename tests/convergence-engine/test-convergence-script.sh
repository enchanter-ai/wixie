#!/usr/bin/env bash
# Test: convergence.py improves a weak prompt
set -euo pipefail
REPO_ROOT="${1:-.}"
# Private temp root (WIX-TEST-ENV-001): every scratch path below derives from WIXIE_TEST_ROOT.
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"

WORK="$(wixie_mktemp_d convergence-script)" || exit 97
trap 'rm -rf "$WORK"' EXIT
TMPFILE="$WORK/_test_prompt.txt"
echo "maybe try to write something if possible. perhaps do some analysis somewhat." > "$TMPFILE"

python "$REPO_ROOT/shared/scripts/convergence.py" "$TMPFILE" --max 5 > /dev/null 2>&1 || true

CONTENT=$(cat "$TMPFILE")
HITS=0
echo "$CONTENT" | grep -qi "domain expert" && HITS=$((HITS+1)) || true
echo "$CONTENT" | grep -qi "output format" && HITS=$((HITS+1)) || true
echo "$CONTENT" | grep -qi "edge case" && HITS=$((HITS+1)) || true
echo "$CONTENT" | grep -qi "unsure\|verify" && HITS=$((HITS+1)) || true

rm -f "$TMPFILE"
[[ $HITS -ge 2 ]]
