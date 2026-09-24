#!/usr/bin/env bash
# Test: WIX-RUN-004 corrupt derived catalog is quarantined and rebuilt from the artifact log
# (truncated / invalid / non-UTF-8 / wrong-type / structurally invalid catalogs, interrupted
# recovery); read-only commands refuse with exit 74. See test_run004_recovery.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/inference_engine/test_run004_recovery.py"
