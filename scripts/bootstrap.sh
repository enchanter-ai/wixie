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
# this host: real argument-injection, not hypothetical. A value containing an
# embedded double quote is also refused: none of the supported source forms
# ever need one, and Windows PowerShell 5.1 splits such a value into several
# native argv entries when invoking an external command (verified: a VIS_REPO
# containing a literal `"` reaches git as more than one argument even behind
# `--`), which is fragile regardless of what comes after. Three independent
# layers close this:
#   1. This allowlist rejects anything that is not a plausible git source
#      (https/http/ssh/git@ URL or an absolute path), and separately rejects
#      any value containing a `"`, BEFORE any git call.
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
  if [[ "$v" == *'"'* ]]; then
    err "VIS_REPO contains a double quote, which no supported source form needs: $v"
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

# --- strict .vis-lock parser (--verify only) ----------------------------------
# Parses the lock against the schema exactly, not just well-enough-to-extract
# specific fields: rejects an unknown top-level key, an unknown key inside a
# package block or a conduct_files entry, a duplicate top-level key, a
# duplicate package block (even with a forged tag_commit), and a duplicate
# conduct_files entry (even with a bogus sha1) -- every one of these used to
# pass silently because the old ad-hoc awk/grep extraction only ever looked
# for the specific field it wanted and never noticed anything extra.
# On success populates (bash globals, arrays/assoc arrays reset each call):
#   LOCK_TOP_KEYS[]        LOCK_PKG_NAMES[]        LOCK_CONDUCT_PATHS[]
#   LOCK_PKG_FIELD["pkg:field"]   LOCK_CONDUCT_SHA1["path"]   LOCK_TOP_FIELD["key"]
# On any violation: prints a named cause via err() and returns 1.
lock_strict_parse() {
  local file="$1"
  LOCK_TOP_KEYS=()
  LOCK_PKG_NAMES=()
  declare -gA LOCK_PKG_FIELD=()
  LOCK_CONDUCT_PATHS=()
  declare -gA LOCK_CONDUCT_SHA1=()
  declare -gA LOCK_TOP_FIELD=()
  local -A top_seen=()
  local -A pkg_seen=()
  local -A conduct_seen=()

  local state="top"
  local cur_pkg=""
  local -A cur_pkg_keys_seen=()
  local cur_path=""
  local cur_path_has_sha1=0
  local lineno=0
  local line

  while IFS= read -r line || [[ -n "$line" ]]; do
    lineno=$((lineno + 1))
    line="${line%$'\r'}"  # tolerate a CRLF-saved lock without corrupting field values
    [[ -z "$line" ]] && continue
    [[ "$line" == \#* ]] && continue

    if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*):[[:space:]]?(.*)$ ]]; then
      local key="${BASH_REMATCH[1]}" val="${BASH_REMATCH[2]}"
      if [[ "$state" == "conduct" && -n "$cur_path" && "$cur_path_has_sha1" -eq 0 ]]; then
        err "conduct entry incomplete (missing sha1) for path: $cur_path (line $lineno)"
        return 1
      fi
      case "$key" in
        lock_version|mode|resolved_at|packages|conduct_files|vis_head) : ;;
        *) err "unknown top-level key in lock: $key (line $lineno)"; return 1 ;;
      esac
      if [[ -n "${top_seen[$key]:-}" ]]; then
        err "duplicate top-level key in lock: $key (line $lineno)"
        return 1
      fi
      top_seen[$key]=1
      LOCK_TOP_KEYS+=("$key")
      case "$key" in
        packages) state="packages" ;;
        conduct_files) state="conduct" ; cur_path="" ; cur_path_has_sha1=0 ;;
        *) state="top" ; LOCK_TOP_FIELD["$key"]="$val" ;;
      esac
      continue
    fi

    if [[ "$state" == "packages" || "$state" == "pkgblock" ]]; then
      if [[ "$state" == "pkgblock" && "$line" =~ ^\ \ \ \ ([a-z_]+):[[:space:]]?(.*)$ ]]; then
        local fkey="${BASH_REMATCH[1]}" fval="${BASH_REMATCH[2]}"
        case "$fkey" in
          version|tag|tag_commit) : ;;
          *) err "unknown key in package '$cur_pkg' block: $fkey (line $lineno)"; return 1 ;;
        esac
        if [[ -n "${cur_pkg_keys_seen[$fkey]:-}" ]]; then
          err "duplicate key '$fkey' in package '$cur_pkg' block (line $lineno)"
          return 1
        fi
        cur_pkg_keys_seen[$fkey]=1
        LOCK_PKG_FIELD["$cur_pkg:$fkey"]="$fval"
        continue
      fi
      if [[ "$line" =~ ^\ \ ([a-z][a-zA-Z0-9_]*):[[:space:]]*$ ]]; then
        local pkgname="${BASH_REMATCH[1]}"
        if [[ -n "${pkg_seen[$pkgname]:-}" ]]; then
          err "duplicate package block in lock: $pkgname (line $lineno)"
          return 1
        fi
        pkg_seen[$pkgname]=1
        LOCK_PKG_NAMES+=("$pkgname")
        cur_pkg="$pkgname"
        cur_pkg_keys_seen=()
        state="pkgblock"
        continue
      fi
      err "malformed line under 'packages:' (line $lineno): $line"
      return 1
    fi

    if [[ "$state" == "conduct" ]]; then
      if [[ "$line" =~ ^\ \ -\ path:[[:space:]]?(.*)$ ]]; then
        if [[ -n "$cur_path" && "$cur_path_has_sha1" -eq 0 ]]; then
          err "conduct entry incomplete (missing sha1) for path: $cur_path (line $lineno)"
          return 1
        fi
        local p="${BASH_REMATCH[1]}"
        if [[ -n "${conduct_seen[$p]:-}" ]]; then
          err "duplicate conduct_files entry for path: $p (line $lineno)"
          return 1
        fi
        conduct_seen[$p]=1
        LOCK_CONDUCT_PATHS+=("$p")
        cur_path="$p"
        cur_path_has_sha1=0
        continue
      fi
      if [[ "$line" =~ ^\ \ \ \ ([a-z0-9_]+):[[:space:]]?(.*)$ ]]; then
        local ckey="${BASH_REMATCH[1]}" cval="${BASH_REMATCH[2]}"
        if [[ -z "$cur_path" ]]; then
          err "conduct entry field '$ckey' with no preceding '- path:' (line $lineno)"
          return 1
        fi
        case "$ckey" in
          sha1)
            if [[ "$cur_path_has_sha1" -eq 1 ]]; then
              err "duplicate 'sha1' key for conduct entry: $cur_path (line $lineno)"
              return 1
            fi
            LOCK_CONDUCT_SHA1["$cur_path"]="$cval"
            cur_path_has_sha1=1
            ;;
          *) err "unknown key in conduct_files entry '$cur_path': $ckey (line $lineno)"; return 1 ;;
        esac
        continue
      fi
      err "malformed line under 'conduct_files:' (line $lineno): $line"
      return 1
    fi

    err "malformed line (line $lineno): $line"
    return 1
  done < "$file"

  if [[ "$state" == "conduct" && -n "$cur_path" && "$cur_path_has_sha1" -eq 0 ]]; then
    err "conduct entry incomplete (missing sha1) for path: $cur_path (end of file)"
    return 1
  fi
  return 0
}

# --- enumerate every @-import across the WHOLE repo, by RESOLUTION ----------
# Not just CLAUDE.md, and not a literal "@.vis-cache/vis/" string match:
# every @<relpath> token in every *.md file is resolved relative to the
# FILE THAT CONTAINS IT (any number of ../ segments, any spelling), exactly
# like plugins/deep-research/agents/ciber.md's @../../../vis/... form. A
# resolved path landing inside the materialized cache is a real import that
# needs coverage; one landing directly in the raw sibling vis (not yet
# repointed to the cache) is a hard error -- this script never silently
# imports raw sibling content.
#
# Exclusion of .git/.vis-cache/state/node_modules is applied to path
# components RELATIVE TO $PLUGIN_DIR only. A literal "find ... -path
# '*/state/*'" would also match an ANCESTOR of $PLUGIN_DIR named "state"
# (e.g. the repo checked out under .../state/wixie) and silently exclude
# every file -- exactly the PS 5.1 fail-open bug this mirrors and avoids.

mapfile -d '' -t ALL_MD_FILES < <(find "$PLUGIN_DIR" -name '*.md' -type f -print0 2>/dev/null)

declare -a MD_FILES=()
for f in "${ALL_MD_FILES[@]}"; do
  relf="${f#"$PLUGIN_DIR"/}"
  case "/$relf/" in
    */.git/*|*/.vis-cache/*|*/state/*|*/node_modules/*) continue ;;
  esac
  MD_FILES+=("$f")
done

AT_IMPORT_RE='@((\.\./)+|\.[A-Za-z0-9._-]*/|[a-z][A-Za-z0-9_-]*/)[A-Za-z0-9._/-]*\.[A-Za-z0-9]+'

declare -A IMPORT_SEEN=()
IMPORT_PATHS=()
UNPINNED_FOUND=0
for f in "${MD_FILES[@]}"; do
  fdir="$(dirname "$f")"
  while IFS= read -r tok; do
    [[ -z "$tok" ]] && continue
    resolved="$(realpath -m "$fdir/$tok" 2>/dev/null)" || continue
    case "$resolved" in
      "$CACHE_DIR"/*)
        key="${resolved#"$CACHE_DIR"/}"
        if [[ -z "${IMPORT_SEEN[$key]:-}" ]]; then
          IMPORT_SEEN[$key]=1
          IMPORT_PATHS+=("$key")
        fi
        ;;
      "$VIS_DIR"/*)
        err "unpinned @-import: $f references @$tok, which resolves directly into the vis sibling ($resolved) instead of the materialized cache ($CACHE_DIR/...). Repoint it to the correct relative path into .vis-cache/vis/."
        UNPINNED_FOUND=1
        ;;
    esac
  done < <(grep -oE "$AT_IMPORT_RE" "$f" 2>/dev/null | sed 's/^@//')
done

if [[ "$UNPINNED_FOUND" -ne 0 ]]; then
  err "one or more @-imports resolve directly into the vis sibling instead of the materialized cache — the vis sibling is unchanged; nothing was written"
  exit 1
fi

mapfile -t IMPORT_PATHS < <(printf '%s\n' "${IMPORT_PATHS[@]}" | LC_ALL=C sort -u)

if [[ "${#IMPORT_PATHS[@]}" -eq 0 ]]; then
  err "no @-imports resolving into the materialized cache were found anywhere in $PLUGIN_DIR — refusing to bootstrap/verify an empty expected set (this is the failure mode a broken exclusion filter produces)"
  exit 1
fi

# Fail-closed sanity floor, independent of the whole-repo walk above: CLAUDE.md
# alone is always found (it is a required top-level file, checked earlier) and
# its own imports must always be a subset of the final set. If an exclusion
# bug (e.g. a parent directory of the repo happening to be named state/.git/
# node_modules/.vis-cache) silently shrank the whole-repo walk, this catches
# it even in the case where the walk still returned a nonzero-but-short set.
declare -A CLAUDE_ONLY_SEEN=()
CLAUDE_ONLY_COUNT=0
while IFS= read -r tok; do
  [[ -z "$tok" ]] && continue
  resolved="$(realpath -m "$PLUGIN_DIR/$tok" 2>/dev/null)" || continue
  case "$resolved" in
    "$CACHE_DIR"/*)
      key="${resolved#"$CACHE_DIR"/}"
      [[ -n "${CLAUDE_ONLY_SEEN[$key]:-}" ]] && continue
      CLAUDE_ONLY_SEEN[$key]=1
      CLAUDE_ONLY_COUNT=$((CLAUDE_ONLY_COUNT + 1))
      if [[ -z "${IMPORT_SEEN[$key]:-}" ]]; then
        err "sanity check failed: CLAUDE.md imports $key but the whole-repo import walk did not find it — an exclusion filter is likely too broad (e.g. matching an ANCESTOR directory of the repo, not just directories inside it)"
        exit 1
      fi
      ;;
  esac
done < <(grep -oE "$AT_IMPORT_RE" "$CLAUDE_MD" 2>/dev/null | sed 's/^@//')

if [[ "${#IMPORT_PATHS[@]}" -lt "$CLAUDE_ONLY_COUNT" ]]; then
  err "sanity check failed: whole-repo import walk found ${#IMPORT_PATHS[@]} entries, fewer than CLAUDE.md alone ($CLAUDE_ONLY_COUNT) — refusing a short expected set"
  exit 1
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

lock_strict_parse "$LOCK_FILE" || exit 1

lock_version_field="${LOCK_TOP_FIELD[lock_version]:-}"
lock_mode="${LOCK_TOP_FIELD[mode]:-}"
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
  # --- exact package-block set: no extra, none missing (the parser already
  # rejected a duplicate block outright) -------------------------------------
  mapfile -t LOCK_PKGS < <(printf '%s\n' "${LOCK_PKG_NAMES[@]}" | LC_ALL=C sort -u)
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

    observed_version="${LOCK_PKG_FIELD[$pkg:version]:-}"
    observed_tag="${LOCK_PKG_FIELD[$pkg:tag]:-}"
    observed_commit="${LOCK_PKG_FIELD[$pkg:tag_commit]:-}"

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

  # --- exact conduct_files entry set: no extra, none missing (the parser
  # already rejected a duplicate entry outright) ------------------------------
  mapfile -t LOCK_FILES < <(printf '%s\n' "${LOCK_CONDUCT_PATHS[@]}" | LC_ALL=C sort -u)
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

    git -C "$VIS_DIR" show "${sha}:${rel}" -- >/dev/null 2>&1 || {
      err "import resolves to missing file at pin: @.vis-cache/vis/$rel (package $pkg @ ${TAG_NAMES[$idx]} = $sha) — run ./scripts/bootstrap.sh"
      exit 1
    }
    pin_hash=$(git -C "$VIS_DIR" show "${sha}:${rel}" -- 2>/dev/null | sha1sum | awk '{print $1}')

    lock_hash="${LOCK_CONDUCT_SHA1[$rel]:-}"
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
  mapfile -t LOCK_FILES < <(printf '%s\n' "${LOCK_CONDUCT_PATHS[@]}" | LC_ALL=C sort -u)
  mapfile -t EXPECTED_FILES < <(printf '%s\n' "${IMPORT_PATHS[@]}" | LC_ALL=C sort -u)
  if [[ "$(printf '%s\n' "${LOCK_FILES[@]}")" != "$(printf '%s\n' "${EXPECTED_FILES[@]}")" ]]; then
    err "conduct_files entry set in lock does not match what this repo currently imports — run ./scripts/bootstrap.sh --floating"
    exit 1
  fi

  lock_head="${LOCK_TOP_FIELD[vis_head]:-}"
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
    expected="${LOCK_CONDUCT_SHA1[$rel]:-}"
    if [[ "$observed" != "$expected" ]]; then
      err "conduct file $rel modified in the materialized cache since bootstrap — re-bootstrap or revert .vis-cache/"
      exit 1
    fi
  done
fi

# Fail-closed: the number of entries actually verified must equal the
# expected set size, and the expected set itself must be non-trivial (the
# earlier IMPORT_PATHS sanity checks already refuse empty/short; this
# re-confirms nothing was skipped between enumeration and the loops above).
if [[ "${#IMPORT_PATHS[@]}" -eq 0 || "${#LOCK_CONDUCT_PATHS[@]}" -ne "${#IMPORT_PATHS[@]}" ]]; then
  err "verified entry count (${#LOCK_CONDUCT_PATHS[@]}) does not equal the expected set size (${#IMPORT_PATHS[@]}) — refusing"
  exit 1
fi

echo "verified ($MODE): ${#IMPORT_PATHS[@]} conduct files, ${#PKGS[@]} packages, re-derived from the pin"
exit 0
