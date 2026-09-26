#!/usr/bin/env bash
# Wixie installer. The 6 plugins (plus deep-research, which /create invokes) are a
# coordinated pipeline; the `full` meta-plugin pulls them all in via one
# dependency-resolution pass.
set -euo pipefail

REPO="https://github.com/enchanter-ai/wixie"
WIXIE_DIR="${HOME}/.claude/plugins/wixie"

step() { printf "\n\033[1;36m▸ %s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }

step "Wixie installer"

# 1. Clone the monorepo so shared/scripts/*.py (output-test, eval, sim, schema,
#    self-check) are available to the user locally. Plugins themselves are also
#    served via the marketplace command below — the clone is just for scripts.
if [[ -d "$WIXIE_DIR/.git" ]]; then
  git -C "$WIXIE_DIR" pull --ff-only --quiet
  ok "Updated existing clone at $WIXIE_DIR"
else
  git clone --depth 1 --quiet "$REPO" "$WIXIE_DIR"
  ok "Cloned to $WIXIE_DIR"
fi

# 2. Seed the prompts index on fresh installs only (never overwrite user data).
INDEX="$WIXIE_DIR/prompts/index.json"
if [[ ! -f "$INDEX" ]]; then
  mkdir -p "$WIXIE_DIR/prompts"
  printf '{"last_updated":"","prompts":[]}\n' > "$INDEX"
  ok "Initialized prompts index"
fi

cat <<'EOF'

─────────────────────────────────────────────────────────────────────────
  Wixie ships as a 6-plugin pipeline — crafter hands off to convergence,
  which emits tests.json that tester executes, and so on. The `full`
  meta-plugin lists all six, plus deep-research (which /create invokes),
  as dependencies so one install pulls in the whole chain.
─────────────────────────────────────────────────────────────────────────

  Finish in Claude Code with TWO commands:

    /plugin marketplace add enchanter-ai/wixie
    /plugin install full@wixie

  That installs all 7 plugins via dependency resolution. To cherry-pick
  a single plugin instead, use e.g. `/plugin install prompt-harden@wixie`.

  Each installed plugin carries the shared-conduct modules it references
  under its own vendor/ directory (generated from the pinned vis release
  in .vis-lock), so no vis checkout or bootstrap step is needed for it.
  The repo-level CLAUDE.md contract applies inside a full checkout (run
  ./scripts/bootstrap.sh there); see docs/installation.md.

  Verify with:   /plugin list
  Expected:      full + 7 plugins installed under the wixie marketplace.

EOF
