#!/usr/bin/env bash
# bootstrap.sh — canonical first command for an @enchanter-ai sibling plugin.
#
# WIX-INSTALL-002 architecture (D8): production Wixie uses an immutable vis
# package version, never floating HEAD. declared version -> immutable exact
# commit -> exact content materialized -> Wixie imports THAT content ->
# .vis-lock records what was actually materialized.
#
# Two modes:
#
#   PINNED (default; the only mode CI and production use):
#     For every package declared in .vis-versions, resolve the tag
#     enchanter-<pkg>--v<version> to an exact commit in the vis sibling, then
#     read every @-imported file's content directly out of THAT commit via
#     `git show <sha>:<path>` — never from the sibling's checked-out working
#     tree, and the sibling's HEAD/index/working tree are never touched.
#     The materialized content is written into a Wixie-local cache
#     (.vis-cache/vis/, gitignored) that CLAUDE.md's @-imports point at.
#     A version whose tag does not resolve, or whose content is missing a
#     file CLAUDE.md needs, fails loud before anything is written — no
#     fallback to HEAD, no partial lock.
#
#   FLOATING (opt-in only, --floating; local dev convenience, never default,
#   never CI):
#     Reads the same @-imported files from the sibling's current live
#     working tree (read-only) and copies them into the same cache location,
#     so CLAUDE.md's import paths resolve identically either way. The lock
#     records mode: floating and the sibling HEAD it copied from, so --verify
#     can detect drift against that HEAD. This is the pre-remediation
#     behavior, now explicit and never silently substituted for a pin.
#
# Modes:
#   ./scripts/bootstrap.sh                    — pinned bootstrap, write .vis-lock
#   ./scripts/bootstrap.sh --verify            — pinned verify (read-only, no network)
#   ./scripts/bootstrap.sh --floating          — floating bootstrap (opt-in, dev only)
#   ./scripts/bootstrap.sh --floating --verify — floating verify
#
# Idempotent: re-running bootstrap in the same mode against unchanged inputs
# reproduces byte-identical cache content and an identical lock (modulo the
# resolved_at timestamp). Fails loud on any drift or unresolved input; never
# silently falls back to a different mode or to unpinned content.

set -uo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VIS_DIR="$(cd "$PLUGIN_DIR/.." && pwd)/vis"
VIS_REPO="${VIS_REPO:-https://github.com/enchanter-ai/vis}"
VERSIONS_FILE="$PLUGIN_DIR/.vis-versions"
LOCK_FILE="$PLUGIN_DIR/.vis-lock"
CLAUDE_MD="$PLUGIN_DIR/CLAUDE.md"
CACHE_ROOT="$PLUGIN_DIR/.vis-cache"
CACHE_DIR="$CACHE_ROOT/vis"

err() { printf '%s\n' "$*" >&2; }

# --- WIX-SEC-CLONE-001: VIS_REPO allowlist ------------------------------------
# VIS_REPO is an environment variable — operator- or CI-config-controlled, not
# a hardcoded constant — and is passed to `git clone`. A value beginning with
# "-" (e.g. "--upload-pack=touch pwned") would otherwise be parsed by git as
# an option, and an option like --upload-pack runs an arbitrary command on
# this host: real argument-injection, not hypothetical. Two independent
# layers close this:
#   1. This allowlist rejects anything that is not a plausible git source
#      (https/http/ssh/git@ URL or an absolute path) BEFORE any git call.
#   2. Every git invocation that takes VIS_REPO places `--` immediately
#      before it, so even a value this allowlist would (wrongly) accept can
#      never be parsed as an option by git itself.
# A value starting with "-" is refused first, with its own explicit message,
# so the reason is never buried inside a generic "not a recognized form" line.
validate_vis_repo() {
  local v="$1"
  if [[ "$v" == -* ]]; then
    err "VIS_REPO looks like a command-line option, not a repository: $v"
    return 1
  fi
  case "$v" in
    https://*|http://*|ssh://*) return 0 ;;
    git@*:*) return 0 ;;
    /*) return 0 ;;                                    # absolute POSIX path
  esac
  if [[ "$v" =~ ^[A-Za-z]:[\\/] ]]; then
    return 0                                            # absolute Windows path (C:\... or C:/...)
  fi
  err "VIS_REPO is not a supported source form: $v"
  err "  supported: https://..., http://..., ssh://..., git@host:path, or an absolute local path"
  return 1
}

# --- argument parsing (order-independent) ------------------------------------

VERIFY=0
FLOATING=0
for arg in "$@"; do
  case "$arg" in
    --verify) VERIFY=1 ;;
    --floating) FLOATING=1 ;;
    *)
      err "unknown argument: $arg (supported: --verify --floating)"
      exit 2
      ;;
  esac
done

if [[ "$FLOATING" -eq 1 ]]; then
  MODE="floating"
else
  MODE="pinned"
fi

# --- preflight ---------------------------------------------------------------

if [[ ! -f "$VERSIONS_FILE" ]]; then
  err "missing $VERSIONS_FILE — every sibling plugin must pin vis packages"
  exit 1
fi

if [[ ! -f "$CLAUDE_MD" ]]; then
  err "missing $CLAUDE_MD — bootstrap verifies @-imports against this file"
  exit 1
fi

if [[ "$VERIFY" -eq 1 ]]; then
  if [[ ! -d "$VIS_DIR/.git" ]]; then
    err "vis sibling missing — run ./scripts/bootstrap.sh"
    exit 1
  fi
else
  # Bootstrap (either mode): the sibling only needs to exist and hold the
  # objects/files we will read. Clone if missing; best-effort fetch of tags
  # (never fatal — a disposable/offline sibling that already holds the
  # needed objects must still work with no network).
  if [[ ! -d "$VIS_DIR/.git" ]]; then
    validate_vis_repo "$VIS_REPO" || exit 1
    err "vis sibling missing at $VIS_DIR — cloning"
    git clone -- "$VIS_REPO" "$VIS_DIR" || {
      err "clone failed — set VIS_REPO or clone manually"
      exit 1
    }
  fi
  git -C "$VIS_DIR" fetch --tags --quiet 2>/dev/null \
    || err "note: git fetch --tags failed or unavailable (offline?) — continuing with local refs"
fi

# --- parse .vis-versions --------------------------------------------
# Format: lines like  core: "~0.6.0"
# We extract (pkg, version) pairs. Comment lines (#…) and blanks ignored.

declare -a PKGS=()
declare -a VERS=()
while IFS= read -r line; do
  line="${line%%#*}"
  line="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  [[ -z "$line" ]] && continue
  if [[ "$line" =~ ^([a-z]+):[[:space:]]*\"?([~^]?[0-9][^\"[:space:]]*)\"?[[:space:]]*$ ]]; then
    PKGS+=("${BASH_REMATCH[1]}")
    raw="${BASH_REMATCH[2]}"
    VERS+=("${raw#[~^]}")
  else
    err "warning: unparsed line in .vis-versions: $line"
  fi
done < "$VERSIONS_FILE"

if [[ "${#PKGS[@]}" -eq 0 ]]; then
  err "no packages parsed from $VERSIONS_FILE"
  exit 1
fi

# --- resolve per-package pin (pinned mode only) -------------------------------

declare -a TAG_NAMES=()
declare -a TAG_COMMITS=()
if [[ "$MODE" == "pinned" ]]; then
  for i in "${!PKGS[@]}"; do
    pkg="${PKGS[$i]}"
    ver="${VERS[$i]}"
    tag="enchanter-${pkg}--v${ver}"
    sha=$(git -C "$VIS_DIR" rev-list -n 1 "refs/tags/${tag}" -- 2>/dev/null || true)
    if [[ -z "$sha" ]]; then
      err "tag missing in vis: ${tag}"
      err "  -> bump .vis-versions or check available tags: git -C $VIS_DIR tag"
      exit 1
    fi
    TAG_NAMES+=("$tag")
    TAG_COMMITS+=("$sha")
  done
fi

pkg_index_for() {
  # $1 = package name -> prints array index, or nothing if not declared
  local want="$1"
  for i in "${!PKGS[@]}"; do
    [[ "${PKGS[$i]}" == "$want" ]] && { printf '%s' "$i"; return 0; }
  done
  return 1
}

# --- walk CLAUDE.md for @-imports under the cache prefix ----------------------

mapfile -t IMPORT_PATHS < <(
  grep -oE '@\.vis-cache/vis/packages/[a-z]+/[A-Za-z0-9._/-]+\.[a-zA-Z]+' "$CLAUDE_MD" | \
    sed 's#^@\.vis-cache/vis/##' | LC_ALL=C sort -u
)

if [[ "${#IMPORT_PATHS[@]}" -eq 0 ]]; then
  err "warning: no @.vis-cache/vis/... imports found in $CLAUDE_MD"
fi

# --- materialize into a staging dir, never touching the sibling's checkout ---

STAGE_DIR="$CACHE_ROOT/.stage-$$"
cleanup_stage() { rm -rf "$STAGE_DIR" 2>/dev/null || true; }
trap cleanup_stage EXIT

declare -a HASH_PATHS=()
declare -a HASH_VALUES=()
MISSING=0

if [[ "$VERIFY" -eq 0 ]]; then
  rm -rf "$STAGE_DIR"
  mkdir -p "$STAGE_DIR"

  for rel in "${IMPORT_PATHS[@]}"; do
    dest="$STAGE_DIR/$rel"
    mkdir -p "$(dirname "$dest")"

    if [[ "$MODE" == "pinned" ]]; then
      pkg="$(printf '%s' "$rel" | sed -nE 's#^packages/([^/]+)/.*#\1#p')"
      if [[ -z "$pkg" ]]; then
        err "import path does not belong to a package/: @.vis-cache/vis/$rel"
        MISSING=1
        continue
      fi
      idx="$(pkg_index_for "$pkg")" || {
        err "import references package '$pkg' not declared in $VERSIONS_FILE: @.vis-cache/vis/$rel"
        MISSING=1
        continue
      }
      sha="${TAG_COMMITS[$idx]}"
      if ! git -C "$VIS_DIR" show "${sha}:${rel}" -- > "$dest" 2>/dev/null; then
        rm -f "$dest"
        err "import resolves to missing file at pin: @.vis-cache/vis/$rel (package $pkg @ ${TAG_NAMES[$idx]} = $sha)"
        MISSING=1
        continue
      fi
    else
      src="$VIS_DIR/$rel"
      if [[ ! -f "$src" ]]; then
        err "import resolves to missing file: @.vis-cache/vis/$rel (floating, vis working tree)"
        MISSING=1
        continue
      fi
      cp -- "$src" "$dest"
    fi

    h=$(sha1sum "$dest" | awk '{print $1}')
    HASH_PATHS+=("$rel")
    HASH_VALUES+=("$h")
  done

  if [[ "$MISSING" -ne 0 ]]; then
    err "one or more @-imports unresolved — the vis sibling is unchanged; nothing was written"
    exit 1
  fi

  # Atomic-ish swap: build fully in STAGE_DIR, then replace CACHE_DIR only on
  # full success. A failed run above never reaches here, so a previously
  # working CACHE_DIR is left untouched by a failed re-bootstrap attempt.
  rm -rf "$CACHE_DIR"
  mkdir -p "$CACHE_ROOT"
  mv "$STAGE_DIR" "$CACHE_DIR"
else
  # --verify: re-hash whatever is currently materialized in CACHE_DIR. Never
  # touches the sibling's working tree; for pinned mode it does not even
  # require the sibling's checked-out HEAD to be anything in particular.
  if [[ ! -d "$CACHE_DIR" || ! -f "$LOCK_FILE" ]]; then
    err "vis not bootstrapped — run ./scripts/bootstrap.sh"
    exit 1
  fi
  for rel in "${IMPORT_PATHS[@]}"; do
    full="$CACHE_DIR/$rel"
    if [[ ! -f "$full" ]]; then
      err "import resolves to missing file in cache: @.vis-cache/vis/$rel — run ./scripts/bootstrap.sh"
      MISSING=1
      continue
    fi
    h=$(sha1sum "$full" | awk '{print $1}')
    HASH_PATHS+=("$rel")
    HASH_VALUES+=("$h")
  done
  if [[ "$MISSING" -ne 0 ]]; then
    exit 1
  fi
fi

# --- write or verify .vis-lock ------------------------------------------------

generate_lock() {
  local iso
  iso=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  {
    echo "# .vis-lock — auto-generated by scripts/bootstrap.sh"
    echo "# Do not edit by hand. Run ./scripts/bootstrap.sh to refresh."
    echo "lock_version: 2"
    echo "mode: $MODE"
    echo "resolved_at: $iso"
    if [[ "$MODE" == "pinned" ]]; then
      echo "packages:"
      for i in "${!PKGS[@]}"; do
        echo "  ${PKGS[$i]}:"
        echo "    version: v${VERS[$i]}"
        echo "    tag: ${TAG_NAMES[$i]}"
        echo "    tag_commit: ${TAG_COMMITS[$i]}"
      done
    else
      echo "vis_head: $(git -C "$VIS_DIR" rev-parse HEAD)"
    fi
    echo "conduct_files:"
    for i in "${!HASH_PATHS[@]}"; do
      echo "  - path: ${HASH_PATHS[$i]}"
      echo "    sha1: ${HASH_VALUES[$i]}"
    done
  } > "$LOCK_FILE"
}

if [[ "$VERIFY" -eq 0 ]]; then
  generate_lock
  echo "bootstrapped ($MODE): ${#PKGS[@]} packages, ${#HASH_PATHS[@]} conduct files"
  echo "materialized: $CACHE_DIR"
  echo "wrote $LOCK_FILE"
  exit 0
fi

# --verify path (both modes): lock must exist and match exactly.

lock_text="$(cat "$LOCK_FILE")"

lock_mode=$(printf '%s\n' "$lock_text" | grep -E '^mode:' | awk '{print $2}')
if [[ -z "$lock_mode" ]]; then
  err "lock is stale or wrong-schema (missing 'mode:') — run ./scripts/bootstrap.sh"
  exit 1
fi
if [[ "$lock_mode" != "$MODE" ]]; then
  err "lock mode mismatch: lock says $lock_mode, verify requested $MODE — re-run bootstrap in that mode first"
  exit 1
fi

if [[ "$MODE" == "pinned" ]]; then
  for i in "${!PKGS[@]}"; do
    pkg="${PKGS[$i]}"
    expected="${TAG_COMMITS[$i]}"
    observed=$(awk -v pkg="$pkg" '
      $0 ~ "^  "pkg":" { in_pkg=1; next }
      in_pkg && /^  [a-z]/ && $0 !~ "^    " { in_pkg=0 }
      in_pkg && /^    tag_commit:/ { print $2; exit }
    ' "$LOCK_FILE")
    if [[ -z "$observed" ]]; then
      err "package ${pkg}: missing from lock — run ./scripts/bootstrap.sh"
      exit 1
    fi
    if [[ "$observed" != "$expected" ]]; then
      err "package ${pkg}: recorded tag/version no longer resolves to the same content (lock ${observed}, tag now resolves to ${expected}) — a moved/retagged pin, or .vis-versions changed without re-bootstrapping. Run ./scripts/bootstrap.sh"
      exit 1
    fi
  done
else
  lock_head=$(printf '%s\n' "$lock_text" | grep -E '^vis_head:' | awk '{print $2}')
  live_head=$(git -C "$VIS_DIR" rev-parse HEAD)
  if [[ "$lock_head" != "$live_head" ]]; then
    err "vis drift (floating mode): lock says $lock_head, checkout is $live_head — run ./scripts/bootstrap.sh --floating to re-resolve"
    exit 1
  fi
fi

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
    err "conduct file $rel modified in the materialized cache since bootstrap — re-bootstrap or revert .vis-cache/"
    exit 1
  fi
done

echo "verified ($MODE): ${#HASH_PATHS[@]} conduct files, ${#PKGS[@]} packages"
exit 0
