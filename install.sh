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
echo "Done. Run in Claude Code:"
echo ""
echo "  /plugin add $FLUX_DIR/plugins/prompt-crafter"
echo "  /plugin add $FLUX_DIR/plugins/prompt-refiner"
echo "  /plugin add $FLUX_DIR/plugins/convergence-engine"
echo ""
echo "Or add the marketplace:"
echo "  /plugin marketplace add $FLUX_DIR"
echo ""
echo "Start with prompt-crafter — it's the one you'll use most."
