#!/usr/bin/env bash
# Test: WIX-RUN-003 follow-up: rejections new since the last reconcile are counted and listed
# first, never hidden behind older ones. See test_run003_new_rejections.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/inference_engine/test_run003_new_rejections.py"
