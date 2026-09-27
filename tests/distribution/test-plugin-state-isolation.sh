#!/usr/bin/env bash
# Test: WIX-SEC-WS-001 an installed plugin tree stays byte-identical: hooks, inference engine,
# efficacy-replay and deep-research write runtime state only to CLAUDE_PLUGIN_DATA (or an explicit
# location), never into CLAUDE_PLUGIN_ROOT. Offline; never invokes the claude CLI or a model.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/distribution/test_plugin_state_isolation.py"
