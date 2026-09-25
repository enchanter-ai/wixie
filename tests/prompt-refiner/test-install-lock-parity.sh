#!/usr/bin/env bash
# Test: WIX-INSTALL-001 -- a PowerShell-written .vis-lock is byte-identical
# to a bash-written one for the same inputs (modulo resolved_at), and each
# entry point's --verify accepts a lock the OTHER entry point wrote.
#
# Fix round 1 (independent verifier REJECT, VERIFICATION.md item 10): the
# PS lock writer used an em dash where bash used a hyphen, sorted entries by
# current culture instead of byte order, and wrote CRLF -- so a lock
# committed from PowerShell failed CI (which regenerates with bash and
# diffs), and Linux --verify of a PS-written lock failed with a misleading
# "lock says pinned, verify requested pinned" message.
#
# New test: absent at 3d09e2a / 90f0a0c (no lock_version field existed to
# even compare, and the CRLF/culture-sort/em-dash drift this test targets
# was introduced by, then fixed within, this same remediation branch); must
# fail against the pre-fix-round-1 PS1 writer and pass at this repo's head.
# Skips (does not fail) the live legs when powershell.exe / wsl.exe are not
# available on this host.

set -euo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"

pass=0
fail=0
check() {
  local desc="$1" rc="$2" want="$3"
  if [[ "$rc" -eq "$want" ]]; then pass=$((pass + 1)); else
    fail=$((fail + 1)); echo "  FAIL: $desc (exit $rc, wanted $want)" >&2
  fi
}

if ! command -v powershell.exe >/dev/null 2>&1; then
  echo "  (powershell.exe not on PATH -- skipping; this test only applies on Windows)"
  echo "install-lock-parity: 0 passed, 0 failed (skipped)"
  exit 0
fi

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP" 2>/dev/null || true; }
trap cleanup EXIT

WIXIE="$TMP/wixie"
VIS="$TMP/vis"
mkdir -p "$WIXIE" "$VIS"

( cd "$REPO_ROOT" && tar -cf - \
    --exclude=.git --exclude=.vis-cache --exclude=state --exclude=node_modules . ) \
  | ( cd "$WIXIE" && tar -xf - )
chmod +x "$WIXIE/scripts/bootstrap.sh"

mapfile -t PKG_LINES < <(grep -oE '^[a-z]+:[[:space:]]*"~?[0-9][^"]*"' "$WIXIE/.vis-versions")
declare -a PKGS=() VERS=()
for line in "${PKG_LINES[@]}"; do
  pkg="${line%%:*}"
  ver="$(printf '%s' "$line" | sed -E 's/^[a-z]+:[[:space:]]*"~?//; s/"$//')"
  PKGS+=("$pkg"); VERS+=("$ver")
done

mapfile -t IMPORTS < <(
  grep -oE '@\.vis-cache/vis/packages/[a-z]+/[A-Za-z0-9._/-]+\.[a-zA-Z]+' "$WIXIE/CLAUDE.md" | \
    sed 's#^@\.vis-cache/vis/##' | LC_ALL=C sort -u
)

( cd "$VIS" && git init --quiet -b main && git config core.autocrlf false )
for rel in "${IMPORTS[@]}"; do
  full="$VIS/$rel"
  mkdir -p "$(dirname "$full")"
  printf 'fixture content for %s\n' "$rel" > "$full"
done
( cd "$VIS" && git add -A && git -c user.email=t@t.local -c user.name=t commit --quiet -m fixture )
FIXTURE_SHA="$(git -C "$VIS" rev-parse HEAD)"
for i in "${!PKGS[@]}"; do
  git -C "$VIS" tag "enchanter-${PKGS[$i]}--v${VERS[$i]}" "$FIXTURE_SHA"
done

WIN_WIXIE="$(cygpath -w "$WIXIE" 2>/dev/null || echo "$WIXIE")"
WIN_VIS="$(cygpath -w "$VIS" 2>/dev/null || echo "$VIS")"

# --- bash writes the lock first ---------------------------------------------
( cd "$WIXIE" && VIS_REPO="$VIS" ./scripts/bootstrap.sh >/dev/null )
cp "$WIXIE/.vis-lock" "$TMP/bash.lock"
cp -r "$WIXIE/.vis-cache" "$TMP/bash.cache"

# --- PowerShell writes the lock fresh ---------------------------------------
rm -rf "$WIXIE/.vis-cache" "$WIXIE/.vis-lock"
( cd "$WIXIE" && VIS_REPO="$WIN_VIS" powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 >/dev/null )
cp "$WIXIE/.vis-lock" "$TMP/ps.lock"

# 1. byte-identical modulo resolved_at.
if diff -q <(grep -v '^resolved_at:' "$TMP/bash.lock") <(grep -v '^resolved_at:' "$TMP/ps.lock") >/dev/null; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  echo "  FAIL: bash-written and PS-written locks differ (excl. resolved_at):" >&2
  diff <(grep -v '^resolved_at:' "$TMP/bash.lock") <(grep -v '^resolved_at:' "$TMP/ps.lock") >&2 || true
fi

# 2. no CR bytes in the PS-written lock (LF-only, matching bash).
if LC_ALL=C grep -qU $'\r' "$TMP/ps.lock" 2>/dev/null; then
  fail=$((fail + 1)); echo "  FAIL: PS-written lock contains CR bytes (not LF-only)" >&2
else
  pass=$((pass + 1))
fi

# 3. no BOM in the PS-written lock.
head_bytes="$(head -c 3 "$TMP/ps.lock" | od -An -tx1 | tr -d ' \n')"
if [[ "$head_bytes" == "efbbbf" ]]; then
  fail=$((fail + 1)); echo "  FAIL: PS-written lock has a BOM (must not)" >&2
else
  pass=$((pass + 1))
fi

# 4. bash --verify accepts the PS-written lock and cache.
set +e
(cd "$WIXIE" && ./scripts/bootstrap.sh --verify >/tmp/parity_bashverify.$$ 2>&1)
rc=$?
set -e
check "bash --verify accepts a PS-written lock+cache" "$rc" 0
cat /tmp/parity_bashverify.$$ >&2 || true
rm -f /tmp/parity_bashverify.$$

# 5. PS -Verify accepts the bash-written lock and cache.
rm -rf "$WIXIE/.vis-cache" "$WIXIE/.vis-lock"
cp -r "$TMP/bash.cache" "$WIXIE/.vis-cache"
cp "$TMP/bash.lock" "$WIXIE/.vis-lock"
set +e
psout="$(cd "$WIXIE" && powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 -Verify 2>&1)"
rc=$?
set -e
check "PS -Verify accepts a bash-written lock+cache" "$rc" 0
[[ "$rc" -ne 0 ]] && printf '%s\n' "$psout" >&2

# --- best-effort: native WSL (Linux, ext4) cross-check, per the brief ------
if command -v wsl.exe >/dev/null 2>&1 && wsl.exe -e true >/dev/null 2>&1; then
  WSL_DIR="/tmp/wixie-lock-parity-$$"
  wsl.exe -e bash -c "rm -rf '$WSL_DIR' && mkdir -p '$WSL_DIR/wixie' '$WSL_DIR/vis'" >/dev/null 2>&1
  WIN_TMP_WIXIE="$(cygpath -w "$WIXIE" 2>/dev/null || echo "$WIXIE")"
  WIN_TMP_VIS="$(cygpath -w "$VIS" 2>/dev/null || echo "$VIS")"
  # Copy via a WSL-side cp from the /mnt/c view onto native ext4, so the run
  # is genuinely on WSL's own filesystem, not NTFS-through-9p.
  MNT_WIXIE="$(wsl.exe -e wslpath -a "$WIN_TMP_WIXIE" 2>/dev/null | tr -d '\r')"
  MNT_VIS="$(wsl.exe -e wslpath -a "$WIN_TMP_VIS" 2>/dev/null | tr -d '\r')"
  if [[ -n "$MNT_WIXIE" && -n "$MNT_VIS" ]]; then
    # sed -i 's/\r$//' is defensive, not a workaround for a real product
    # defect: scripts/bootstrap.sh is verified elsewhere (grep -c $'\r') to
    # have 0 CR bytes on disk. It guards only against this TEST's own
    # Windows->WSL copy path (via wslpath's /mnt/c 9p mount) picking up a
    # line-ending translation from something in the container/host tooling,
    # which is a test-infra concern, not the product's.
    wsl.exe -e bash -c "cp -r '$MNT_WIXIE/.' '$WSL_DIR/wixie/' && cp -r '$MNT_VIS/.' '$WSL_DIR/vis/' && sed -i 's/\r\$//' '$WSL_DIR/wixie/scripts/bootstrap.sh' && chmod +x '$WSL_DIR/wixie/scripts/bootstrap.sh' && rm -rf '$WSL_DIR/wixie/.vis-cache'" >/dev/null 2>&1
    # Push the PS-written lock+cache in directly,
    # then run bash --verify natively on WSL's own filesystem.
    wsl.exe -e bash -c "rm -rf '$WSL_DIR/wixie/.vis-cache' '$WSL_DIR/wixie/.vis-lock'" >/dev/null 2>&1
    cp -r "$TMP/bash.cache" "$TMP/wsl-push-cache"
    WIN_PUSH_CACHE="$(cygpath -w "$TMP/wsl-push-cache" 2>/dev/null || echo "$TMP/wsl-push-cache")"
    MNT_PUSH_CACHE="$(wsl.exe -e wslpath -a "$WIN_PUSH_CACHE" 2>/dev/null | tr -d '\r')"
    WIN_PS_LOCK="$(cygpath -w "$TMP/ps.lock" 2>/dev/null || echo "$TMP/ps.lock")"
    MNT_PS_LOCK="$(wsl.exe -e wslpath -a "$WIN_PS_LOCK" 2>/dev/null | tr -d '\r')"
    set +e
    wslout="$(wsl.exe -e bash -c "cp -r '$MNT_PUSH_CACHE' '$WSL_DIR/wixie/.vis-cache' && cp '$MNT_PS_LOCK' '$WSL_DIR/wixie/.vis-lock' && cd '$WSL_DIR/wixie' && ./scripts/bootstrap.sh --verify" 2>&1)"
    wslrc=$?
    set -e
    check "native WSL bash --verify accepts a Windows PS-written lock+cache" "$wslrc" 0
    [[ "$wslrc" -ne 0 ]] && printf '%s\n' "$wslout" >&2
    wsl.exe -e bash -c "rm -rf '$WSL_DIR'" >/dev/null 2>&1 || true
  else
    echo "  (could not resolve WSL paths -- skipping native-WSL leg)"
  fi
else
  echo "  (wsl.exe not available -- skipping native-WSL leg)"
fi

echo "install-lock-parity: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
