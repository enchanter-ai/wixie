# Getting started with Flux

Flux is prompt engineering for engineers who would rather ship than iterate by hand. This page gets you from zero to a scored, DEPLOY-verdict prompt in under 5 minutes.

## 1. Install (60 seconds)

```
/plugin marketplace add enchanted-plugins/flux
/plugin install full@flux
/plugin list
```

You should see six plugins: `prompt-crafter`, `prompt-refiner`, `convergence-engine`, `prompt-tester`, `prompt-harden`, `prompt-translate`. If any are missing, see [installation.md](installation.md).

## 2. Craft a prompt (2 minutes)

```
/create B2B ticket routing system like Zendesk, for Claude Opus
```

Flux will:

1. Research adjacent tools (Zendesk, Freshdesk, Intercom…).
2. Select 3 techniques from its 16-technique library based on the task domain.
3. Generate the prompt in the format native to the target model — XML for Claude, Markdown-sandwich for GPT, minimal for o-series, always-few-shot for Gemini.
4. Write `prompts/b2b-ticket-router/` with `prompt.xml` + `metadata.json`.

Inspect the artifacts:

```bash
ls prompts/b2b-ticket-router/
# prompt.xml   metadata.json
```

## 3. Converge to DEPLOY (60 seconds)

```
/converge prompts/b2b-ticket-router
```

The convergence engine scores on 5 axes + 8 binary assertions, forms a hypothesis about which axis to lift, applies the fix, re-scores, and auto-reverts if the overall score drops.

Stops when one of:

- **DEPLOY** — σ < 0.45 AND overall ≥ 9.0 AND every axis ≥ 7.0 AND 8/8 assertions pass.
- **HOLD** — hit a plateau; see `learnings.md` for what was tried.
- **FAIL** — reviewer flagged a registry or format issue.

You should see DEPLOY within 2-4 iterations.

## 4. Add tests (optional)

```
/test-prompt prompts/b2b-ticket-router
```

Writes `tests.json` with ≥ 3 regression cases including at least one edge case, runs them against the prompt, and reports pass/fail.

## 5. Harden (optional)

```
/harden prompts/b2b-ticket-router
```

Runs 12 adversarial attack patterns (prompt injection, role override, data extraction, encoding bypass, multi-turn escalation, …). Emits `audit.json` with VULNERABLE / RESISTANT per attack and suggested defenses.

## 6. Translate to another model

```
/translate-prompt prompts/b2b-ticket-router --to gpt-4.1
```

Rewrites the prompt for the target model's preferred format. Emits a score comparison so you know the translation preserved intent.

## What you end up with

```
prompts/b2b-ticket-router/
├── prompt.xml          Production-ready prompt
├── metadata.json       Scores, model, tokens, cost
├── tests.json          Regression assertions
├── report.pdf          Dark-themed single-page audit
└── learnings.md        Convergence hypothesis log (persists across sessions)
```

## Next steps

- [Glossary](glossary.md) — axes, engines, SAT, σ, DEPLOY / HOLD / FAIL defined.
- [docs/science/README.md](science/README.md) — the math behind each engine, derived.
- [docs/architecture/](architecture/) — auto-generated diagram of the pipeline.
- [README.md](../README.md) § vs Everything Else — honest comparison table.

Broken first run? → [troubleshooting.md](troubleshooting.md).
