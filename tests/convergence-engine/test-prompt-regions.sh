#!/usr/bin/env bash
# Test: WIX-CONV-001 (D15) -- the explicit editability contract. convergence.py, output-test.py's
# try_offline_fix and its LLM fix path change ONLY the bodies of regions explicitly marked with
# "@wixie-editable/1" marker lines (shared/scripts/prompt_regions.py); unannotated prompts are
# never written; a structural failure is never DEPLOY / exit 0. See test_prompt_regions.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/convergence-engine/test_prompt_regions.py" "$REPO_ROOT" >/dev/null 2>&1
