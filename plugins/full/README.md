# full

**Meta-plugin. Installs every Wixie plugin at once.**

This plugin has no hooks, skills, or agents of its own. It exists so you can install the whole 6-plugin pipeline with one command:

```
/plugin marketplace add enchanter-ai/wixie
/plugin install full@wixie
```

Claude Code resolves the six dependencies and installs:

- `convergence-engine` — 100-iteration autonomous optimizer
- `prompt-crafter` — creates production-ready prompts
- `prompt-harden` — 12 adversarial attack patterns
- `prompt-refiner` — improves existing prompts
- `prompt-tester` — runs `tests.json` assertions
- `prompt-translate` — ports prompts between 274 models

If you want to cherry-pick a single plugin (e.g. just `prompt-harden`), you can — but the plugins hand off to each other at runtime, so you'll typically want them all.

## Behavioral modules

Inherits the [shared behavioral modules](../../shared/) via root [CLAUDE.md](../../CLAUDE.md) — discipline, context, verification, delegation, failure-modes, tool-use, formatting, skill-authoring, hooks, precedent.
