#!/usr/bin/env bash
# Test: WIX-RUN-003 malformed artifact records are rejected with file:line and a reason, never
# silently dropped; reconcile distinguishes clean (0) from partial (3); a torn final line
# cannot swallow the next append. See test_run003_malformed.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/inference_engine/test_run003_malformed.py"
