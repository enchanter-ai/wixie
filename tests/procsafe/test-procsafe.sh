#!/usr/bin/env bash
# Test: shared/scripts/procsafe.py — owned-tree-only termination, never by name (incident 2026-10-01).
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/procsafe/test_procsafe.py" "$REPO_ROOT"
