# Wixie glossary

Terms of art used across Wixie. Short definitions; the math lives in [docs/science/README.md](science/README.md).

## Scoring

### 5 axes

Wixie scores every prompt on five independent dimensions. Each is scored 0-10 against a rubric held in the convergence engine's optimizer.

| # | Axis | What it measures |
|---|------|------------------|
| 1 | Clarity | Is the ask unambiguous? Could a stranger execute it without guessing? |
| 2 | Specificity | Are inputs, outputs, edge cases, and constraints named concretely — no "appropriately", "as needed", "some"? |
| 3 | Structure | Does the prompt follow the target model's preferred shape (XML for Claude, Markdown-sandwich for GPT, etc.)? |
| 4 | Failure resilience | Does it anticipate edge cases, explicit refusals, and handling for bad input? |
| 5 | Efficiency | Token-economy: does it say what it needs in the smallest form the target family reliably attends to? |

Axes combine into an **overall score**. Combination is not a straight mean — low scores on Structure or Failure Resilience penalize the overall disproportionately, because those are the axes that cause production regressions.

### σ (sigma)

```
σ(P) = sqrt( Σᵢ (Sᵢ(P) − 10)² / 5 )
```

Standard deviation of the 5 axis scores from the ideal (10). Lower is better. σ < 0.45 is part of the DEPLOY bar — it means every axis is tight, not that one axis is excellent and another is weak.

A prompt with scores `[10, 10, 6, 9, 10]` has an overall ≈ 9.0 but a σ much higher than `[9, 9, 9, 9, 9]`. Wixie treats the second as deployable and the first as HOLD, regardless of headline score.

### 8 SAT assertions

Boolean overlay on the continuous 5-axis score. DEPLOY requires **all 8** to hold.

| Assertion | Meaning |
|-----------|---------|
| `has_role` | Agent persona / identity stated. |
| `has_task` | The ask appears in one sentence. |
| `has_format` | Output shape is specified (schema, tags, structure). |
| `has_constraints` | Hard rules are named. |
| `has_edge_cases` | Known tricky inputs and their handling are stated. |
| `no_hedges` | No "appropriately", "as needed", "some", "usually", or similar. |
| `no_filler` | No scaffolding text that restates the task or pads for politeness. |
| `has_structure` | Consistent tagging / sectioning. No drift in anchor names. |

7/8 is **not** a pass. The assertions are a zero-tolerance floor.

## Verdicts

### DEPLOY

`σ < 0.45 AND overall ≥ 9.0 AND every axis ≥ 7.0 AND all 8 SAT assertions hold`.

Ships as-is. Artifacts saved, metadata written, PDF audit generated.

### HOLD

Any of:

- σ ≥ 0.45 (tightness failing — re-converge).
- Any axis < 7.0 (a dimension is below floor).
- 1 or more SAT assertions failing.

Never promote a HOLD to DEPLOY by loosening the rubric. The honest-numbers contract (see root `CLAUDE.md`) is the product.

### FAIL

Reviewer flagged a structural issue:

- Registry mismatch (target model not in `shared/models-registry.json`).
- Stale technique (deprecated flag or API version).
- Format drift (tag names inconsistent across the prompt).

FAIL requires fixing the flagged issue and re-running. Does **not** get worked around.

## Engines

Six named engines, each with a formal derivation in [docs/science/README.md](science/README.md).

| ID | Name | Purpose |
|----|------|---------|
| E1 | Gauss Convergence | Iterative optimization — accept an iteration only if σ drops. |
| E2 | Boolean Satisfiability Overlay | The 8-assertion SAT gate layered on continuous scores. |
| E3 | Cross-Domain Adaptation | Constraint-preserving prompt translation across 64 models. |
| E4 | Adversarial Robustness | 12-attack harden suite, OWASP LLM Top 10 coverage. |
| E5 | Static-Dynamic Dual Verification | Structure scoring + real-output assertion testing. |
| E6 | Gauss Accumulation | Cross-session learning — `learnings.md` compounding over time. |

## Agent tiers

| Tier | Model | Role |
|------|-------|------|
| Orchestrator | Opus | Judgment, intent, technique selection. Used by the crafter and refiner. |
| Executor | Sonnet | Convergence loop, adversarial attacks, format conversion, test execution. |
| Validator | Haiku | Shape checks, freshness audits, registry consistency. |

Routing tasks across tiers is a cost / quality contract, not a style preference. A Haiku job on Opus burns budget; an Opus job on Haiku misses judgment calls.

## Format dialects

Wixie emits prompts in one of four shapes depending on the target model family:

- **XML** — Claude (any tier). `<role>`, `<task>`, `<context>`, `<constraints>`, `<format>`, `<examples>`, `<edge_cases>`.
- **Markdown with sandwich method** — GPT-4.x / 5. Instructions at the top and bottom; examples sandwiched in the middle (GPT attends less to the middle, so the bottom restatement is the recall anchor).
- **Stripped minimal** — o-series (o1, o3). No few-shot, no "think step by step", no role-play preamble. The model reasons internally at length; external CoT hurts.
- **Always-few-shot** — Gemini. 2-5 demonstrations baseline; zero-shot recall is measurably weaker.

The full rationale lives in [../foundations/packages/skills/conduct/formatting.md](../../foundations/packages/skills/conduct/formatting.md).

## `learnings.md`

Per-prompt cross-session memory. Each iteration logs a hypothesis (which axis to lift) and the outcome (score delta, failure code). Subsequent sessions read the log before picking a new axis — E6 accumulation means the engine gets smarter with use, not just the current session.

Failure codes (F01–F14) are defined in [../foundations/packages/core/conduct/failure-modes.md](../../foundations/packages/core/conduct/failure-modes.md).

## See also

- [README.md](../README.md) — what Wixie does end-to-end.
- [docs/getting-started.md](getting-started.md) — 5-minute first run.
- [docs/science/README.md](science/README.md) — the formal model for every term above.
- [docs/architecture/](architecture/) — auto-generated pipeline diagram.
