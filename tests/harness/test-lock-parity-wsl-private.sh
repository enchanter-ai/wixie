#!/usr/bin/env bash
# Test: WIX-TEST-ENV-001 -- tests/prompt-refiner/test-install-lock-parity.sh keeps its native-WSL
# leg (it RUNS, it is not skipped, whenever wsl.exe works) but does all of its work under a private
# WIXIE_TEST_ROOT: the leg reports a Linux kernel and a working dir inside the root's WSL view,
# the root's tmp/ is empty afterwards (cleaned), and the run creates NO entry in the WSL distro's
# shared /tmp and NO test-named entry in the real Windows %TEMP%.
#
# Before the fix the leg wrote /tmp/wixie-lock-parity-$$ inside WSL and /tmp/parity_bashverify.$$
# (Git Bash /tmp = the real %TEMP% on this host) -- INC-04.
#
# Real %TEMP% is shared with every other process on the machine, so a new entry there is only
# counted against this test when its name matches something the test tree creates (mktemp's
# tmp.*, parity_*, wixie*, *lock-parity*, __PSScriptPolicyTest_*); other new entries are printed
# as unattributed. In WSL /tmp the only allowance is systemd's own PrivateTmp directories
# (root-owned systemd-private-<boot id>-<unit>.service-*), which systemd recreates whenever the
# distro or its services (re)start -- e.g. when the VM idles out during the long Windows-side part
# of the run and the next wsl.exe call boots it again. They are reported, not counted; a
# keep-alive wsl.exe process holds the distro up for the measurement so they normally do not
# churn at all. Any other new WSL /tmp entry fails.
# Skips (passes) only where powershell.exe or wsl.exe is unavailable (e.g. Linux CI).
set -euo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"

if ! command -v powershell.exe >/dev/null 2>&1 || ! wixie_wsl_available; then
  echo "lock-parity-wsl-private: skipped (needs powershell.exe and a working wsl.exe)"
  exit 0
fi
[[ -n "${LOCALAPPDATA:-}" ]] || { echo "  FAIL: LOCALAPPDATA unset; cannot locate the real %TEMP%" >&2; exit 1; }
REAL_TEMP="$(cygpath -u "$LOCALAPPDATA")/Temp"

SUB="$(wixie_mktemp_d lock-parity-root)" || exit 97
wsl.exe -e sleep 1800 >/dev/null 2>&1 &   # keep the distro up for the measurement window
KEEPALIVE=$!
trap 'kill "$KEEPALIVE" 2>/dev/null || true; rm -rf "$SUB"' EXIT
wsl.exe -e true >/dev/null 2>&1
fail=0
bad() { fail=$((fail + 1)); echo "  FAIL: $*" >&2; }

list_wsl_tmp() { wsl.exe -e bash -c 'ls -1A /tmp' 2>/dev/null | tr -d '\r' | LC_ALL=C sort; }  # wixie-temp-ok: read-only listing
list_real_temp() { ls -1A "$REAL_TEMP" 2>/dev/null | LC_ALL=C sort; }

list_wsl_tmp > "$SUB/wsl.before"
list_real_temp > "$SUB/temp.before"

set +e
out="$(WIXIE_TEST_ROOT="$SUB" bash "$REPO_ROOT/tests/prompt-refiner/test-install-lock-parity.sh" "$REPO_ROOT" 2>&1)"
rc=$?
set -e

list_wsl_tmp > "$SUB/wsl.after"
list_real_temp > "$SUB/temp.after"

[[ "$rc" -eq 0 ]] || { bad "lock-parity test exited $rc"; printf '%s\n' "$out" >&2; }

sub_wsl="$(wixie_wsl_path "$SUB/tmp")" || exit 97
leg="$(printf '%s\n' "$out" | grep '^wsl-leg: kernel=' || true)"
[[ -n "$leg" ]] || bad "native-WSL leg did not run (no 'wsl-leg: kernel=' line)"
[[ "$leg" == "wsl-leg: kernel=Linux dir=$sub_wsl/"* ]] || bad "WSL leg ran outside the private root: '$leg' (want prefix $sub_wsl/)"
printf '%s\n' "$out" | grep -q "^wsl-leg: cleaned $sub_wsl/" || bad "WSL leg did not report cleaning its private dir"
leftover="$(ls -1A "$SUB/tmp" 2>/dev/null || true)"
[[ -z "$leftover" ]] || bad "scratch left under the private root: $leftover"

SYSTEMD_PRIV='^systemd-private-[0-9a-f]{32}-[A-Za-z0-9@_.-]+\.service-[A-Za-z0-9]+$'
new_all_wsl="$(LC_ALL=C comm -13 "$SUB/wsl.before" "$SUB/wsl.after")"
new_wsl="$(printf '%s\n' "$new_all_wsl" | grep -vE "$SYSTEMD_PRIV" | grep -v '^$' || true)"
lifecycle="$(printf '%s\n' "$new_all_wsl" | grep -E "$SYSTEMD_PRIV" || true)"
[[ -z "$new_wsl" ]] || bad "new entries in WSL shared /tmp: $new_wsl"
[[ -z "$lifecycle" ]] || echo "  note: systemd PrivateTmp dirs recreated by a distro/service restart (not test output): $lifecycle"
new_temp="$(LC_ALL=C comm -13 "$SUB/temp.before" "$SUB/temp.after")"
ours="$(printf '%s\n' "$new_temp" | grep -E '^(tmp\.|parity_|wixie|.*lock-parity|__PSScriptPolicyTest_)' || true)"
[[ -z "$ours" ]] || bad "new test-named entries in the real %TEMP% ($REAL_TEMP): $ours"
others="$(printf '%s\n' "$new_temp" | grep -vE '^(tmp\.|parity_|wixie|.*lock-parity|__PSScriptPolicyTest_)' | grep -v '^$' || true)"
[[ -z "$others" ]] || echo "  note: unattributed new entries in the real %TEMP% (other processes): $others"

echo "$leg"
echo "lock-parity-wsl-private: new WSL-tmp entries=$(printf '%s' "$new_wsl" | grep -c . || true)," \
     "new test-named real %TEMP% entries=$(printf '%s' "$ours" | grep -c . || true), failures=$fail"
[[ "$fail" -eq 0 ]]
