#!/usr/bin/env bash
# Test: WIX-INSTALL-002 --verify re-derives from the pin and enforces exact
# schema/entry-set equality, not just "does the cache match the lock".
#
# Fix round 1 (independent verifier REJECT, VERIFICATION.md item 5): a
# forged version/tag field, lock_version 99, an extra/missing package block
# or conduct_files entry, and a lock+cache pair whose content came from a
# different commit than the one currently declared all passed --verify
# (exit 0) at the previous head. This test proves each one now fails, named.
#
# New test: absent at 3d09e2a / 90f0a0c (no lock_version check at all, no
# version/tag field comparison, no exact entry-set enforcement, no
# re-derivation from the pin independent of the cache); must fail there and
# pass at this repo's head.

set -euo pipefail
REPO_ROOT="${1:-.}"
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
# Private temp root (WIX-TEST-ENV-001): every scratch path below derives from WIXIE_TEST_ROOT.
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"
BOOTSTRAP_SH="$REPO_ROOT/scripts/bootstrap.sh"

TMP="$(wixie_mktemp_d install-verify-strictness)" || exit 97
cleanup() { rm -rf "$TMP" 2>/dev/null || true; }
trap cleanup EXIT

WIXIE="$TMP/wixie"
VIS="$TMP/vis"
mkdir -p "$WIXIE" "$VIS"

# --- a small, self-contained fixture: 1 package, 2 conduct files -----------
mkdir -p "$WIXIE/scripts" "$WIXIE/plugins"
cp "$BOOTSTRAP_SH" "$WIXIE/scripts/bootstrap.sh"
chmod +x "$WIXIE/scripts/bootstrap.sh"
cat > "$WIXIE/.vis-versions" <<'EOF'
core: "~1.0.0"
EOF
cat > "$WIXIE/CLAUDE.md" <<'EOF'
- @.vis-cache/vis/packages/core/conduct/a.md
- @.vis-cache/vis/packages/core/conduct/b.md
EOF

( cd "$VIS" && git init --quiet -b main && git config core.autocrlf false )
mkdir -p "$VIS/packages/core/conduct"
echo "content a" > "$VIS/packages/core/conduct/a.md"
echo "content b" > "$VIS/packages/core/conduct/b.md"
( cd "$VIS" && git add -A && git -c user.email=t@t.local -c user.name=t commit --quiet -m fixture )
SHA1="$(git -C "$VIS" rev-parse HEAD)"
git -C "$VIS" tag enchanter-core--v1.0.0 "$SHA1"

# --- a SECOND commit/tag with different content, for the "lock+cache from
# another commit" case ------------------------------------------------------
echo "content a v2" > "$VIS/packages/core/conduct/a.md"
( cd "$VIS" && git add -A && git -c user.email=t@t.local -c user.name=t commit --quiet -m fixture2 )
SHA2="$(git -C "$VIS" rev-parse HEAD)"
git -C "$VIS" tag enchanter-core--v2.0.0 "$SHA2"

pass=0
fail=0
check() {
  local desc="$1" rc="$2" want="$3"
  if [[ "$rc" -eq "$want" ]]; then pass=$((pass + 1)); else
    fail=$((fail + 1)); echo "  FAIL: $desc (exit $rc, wanted $want)" >&2
  fi
}

( cd "$WIXIE" && VIS_REPO="$VIS" ./scripts/bootstrap.sh >/dev/null )
cp "$WIXIE/.vis-lock" "$TMP/good.lock"

restore_good() { cp "$TMP/good.lock" "$WIXIE/.vis-lock"; }

# 1. lock_version: 99 must fail.
restore_good
sed -i 's/^lock_version: 2/lock_version: 99/' "$WIXIE/.vis-lock"
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >"$TMP/out1.txt" 2>&1); rc=$?; set -e
check "lock_version 99 is rejected" "$rc" 1
grep -qi "lock_version" "$TMP/out1.txt" || { fail=$((fail+1)); echo "  FAIL: no lock_version-named cause" >&2; }
rm -f "$TMP/out1.txt"

# 2. forged version: field (tag_commit left correct) must fail.
restore_good
sed -i 's/version: v1.0.0/version: v9.9.9/' "$WIXIE/.vis-lock"
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >"$TMP/out2.txt" 2>&1); rc=$?; set -e
check "forged 'version:' field is rejected" "$rc" 1
grep -qi "version" "$TMP/out2.txt" || { fail=$((fail+1)); echo "  FAIL: no version-named cause" >&2; }
rm -f "$TMP/out2.txt"

# 3. forged tag: field must fail.
restore_good
sed -i 's/tag: enchanter-core--v1.0.0/tag: enchanter-core--v9.9.9/' "$WIXIE/.vis-lock"
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >"$TMP/out3.txt" 2>&1); rc=$?; set -e
check "forged 'tag:' field is rejected" "$rc" 1
rm -f "$TMP/out3.txt"

# 4. extra, unexpected conduct_files entry must fail.
restore_good
cat >> "$WIXIE/.vis-lock" <<'EOF'
  - path: packages/core/conduct/bogus.md
    sha1: 0000000000000000000000000000000000000000
EOF
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >"$TMP/out4.txt" 2>&1); rc=$?; set -e
check "extra conduct_files entry is rejected" "$rc" 1
grep -qi "unexpected entry\|entry set" "$TMP/out4.txt" || { fail=$((fail+1)); echo "  FAIL: no entry-set-named cause" >&2; }
rm -f "$TMP/out4.txt"

# 5. missing conduct_files entry (comment one out) must fail.
restore_good
python3 - "$WIXIE/.vis-lock" <<'PYEOF'
import sys
p = sys.argv[1]
lines = open(p, encoding='utf-8').read().splitlines(keepends=True)
out = []
skip = 0
for i, l in enumerate(lines):
    if skip:
        skip -= 1
        continue
    if l.strip() == "- path: packages/core/conduct/b.md":
        skip = 1  # also drop its sha1 line
        continue
    out.append(l)
open(p, 'w', encoding='utf-8', newline='').write(''.join(out))
PYEOF
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >"$TMP/out5.txt" 2>&1); rc=$?; set -e
check "missing conduct_files entry is rejected" "$rc" 1
rm -f "$TMP/out5.txt"

# 6. extra, unexpected package block must fail.
restore_good
python3 - "$WIXIE/.vis-lock" <<'PYEOF'
import sys
p = sys.argv[1]
t = open(p, encoding='utf-8').read()
extra = "  bogus:\n    version: v1.0.0\n    tag: bogus--v1.0.0\n    tag_commit: 0000000000000000000000000000000000000000\n"
t = t.replace("conduct_files:", extra + "conduct_files:", 1)
open(p, 'w', encoding='utf-8', newline='').write(t)
PYEOF
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >"$TMP/out6.txt" 2>&1); rc=$?; set -e
check "extra package block is rejected" "$rc" 1
grep -qi "package block" "$TMP/out6.txt" || { fail=$((fail+1)); echo "  FAIL: no package-block-named cause" >&2; }
rm -f "$TMP/out6.txt"

# 7. lock+cache pair from a DIFFERENT commit (self-consistent with each
#    other, but not what the current pin actually contains) must fail.
sed -i 's/^core: "~1.0.0"/core: "~2.0.0"/' "$WIXIE/.vis-versions"
( cd "$WIXIE" && VIS_REPO="$VIS" ./scripts/bootstrap.sh >/dev/null )
cp "$WIXIE/.vis-lock" "$TMP/v2.lock"
sed -i 's/^core: "~2.0.0"/core: "~1.0.0"/' "$WIXIE/.vis-versions"
# lock/cache still describe v2.0.0's content; .vis-versions now wants v1.0.0
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >"$TMP/out7.txt" 2>&1); rc=$?; set -e
check "lock+cache from a different (but internally self-consistent) commit is rejected" "$rc" 1
rm -f "$TMP/out7.txt"

# 8. cache tampered alone (lock stays correct) must fail, distinctly.
( cd "$WIXIE" && VIS_REPO="$VIS" ./scripts/bootstrap.sh >/dev/null )
echo "tampered" >> "$WIXIE/.vis-cache/vis/packages/core/conduct/a.md"
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >"$TMP/out8.txt" 2>&1); rc=$?; set -e
check "cache-only tampering is rejected" "$rc" 1
grep -qi "modified in the materialized cache" "$TMP/out8.txt" || { fail=$((fail+1)); echo "  FAIL: cache-tamper message not distinguished from lock-forgery message" >&2; }
rm -f "$TMP/out8.txt"

# 9. sanity: the good lock still verifies clean.
( cd "$WIXIE" && VIS_REPO="$VIS" ./scripts/bootstrap.sh >/dev/null )
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >/dev/null 2>&1); rc=$?; set -e
check "unmodified lock still verifies clean" "$rc" 0

# 10. DUPLICATE conduct entry -- the SAME path appended a second time with a
#     bogus sha1 (distinct from #4's UNKNOWN extra path). Fix round 2
#     (VERIFICATION.md fix_round item 2): this passed under both bash and PS
#     at the previous head because the old ad-hoc awk/grep extraction just
#     grabbed the FIRST match for a given path and never noticed a second.
restore_good
cat >> "$WIXIE/.vis-lock" <<'EOF'
  - path: packages/core/conduct/a.md
    sha1: bogus000000000000000000000000000000000000
EOF
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >"$TMP/out10.txt" 2>&1); rc=$?; set -e
check "duplicate conduct entry (same path, bogus sha1) is rejected" "$rc" 1
grep -qi "duplicate conduct_files entry" "$TMP/out10.txt" || { fail=$((fail+1)); echo "  FAIL: no duplicate-entry-named cause" >&2; }
rm -f "$TMP/out10.txt"

# 11. DUPLICATE package block -- the SAME package name ("core") appended a
#     second time with a forged tag_commit (distinct from #6's UNKNOWN extra
#     "bogus" package name). This passed under PS (though bash already
#     rejected it) at the previous head.
restore_good
python3 - "$WIXIE/.vis-lock" <<'PYEOF'
import sys
p = sys.argv[1]
t = open(p, encoding='utf-8').read()
extra = "  core:\n    version: v1.0.0\n    tag: enchanter-core--v1.0.0\n    tag_commit: 9999999999999999999999999999999999999999\n"
t = t.replace("conduct_files:", extra + "conduct_files:", 1)
open(p, 'w', encoding='utf-8', newline='').write(t)
PYEOF
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >"$TMP/out11.txt" 2>&1); rc=$?; set -e
check "duplicate package block (same name, forged tag_commit) is rejected" "$rc" 1
grep -qi "duplicate package block" "$TMP/out11.txt" || { fail=$((fail+1)); echo "  FAIL: no duplicate-package-block-named cause" >&2; }
rm -f "$TMP/out11.txt"

# 12. Unknown TOP-LEVEL key must fail (not just unknown keys nested inside a
#     package/conduct entry, already covered above by other cases).
restore_good
python3 - "$WIXIE/.vis-lock" <<'PYEOF'
import sys
p = sys.argv[1]
t = open(p, encoding='utf-8').read()
t = t.replace("lock_version: 2", "lock_version: 2\nbogus_top: hax", 1)
open(p, 'w', encoding='utf-8', newline='').write(t)
PYEOF
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >"$TMP/out12.txt" 2>&1); rc=$?; set -e
check "unknown top-level key is rejected" "$rc" 1
grep -qi "unknown top-level key" "$TMP/out12.txt" || { fail=$((fail+1)); echo "  FAIL: no unknown-top-level-key-named cause" >&2; }
rm -f "$TMP/out12.txt"

# 13. Unknown key inside a PACKAGE block.
restore_good
python3 - "$WIXIE/.vis-lock" <<'PYEOF'
import re, sys
p = sys.argv[1]
t = open(p, encoding='utf-8').read()
t = re.sub(r'(    tag_commit: [0-9a-f]+\n)', r'\1    bogus: 1\n', t, count=1)
open(p, 'w', encoding='utf-8', newline='').write(t)
PYEOF
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >"$TMP/out13.txt" 2>&1); rc=$?; set -e
check "unknown key inside a package block is rejected" "$rc" 1
grep -qi "unknown key in package" "$TMP/out13.txt" || { fail=$((fail+1)); echo "  FAIL: no unknown-package-key-named cause" >&2; }
rm -f "$TMP/out13.txt"

# 14. Unknown key inside a CONDUCT_FILES entry.
restore_good
python3 - "$WIXIE/.vis-lock" <<'PYEOF'
import re, sys
p = sys.argv[1]
t = open(p, encoding='utf-8').read()
t = re.sub(r'(    sha1: [0-9a-f]+\n)', r'\1    bogus: 1\n', t, count=1)
open(p, 'w', encoding='utf-8', newline='').write(t)
PYEOF
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >"$TMP/out14.txt" 2>&1); rc=$?; set -e
check "unknown key inside a conduct_files entry is rejected" "$rc" 1
grep -qi "unknown key in conduct_files entry" "$TMP/out14.txt" || { fail=$((fail+1)); echo "  FAIL: no unknown-conduct-key-named cause" >&2; }
rm -f "$TMP/out14.txt"

# 15. final sanity: the good lock still verifies clean after all the above.
restore_good
set +e; (cd "$WIXIE" && ./scripts/bootstrap.sh --verify >/dev/null 2>&1); rc=$?; set -e
check "unmodified lock still verifies clean (final)" "$rc" 0

echo "install-verify-strictness: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
