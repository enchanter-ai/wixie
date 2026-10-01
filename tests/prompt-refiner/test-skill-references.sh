#!/usr/bin/env bash
# Test: prompt-improver SKILL.md references exist (shared resources)
set -euo pipefail
REPO_ROOT="${1:-.}"

SHARED="$REPO_ROOT/shared"

[[ -f "$SHARED/references/technique-engine.md" ]] || exit 1
[[ -f "$SHARED/references/model-profiles.md" ]]   || exit 1
[[ -f "$SHARED/references/output-formats.md" ]]   || exit 1
[[ -f "$SHARED/references/prompt-anatomy.md" ]]   || exit 1
[[ -f "$SHARED/scripts/self-eval.py" ]]           || exit 1
[[ -f "$SHARED/models-registry.json" ]]           || exit 1

# prompts/ is gitignored (.gitignore:8), so it exists only in a developer's working tree. Asserting
# its presence made this test fail in every clean checkout and in CI, which is why it was red at the
# audited revision. Its absence is normal; only a non-directory sitting at that path is wrong.
[[ ! -e "$REPO_ROOT/prompts" || -d "$REPO_ROOT/prompts" ]] || exit 1
