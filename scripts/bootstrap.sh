#!/usr/bin/env bash
# bootstrap.sh — canonical first command for an @enchanter-ai sibling plugin.
#
# Behavior (per s2.0 4-layer recommendation, Layer 1):
#   1. Read .foundations-versions (YAML-ish: "<pkg>: \"~<ver>\"").
#   2. Ensure ../foundations exists (clone if missing).
#   3. Fetch tags; checkout each pinned package tag (enchanter-<pkg>--v<ver>).
#      Note: tags retain the historical `enchanter-` prefix even after the
#      repo rename; the script prepends it during tag lookup.
#   4. Verify every @../foundations/... reference in CLAUDE.md resolves.
#   5. Write .foundations-lock with foundations SHA, per-package tag commits,
#      and SHA-1 of every conduct file referenced by CLAUDE.md.
#
# Modes:
#   ./scripts/bootstrap.sh           — perform full bootstrap, write lock
#   ./scripts/bootstrap.sh --verify  — read-only; re-resolve and compare against
#                                      .foundations-lock; exit 1 on any mismatch.
#                                      Used by CI (hash-coverage all-or-nothing).
#
# Idempotent. Fails loud on any drift.

set -uo pipefail

MODE="${1:-bootstrap}"
PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FOUNDATIONS_DIR="$(cd "$PLUGIN_DIR/.." && pwd)/foundations"
FOUNDATIONS_REPO="${FOUNDATIONS_REPO:-https://github.com/enchanter-ai/foundations}"
VERSIONS_FILE="$PLUGIN_DIR/.foundations-versions"
LOCK_FILE="$PLUGIN_DIR/.foundations-lock"
CLAUDE_MD="$PLUGIN_DIR/CLAUDE.md"

err() { printf '%s\n' "$*" >&2; }

# --- preflight ---------------------------------------------------------------

if [[ ! -f "$VERSIONS_FILE" ]]; then
  err "missing $VERSIONS_FILE — every sibling plugin must pin foundations packages"
  exit 1
fi

if [[ ! -f "$CLAUDE_MD" ]]; then
  err "missing $CLAUDE_MD — bootstrap verifies @-imports against this file"
  exit 1
fi

# --- parse .foundations-versions --------------------------------------------
# Format: lines like  core: "~0.6.0"
# We extract (pkg, version) pairs. Comment lines (#…) and blanks ignored.

declare -a PKGS=()
declare -a VERS=()
while IFS= read -r line; do
  # strip comments + whitespace
  line="${line%%#*}"
  line="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  [[ -z "$line" ]] && continue
  # match: <pkg>: "<spec>"
  if [[ "$line" =~ ^([a-z]+):[[:space:]]*\"?([~^]?[0-9][^\"[:space:]]*)\"?[[:space:]]*$ ]]; then
    PKGS+=("${BASH_REMATCH[1]}")
    # strip a leading ~ or ^ for the tag lookup
    raw="${BASH_REMATCH[2]}"
    VERS+=("${raw#[~^]}")
  else
    err "warning: unparsed line in .foundations-versions: $line"
  fi
done < "$VERSIONS_FILE"

if [[ "${#PKGS[@]}" -eq 0 ]]; then
  err "no packages parsed from $VERSIONS_FILE"
  exit 1
fi

# --- ensure foundations sibling exists --------------------------------------

if [[ "$MODE" != "--verify" ]]; then
  if [[ ! -d "$FOUNDATIONS_DIR/.git" ]]; then
    err "foundations sibling missing at $FOUNDATIONS_DIR — cloning"
    git clone "$FOUNDATIONS_REPO" "$FOUNDATIONS_DIR" || {
      err "clone failed — set FOUNDATIONS_REPO or clone manually"
      exit 1
    }
  fi
  git -C "$FOUNDATIONS_DIR" fetch --tags --quiet || {
    err "git fetch --tags failed in $FOUNDATIONS_DIR"
    exit 1
  }
else
  if [[ ! -d "$FOUNDATIONS_DIR/.git" ]]; then
    err "foundations sibling missing — run ./scripts/bootstrap.sh"
    exit 1
  fi
fi

# --- resolve per-package tag commits ----------------------------------------

declare -a TAG_COMMITS=()
for i in "${!PKGS[@]}"; do
  pkg="${PKGS[$i]}"
  ver="${VERS[$i]}"
  tag="enchanter-${pkg}--v${ver}"
  sha=$(git -C "$FOUNDATIONS_DIR" rev-list -n 1 "refs/tags/${tag}" 2>/dev/null || true)
  if [[ -z "$sha" ]]; then
    err "tag missing in foundations: ${tag}"
    err "  → bump .foundations-versions or check available tags: git -C $FOUNDATIONS_DIR tag"
    exit 1
  fi
  TAG_COMMITS+=("$sha")
done

# Foundations checkout SHA = HEAD of foundations (used as overall pointer).
FOUND_SHA=$(git -C "$FOUNDATIONS_DIR" rev-parse HEAD)

# --- walk CLAUDE.md for @-imports and SHA-1 each --------------------------

# Capture every line of the form  @../foundations/<rel-path>
# Tolerates surrounding markdown (e.g., "- @../foundations/...md — desc").
mapfile -t IMPORT_PATHS < <(
  grep -oE '@\.\./foundations/[A-Za-z0-9._/-]+' "$CLAUDE_MD" | \
    sed 's#^@\.\./foundations/##' | sort -u
)

if [[ "${#IMPORT_PATHS[@]}" -eq 0 ]]; then
  err "warning: no @../foundations/... imports found in $CLAUDE_MD"
fi

# Compute SHA-1 of each referenced file. Bail loud on any miss.
declare -a HASH_PATHS=()
declare -a HASH_VALUES=()
MISSING=0
for rel in "${IMPORT_PATHS[@]}"; do
  full="$FOUNDATIONS_DIR/$rel"
  if [[ ! -f "$full" ]]; then
    err "import resolves to missing file: @../foundations/$rel"
    MISSING=1
    continue
  fi
  # sha1sum on Git-Bash/Windows produces "<hash> *<path>" or "<hash>  <path>"; first field is hash.
  h=$(sha1sum "$full" | awk '{print $1}')
  HASH_PATHS+=("$rel")
  HASH_VALUES+=("$h")
done

if [[ "$MISSING" -ne 0 ]]; then
  err "one or more @-imports unresolved — run ./scripts/bootstrap.sh after fixing .foundations-versions"
  exit 1
fi

# --- write or verify .foundations-lock --------------------------------------

generate_lock() {
  local iso
  iso=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  {
    echo "# .foundations-lock — auto-generated by scripts/bootstrap.sh"
    echo "# Do not edit by hand. Run ./scripts/bootstrap.sh to refresh."
    echo "foundations_commit: $FOUND_SHA"
    echo "resolved_at: $iso"
    echo "packages:"
    for i in "${!PKGS[@]}"; do
      echo "  ${PKGS[$i]}:"
      echo "    version: v${VERS[$i]}"
      echo "    tag_commit: ${TAG_COMMITS[$i]}"
    done
    echo "conduct_files:"
    for i in "${!HASH_PATHS[@]}"; do
      echo "  - path: ${HASH_PATHS[$i]}"
      echo "    sha1: ${HASH_VALUES[$i]}"
    done
  } > "$LOCK_FILE"
}

if [[ "$MODE" != "--verify" ]]; then
  generate_lock
  echo "bootstrapped: ${#PKGS[@]} packages, ${#HASH_PATHS[@]} conduct files, foundations SHA $FOUND_SHA"
  echo "wrote $LOCK_FILE"
  exit 0
fi

# --verify path: lock must exist and match exactly.

if [[ ! -f "$LOCK_FILE" ]]; then
  err "foundations not bootstrapped — run ./scripts/bootstrap.sh"
  exit 1
fi

# Compare foundations_commit
lock_found=$(grep -E '^foundations_commit:' "$LOCK_FILE" | awk '{print $2}')
if [[ "$lock_found" != "$FOUND_SHA" ]]; then
  err "foundations drift: lock says $lock_found, checkout is $FOUND_SHA — run ./scripts/bootstrap.sh to re-resolve"
  exit 1
fi

# Compare per-package tag_commit. Sequential grep is fine; the package count is small.
for i in "${!PKGS[@]}"; do
  pkg="${PKGS[$i]}"
  expected="${TAG_COMMITS[$i]}"
  # Pull the tag_commit line that follows the package header in YAML.
  observed=$(awk -v pkg="$pkg" '
    $0 ~ "^  "pkg":" { in_pkg=1; next }
    in_pkg && /^  [a-z]/ && $0 !~ "^    " { in_pkg=0 }
    in_pkg && /^    tag_commit:/ { print $2; exit }
  ' "$LOCK_FILE")
  if [[ "$observed" != "$expected" ]]; then
    err "package ${pkg}: lock ${observed}, checkout ${expected} — run ./scripts/bootstrap.sh"
    exit 1
  fi
done

# Compare every conduct file SHA-1.
for i in "${!HASH_PATHS[@]}"; do
  rel="${HASH_PATHS[$i]}"
  expected="${HASH_VALUES[$i]}"
  observed=$(awk -v rel="$rel" '
    $0 == "  - path: "rel { in_blk=1; next }
    in_blk && /^    sha1:/ { print $2; exit }
    in_blk && /^  - path:/ { in_blk=0 }
  ' "$LOCK_FILE")
  if [[ -z "$observed" ]]; then
    err "conduct file not in lock: $rel — run ./scripts/bootstrap.sh"
    exit 1
  fi
  if [[ "$observed" != "$expected" ]]; then
    err "conduct file $rel modified since bootstrap — re-bootstrap or revert"
    exit 1
  fi
done

echo "verified: ${#HASH_PATHS[@]} conduct files, ${#PKGS[@]} packages, foundations SHA $FOUND_SHA"
exit 0
