#!/usr/bin/env bash
# Test: /test-prompt's measure step (efficacy-replay corpus mode) — model call MOCKED.
# Shares the offline harness with the convergence-engine suite (same script both skills call).
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/convergence-engine/test_corpus_measure.py" "$REPO_ROOT" >/dev/null
