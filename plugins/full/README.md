# full

**Meta-plugin. Installs the six core Wixie prompt-engineering plugins at once.**

This plugin has no hooks, skills, or agents of its own. It exists so you can install the whole 6-plugin pipeline with one command. It intentionally does not pull in the two opt-in plugins — `inference-engine` (gated behind `WIXIE_INFERENCE_ENABLED`) and `deep-research` — install those separately if you need them:

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
- `prompt-translate` — ports prompts between 447 models

If you want to cherry-pick a single plugin (e.g. just `prompt-harden`), you can — but the plugins hand off to each other at runtime, so you'll typically want them all.

## Behavioral modules

In a full repository checkout, inherits the [shared behavioral modules](../../shared/) via root [CLAUDE.md](../../CLAUDE.md) — discipline, context, verification, delegation, failure-modes, tool-use, formatting, skill-authoring, hooks, precedent. A marketplace install of this plugin does not receive the root `CLAUDE.md`; this meta-plugin ships no files of its own; each plugin it installs carries the scripts, model registry, references, shared-conduct modules and `CLAUDE.md` sections it uses under its own `vendor/` (see [What an installed plugin carries](../../docs/installation.md#what-an-installed-plugin-carries)).
