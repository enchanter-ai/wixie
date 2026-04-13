#!/usr/bin/env bash
set -euo pipefail

FLUX_DIR="${HOME}/.claude/plugins/flux"

if [[ -d "$FLUX_DIR" ]]; then
  echo "Flux already installed at $FLUX_DIR"
  echo "To update: cd $FLUX_DIR && git pull"
  exit 0
fi

echo "Installing Flux..."
git clone --depth 1 https://github.com/enchanted-plugins/flux "$FLUX_DIR"

# Reset prompts index (fresh install)
echo '{"last_updated":"","prompts":[]}' > "$FLUX_DIR/prompts/index.json"

echo ""
echo "Done! Now run this ONE command in Claude Code:"
echo ""
echo "  /plugin marketplace add enchanted-plugins/flux"
echo ""
echo "That's it. All 6 plugins are now discoverable via /plugin → Discover."
