#!/usr/bin/env bash
# Test: convergence.py's printed VERDICT line, its process exit code, and its --json
# machine-readable payload always agree (WIX-EVAL-004). Exercises the REAL
# main()/run()/deploy_verdict()/_print_final() path for six fixture shapes (all-pass
# DEPLOY, score-only failure, single-axis failure, sigma-only failure, a failed SAT
# assertion, and an unexpected internal error) plus a real subprocess run of the
# audited challenge/exit-gate-fixture prompt. See test_verdict_exit_agreement.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/convergence-engine/test_verdict_exit_agreement.py" "$REPO_ROOT" >/dev/null
