#!/usr/bin/env bash
# bootstrap.sh — canonical first command for an @enchanter-ai sibling plugin.
#
# WIX-INSTALL-002 architecture (D8): production Wixie uses an immutable vis
# package version, never floating HEAD. declared version -> immutable exact
# commit -> exact content materialized -> Wixie imports THAT content ->
# .vis-lock records what was actually materialized.
#
# MERGE PRECONDITION for the branch that carries this script: the vis owner
# must cut the enchanter-<pkg>--v<version> tags declared in .vis-versions
# (real tags in the real vis repo, not a disposable clone) and this repo's
# committed .vis-lock must be regenerated with this script against a sibling
# that has those real tags, BEFORE this branch merges. Merging first means
# every checkout that runs bootstrap before the tags exist gets an explicit
# "tag missing in vis" refusal (never a silent fallback — see below) and
# `.vis-lock`/CI verify will not match a lock generated against the real
# tags until they exist. See CROSS_REPO_VERSIONING.md / the vis-side
# CHANGELOG entry for that release's own open decisions.
#
# Two modes:
#
#   PINNED (default; the only mode CI and production use):
#     For every package declared in .vis-versions, resolve the tag
#     enchanter-<pkg>--v<version> to an exact commit in the vis sibling
#     (read-only: refs/tags/* already present locally — this script never
#     fetches, so it never mutates the sibling's FETCH_HEAD, remote-tracking
#     refs, tags or config), then read every @-imported file's content
#     directly out of THAT commit via `git show <sha>:<path>` — never from
#     the sibling's checked-out working tree, and the sibling's
#     HEAD/index/working tree are never touched. The materialized content is
#     written into a Wixie-local cache (.vis-cache/vis/, gitignored) that
#     every @.vis-cache/vis/... import (CLAUDE.md AND every plugin
#     agent/skill file — enumerated across the whole repo tree, not just
#     CLAUDE.md) points at. A version whose tag does not resolve LOCALLY, or
#     whose content is missing a file something imports, fails loud before
#     anything is written — no fallback to HEAD, no partial lock, and the
#     advice is to fetch the tag or wait for the vis owner to cut it, never
#     "bump .vis-versions" (that is only correct if you actually intend a
#     different, already-released pin).
#
#   FLOATING (opt-in only, --floating; local dev convenience, never default,
#   never CI):
#     Reads the same @-imported files from the sibling's current live
#     working tree (read-only) and copies them into the same cache location,
#     so import paths resolve identically either way. The lock records
#     mode: floating and the sibling HEAD it copied from, so --verify can
#     detect drift against that HEAD. This is the pre-remediation behavior,
#     now explicit and never silently substituted for a pin.
#
# Modes:
#   ./scripts/bootstrap.sh                    — pinned bootstrap, write .vis-lock
#   ./scripts/bootstrap.sh --verify            — pinned verify (read-only, no network, no mutation)
#   ./scripts/bootstrap.sh --floating          — floating bootstrap (opt-in, dev only)
#   ./scripts/bootstrap.sh --floating --verify — floating verify
#
# --verify does not just re-hash whatever is sitting in the local cache: for
# every expected conduct file it re-resolves the package's tag from the
# sibling's current local refs and re-reads the file's content straight from
# that commit (git show), then requires the freshly re-derived hash, the
# lock's recorded hash, AND the on-disk cache's hash to all agree — plus the
# lock's package version/tag/tag_commit fields (all three, not just
# tag_commit) to match what .vis-versions currently declares, the
# lock_version to match exactly, and the package/conduct_files entry sets to
# match exactly (an extra or missing block/entry is refused just like a
# missing one). A forged lock field, a lock+cache pair copied from a
# different commit, or a stale schema all fail non-zero with a named cause.
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
CLAUDE_MD="$PLUGIN_DIR/CLAUDE.md"
LOCK_FILE="$PLUGIN_DIR/.vis-lock"
CACHE_ROOT="$PLUGIN_DIR/.vis-cache"
CACHE_DIR="$CACHE_ROOT/vis"
LOCK_SCHEMA_VERSION="2"

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

if [[ ! -d "$VIS_DIR/.git" ]]; then
  if [[ "$VERIFY" -eq 1 ]]; then
    err "vis sibling missing — run ./scripts/bootstrap.sh"
    exit 1
  fi
  # Creating a NEW sibling (nothing existing to mutate) is not the same as
  # fetching into one that's already there — see the no-fetch note below.
  validate_vis_repo "$VIS_REPO" || exit 1
  err "vis sibling missing at $VIS_DIR — cloning"
  git clone -- "$VIS_REPO" "$VIS_DIR" || {
    err "clone failed — set VIS_REPO or clone manually"
    exit 1
  }
fi

# No `git fetch` here, ever, in either mode, against an existing sibling.
# `git fetch --tags` writes FETCH_HEAD, fast-forwards refs/remotes/origin/*,
# can add new tags, and can trigger `git maintenance --auto` — all real
# mutations of a checkout other repos/sessions may share. This script only
# ever reads: refs/tags/* resolution (rev-list) and blob content (show),
# both plumbing, neither one writes anything. If a needed tag is not present
# in the sibling's LOCAL refs, that is reported as an explicit failure (see
# the tag-resolution loop below) telling the operator to fetch it
# themselves or wait for the vis owner to cut it — this script will not do
# it silently on their behalf.

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

# --- resolve per-package pin (pinned mode only; read-only, local refs only) --

declare -a TAG_NAMES=()
declare -a TAG_COMMITS=()
if [[ "$MODE" == "pinned" ]]; then
  for i in "${!PKGS[@]}"; do
    pkg="${PKGS[$i]}"
    ver="${VERS[$i]}"
    tag="enchanter-${pkg}--v${ver}"
    sha=$(git -C "$VIS_DIR" rev-list -n 1 "refs/tags/${tag}" -- 2>/dev/null || true)
    if [[ -z "$sha" ]]; then
      err "vis tag ${tag} not found locally."
      err "  This script never fetches automatically (to avoid mutating the shared vis sibling)."
      err "  Either fetch it yourself:  git -C $VIS_DIR fetch --tags"
      err "  or the vis owner has not cut this release yet — wait for it."
      err "  Only bump .vis-versions if you intend to pin a different, already-released version."
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

# --- enumerate every @.vis-cache/vis/... import across the WHOLE repo -------
# Not just CLAUDE.md: plugin agents/skills reference vis conduct directly
# too (e.g. plugins/deep-research/agents/*.md), and every one of them must
# resolve to the same materialized pinned content.

mapfile -t IMPORT_PATHS < <(
  grep -rhoE '@\.vis-cache/vis/packages/[a-z]+/[A-Za-z0-9._/-]+\.[a-zA-Z]+' \
    "$PLUGIN_DIR" \
    --include='*.md' \
    --exclude-dir='.vis-cache' --exclude-dir='.git' --exclude-dir='state' \
    --exclude-dir='node_modules' \
    2>/dev/null | \
    sed 's#^@\.vis-cache/vis/##' | LC_ALL=C sort -u
)

if [[ "${#IMPORT_PATHS[@]}" -eq 0 ]]; then
  err "warning: no @.vis-cache/vis/... imports found anywhere in $PLUGIN_DIR"
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

  {
    echo "# .vis-lock - auto-generated by scripts/bootstrap.sh"
    echo "# Do not edit by hand. Run ./scripts/bootstrap.sh to refresh."
    echo "lock_version: $LOCK_SCHEMA_VERSION"
    echo "mode: $MODE"
    echo "resolved_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
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

  echo "bootstrapped ($MODE): ${#PKGS[@]} packages, ${#HASH_PATHS[@]} conduct files"
  echo "materialized: $CACHE_DIR"
  echo "wrote $LOCK_FILE"
  exit 0
fi

# ============================================================================
# --verify: re-derive everything from the pin; never trust the cache alone.
# ============================================================================

if [[ ! -f "$LOCK_FILE" ]]; then
  err "vis not bootstrapped — run ./scripts/bootstrap.sh"
  exit 1
fi

lock_text="$(cat "$LOCK_FILE")"

lock_version_field=$(printf '%s\n' "$lock_text" | grep -E '^lock_version:' | awk '{print $2}')
lock_mode=$(printf '%s\n' "$lock_text" | grep -E '^mode:' | awk '{print $2}')
if [[ -z "$lock_mode" || -z "$lock_version_field" ]]; then
  err "lock is stale or wrong-schema (missing 'mode:' or 'lock_version:') — run ./scripts/bootstrap.sh"
  exit 1
fi
if [[ "$lock_version_field" != "$LOCK_SCHEMA_VERSION" ]]; then
  err "lock_version mismatch: lock says $lock_version_field, this bootstrap understands $LOCK_SCHEMA_VERSION — run ./scripts/bootstrap.sh to rewrite it, or you are looking at a lock from an incompatible bootstrap version"
  exit 1
fi
if [[ "$lock_mode" != "$MODE" ]]; then
  err "lock mode mismatch: lock says $lock_mode, verify requested $MODE — re-run bootstrap in that mode first"
  exit 1
fi

if [[ ! -d "$CACHE_DIR" ]]; then
  err "vis not bootstrapped — run ./scripts/bootstrap.sh"
  exit 1
fi

if [[ "$MODE" == "pinned" ]]; then
  # --- exact package-block set: no extra, none missing -----------------------
  mapfile -t LOCK_PKGS < <(
    awk '
      /^packages:$/ { inpkg=1; next }
      inpkg && /^[A-Za-z_][A-Za-z0-9_]*:$/ { inpkg=0 }
      inpkg && /^  [a-z][a-zA-Z0-9_]*:$/ { line=$0; sub(/^  /,"",line); sub(/:$/,"",line); print line }
    ' "$LOCK_FILE" | LC_ALL=C sort -u
  )
  mapfile -t EXPECTED_PKGS < <(printf '%s\n' "${PKGS[@]}" | LC_ALL=C sort -u)
  if [[ "$(printf '%s\n' "${LOCK_PKGS[@]}")" != "$(printf '%s\n' "${EXPECTED_PKGS[@]}")" ]]; then
    err "package block set in lock does not match .vis-versions exactly:"
    err "  lock has:     ${LOCK_PKGS[*]:-<none>}"
    err "  expected:     ${EXPECTED_PKGS[*]:-<none>}"
    err "  (an extra or unexpected package block is refused just like a missing one)"
    exit 1
  fi

  # --- per-package: version, tag, tag_commit ALL re-derived and compared -----
  for i in "${!PKGS[@]}"; do
    pkg="${PKGS[$i]}"
    expected_version="v${VERS[$i]}"
    expected_tag="${TAG_NAMES[$i]}"
    expected_commit="${TAG_COMMITS[$i]}"

    block=$(awk -v pkg="$pkg" '
      $0 ~ "^  "pkg":" { in_pkg=1; next }
      in_pkg && /^  [a-z]/ && $0 !~ "^    " { in_pkg=0 }
      in_pkg { print }
    ' "$LOCK_FILE")

    observed_version=$(printf '%s\n' "$block" | grep -E '^    version:' | awk '{print $2}')
    observed_tag=$(printf '%s\n' "$block" | grep -E '^    tag:' | awk '{print $2}')
    observed_commit=$(printf '%s\n' "$block" | grep -E '^    tag_commit:' | awk '{print $2}')

    if [[ -z "$observed_version" || -z "$observed_tag" || -z "$observed_commit" ]]; then
      err "package ${pkg}: lock block incomplete (missing version/tag/tag_commit) — run ./scripts/bootstrap.sh"
      exit 1
    fi
    if [[ "$observed_version" != "$expected_version" ]]; then
      err "package ${pkg}: lock 'version:' is ${observed_version}, .vis-versions currently declares ${expected_version} — forged field or stale lock. Run ./scripts/bootstrap.sh"
      exit 1
    fi
    if [[ "$observed_tag" != "$expected_tag" ]]; then
      err "package ${pkg}: lock 'tag:' is ${observed_tag}, expected ${expected_tag} — forged field or stale lock. Run ./scripts/bootstrap.sh"
      exit 1
    fi
    if [[ "$observed_commit" != "$expected_commit" ]]; then
      err "package ${pkg}: recorded tag/version no longer resolves to the same content (lock ${observed_commit}, tag now resolves to ${expected_commit}) — a moved/retagged pin, or .vis-versions changed without re-bootstrapping. Run ./scripts/bootstrap.sh"
      exit 1
    fi
  done

  # --- exact conduct_files entry set: no extra, none missing -----------------
  mapfile -t LOCK_FILES < <(
    awk '/^conduct_files:$/ {infiles=1; next} infiles && /^  - path:/ {sub(/^  - path: /,""); print}' "$LOCK_FILE" \
      | LC_ALL=C sort -u
  )
  mapfile -t EXPECTED_FILES < <(printf '%s\n' "${IMPORT_PATHS[@]}" | LC_ALL=C sort -u)
  if [[ "$(printf '%s\n' "${LOCK_FILES[@]}")" != "$(printf '%s\n' "${EXPECTED_FILES[@]}")" ]]; then
    err "conduct_files entry set in lock does not match what this repo currently imports:"
    comm -23 <(printf '%s\n' "${LOCK_FILES[@]}") <(printf '%s\n' "${EXPECTED_FILES[@]}") | while read -r p; do
      [[ -n "$p" ]] && err "  unexpected entry in lock (no longer imported): $p"
    done
    comm -13 <(printf '%s\n' "${LOCK_FILES[@]}") <(printf '%s\n' "${EXPECTED_FILES[@]}") | while read -r p; do
      [[ -n "$p" ]] && err "  missing from lock (imported but not covered): $p"
    done
    err "Run ./scripts/bootstrap.sh"
    exit 1
  fi

  # --- per-file: re-derive from the pin, compare against lock AND cache ------
  for rel in "${IMPORT_PATHS[@]}"; do
    pkg="$(printf '%s' "$rel" | sed -nE 's#^packages/([^/]+)/.*#\1#p')"
    idx="$(pkg_index_for "$pkg")" || {
      err "import references package '$pkg' not declared in $VERSIONS_FILE: @.vis-cache/vis/$rel"
      exit 1
    }
    sha="${TAG_COMMITS[$idx]}"

    pin_content=$(git -C "$VIS_DIR" show "${sha}:${rel}" -- 2>/dev/null) || {
      err "import resolves to missing file at pin: @.vis-cache/vis/$rel (package $pkg @ ${TAG_NAMES[$idx]} = $sha) — run ./scripts/bootstrap.sh"
      exit 1
    }
    pin_hash=$(git -C "$VIS_DIR" show "${sha}:${rel}" -- 2>/dev/null | sha1sum | awk '{print $1}')

    lock_hash=$(awk -v rel="$rel" '
      $0 == "  - path: "rel { in_blk=1; next }
      in_blk && /^    sha1:/ { print $2; exit }
      in_blk && /^  - path:/ { in_blk=0 }
    ' "$LOCK_FILE")
    if [[ -z "$lock_hash" ]]; then
      err "conduct file not in lock: $rel — run ./scripts/bootstrap.sh"
      exit 1
    fi

    cache_file="$CACHE_DIR/$rel"
    if [[ ! -f "$cache_file" ]]; then
      err "import resolves to missing file in cache: @.vis-cache/vis/$rel — run ./scripts/bootstrap.sh"
      exit 1
    fi
    cache_hash=$(sha1sum "$cache_file" | awk '{print $1}')

    if [[ "$pin_hash" != "$lock_hash" ]]; then
      err "conduct file $rel: lock sha1 ($lock_hash) does not match content freshly re-derived from the pinned commit ($pin_hash) — forged lock, or the lock (and possibly the cache) came from a different commit. Run ./scripts/bootstrap.sh"
      exit 1
    fi
    if [[ "$cache_hash" != "$lock_hash" ]]; then
      err "conduct file $rel modified in the materialized cache since bootstrap ($cache_hash != $lock_hash) — re-bootstrap or revert .vis-cache/"
      exit 1
    fi
  done

else
  # --- floating mode: unchanged from the previous design ---------------------
  mapfile -t LOCK_FILES < <(
    awk '/^conduct_files:$/ {infiles=1; next} infiles && /^  - path:/ {sub(/^  - path: /,""); print}' "$LOCK_FILE" \
      | LC_ALL=C sort -u
  )
  mapfile -t EXPECTED_FILES < <(printf '%s\n' "${IMPORT_PATHS[@]}" | LC_ALL=C sort -u)
  if [[ "$(printf '%s\n' "${LOCK_FILES[@]}")" != "$(printf '%s\n' "${EXPECTED_FILES[@]}")" ]]; then
    err "conduct_files entry set in lock does not match what this repo currently imports — run ./scripts/bootstrap.sh --floating"
    exit 1
  fi

  lock_head=$(printf '%s\n' "$lock_text" | grep -E '^vis_head:' | awk '{print $2}')
  live_head=$(git -C "$VIS_DIR" rev-parse HEAD)
  if [[ "$lock_head" != "$live_head" ]]; then
    err "vis drift (floating mode): lock says $lock_head, checkout is $live_head — run ./scripts/bootstrap.sh --floating to re-resolve"
    exit 1
  fi

  for rel in "${IMPORT_PATHS[@]}"; do
    full="$CACHE_DIR/$rel"
    if [[ ! -f "$full" ]]; then
      err "import resolves to missing file in cache: @.vis-cache/vis/$rel — run ./scripts/bootstrap.sh --floating"
      exit 1
    fi
    observed=$(sha1sum "$full" | awk '{print $1}')
    expected=$(awk -v rel="$rel" '
      $0 == "  - path: "rel { in_blk=1; next }
      in_blk && /^    sha1:/ { print $2; exit }
      in_blk && /^  - path:/ { in_blk=0 }
    ' "$LOCK_FILE")
    if [[ "$observed" != "$expected" ]]; then
      err "conduct file $rel modified in the materialized cache since bootstrap — re-bootstrap or revert .vis-cache/"
      exit 1
    fi
  done
fi

echo "verified ($MODE): ${#IMPORT_PATHS[@]} conduct files, ${#PKGS[@]} packages, re-derived from the pin"
exit 0
