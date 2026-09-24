#!/usr/bin/env bash
# Test: WIX-RUN-001 follow-up: a contended emit (engine and wrapper) finishes within the
# smallest hook timeout; pending renames are fsynced; stale pending temp files are cleaned.
# See test_run001_emit_bound.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/inference_engine/test_run001_emit_bound.py"
