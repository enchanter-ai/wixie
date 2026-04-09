#!/usr/bin/env bash
set -euo pipefail

FLUX_DIR="${HOME}/.claude/plugins/flux"

if [[ -d "$FLUX_DIR" ]]; then
  echo "Flux already installed at $FLUX_DIR"
  echo "To update: cd $FLUX_DIR && git pull"
  exit 0
fi

echo "Installing Flux..."
git clone https://github.com/enchanted-plugins/flux "$FLUX_DIR"

echo ""
echo "Done. Run in Claude Code:"
echo ""
echo "  /plugin add $FLUX_DIR/plugins/prompt-crafter"
echo "  /plugin add $FLUX_DIR/plugins/prompt-refiner"
echo ""
echo "Or add the marketplace:"
echo "  /plugin marketplace add $FLUX_DIR"
echo ""
echo "Start with prompt-crafter — it's the one you'll use most."
