#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="${1:-.}"
P="$REPO_ROOT/plugins/prompt-harden"
[[ -f "$P/.claude-plugin/plugin.json" ]] || exit 1
[[ -f "$P/skills/harden/SKILL.md" ]] || exit 1
[[ -f "$P/agents/red-team.md" ]] || exit 1
[[ -f "$P/README.md" ]] || exit 1
python -c "import json,sys,os; d=json.load(open(os.path.normpath(sys.argv[1]))); assert d['name']=='wixie-prompt-harden'" "$P/.claude-plugin/plugin.json"
