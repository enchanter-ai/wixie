#!/usr/bin/env bash
# Test: WIX-INSTALL-002 exclusion filters apply to path components RELATIVE
# TO THE REPO ROOT only -- never as a substring match against the whole
# filesystem path, which would also match an ANCESTOR directory of the repo
# itself (e.g. the repo checked out under .../state/wixie) and silently
# exclude everything.
#
# Fix round 2 (independent verifier re-verify, VERIFICATION.md fix_round
# item 3): under PowerShell 5.1, when any PARENT directory of the repo was
# named state, .git, node_modules or .vis-cache, bootstrap materialized 0
# files and exited 0, and -Verify exited 0 against a correct lock. Bash was
# unaffected (its `find`/`grep --exclude-dir` traversal only ever descends
# from the repo root, so an ancestor name was never a hazard there), but
# this test proves the fixed behaviour on both entry points.
#
# Deliberately lightweight (a small self-contained 1-package/2-file
# fixture, not a full copy of the real repo tree) so the four ancestor
# names x two entry points run quickly and deterministically -- the bug is
# in the exclusion-filter logic, not in any specific real file content.
#
# New test: absent at 64c51a5 (the PS 5.1 exclusion used a full-path
# substring match); the PS leg fails there under any of the four ancestor
# names and passes at head. Skips (does not fail) the PowerShell leg where
# it is unavailable on this host.

set -euo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
# Private temp root (WIX-TEST-ENV-001): every scratch path below derives from WIXIE_TEST_ROOT.
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"
BOOTSTRAP_SH="$REPO_ROOT/scripts/bootstrap.sh"
BOOTSTRAP_PS1="$REPO_ROOT/scripts/bootstrap.ps1"

pass=0
fail=0
check() {
  local desc="$1" rc="$2" want="$3"
  if [[ "$rc" -eq "$want" ]]; then pass=$((pass + 1)); else
    fail=$((fail + 1)); echo "  FAIL: $desc (exit $rc, wanted $want)" >&2
  fi
}

TMP="$(wixie_mktemp_d install-ancestor-dirs)" || exit 97
cleanup() { rm -rf "$TMP" 2>/dev/null || true; }
trap cleanup EXIT

# --- one small, self-contained fixture pair, rebuilt fresh under each
# ancestor directory name -----------------------------------------------
build_fixture() {
  local dest="$1"
  mkdir -p "$dest/wixie/scripts" "$dest/wixie/plugins/pkg/agents" "$dest/vis/packages/core/conduct"
  cp "$BOOTSTRAP_SH" "$dest/wixie/scripts/bootstrap.sh"
  [[ -f "$BOOTSTRAP_PS1" ]] && cp "$BOOTSTRAP_PS1" "$dest/wixie/scripts/bootstrap.ps1"
  chmod +x "$dest/wixie/scripts/bootstrap.sh"
  cat > "$dest/wixie/.vis-versions" <<'EOF'
core: "~1.0.0"
EOF
  cat > "$dest/wixie/CLAUDE.md" <<'EOF'
- @.vis-cache/vis/packages/core/conduct/a.md
EOF
  # A nested agent file 2 directories deep, exactly like the real
  # plugins/deep-research/agents/*.md files, so the test also exercises
  # depth-relative resolution alongside the exclusion-filter fix.
  cat > "$dest/wixie/plugins/pkg/agents/probe.md" <<'EOF'
- @../../../.vis-cache/vis/packages/core/conduct/b.md
EOF
  echo "content a" > "$dest/vis/packages/core/conduct/a.md"
  echo "content b" > "$dest/vis/packages/core/conduct/b.md"
  ( cd "$dest/vis" && git init --quiet -b main && git config core.autocrlf false \
      && git add -A && git -c user.email=t@t.local -c user.name=t commit --quiet -m fixture )
  local sha; sha="$(git -C "$dest/vis" rev-parse HEAD)"
  git -C "$dest/vis" tag enchanter-core--v1.0.0 "$sha"
}

for name in state .git node_modules .vis-cache; do
  safe="$(printf '%s' "$name" | tr -d '.')"
  parent="$TMP/parent-$safe"
  mkdir -p "$parent/$name"
  build_fixture "$parent/$name"

  # --- bash (Git Bash on this host; find/grep --exclude-dir only ever
  # descends from the repo root, so this leg is a regression guard, not
  # expected to ever have failed) ------------------------------------------
  set +e
  (cd "$parent/$name/wixie" && VIS_REPO="$parent/$name/vis" ./scripts/bootstrap.sh >"$TMP/anc_boot.out" 2>&1)
  RC=$?
  set -e
  check "[$name] bash bootstrap succeeds" "$RC" 0
  CNT=$(find "$parent/$name/wixie/.vis-cache" -type f 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$CNT" -eq 2 ]]; then pass=$((pass + 1)); else
    fail=$((fail + 1)); echo "  FAIL: [$name] bash materialized $CNT files, expected 2 (output: $(cat "$TMP/anc_boot.out"))" >&2
  fi
  rm -f "$TMP/anc_boot.out"
  set +e
  (cd "$parent/$name/wixie" && ./scripts/bootstrap.sh --verify >/dev/null 2>&1)
  RC=$?
  set -e
  check "[$name] bash --verify passes" "$RC" 0

  # --- PowerShell 5.1 (this host), if available ---------------------------
  if [[ -f "$parent/$name/wixie/scripts/bootstrap.ps1" ]] && command -v powershell.exe >/dev/null 2>&1; then
    rm -rf "$parent/$name/wixie/.vis-cache" "$parent/$name/wixie/.vis-lock"
    set +e
    OUT_PS="$(cd "$parent/$name/wixie" && VIS_REPO="$parent/$name/vis" powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 2>&1)"
    RC_PS=$?
    set -e
    check "[$name] PS 5.1 bootstrap succeeds" "$RC_PS" 0
    CNT_PS=$(find "$parent/$name/wixie/.vis-cache" -type f 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$CNT_PS" -eq 2 ]]; then pass=$((pass + 1)); else
      fail=$((fail + 1)); echo "  FAIL: [$name] PS 5.1 materialized $CNT_PS files, expected 2 (output: $OUT_PS)" >&2
    fi
    set +e
    (cd "$parent/$name/wixie" && powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 -Verify >/dev/null 2>&1)
    RC_PS2=$?
    set -e
    check "[$name] PS 5.1 -Verify passes" "$RC_PS2" 0
  else
    echo "  ([$name] powershell.exe or bootstrap.ps1 unavailable -- skipping PS leg)"
  fi
done

echo "install-ancestor-dirs: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
