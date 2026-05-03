# Wixie — Agent Contract

Audience: Claude. Wixie engineers prompts — crafts, converges, tests, hardens, translates — via a managed Opus/Sonnet/Haiku network across 64 target models.

## Shared behavioral modules

These apply to every skill in every plugin. Load once; do not re-derive.

- @shared/conduct/discipline.md — coding conduct: think-first, simplicity, surgical edits, goal-driven loops
- @shared/conduct/context.md — attention-budget hygiene, U-curve placement, checkpoint protocol
- @shared/conduct/verification.md — independent checks, baseline snapshots, dry-run for destructive ops
- @shared/conduct/doubt-engine.md — adversarial self-check before agreement; counter to F01 sycophancy; fires on user proposals AND your own prior framing
- @shared/conduct/delegation.md — subagent contracts, tool whitelisting, parallel vs. serial rules
- @shared/conduct/failure-modes.md — 14-code taxonomy for `learnings.md` so E6 can aggregate
- @shared/conduct/tool-use.md — tool-choice hygiene, error payload contract, parallel-dispatch rules
- @shared/conduct/formatting.md — per-target format (XML/Markdown/minimal/few-shot), prefill + stop sequences
- @shared/conduct/skill-authoring.md — SKILL.md frontmatter discipline, discovery test
- @shared/conduct/hooks.md — advisory-only hooks, injection over denial, fail-open
- @shared/conduct/precedent.md — log self-observed failures to `state/precedent-log.md`; consult before risky steps
- @shared/conduct/tier-sizing.md — prompt verbosity scales inversely with model tier; Haiku needs mechanical steps, Opus runs on intent
- @shared/conduct/web-fetch.md — external URL handling: cache, dedup, budget; WebFetch is Haiku-tier-only
- @shared/conduct/inference-substrate.md — cross-session evidence accumulation; emit to and read from the inference-engine substrate without corrupting its honest-numbers contract

When a module conflicts with a plugin-local instruction, the plugin wins — but log the override.

## Lifecycle

Wixie is skill-invoked, not hook-driven. The single hook is advisory (prompt-save notification). Each skill hands artifacts to the next.

| Stage | Skill | Agent tier | Artifact produced |
|-------|-------|-----------|-------------------|
| Research | `/deep-research` (also auto-fires inside `/create`) | Opus decomposer/synth + Sonnet triangulator + Haiku fetchers/validator | `state/briefs/<slug>/{claims.json, sources.jsonl, trace.json}` |
| Craft | `/create` | Opus orchestrator + Haiku reviewer | `prompt.*`, `metadata.json` |
| Refine | `/refine` | Opus orchestrator + Haiku reviewer | `prompt.*` (v++), `metadata.json` |
| Converge | `/converge` | Sonnet optimizer + Haiku reviewer | `learnings.md`, updated scores |
| Test | `/test-prompt` | Sonnet executor | `tests.json`, pass/fail |
| Harden | `/harden` | Sonnet red-team | `audit.json` (12 attacks) |
| Translate | `/translate-prompt --to <model>` | Sonnet adapter | `prompt.<new>`, score comparison |

## Engines

E0 Deep Research (factual ground truth) · E1 Gauss Convergence · E2 Boolean Satisfiability Overlay · E3 Cross-Domain Adaptation · E4 Adversarial Robustness · E5 Static-Dynamic Dual Verification · E6 Gauss Accumulation (self-learning). Derivations: `docs/science/README.md`.

E0 auto-fires inside `/create` (and `/refine`) when the topic depends on external or time-sensitive facts, producing a verified cited brief that the crafter folds into the prompt's `<context>`. Standalone entry: `/deep-research <topic>`. Briefs are reused across skills when `freshness < 30 days`.

## DEPLOY bar

| Verdict | Criteria | Action |
|---------|----------|--------|
| DEPLOY | σ < 0.45 **and** overall ≥ 9.0 **and** all 5 axes ≥ 7.0 **and** 8/8 SAT assertions pass | Ship. Save artifacts. |
| HOLD | σ ≥ 0.45 or any axis < 7.0 | Re-run `/converge`. Do not hand back weak prompts. |
| FAIL | Reviewer flags registry mismatch / stale technique / format drift | Fix the flagged issue, then retry. |

σ = standard deviation of the 5 axis scores from 10. 8 SAT assertions: `has_role`, `has_task`, `has_format`, `has_constraints`, `has_edge_cases`, `no_hedges`, `no_filler`, `has_structure`.

## Behavioral contracts

1. **IMPORTANT — Check `shared/models-registry.json` before generating.** If the developer picked a model that mismatches the task domain (Claude for pure image gen, Gemini without examples, o-series with long CoT, etc.), warn with a better alternative **before** spending tokens.
2. **Format follows model.** XML for Claude, Markdown + sandwich method for GPT, stripped minimal for o-series, always-few-shot for Gemini. Do not ship a Claude-format prompt to a non-Claude target without `/translate-prompt`.
3. **YOU MUST respect the no-regression contract.** When `/converge` auto-reverts an iteration, log the failed hypothesis to `learnings.md` and pick a different axis. Do not override.
4. **YOU MUST NOT inflate scores.** The honest-numbers contract is the product. If 7/8 assertions pass, the verdict is HOLD, not DEPLOY — regardless of overall score.
5. **Ask, don't guess.** If a metadata field is unknown, ask the developer or run the engine. Never fabricate scores, costs, or technique lists.
6. **ESCALATE on image prompts.** DALL-E, Midjourney, SD, Wixie, Nano Banana, etc. are collaborative — wait for the developer's 1–10 rating and visual feedback each round. After 5+ rounds without progress, recommend a different image model.
7. **ESCALATE on unknown target model.** If the target model ID is not in `shared/models-registry.json`, stop and ask. The registry is the capability source of truth.
8. **Offer commit + push after registry or shared-artifact edits.** Whenever you edit `shared/models-registry.json`, a `shared/conduct/*.md` module, or anything a downstream plugin reads as source-of-truth, end the turn by asking whether to commit and push — don't wait for the developer to remember. State the change in one line ("registry bumped to N models, last_updated YYYY-MM-DD") and wait for yes before running git.

## Artifacts per prompt

```
prompts/<name>/
├── prompt.<ext>       production prompt, format matches target model
├── metadata.json      model, tokens, cost, 5-axis scores, 8 assertions, version
├── tests.json         regression test cases (≥ 3, ≥ 1 edge-case)
├── report.pdf         dark-themed single-page audit (final only)
└── learnings.md       E6 hypothesis/outcome log — persists across sessions
```

**Folder hygiene.** Intermediate HTML / diffs / scratch live in the plugin's `state/` dir. Only the final PDF stays in `prompts/<name>/`. The prompt folder is a handoff surface, not a work-in-progress.

## Agent tiers

| Tier | Model | Used for |
|------|-------|----------|
| Orchestrator | Opus | Judgment, intent, technique selection (crafter, refiner) |
| Executor | Sonnet | Convergence loop, adversarial attacks, format conversion, test execution |
| Validator | Haiku | Quality gate — file completeness, metadata consistency, score freshness |

Respect the tiering. Routing a Haiku validation task to Opus burns budget and breaks the cost contract.

## Anti-patterns

- **Claude-to-GPT copy.** Dropping a Claude-formatted prompt into a GPT folder. GPT needs sandwich method and different emphasis conventions — run `/translate-prompt`.
- **Scratch in prompts/.** Leaving HTML, diff, or iteration artifacts in the prompt folder. They belong in `state/`; only `report.pdf` ships.
- **Unverified translation.** Handing back a translated prompt without a score comparison. Translation without verification is not translation.
- **Autonomous image loops.** Iterating an image prompt without visual feedback. Text prompts converge on assertions; image prompts converge on developer ratings.
- **DEPLOY claim with stale metadata.** Verdict comes from the current convergence run's scores, not `metadata.json` from a prior session. Re-run self-eval if unsure.
