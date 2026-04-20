<!--
Thanks for contributing to an @enchanted-plugins product.

Before opening this PR, please confirm you've read CONTRIBUTING.md and CLAUDE.md.
Delete any sections below that don't apply.
-->

## What changed

<!-- One or two sentences. What did this PR actually change? -->

## Why

<!-- The motivating problem, bug, or goal. Link issues with `Closes #N` where applicable. -->

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that changes behavior existing users rely on)
- [ ] Documentation-only change
- [ ] Internal refactor (no user-visible change)

## How I tested this

<!--
Describe the verification you ran. Be specific — "tests pass locally" is not enough.
List the commands and the relevant output.
-->

- [ ] `bash tests/run-all.sh` passes
- [ ] `python docs/architecture/generate.py` regenerated clean (no hand-edits)
- [ ] Renderer toolchain re-rendered any touched SVGs
- [ ] Manual verification of affected commands/hooks in a Claude Code session

## Ecosystem contract checklist

- [ ] No new runtime dependencies (bash + jq for hooks; Python stdlib for scripts)
- [ ] Shared conduct modules in `shared/conduct/` are unchanged, or the rationale for divergence is captured in the PR body
- [ ] No sibling-identifier leaks (this repo does not reference another sibling by filesystem path)
- [ ] No hand-edited architecture diagrams (regenerate via `generate.py`)
- [ ] No `.gitkeep` alongside real content
- [ ] Temp/scratch work lives in `state/`, not in `docs/` or `prompts/`

## Screenshots / output (if relevant)

<!-- For UI, diagram, or command-output changes. -->

## Related issues / ADRs

<!-- Link ADRs in docs/adr/ if this PR implements an architectural decision. -->
