#!/usr/bin/env bash
# Test: WIX-DIST-003 the declared install graph (plugin.json `dependencies`, resolved
# transitively) covers every cross-plugin runtime reference in shipped skills/agents/hooks,
# e.g. prompt-crafter's /create Phase 2.7 invoking the deep-research skill. Offline;
# never invokes the claude CLI or a model.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/distribution/test_plugin_dependencies.py"
