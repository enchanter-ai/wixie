#!/usr/bin/env bash
# Test: WIX-RUN-002 (V-RUN002-1) copies, concatenations and in-place duplicates of an
# engine-written event log add nothing; distinct events still count.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/inference_engine/test_run002_log_copies.py"
