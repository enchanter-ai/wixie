#!/usr/bin/env bash
# Test: prompt-refiner plugin.json is valid and has required fields
set -euo pipefail
REPO_ROOT="${1:-.}"

python -c "
import json, sys, os
path = os.path.normpath(sys.argv[1])
data = json.load(open(path))
assert data['name'] == 'wixie-prompt-refiner', f'wrong name: {data[\"name\"]}'
assert 'description' in data, 'missing description'
assert 'skills' in data, 'missing skills'
assert './skills/prompt-improver/' in data['skills'], 'missing prompt-improver skill'
print('plugin.json OK')
" "$REPO_ROOT/plugins/prompt-refiner/.claude-plugin/plugin.json"
