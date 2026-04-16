# Flux — What You Need To Know

You have Flux installed. It engineers prompts — crafts, converges, tests, hardens, and translates across 64 models — via a coordinated agent network.

## What's happening behind the scenes

Flux is not a single hook chain; it's a pipeline invoked by slash commands. Each stage hands artifacts to the next:

1. **prompt-crafter** (`/create`) — Opus orchestrator scans context, asks clarifying questions, selects techniques from the 64-model registry, generates `prompt.xml` + `metadata.json`
2. **convergence-engine** (`/converge`) — Sonnet optimizer runs the Gauss Convergence Method, up to 100 hypothesis-driven iterations, auto-reverts regressions
3. **prompt-tester** (`/test-prompt`) — Sonnet executor runs binary assertions against real model output
4. **prompt-harden** (`/harden`) — Sonnet red-team runs 12 adversarial attack patterns, suggests defenses
5. **prompt-translate** (`/translate-prompt`) — Sonnet adapter rewrites the prompt for a target model, preserving semantics
6. **prompt-refiner** (`/refine`) — Opus re-enters the loop on an existing prompt

Every stage writes back to `prompts/<name>/` and appends to `learnings.md` (A6 — Gauss Accumulation) so the engine gets smarter across sessions.

## Target bar — what "DEPLOY" means

| Verdict | Criteria | Your action |
|---------|----------|-------------|
| DEPLOY | σ < 0.45, overall ≥ 9.0, all axes ≥ 7.0, 8/8 assertions pass | Ship it. Save artifacts. |
| HOLD | σ ≥ 0.45 or axis < 7.0 | Re-run `/converge` — don't hand back a weak prompt |
| FAIL | Reviewer flags registry mismatch, stale technique, or format drift | Fix the flagged issue before retrying |

σ is the Gauss deviation from perfection across 5 axes. The 8 binary assertions are SAT-first: `has_role`, `has_task`, `has_format`, `has_constraints`, `has_edge_cases`, `no_hedges`, `no_filler`, `has_structure`.

## What you MUST do

1. **Before generating any prompt**: Check the 64-model registry in `shared/models-registry.json`. If the developer picked a model that mismatches the task domain (e.g. Claude for pure image gen, Gemini without examples, o-series with long CoT instructions), warn them with a better alternative before spending tokens.

2. **Format follows model**: XML for Claude, Markdown + sandwich method for GPT, stripped minimal for o-series, always-few-shot for Gemini. Don't ship a Claude-style prompt to GPT without running `/translate-prompt`.

3. **When `/converge` reports a regression**: Do not override the auto-revert. The engine's contract is "no regression allowed" — revert is correct. Log the failed hypothesis to `learnings.md` and try a different axis.

4. **When writing convergence artifacts**: Intermediate HTML / diff / scratch files go in the plugin's `state/` dir. Only the final PDF stays in `prompts/<name>/report.pdf`. Prompt folder should be clean.

5. **When the developer asks "is this prompt safe"**: Run `/harden` — don't eyeball it. The 12 attack patterns cover OWASP LLM Top 10. Report VULNERABLE/RESISTANT per attack, not a vague verdict.

6. **When translating between models**: Preserve semantics, strip anti-patterns of the target model, add few-shot if the target needs it. Attach a score comparison to the output — translation without verification is not translation.

7. **Image prompts are collaborative, not autonomous**: For DALL-E, Midjourney, SD, Flux, Nano Banana, etc., don't loop blindly. Wait for the developer's 1-10 rating and visual feedback each round. After 5+ rounds without progress, suggest trying a different image model.

## Commands the developer can use

- `/create` — generate a production-ready prompt from an intent
- `/refine` — improve an existing prompt (re-enters convergence)
- `/converge` — run the 100-iteration Gauss Convergence optimizer
- `/test-prompt` — run binary assertions against real model output
- `/harden` — 12 adversarial attacks + defense suggestions
- `/translate-prompt --to <model>` — port the prompt to a different model

## What you get per prompt

```
prompts/<name>/
├── prompt.xml        Production prompt (format matches target model)
├── metadata.json     Model, tokens, cost, 5-axis scores, 8 assertions
├── tests.json        Regression test cases
├── report.pdf        Dark-themed single-page PDF audit
└── learnings.md      Hypothesis/outcome log (A6 — Gauss Accumulation)
```

Developer conventions for this directory:
- **Never fabricate metadata fields** — if you don't know the score, ask or run the engine. Ask, don't guess.
- **PDF lives with the prompt; HTML lives in state** — the prompt folder stays clean for handoff.

## Agent tiers

| Agent | Model | Plugin | Role |
|-------|-------|--------|------|
| orchestrator | Opus | prompt-crafter, prompt-refiner | Judgment, intent, technique selection |
| optimizer | Sonnet | convergence-engine | 100-iteration loop, hypothesis/revert |
| executor | Sonnet | prompt-tester | Runs assertions against real output |
| red-team | Sonnet | prompt-harden | 12 attack patterns |
| adapter | Sonnet | prompt-translate | Cross-model rewrite |
| reviewer | Haiku | crafter, refiner | Validation, freshness, format, registry cross-ref |

Respect the tiering. Don't route a Haiku validation task to Opus "just to be safe" — it burns budget and breaks the contract.

## What NOT to do

- Don't ship a prompt without running `/converge` to DEPLOY — unverified prompts aren't Flux output
- Don't write intermediate HTML or scratch files into `prompts/<name>/` — those belong in plugin state dirs
- Don't bypass the auto-revert when convergence regresses — the contract is no-regression
- Don't guess at model capabilities — read `shared/models-registry.json`
- Don't copy a Claude-format prompt into a GPT folder without `/translate-prompt`
- Don't inflate scores in reports or claim DEPLOY when assertions fail — the honest-numbers contract is the product
- Don't loop image prompts autonomously — they require the developer's visual feedback
