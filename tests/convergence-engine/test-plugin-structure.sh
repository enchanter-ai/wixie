#!/usr/bin/env bash
# Test: convergence-engine plugin has required structure
set -euo pipefail
REPO_ROOT="${1:-.}"

PLUGIN="$REPO_ROOT/plugins/convergence-engine"

[[ -f "$PLUGIN/.claude-plugin/plugin.json" ]]       || exit 1
[[ -f "$PLUGIN/skills/converge/SKILL.md" ]]         || exit 1
[[ -f "$PLUGIN/agents/optimizer.md" ]]              || exit 1
[[ -f "$PLUGIN/agents/reviewer.md" ]]               || exit 1
[[ -f "$PLUGIN/README.md" ]]                        || exit 1
[[ -d "$PLUGIN/state" ]]                            || exit 1
