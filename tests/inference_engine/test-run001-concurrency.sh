#!/usr/bin/env bash
# Test: WIX-RUN-001 concurrent reconcile and the emit-lock policy (forced contention via an
# external lock holder: reconcile/backfill exit 75 within the bound, emit queues durably and is
# folded in exactly once; concurrent reconciles and emits end in documented outcomes with a
# complete catalog; inference-emit.sh exits 0 only for recorded events).
# See test_run001_concurrency.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/inference_engine/test_run001_concurrency.py"
