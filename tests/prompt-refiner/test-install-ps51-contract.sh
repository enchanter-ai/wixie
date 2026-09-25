#!/usr/bin/env bash
# Test: WIX-INSTALL-001 -- Windows PowerShell 5.1 parses and executes
# bootstrap.ps1, the supported-shell contract is documented, and the fix
# does not depend on source-file encoding.
#
# New test: absent at 3d09e2a (no BOM, non-ASCII em-dashes, no version gate,
# no documented shell contract); must fail there and pass at this repo's head.

set -euo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
PS1="$REPO_ROOT/scripts/bootstrap.ps1"

[[ -f "$PS1" ]] || { echo "missing $PS1" >&2; exit 1; }

pass=0
fail=0
ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "  FAIL: $1" >&2; }

# 1. BOM present.
head_bytes="$(head -c 3 "$PS1" | od -An -tx1 | tr -d ' \n')"
if [[ "$head_bytes" == "efbbbf" ]]; then ok; else bad "no UTF-8 BOM at file start"; fi

# 2. Zero non-ASCII bytes in the file content (BOM's own 3 bytes are the
#    only bytes >= 0x80 the file is allowed to contain).
non_ascii_total=$(LC_ALL=C grep -o $'[\x80-\xff]' "$PS1" | wc -l | tr -d ' ')
if [[ "$non_ascii_total" -eq 3 ]]; then ok; else bad "expected exactly 3 non-ASCII bytes (the BOM), found $non_ascii_total"; fi

# 3. Explicit version gate rejecting PowerShell < 5 before real work starts.
grep -q 'PSVersionTable.PSVersion.Major -lt 5' "$PS1" && ok || bad "no PSVersionTable version gate"

# 4. The supported-shell contract names Windows PowerShell 5.1 as supported
#    and pwsh 7 as explicitly unverified (not silently claimed).
grep -qi 'Windows PowerShell 5.1' "$PS1" && ok || bad "contract does not name Windows PowerShell 5.1"
grep -qi 'UNKNOWN' "$PS1" && ok || bad "contract does not mark the pwsh 7 leg UNKNOWN"

# 5. Live parse + execute under real Windows PowerShell 5.1, if available on
#    this host (skip, not fail, off-Windows -- this repo's CI/dev target is
#    Windows for this leg; bootstrap.sh covers everything else).
if command -v powershell.exe >/dev/null 2>&1; then
  PSVER="$(powershell.exe -NoProfile -Command '$PSVersionTable.PSVersion.ToString()' 2>/dev/null | tr -d '\r')"
  echo "  (live PowerShell version on this host: $PSVER)"

  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  # -Verify with no vis sibling at all: must fail with OUR message, not a
  # ParserError. A ParserError's stderr contains "ParserError" /
  # "MissingEndParenthesisInMethodCall"-style CategoryInfo; ours does not.
  mkdir -p "$TMP/plugin/scripts"
  cp "$PS1" "$TMP/plugin/scripts/bootstrap.ps1"
  echo "core: \"~1.0.0\"" > "$TMP/plugin/.vis-versions"
  echo "# fixture" > "$TMP/plugin/CLAUDE.md"
  set +e
  OUT="$(cd "$TMP/plugin" && powershell.exe -NoProfile -File scripts/bootstrap.ps1 -Verify 2>&1)"
  RC=$?
  set -e
  if printf '%s' "$OUT" | grep -qi "ParserError\|MissingEndParenthesis\|Unrecognized token"; then
    bad "bootstrap.ps1 failed to PARSE under real Windows PowerShell 5.1: $OUT"
  else
    ok
  fi
  [[ "$RC" -ne 0 ]] && ok || bad "expected nonzero exit with no vis sibling present"
  printf '%s' "$OUT" | grep -q "vis sibling missing" && ok || bad "missing expected 'vis sibling missing' message"
else
  echo "  (powershell.exe not on PATH -- skipping live PS5.1 parse/execute checks)"
fi

echo "install-ps51-contract: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
