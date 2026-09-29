#!/usr/bin/env bash
# Test: WIX-IE-EMIT-WIN-001 the inference-emit skill's Step 2 command feeds the record on stdin
# (no `<(` process substitution into python) and records the event exactly once when run in bash.
# See test_emit_skill_stdin.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/inference_engine/test_emit_skill_stdin.py"
