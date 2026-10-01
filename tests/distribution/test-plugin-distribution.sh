#!/usr/bin/env bash
# Test: WIX-DIST-001 plugin manifests use the CLI-accepted shape (no `agents`
# directory string) and every plugin's vendored shared conduct is complete and
# identical to the pin (offline; synthetic vis fixture for drift cases).
# See test_plugin_distribution.py. Never invokes the claude CLI.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/distribution/test_plugin_distribution.py"
