# Contributing to Flux

## Stack

Python (stdlib only) for scripts. Markdown for skills and references. No external dependencies.

## Critical Rules

Before submitting a PR, verify:

1. **Zero pip installs** — scripts use only Python stdlib. No external packages.
2. **SKILL.md uses `${CLAUDE_PLUGIN_ROOT}/../../shared/`** — never hardcoded paths.
3. **models-registry.json stays current** — bump `last_updated` when changing model specs.
4. **Reference files stay factual** — cite sources for model-specific claims.
5. **Self-eval scores honestly** — don't inflate heuristic weights to produce higher scores.
6. **Every plugin has identical structure** — `.claude-plugin/`, `skills/`, `state/`, `README.md`.

## Structure

```
shared/                      ← resources used by all plugins
  references/                ← technique engine, model profiles, formats
  scripts/                   ← self-eval.py, token-count.py
  models-registry.json       ← single source of truth for model data
prompts/                     ← saved prompts (shared output directory)
plugins/<name>/              ← each plugin (CLAUDE_PLUGIN_ROOT)
  .claude-plugin/plugin.json
  skills/<skill>/SKILL.md
  state/.gitkeep
  README.md
```

## Adding a Model

1. Add the entry to `shared/models-registry.json`
2. Add format specs to `shared/references/model-profiles.md`
3. Update the supported models table in the root `README.md`
4. Bump `last_updated` in models-registry.json

## Adding a Technique

1. Add the technique to `shared/references/technique-engine.md`
2. Include: when to use, when to avoid, model-specific anti-patterns
3. Update the technique count in README.md and SKILL.md

## Testing

```bash
bash tests/run-all.sh
```

Each test pipes sample prompts to scripts and verifies exit codes and output.

## Submitting

1. Reference files are accurate and sourced
2. models-registry.json is valid JSON
3. Scripts run with Python 3.8+ stdlib only
4. No broken `${CLAUDE_PLUGIN_ROOT}` paths in SKILL.md
