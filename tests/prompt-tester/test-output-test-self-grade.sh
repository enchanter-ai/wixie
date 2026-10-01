#!/usr/bin/env bash
# Test: WIX-SEC-OT-SELF-GRADE-001 -- the target's own self-check / status / verdict text has zero
# authority over output-test.py's scores, verdict, loop termination and exit code.
# See test_output_test_self_grade.py (offline: stub clients, no model, no network).
set -euo pipefail
REPO_ROOT="${1:-.}"
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"
python "$REPO_ROOT/tests/prompt-tester/test_output_test_self_grade.py" "$REPO_ROOT" >/dev/null 2>&1
