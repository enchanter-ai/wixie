#!/usr/bin/env bash
# Test: WIX-SEC-REPORT-VERDICT-001 exactly one DEPLOY rule: no product script other than
# shared/scripts/deploy_bar.py decides DEPLOY by its own thresholds; the translate adapter's
# verdict is the canonical bar's. Static, offline.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/distribution/test_single_deploy_rule.py"
