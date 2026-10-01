#!/usr/bin/env bash
# Test: OD-1-RELEASE-IDENTITY every marketplace plugin advertises a version newer than the
# published baseline (10eb827), so `claude plugin update` replaces existing installs. Offline;
# never invokes the claude CLI or a model.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/distribution/test_release_identity.py"
