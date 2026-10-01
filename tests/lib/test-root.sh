# shellcheck shell=bash
# Wixie test temp-root contract (WIX-TEST-ENV-001). Source it; do not execute it.
#
#   WIXIE_TEST_ROOT   the ONE directory every test scratch path derives from. Private to the
#                     harness run: never the shared /tmp, /var/tmp or the real Windows %TEMP%,
#                     and never a directory inside them.
#
# Safety mode is always on: there is no fallback to a global temp directory.
#   - WIXIE_TEST_ROOT set   -> must be an absolute path outside the shared temp dirs; created if
#                              missing. Anything else exits 97 with a message (fail loudly).
#   - WIXIE_TEST_ROOT unset -> <repo>/.test-root/standalone (gitignored), so a test run alone
#                              still never touches global temp. tests/run-all.sh instead creates a
#                              fresh per-run root under <repo>/.test-root/ and removes it at the end.
#
# After sourcing:
#   WIXIE_TEST_TMP             $WIXIE_TEST_ROOT/tmp, exported as TMPDIR, TMP and TEMP, so mktemp,
#                              Python's tempfile, PowerShell and other native Windows children all
#                              resolve inside the root.
#   GIT_CONFIG_GLOBAL          $WIXIE_TEST_ROOT/gitconfig (test identity only): fixture git commands never read
#                              or write the user's ~/.gitconfig.
#   wixie_mktemp_d NAME        private scratch dir under WIXIE_TEST_TMP (the only sanctioned mktemp).
#   wixie_wsl_available        true when wsl.exe exists and starts.
#   wixie_wsl_path PATH        the WSL (/mnt/<drive>/...) view of PATH, which must lie inside the
#                              root; a WSL leg works there instead of the distro's shared /tmp.
#   WIXIE_TEST_ROOT_WSL        WSL view of the root (set by wixie_wsl_available).
#
# Git Bash note: its /tmp mount is fixed when the MSYS runtime starts (on the reference host it is
# the real %TEMP% even after TEMP is exported), so a literal /tmp path can never be redirected.
# tests/harness/test-no-shared-temp.sh forbids literal /tmp paths and bare mktemp in tests.

wixie__die() { echo "WIXIE_TEST_ROOT: $*" >&2; exit 97; }

wixie__native() {  # print a comparable absolute form of $1 (Windows form under MSYS)
  if command -v cygpath >/dev/null 2>&1; then cygpath -am "$1"; else printf '%s\n' "$1"; fi
}

wixie__shared_temp_dirs() {
  printf '%s\n' /tmp /var/tmp /usr/tmp /dev/shm
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -am /tmp
    [[ -n "${LOCALAPPDATA:-}" ]] && cygpath -am "$LOCALAPPDATA/Temp"
    [[ -n "${SYSTEMROOT:-}" ]] && cygpath -am "$SYSTEMROOT/Temp"
  fi
  return 0
}

wixie__inside() {  # wixie__inside CHILD PARENT -> 0 when CHILD is PARENT or below it (case-insensitive)
  local c p
  c="$(printf '%s' "${1%/}" | tr '[:upper:]' '[:lower:]')"
  p="$(printf '%s' "${2%/}" | tr '[:upper:]' '[:lower:]')"
  [[ -n "$p" && ( "$c" == "$p" || "$c" == "$p"/* ) ]]
}

wixie__repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -z "${WIXIE_TEST_ROOT:-}" ]]; then
  WIXIE_TEST_ROOT="$wixie__repo/.test-root/standalone"
fi
case "$WIXIE_TEST_ROOT" in
  /*|[A-Za-z]:[/\\]*) ;;
  *) wixie__die "must be an absolute path, got '$WIXIE_TEST_ROOT'" ;;
esac
# Validate BEFORE creating anything, so a bad root never leaves a directory in shared temp.
wixie__root_native="$(wixie__native "$WIXIE_TEST_ROOT")"
while IFS= read -r wixie__shared; do
  [[ -z "$wixie__shared" ]] && continue
  if wixie__inside "$wixie__root_native" "$wixie__shared"; then
    wixie__die "'$WIXIE_TEST_ROOT' is inside the shared temp dir '$wixie__shared'; use a private directory"
  fi
done < <(wixie__shared_temp_dirs)
mkdir -p "$WIXIE_TEST_ROOT/tmp" || wixie__die "cannot create '$WIXIE_TEST_ROOT/tmp'"
WIXIE_TEST_ROOT="$(cd "$WIXIE_TEST_ROOT" && pwd)"
wixie__root_native="$(wixie__native "$WIXIE_TEST_ROOT")"

WIXIE_TEST_TMP="$WIXIE_TEST_ROOT/tmp"
export WIXIE_TEST_ROOT WIXIE_TEST_TMP
export TMPDIR="$WIXIE_TEST_TMP" TMP="$WIXIE_TEST_TMP" TEMP="$WIXIE_TEST_TMP"
# Fixture repos commit inside the root, so the private gitconfig carries a throwaway test identity
# (never used for real commits: GIT_CONFIG_GLOBAL points here only inside the test run).
[[ -f "$WIXIE_TEST_ROOT/gitconfig" ]] || printf '[user]\n\tname = wixie-test\n\temail = wixie-test@example.invalid\n' > "$WIXIE_TEST_ROOT/gitconfig"
export GIT_CONFIG_GLOBAL="$WIXIE_TEST_ROOT/gitconfig"

wixie_mktemp_d() {
  local d
  d="$(mktemp -d "$WIXIE_TEST_TMP/${1:-t}.XXXXXX")" || wixie__die "mktemp under '$WIXIE_TEST_TMP' failed"
  wixie__inside "$(wixie__native "$d")" "$wixie__root_native" || wixie__die "scratch '$d' escaped the root"
  printf '%s\n' "$d"
}

wixie_wsl_available() {  # also sets WIXIE_TEST_ROOT_WSL; call it in the current shell, not in $(...)
  command -v wsl.exe >/dev/null 2>&1 && command -v cygpath >/dev/null 2>&1 || return 1
  wsl.exe -e true >/dev/null 2>&1 || return 1
  WIXIE_TEST_ROOT_WSL="$(wsl.exe -e wslpath -a "$(cygpath -w "$WIXIE_TEST_ROOT")" 2>/dev/null | tr -d '\r')"
  [[ "$WIXIE_TEST_ROOT_WSL" == /* ]] || wixie__die "cannot map the root into WSL (got '$WIXIE_TEST_ROOT_WSL')"
  export WIXIE_TEST_ROOT_WSL
}

wixie_wsl_path() {
  local p
  [[ -n "${WIXIE_TEST_ROOT_WSL:-}" ]] || wixie__die "wixie_wsl_path called before wixie_wsl_available"
  p="$(wsl.exe -e wslpath -a "$(cygpath -w "$1")" 2>/dev/null | tr -d '\r')"
  [[ "$p" == "$WIXIE_TEST_ROOT_WSL"/* ]] || wixie__die "WSL path '$p' for '$1' is outside the root '$WIXIE_TEST_ROOT_WSL'"
  printf '%s\n' "$p"
}
