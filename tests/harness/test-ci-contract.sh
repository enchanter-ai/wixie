#!/usr/bin/env bash
# Test: WIX-CI-001 static CI contract -- ci.yml runs `bash tests/run-all.sh` with no -x guard or
# skip branch, fails closed, and asserts the WIXIE_SUITE_SUMMARY evidence. Offline.
# See test_ci_contract.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/harness/test_ci_contract.py"
