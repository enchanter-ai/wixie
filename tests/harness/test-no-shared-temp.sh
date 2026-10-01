#!/usr/bin/env bash
# Test: WIX-TEST-ENV-001 static guard -- no test reintroduces a shared temp path (/tmp,
# bare mktemp, home config dirs) outside WIXIE_TEST_ROOT. Offline. See test_no_shared_temp.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/harness/test_no_shared_temp.py"
