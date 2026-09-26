#!/usr/bin/env bash
# Test: convergence.py improves a weak prompt -- inside its explicit editable region
# (WIX-CONV-001 / D15). The weak prompt is annotated with prompt_regions.py (one region over
# the whole text), converged as <folder>/editable/prompt.txt, and the shipped file
# <folder>/prompt.txt must be the stripped, improved text. An unannotated copy of the same
# prompt must NOT be rewritten (critique only).
set -euo pipefail
REPO_ROOT="${1:-.}"
# Private temp root (WIX-TEST-ENV-001): every scratch path below derives from WIXIE_TEST_ROOT.
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"

WORK="$(wixie_mktemp_d convergence-script)" || exit 97
trap 'rm -rf "$WORK"' EXIT
PR="$REPO_ROOT/shared/scripts/prompt_regions.py"
CONV="$REPO_ROOT/shared/scripts/convergence.py"

mkdir -p "$WORK/weak/editable" "$WORK/legacy"
echo "maybe try to write something if possible. perhaps do some analysis somewhat." > "$WORK/weak/prompt.txt"
cp "$WORK/weak/prompt.txt" "$WORK/legacy/prompt.txt"
python "$PR" annotate "$WORK/weak/prompt.txt" "$WORK/weak/editable/prompt.txt" --region body=L1-L1 > /dev/null

python "$CONV" "$WORK/weak/editable/prompt.txt" --max 5 > /dev/null 2>&1 || true

CONTENT=$(cat "$WORK/weak/prompt.txt")
HITS=0
echo "$CONTENT" | grep -qi "domain expert" && HITS=$((HITS+1)) || true
echo "$CONTENT" | grep -qi "output format" && HITS=$((HITS+1)) || true
echo "$CONTENT" | grep -qi "edge case" && HITS=$((HITS+1)) || true
echo "$CONTENT" | grep -qi "unsure\|verify" && HITS=$((HITS+1)) || true
[[ $HITS -ge 2 ]]
# the shipped file is exactly strip(master) and carries no marker text
python "$PR" strip --check "$WORK/weak/editable/prompt.txt" "$WORK/weak/prompt.txt" > /dev/null
if grep -q "wixie-editable" "$WORK/weak/prompt.txt"; then exit 1; fi

# unannotated legacy prompt: never rewritten
BEFORE=$(cat "$WORK/legacy/prompt.txt")
python "$CONV" "$WORK/legacy/prompt.txt" --max 5 > /dev/null 2>&1 || true
[[ "$(cat "$WORK/legacy/prompt.txt")" == "$BEFORE" ]]
