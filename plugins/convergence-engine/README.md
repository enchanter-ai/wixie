# convergence-engine

**Autonomous prompt perfection. Zero user intervention.**

Like gradient descent for prompts. Each iteration scores the prompt, identifies the weakest axis, applies a targeted fix, and re-scores. Repeats up to 100 times until the prompt reaches DEPLOY quality.

## Install

Part of the [Wixie](../..) bundle. The simplest install is the `full` meta-plugin, which pulls in all 6 Wixie plugins via dependency resolution:

```
/plugin marketplace add enchanter-ai/wixie
/plugin install full@wixie
```

To install this plugin on its own: `/plugin install convergence-engine@wixie`. `convergence-engine` is called by `prompt-crafter` and `prompt-refiner`, and its output feeds `prompt-tester` and `prompt-harden` — so on its own it has no callers and no consumers.

## How It Works

```
Input: any prompt file (4.4/10 garbage one-liner)
  │
  ├── Iteration 1:  Score → Fix Clarity (remove hedge words) → 6.2/10
  ├── Iteration 2:  Score → Fix Completeness (add role, format) → 7.8/10
  ├── Iteration 3:  Score → Fix Resilience (add fallbacks) → 8.1/10
  ├── Iteration 4:  Score → PLATEAU
  │
Output: optimized prompt (8.1/10) + updated metadata + fresh report.pdf
```

## Skills

| Skill | Triggers on |
|-------|-------------|
| converge | `/converge`, "optimize until perfect", "run convergence" |

## Agents

| Agent | Role | Model |
|-------|------|-------|
| optimizer | Runs convergence.py, updates artifacts | Opus |
| reviewer | Validates result, checks metadata/registry alignment | Opus |

## What It Fixes

| Axis | Fix Applied |
|------|-------------|
| Clarity | Remove hedge words, shorten long sentences, add imperatives |
| Completeness | Add missing role, output format, constraints, examples |
| Efficiency | Remove filler phrases, deduplicate, clean whitespace |
| Model Fit | Add/remove CoT, fix format for target model, add "think thoroughly" |
| Failure Resilience | Add fallbacks, edge case handling, input validation |

## Exit Conditions

- **DEPLOY:** overall ≥ 9.0, all axes ≥ 7.0
- **PLATEAU:** score unchanged for 3 consecutive iterations
- **MAX:** 100 iterations reached

## Behavioral modules

In a full repository checkout, inherits the [shared behavioral modules](../../shared/) via root [CLAUDE.md](../../CLAUDE.md) — discipline, context, verification, delegation, failure-modes, tool-use, formatting, skill-authoring, hooks, precedent. A marketplace install of this plugin does not receive the root `CLAUDE.md`; the shared-conduct modules this plugin's own files reference ship inside it under `vendor/` (see [What an installed plugin carries](../../docs/installation.md#what-an-installed-plugin-carries)).
