# prompt-crafter

**Creates production-ready prompts. Zero manual iteration.**

Give it a task description. It scans your project context, asks targeted questions, selects from 16 techniques, adapts format to 274 models, then runs the Convergence Engine autonomously until the prompt hits DEPLOY quality.

## Install

Part of the [Wixie](../..) bundle. The simplest install is the `full` meta-plugin, which pulls in all 6 Wixie plugins via dependency resolution:

```
/plugin marketplace add enchanter-ai/wixie
/plugin install full@wixie
```

To install this plugin on its own: `/plugin install prompt-crafter@wixie`. `prompt-crafter` hands off to `convergence-engine`, emits `tests.json` for `prompt-tester`, and pairs with `prompt-harden` / `prompt-translate` downstream — so without the others you'll hit broken handoffs on the first run.

## Pipeline

```
User describes task
  → Phase 1: Context Scan (silent — reads CLAUDE.md, .cursorrules)
  → Phase 2: Interactive Profiling (3-8 targeted questions)
  → Phase 2.5: Model Fit Check (warns if wrong model for task)
  → Phase 3: Generation (technique selection + prompt generation)
  → Phase 4: Multi-Agent Pipeline
      → Convergence Agent (Opus, background, up to 100 iterations)
      → Reviewer Agent (Opus, validates against registry)
      → Save: prompt + metadata + tests + report.pdf
```

## Components

| Type | Name | What it does |
|------|------|-------------|
| Skill | prompt-creator | Main workflow — phases 1-4 |
| Skill | prompt-reviewer | Internal validator (not user-invocable) |
| Agent | convergence | Runs convergence.py in background (Opus) |
| Agent | reviewer | Validates folder against registry (Opus) |
| Hook | PostToolUse | Auto-triggers on prompt file save |

## Triggers

`/create`, "I need a prompt for...", "build me a prompt", "write a system prompt"

## Output

```
prompts/<name>/
├── prompt.<format>     Production-ready prompt
├── metadata.json       Model, tokens, cost, scores, config
├── tests.json          3-5 regression test cases
└── report.pdf          Dark-themed single-page audit report
```

## Behavioral modules

Inherits the [shared behavioral modules](../../shared/) via root [CLAUDE.md](../../CLAUDE.md) — discipline, context, verification, delegation, failure-modes, tool-use, formatting, skill-authoring, hooks, precedent.
