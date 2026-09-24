#!/usr/bin/env bash
# Test: WIX-RUN-002 event identity and replay correctness of the inference engine
# (exact replay, interrupted replay, distinct sessions/events, log-copy re-import, host session
# capture). See test_run002_identity.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/inference_engine/test_run002_identity.py"
