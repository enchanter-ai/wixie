#!/usr/bin/env bash
# Test: WIX-RUN-004 follow-up: wrongly typed top-level catalog fields exit 74 and are rebuilt;
# a corrupt catalog beside an empty log is still quarantined. See test_run004_catalog_fields.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/inference_engine/test_run004_catalog_fields.py"
