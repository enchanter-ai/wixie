#!/usr/bin/env bash
# Test: WIX-SEC-REPORT-VERDICT-001 (CE-1) output-test.py's preflight shows DEPLOY only when the
# canonical bar (shared/scripts/deploy_bar.py) says DEPLOY; canonical HOLD or a missing bar never
# does. Real CLI --dry-run; no model, no network, no key. See test_output_test_deploy_bar.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
# shellcheck source=../lib/test-root.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/test-root.sh"
python -B "$REPO_ROOT/tests/prompt-tester/test_output_test_deploy_bar.py" "$REPO_ROOT" >/dev/null 2>&1
