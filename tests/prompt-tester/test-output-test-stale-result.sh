#!/usr/bin/env bash
# Test: WIX-SEC-OT-STALE-RESULT-001 -- a failed current output-test.py evaluation can never leave a
# previous successful result indistinguishable from the current run (run_id, atomic IN_PROGRESS
# publication, exactly one COMPLETE or ERROR record, schema-validated evaluator/fixer replies,
# UNKNOWN usage, exit 3 for ERROR). See test_output_test_stale_result.py (offline, stub clients).
set -euo pipefail
REPO_ROOT="${1:-.}"
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"
python "$REPO_ROOT/tests/prompt-tester/test_output_test_stale_result.py" "$REPO_ROOT" >/dev/null 2>&1
