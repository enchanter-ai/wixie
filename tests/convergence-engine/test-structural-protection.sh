#!/usr/bin/env bash
# Test: WIX-CONV-001 -- convergence.py's fixers must never modify content inside a
# protected region (fenced code of any language, Markdown/GFM tables, blockquotes,
# <example> blocks); the accept/revert gate must revert a structurally-damaging
# candidate regardless of its heuristic score; every exit path (DEPLOY, plateau,
# max-iterations) must preserve protected regions; output-test.py's try_offline_fix
# must share the same gate; line endings and encoding of the input file must be
# preserved on save. See test_structural_protection.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/convergence-engine/test_structural_protection.py" "$REPO_ROOT" >/dev/null
