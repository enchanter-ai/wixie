#!/usr/bin/env bash
# Test: efficacy-replay.py `corpus` mode — measured DEPLOY bar, model call MOCKED.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/convergence-engine/test_corpus_measure.py" "$REPO_ROOT" >/dev/null
