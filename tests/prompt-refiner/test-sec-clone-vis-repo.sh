#!/usr/bin/env bash
# Test: WIX-SEC-CLONE-001 -- VIS_REPO cannot be interpreted as a git option
# or otherwise cause command injection, dynamically demonstrated (not just a
# static grep for the mitigation) with a harmless canary.
#
# The canary is `--upload-pack=<touch a sentinel file>`. If bootstrap.sh (or
# .ps1) ever passes VIS_REPO to `git clone` unguarded, git would parse this
# as the --upload-pack option and execute the given command as the "upload
# pack" program when it tries to talk to the (nonexistent) remote -- writing
# the sentinel file. This test asserts the sentinel is NEVER created and
# that bootstrap refuses before attempting any git call, for both entry
# points and for several other option-shaped / unsupported forms.
#
# New test: absent at 3d09e2a (no VIS_REPO validation, no `--` before the
# clone target); must fail there (sentinel gets created, or at minimum no
# validation message is produced with no network) and pass at head.

set -uo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"

BOOTSTRAP_SH="$REPO_ROOT/scripts/bootstrap.sh"
[[ -f "$BOOTSTRAP_SH" ]] || { echo "missing $BOOTSTRAP_SH" >&2; exit 1; }

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP" 2>/dev/null || true; }
trap cleanup EXIT

# Disposable plugin dir with just enough to reach the clone attempt: a
# .vis-versions and CLAUDE.md, and NO vis sibling (so bootstrap tries to
# clone one).
PLUGIN="$TMP/plugin"
mkdir -p "$PLUGIN/scripts"
cp "$BOOTSTRAP_SH" "$PLUGIN/scripts/bootstrap.sh"
[[ -f "$REPO_ROOT/scripts/bootstrap.ps1" ]] && cp "$REPO_ROOT/scripts/bootstrap.ps1" "$PLUGIN/scripts/bootstrap.ps1"
chmod +x "$PLUGIN/scripts/bootstrap.sh"
echo 'core: "~1.0.0"' > "$PLUGIN/.vis-versions"
echo '# fixture' > "$PLUGIN/CLAUDE.md"

SENTINEL="$TMP/pwned"
pass=0
fail=0
ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "  FAIL: $1" >&2; }

run_bash_canary() {
  local vis_repo="$1"
  rm -f "$SENTINEL"
  rm -rf "$TMP/vis" 2>/dev/null || true   # bootstrap.sh resolves VIS_DIR = <plugin>/../vis
  (
    cd "$PLUGIN"
    VIS_REPO="$vis_repo" ./scripts/bootstrap.sh > "$TMP/out.txt" 2>&1
  )
  echo $?
}

echo "== bash entry point =="

# 1. The canary itself: --upload-pack=... must never reach git as an option.
CANARY="--upload-pack=touch \"$SENTINEL\""
rc="$(run_bash_canary "$CANARY")"
if [[ -f "$SENTINEL" ]]; then
  bad "sentinel file was created -- VIS_REPO reached git as an option (bash)"
else
  ok
fi
[[ "$rc" -ne 0 ]] && ok || bad "expected nonzero exit for an option-shaped VIS_REPO (bash)"
grep -q "command-line option" "$TMP/out.txt" && ok || bad "missing explicit refusal message for option-shaped VIS_REPO (bash)"

# 2. A second option-shaped canary using -c to prove it's not just
#    --upload-pack specifically that's guarded.
rm -f "$SENTINEL"
CANARY2="-c core.sshCommand=touch \"$SENTINEL\";true"
rc2="$(run_bash_canary "$CANARY2")"
[[ -f "$SENTINEL" ]] && bad "sentinel created via -c core.sshCommand (bash)" || ok
[[ "$rc2" -ne 0 ]] && ok || bad "expected nonzero exit for -c-shaped VIS_REPO (bash)"

# 3. A plainly unsupported (but not option-shaped) form is also refused,
#    with its own distinct message, before any git call.
rc3="$(run_bash_canary "not-a-repo-and-not-a-path")"
[[ "$rc3" -ne 0 ]] && ok || bad "expected nonzero exit for an unsupported VIS_REPO form (bash)"
grep -q "not a supported source form" "$TMP/out.txt" && ok || bad "missing 'not a supported source form' message (bash)"

# 4. A normal, legitimate local absolute-path source still works (no
#    regression): clone a tiny real repo.
LEGIT_SRC="$TMP/legit-vis"
( mkdir -p "$LEGIT_SRC" && cd "$LEGIT_SRC" && git init --quiet -b main \
    && git -c user.email=t@t.local -c user.name=t commit --quiet --allow-empty -m init )
rm -rf "$PLUGIN/../vis" 2>/dev/null || true
rc4="$(run_bash_canary "$LEGIT_SRC")"
# bootstrap will still fail later (no matching tag), but the CLONE itself
# must have been attempted and accepted by validation, i.e. no "not a
# supported source form" / "command-line option" refusal.
if grep -qE "not a supported source form|command-line option" "$TMP/out.txt"; then
  bad "a legitimate absolute local path was wrongly refused (bash)"
else
  ok
fi

# --- PowerShell 5.1 entry point, if available on this host -----------------
if [[ -f "$PLUGIN/scripts/bootstrap.ps1" ]] && command -v powershell.exe >/dev/null 2>&1; then
  echo "== PowerShell 5.1 entry point =="
  rm -f "$SENTINEL"
  rm -rf "$TMP/vis" 2>/dev/null || true
  OUT_PS="$(cd "$PLUGIN" && VIS_REPO="--upload-pack=touch \"$SENTINEL\"" powershell.exe -NoProfile -File scripts/bootstrap.ps1 2>&1)"
  RC_PS=$?
  if [[ -f "$SENTINEL" ]]; then
    bad "sentinel file was created -- VIS_REPO reached git as an option (PowerShell)"
  else
    ok
  fi
  [[ "$RC_PS" -ne 0 ]] && ok || bad "expected nonzero exit for an option-shaped VIS_REPO (PowerShell)"
  printf '%s' "$OUT_PS" | grep -q "command-line option" && ok || bad "missing explicit refusal message (PowerShell): $OUT_PS"
else
  echo "  (bootstrap.ps1 or powershell.exe unavailable -- skipping PowerShell canary)"
fi

# --- static confirmation: `--` present at the clone call site, both files --
grep -qE 'git clone -- ' "$REPO_ROOT/scripts/bootstrap.sh" && ok || bad "bootstrap.sh clone call lacks --"
if [[ -f "$REPO_ROOT/scripts/bootstrap.ps1" ]]; then
  grep -qE 'git clone -- ' "$REPO_ROOT/scripts/bootstrap.ps1" && ok || bad "bootstrap.ps1 clone call lacks --"
fi

echo "sec-clone-vis-repo: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
