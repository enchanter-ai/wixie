#!/usr/bin/env bash
# Test: every @-import in the repo resolves, by RESOLUTION (relative to the
# file that contains it, any number of ../ segments), to either a real file
# inside the materialized cache or a real local repo file -- never to the
# raw sibling vis, and never to nothing.
#
# Fix round 2 (independent verifier re-verify, VERIFICATION.md fix_round
# item 1): plugins/deep-research/agents/ciber.md carried 5
# @../../../vis/... references that were never materialized or locked,
# because the old enumeration only matched the literal string
# "@.vis-cache/vis/" and never actually resolved a path. This test performs
# the SAME kind of resolution the fixed bootstrap.sh/.ps1 now do, but
# independently, over every *.md file in the repo (not just the ones
# bootstrap happens to cover), so a future un-repointed or newly-broken
# import is caught even if some other bug quietly narrowed bootstrap's own
# enumeration.
#
# New test: absent at 64c51a5 (ciber.md's references resolve into the raw
# sibling, not the cache); must fail there and pass at head.

set -euo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
# Private temp root (WIX-TEST-ENV-001): every scratch path below derives from WIXIE_TEST_ROOT.
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"

BOOTSTRAP_SH="$REPO_ROOT/scripts/bootstrap.sh"
[[ -f "$BOOTSTRAP_SH" ]] || { echo "missing $BOOTSTRAP_SH" >&2; exit 1; }

TMP="$(wixie_mktemp_d install-import-resolution)" || exit 97
cleanup() { rm -rf "$TMP" 2>/dev/null || true; }
trap cleanup EXIT

WIXIE="$TMP/wixie"
VIS="$TMP/vis"
mkdir -p "$WIXIE" "$VIS"

( cd "$REPO_ROOT" && tar -cf - \
    --exclude=.git --exclude=.vis-cache --exclude=state --exclude=node_modules --exclude=.test-root . ) \
  | ( cd "$WIXIE" && tar -xf - )
chmod +x "$WIXIE/scripts/bootstrap.sh"

mapfile -t PKG_LINES < <(grep -oE '^[a-z]+:[[:space:]]*"~?[0-9][^"]*"' "$WIXIE/.vis-versions")
declare -a PKGS=() VERS=()
for line in "${PKG_LINES[@]}"; do
  pkg="${line%%:*}"
  ver="$(printf '%s' "$line" | sed -E 's/^[a-z]+:[[:space:]]*"~?//; s/"$//')"
  PKGS+=("$pkg"); VERS+=("$ver")
done

# Build a fixture vis whose commit genuinely contains every file ANY @-import
# in the repo (resolved) could plausibly need: walk the whole repo tree for
# vis-shaped tokens exactly like bootstrap.sh does, and pre-populate the
# fixture with a file at every distinct target.
mapfile -t VIS_TOKENS < <(
  grep -rhoE '@((\.\./)+|\.[A-Za-z0-9._-]*/|[a-z][A-Za-z0-9_-]*/)[A-Za-z0-9._/-]*\.[A-Za-z0-9]+' \
    "$WIXIE" --include='*.md' \
    --exclude-dir='.vis-cache' --exclude-dir='.git' --exclude-dir='state' --exclude-dir='node_modules' \
    2>/dev/null | grep '/vis/' | sed -E 's#^.*/vis/##' | LC_ALL=C sort -u
)

( cd "$VIS" && git init --quiet -b main && git config core.autocrlf false )
for rel in "${VIS_TOKENS[@]}"; do
  full="$VIS/$rel"
  mkdir -p "$(dirname "$full")"
  printf 'fixture content for %s\n' "$rel" > "$full"
done
( cd "$VIS" && git add -A && git -c user.email=t@t.local -c user.name=t commit --quiet -m fixture )
FIXTURE_SHA="$(git -C "$VIS" rev-parse HEAD)"
for i in "${!PKGS[@]}"; do
  git -C "$VIS" tag "enchanter-${PKGS[$i]}--v${VERS[$i]}" "$FIXTURE_SHA"
done

pass=0
fail=0
check() {
  local desc="$1" rc="$2" want="$3"
  if [[ "$rc" -eq "$want" ]]; then pass=$((pass + 1)); else
    fail=$((fail + 1)); echo "  FAIL: $desc (exit $rc, wanted $want)" >&2
  fi
}

# 1. bootstrap must succeed (proves the whole-repo, resolution-based
#    enumeration in bootstrap.sh itself covers ciber.md and everything else).
set +e
OUT="$(cd "$WIXIE" && VIS_REPO="$VIS" ./scripts/bootstrap.sh 2>&1)"
RC=$?
set -e
check "bootstrap succeeds with every @-import materializable" "$RC" 0
[[ "$RC" -ne 0 ]] && printf '%s\n' "$OUT" >&2

# 2. Independent resolution pass over the WHOLE repo (this test's own logic,
#    not bootstrap's): every @-import must resolve, after bootstrap, to an
#    existing file, and must never resolve into the raw sibling vis dir.
CACHE_DIR="$WIXIE/.vis-cache/vis"
UNRESOLVED=0
INTO_SIBLING=0
CHECKED=0
while IFS= read -r -d '' mdfile; do
  fdir="$(dirname "$mdfile")"
  while IFS= read -r tok; do
    [[ -z "$tok" ]] && continue
    CHECKED=$((CHECKED + 1))
    resolved="$(realpath -m "$fdir/$tok" 2>/dev/null)" || { UNRESOLVED=$((UNRESOLVED + 1)); echo "  does not resolve at all: $mdfile -> @$tok" >&2; continue; }
    case "$resolved" in
      "$VIS"/*)
        INTO_SIBLING=$((INTO_SIBLING + 1))
        echo "  resolves into the raw sibling vis (not the cache): $mdfile -> @$tok -> $resolved" >&2
        ;;
      "$CACHE_DIR"/*)
        if [[ ! -f "$resolved" ]]; then
          UNRESOLVED=$((UNRESOLVED + 1))
          echo "  resolves into the cache but the file is missing: $mdfile -> @$tok -> $resolved" >&2
        fi
        ;;
      *)
        # A local repo import (e.g. @shared/conduct/...): must exist.
        if [[ ! -f "$resolved" ]]; then
          UNRESOLVED=$((UNRESOLVED + 1))
          echo "  local import does not resolve to an existing file: $mdfile -> @$tok -> $resolved" >&2
        fi
        ;;
    esac
  done < <(grep -oE '@((\.\./)+|\.[A-Za-z0-9._-]*/|[a-z][A-Za-z0-9_-]*/)[A-Za-z0-9._/-]*\.[A-Za-z0-9]+' "$mdfile" 2>/dev/null | sed 's/^@//')
done < <(find "$WIXIE" -name '*.md' -type f \
           -not -path '*/.git/*' -not -path '*/.vis-cache/*' \
           -not -path '*/state/*' -not -path '*/node_modules/*' -print0)

check "at least one @-import was actually checked (sanity)" "$([[ "$CHECKED" -gt 0 ]] && echo 0 || echo 1)" 0
check "no @-import resolves into the raw sibling vis" "$INTO_SIBLING" 0
check "every @-import resolves to an existing file" "$UNRESOLVED" 0

echo "checked $CHECKED @-imports across the repo"
echo "install-import-resolution: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
