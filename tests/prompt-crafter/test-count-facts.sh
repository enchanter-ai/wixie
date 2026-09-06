#!/usr/bin/env bash
# Test: documented counts (model count, etc.) match the source of truth.
# Fails loudly on drift — run `python shared/scripts/count-facts.py inject` to fix.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/shared/scripts/count-facts.py" check
