#!/usr/bin/env bash
# Test: WIX-IE-EMIT-WRAPPER-001 (D25) the inference-emit hook wrapper ships inside the installed
# plugin and runs from a plugin-only copy. See test_emit_wrapper_installed.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/inference_engine/test_emit_wrapper_installed.py"
