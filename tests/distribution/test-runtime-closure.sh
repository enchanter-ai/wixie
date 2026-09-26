#!/usr/bin/env bash
# Test: WIX-DIST-002 every installed plugin carries the runtime dependency closure
# of its skills/agents/hooks (vendored, byte-identical, provenance-recorded), its
# scripts run from a plugin copied alone, and vendor-conduct.py --check fails on
# every drift class. Offline; never invokes the claude CLI or a model.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/distribution/test_runtime_closure.py"
