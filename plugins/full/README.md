# full

**Meta-plugin. Installs the Wixie prompt-engineering pipeline at once: the six core plugins plus `deep-research`.**

This plugin has no hooks, skills, or agents of its own. It exists so you can install the whole pipeline with one command. It includes `deep-research` because `/create` (`prompt-crafter`) invokes it and `prompt-crafter` declares it as a dependency. It intentionally does not pull in the opt-in `inference-engine` (gated behind `WIXIE_INFERENCE_ENABLED`); install that separately if you need it:

```
/plugin marketplace add enchanter-ai/wixie
/plugin install full@wixie
```

Claude Code resolves the seven dependencies and installs:

- `convergence-engine` — 100-iteration autonomous optimizer
- `deep-research` — E0 cited research briefs; required by `/create` (a dependency of `prompt-crafter`)
- `prompt-crafter` — creates production-ready prompts
- `prompt-harden` — 12 adversarial attack patterns
- `prompt-refiner` — improves existing prompts
- `prompt-tester` — runs `tests.json` assertions
- `prompt-translate` — ports prompts between 447 models

If you want to cherry-pick a single plugin (e.g. just `prompt-harden`), you can — but the plugins hand off to each other at runtime, so you'll typically want them all.

## Behavioral modules

In a full repository checkout, inherits the [shared behavioral modules](../../shared/) via root [CLAUDE.md](../../CLAUDE.md) — discipline, context, verification, delegation, failure-modes, tool-use, formatting, skill-authoring, hooks, precedent. A marketplace install of this plugin does not receive the root `CLAUDE.md`; this meta-plugin ships no files of its own; each plugin it installs carries the scripts, model registry, references, shared-conduct modules and `CLAUDE.md` sections it uses under its own `vendor/` (see [What an installed plugin carries](../../docs/installation.md#what-an-installed-plugin-carries)).
