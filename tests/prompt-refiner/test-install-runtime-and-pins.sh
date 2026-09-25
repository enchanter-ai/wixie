#!/usr/bin/env bash
# Test: WIX-INSTALL-002 pinned-package materialization contract.
#
# Builds a disposable, fully self-contained fixture vis sibling (not the real
# enchanter-ai/vis — no network, deterministic) whose tags exactly satisfy
# REPO_ROOT's own CLAUDE.md/.vis-versions, then exercises the real, non-mocked
# scripts/bootstrap.sh end to end: full pinned bootstrap must SUCCEED (not
# just refuse), the fixture vis sibling's HEAD/index/working tree must be
# byte-identical before and after, --verify must pass, changing the fixture
# vis's live HEAD must not change --verify's pinned result, re-bootstrap must
# be idempotent (byte-identical cache + lock modulo resolved_at), a missing
# pinned tag must fail loudly without mutating the sibling, and a
# stale/tampered lock must fail --verify.
#
# New test: absent at 3d09e2a (script did not materialize pinned content and
# had no --floating distinction); must fail there and pass at this repo's
# head.

set -euo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"

BOOTSTRAP_SH="$REPO_ROOT/scripts/bootstrap.sh"
CLAUDE_MD="$REPO_ROOT/CLAUDE.md"
VERSIONS_FILE="$REPO_ROOT/.vis-versions"

[[ -x "$BOOTSTRAP_SH" || -f "$BOOTSTRAP_SH" ]] || { echo "missing $BOOTSTRAP_SH" >&2; exit 1; }
[[ -f "$CLAUDE_MD" ]] || { echo "missing $CLAUDE_MD" >&2; exit 1; }
[[ -f "$VERSIONS_FILE" ]] || { echo "missing $VERSIONS_FILE" >&2; exit 1; }

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP" 2>/dev/null || true; }
trap cleanup EXIT

WIXIE="$TMP/wixie"
VIS="$TMP/vis"
mkdir -p "$WIXIE" "$VIS"

# --- copy REPO_ROOT's working tree (not a git clone: we need uncommitted
# working-tree state too, e.g. when this test runs against a work-in-progress
# checkout) into a disposable sibling location ------------------------------
( cd "$REPO_ROOT" && tar -cf - \
    --exclude=.git --exclude=.vis-cache --exclude=state --exclude=node_modules . ) \
  | ( cd "$WIXIE" && tar -xf - )
chmod +x "$WIXIE/scripts/bootstrap.sh" 2>/dev/null || true

# --- parse .vis-versions and CLAUDE.md imports from the copy ---------------
mapfile -t PKG_LINES < <(grep -oE '^[a-z]+:[[:space:]]*"~?[0-9][^"]*"' "$WIXIE/.vis-versions")
declare -a PKGS=() VERS=()
for line in "${PKG_LINES[@]}"; do
  pkg="${line%%:*}"
  ver="$(printf '%s' "$line" | sed -E 's/^[a-z]+:[[:space:]]*"~?//; s/"$//')"
  PKGS+=("$pkg")
  VERS+=("$ver")
done
[[ "${#PKGS[@]}" -gt 0 ]] || { echo "no packages parsed from .vis-versions" >&2; exit 1; }

mapfile -t IMPORTS < <(
  grep -oE '@\.vis-cache/vis/packages/[a-z]+/[A-Za-z0-9._/-]+\.[a-zA-Z]+' "$WIXIE/CLAUDE.md" | \
    sed 's#^@\.vis-cache/vis/##' | LC_ALL=C sort -u
)
[[ "${#IMPORTS[@]}" -gt 0 ]] || { echo "no @.vis-cache/vis/... imports found" >&2; exit 1; }

# --- build the fixture vis: a real git repo whose commit genuinely contains
# every imported path, tagged per-package exactly as .vis-versions declares --
( cd "$VIS" && git init --quiet -b main && git config core.autocrlf false )
for rel in "${IMPORTS[@]}"; do
  full="$VIS/$rel"
  mkdir -p "$(dirname "$full")"
  printf 'fixture content for %s\n' "$rel" > "$full"
done
(
  cd "$VIS"
  git add -A
  git -c user.email="fixture@test.local" -c user.name="fixture" commit --quiet -m "fixture: satisfy REPO_ROOT's CLAUDE.md imports"
)
FIXTURE_SHA="$(git -C "$VIS" rev-parse HEAD)"
for i in "${!PKGS[@]}"; do
  git -C "$VIS" tag "enchanter-${PKGS[$i]}--v${VERS[$i]}" "$FIXTURE_SHA"
done

pass=0
fail=0
check() {
  local desc="$1" rc="$2" want="$3"
  if [[ "$rc" -eq "$want" ]]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    echo "  FAIL: $desc (exit $rc, wanted $want)" >&2
  fi
}

snapshot_vis() {
  git -C "$VIS" rev-parse HEAD
  git -C "$VIS" status --porcelain
  ( cd "$VIS" && find . -path ./.git -prune -o -type f -print | LC_ALL=C sort | xargs sha256sum )
}

BEFORE="$(snapshot_vis)"

# 1. full pinned bootstrap must SUCCEED end to end against the fixture pin.
set +e
OUT="$(cd "$WIXIE" && VIS_REPO="$VIS" ./scripts/bootstrap.sh 2>&1)"
RC=$?
set -e
check "pinned bootstrap succeeds against a satisfying fixture pin" "$RC" 0
printf '%s\n' "$OUT" | grep -q "bootstrapped (pinned)" || { fail=$((fail + 1)); echo "  FAIL: missing 'bootstrapped (pinned)' in output" >&2; }

# 2. every import resolved into the cache.
missing_cache=0
for rel in "${IMPORTS[@]}"; do
  [[ -f "$WIXIE/.vis-cache/vis/$rel" ]] || missing_cache=$((missing_cache + 1))
done
check "every @-import materialized in .vis-cache/vis" "$missing_cache" 0

# 3. sibling vis is byte/state-identical after a full bootstrap.
AFTER="$(snapshot_vis)"
if [[ "$BEFORE" == "$AFTER" ]]; then pass=$((pass + 1)); else
  fail=$((fail + 1)); echo "  FAIL: fixture vis sibling mutated by bootstrap" >&2
fi

# 4. --verify passes against what bootstrap just wrote.
set +e
(cd "$WIXIE" && ./scripts/bootstrap.sh --verify >/dev/null 2>&1)
RC=$?
set -e
check "--verify passes after a clean bootstrap" "$RC" 0

# 5. moving the fixture sibling's live HEAD does not change pinned --verify.
git -C "$VIS" checkout --quiet -b elsewhere "$FIXTURE_SHA"
git -C "$VIS" commit --quiet --allow-empty -m "unrelated dev commit, moves HEAD away from the pin"
set +e
(cd "$WIXIE" && ./scripts/bootstrap.sh --verify >/dev/null 2>&1)
RC=$?
set -e
check "pinned --verify unaffected by sibling HEAD moving" "$RC" 0
git -C "$VIS" checkout --quiet "$FIXTURE_SHA"
git -C "$VIS" branch -D elsewhere --quiet 2>/dev/null || git -C "$VIS" branch -D elsewhere
AFTER2="$(snapshot_vis)"

# 6. idempotent re-bootstrap: byte-identical cache + lock (modulo resolved_at).
cp "$WIXIE/.vis-lock" "$TMP/lock1"
( cd "$WIXIE" && find .vis-cache -type f | LC_ALL=C sort | xargs sha1sum ) > "$TMP/cache1"
(cd "$WIXIE" && VIS_REPO="$VIS" ./scripts/bootstrap.sh >/dev/null)
cp "$WIXIE/.vis-lock" "$TMP/lock2"
( cd "$WIXIE" && find .vis-cache -type f | LC_ALL=C sort | xargs sha1sum ) > "$TMP/cache2"
if diff -q <(grep -v '^resolved_at:' "$TMP/lock1") <(grep -v '^resolved_at:' "$TMP/lock2") >/dev/null \
  && diff -q "$TMP/cache1" "$TMP/cache2" >/dev/null; then
  pass=$((pass + 1))
else
  fail=$((fail + 1)); echo "  FAIL: re-bootstrap is not idempotent" >&2
fi

# 7. missing pinned tag fails explicitly, no sibling mutation, no lock clobber.
cp "$WIXIE/.vis-lock" "$TMP/lock-good"
sed -i 's/~[0-9][0-9.]*"/~99.99.99"/' "$WIXIE/.vis-versions"
BEFORE3="$(snapshot_vis)"
set +e
OUT3="$(cd "$WIXIE" && VIS_REPO="$VIS" ./scripts/bootstrap.sh 2>&1)"
RC=$?
set -e
check "bootstrap fails explicitly when the pinned tag is missing" "$RC" 1
printf '%s\n' "$OUT3" | grep -q "not found locally" || { fail=$((fail + 1)); echo "  FAIL: missing explicit 'not found locally' message" >&2; }
printf '%s\n' "$OUT3" | grep -qi "bump .vis-versions if you intend" || { fail=$((fail + 1)); echo "  FAIL: missing conditional (not primary) 'bump .vis-versions' advice" >&2; }
AFTER3="$(snapshot_vis)"
if [[ "$BEFORE3" == "$AFTER3" ]]; then pass=$((pass + 1)); else
  fail=$((fail + 1)); echo "  FAIL: failed bootstrap mutated the fixture vis sibling" >&2
fi
if diff -q <(grep -v '^resolved_at:' "$TMP/lock-good") <(grep -v '^resolved_at:' "$WIXIE/.vis-lock") >/dev/null; then
  pass=$((pass + 1))
else
  fail=$((fail + 1)); echo "  FAIL: a failed bootstrap clobbered the previous good .vis-lock" >&2
fi
# restore the real pin
for i in "${!PKGS[@]}"; do :; done
cp "$WIXIE/CLAUDE.md" /dev/null 2>/dev/null || true
( cd "$WIXIE" && sed -i "s/~99.99.99\"/~${VERS[0]}\"/" .vis-versions )
# (all four packages share the same version in this repo's .vis-versions;
#  if that ever stops being true this line needs one sed per package)

# 8. stale/tampered lock fails --verify.
(cd "$WIXIE" && VIS_REPO="$VIS" ./scripts/bootstrap.sh >/dev/null)
sed -i '0,/sha1: /{s/sha1: ./sha1: 0/}' "$WIXIE/.vis-lock"
set +e
(cd "$WIXIE" && ./scripts/bootstrap.sh --verify >/dev/null 2>&1)
RC=$?
set -e
check "--verify fails on a tampered lock hash" "$RC" 1

# 9. --floating is a distinct, explicit, non-default mode.
grep -q -- '--floating' "$REPO_ROOT/scripts/bootstrap.sh" || { fail=$((fail + 1)); echo "  FAIL: no --floating flag in bootstrap.sh" >&2; }
grep -q -- '-Floating' "$REPO_ROOT/scripts/bootstrap.ps1" || { fail=$((fail + 1)); echo "  FAIL: no -Floating flag in bootstrap.ps1" >&2; }

# 10. VIS_REPO argument-injection guard present (WIX-SEC-CLONE-001; see also
#     test-sec-clone-vis-repo.sh for the dynamic exploit-attempt regression).
grep -qE 'git clone -- ' "$REPO_ROOT/scripts/bootstrap.sh" || { fail=$((fail + 1)); echo "  FAIL: bootstrap.sh clone call lacks --" >&2; }
grep -qE 'git clone -- ' "$REPO_ROOT/scripts/bootstrap.ps1" || { fail=$((fail + 1)); echo "  FAIL: bootstrap.ps1 clone call lacks --" >&2; }

# 11. Never fetches into an existing sibling (static: no `git ... fetch`
#     INVOCATION anywhere in either script -- clone is allowed, fetch is
#     not; comments and the operator-advice error strings legitimately
#     mention "fetch" and must not trip this, so strip both before checking).
strip_noise() {
  grep -vE '^\s*#' "$1" | grep -vE 'err "|err '"'"'|Console\]::Error'
}
if strip_noise "$REPO_ROOT/scripts/bootstrap.sh" | grep -qE '(^|[^-])\bgit(\.exe)?\b[^#]*\bfetch\b'; then
  fail=$((fail + 1)); echo "  FAIL: bootstrap.sh still invokes 'git ... fetch' (must never mutate an existing sibling)" >&2
fi
if strip_noise "$REPO_ROOT/scripts/bootstrap.ps1" | grep -qE '&\s*git\b[^#]*\bfetch\b'; then
  fail=$((fail + 1)); echo "  FAIL: bootstrap.ps1 still invokes 'git ... fetch' (must never mutate an existing sibling)" >&2
fi

# 12. Import enumeration covers the WHOLE repo, not just CLAUDE.md: a
#     plugin agent/skill file importing a vis path CLAUDE.md never mentions
#     must still be materialized.
FIRST_PKG="${PKGS[0]}"
EXTRA_REL="packages/${FIRST_PKG}/conduct/_fixture-only-agent-import.md"
printf 'fixture content for %s (agent-only import)\n' "$EXTRA_REL" > "$VIS/$EXTRA_REL"
(
  cd "$VIS"
  git add -A
  git -c user.email="fixture@test.local" -c user.name="fixture" commit --quiet -m "fixture: add an agent-only import"
)
NEW_SHA="$(git -C "$VIS" rev-parse HEAD)"
for i in "${!PKGS[@]}"; do
  git -C "$VIS" tag -f "enchanter-${PKGS[$i]}--v${VERS[$i]}" "$NEW_SHA" >/dev/null
done
EXTRA_AGENT="$WIXIE/plugins/_fixture-agent"
mkdir -p "$EXTRA_AGENT"
cat > "$EXTRA_AGENT/probe.md" <<EOF
Probe agent file referencing a vis import that CLAUDE.md never mentions:
@.vis-cache/vis/$EXTRA_REL
EOF
set +e
OUT4="$(cd "$WIXIE" && VIS_REPO="$VIS" ./scripts/bootstrap.sh 2>&1)"
RC4=$?
set -e
check "bootstrap succeeds and picks up an agent-only (non-CLAUDE.md) import" "$RC4" 0
if [[ -f "$WIXIE/.vis-cache/vis/$EXTRA_REL" ]]; then
  pass=$((pass + 1))
else
  fail=$((fail + 1)); echo "  FAIL: agent-only import $EXTRA_REL was not materialized -- enumeration is still CLAUDE.md-only" >&2
fi
rm -rf "$EXTRA_AGENT"

echo "install-runtime-and-pins: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
