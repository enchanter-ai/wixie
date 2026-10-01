# Tier Sizing — Prompt Verbosity Scales Inversely with Model Tier

Audience: any author writing agent prompts that target a specific model tier. How much detail an agent prompt needs, by the tier of the model that will run it. A low-tier prompt written at high-tier density is a silent quality loss.

## The principle

- **Top tier** (e.g., Opus, GPT-5, Gemini 2.5 Pro) runs on *intent*. Give it the goal, constraints, output shape; trust it to pick the method.
- **Mid tier** (e.g., Sonnet, GPT-4o, Gemini 2.5 Flash) runs on *decomposition*. Give it the goal plus the cross-unit passes it should run.
- **Low tier** (e.g., Haiku, GPT-4o-mini, Gemini 2.5 Flash-Lite) runs on *mechanical steps*. Decompose every judgment into a boolean test.

Writing the same prompt for all three is a correctness bug on the lower tiers. Low-tier models don't bridge gaps — they follow what's written, literally. Mid-tier bridges shallow gaps but silently picks a decomposition that may not be yours. Top-tier bridges deep gaps but burns budget when you over-specify.

> *"Extract facts relevant to the sub-question"* — fine for top tier, vague for mid, broken for low.

## The rubric

| Tier | Prompt density | What must be explicit |
|------|----------------|------------------------|
| **Top** | Intent-level | Goal, hard constraints, output shape. Nothing more — let the model pick the method. |
| **Mid** | Decomposed | Goal + the specific passes in order (e.g., "merge duplicates, then check independence, then detect contradictions"). Each pass is stated, but not further decomposed. |
| **Low** | Senior-to-junior | Each judgment split into yes/no tests. No step reads "appropriately", "relevant", "carefully". Stop conditions are explicit. |

A good heuristic: if a new junior engineer could execute the prompt without asking questions, it's low-tier-ready. If they need to infer intent, it's mid-tier-ready. If they have to reason about the whole task, it's top-tier-ready.

## The senior-to-junior checklist (low-tier)

Every low-tier prompt passes these:

1. **No adverbs of judgment.** "Relevant", "appropriate", "clearly", "carefully", "reasonably" must be replaced by a test.
2. **Each step has a stop condition.** "Read the page" → "Read the top 2–3 main paragraphs; stop at the first heading whose text doesn't match the sub-question."
3. **Tests are boolean, not gradient.** Not "is this a good source" but "is `source_type` one of `{official, paper}`?".
4. **Format is literal.** Not "return JSON" but "return ONLY this JSON shape, no preamble, no markdown fences, no trailing text".
5. **Failure paths are enumerated.** Not "handle errors gracefully" but "if paywalled → return `{error: 'unfetchable'}`; if 404 → return `{error: 'not_found'}`".
6. **Length bounds are numeric.** "Under 400 words", not "concise". "≤ 200 chars", not "brief".
7. **Forbidden behaviors are named.** "Do NOT spawn sub-subagents", "Do NOT invent a date if absent", "NEVER paraphrase in the `quote` field".
8. **Explanatory math and theory prose are not instructions.** If a formula, algorithm derivation, or background paragraph appears, the low-tier model treats it as noise that competes with the actual steps. Strip it — or move it into a `## Why` section at the bottom that the agent is told to ignore. The *instruction* is the bash command, the decision table, the boolean test — not the math that motivates them.

## Density, measured

Rough target sizes for a well-written agent prompt (body only, excluding frontmatter + failure modes + anti-patterns tables):

| Tier | Prompt body | Total file |
|------|-------------|------------|
| Top | 200–400 tokens of instruction | 400–700 tokens |
| Mid | 400–700 tokens | 700–1200 tokens |
| Low | 700–1200 tokens | 1200–1800 tokens |

Under-sizing produces wrong outputs silently. Over-sizing produces bloat, slower reads, and — for top tier specifically — signals distrust that can degrade the reasoning.

Tier selection reduces cost per token; [`./cost-accounting.md`](./cost-accounting.md) covers the session-wide budget ceiling. Both levers are required: choosing the correct tier without a spawn or tool-call cap leaves the total session cost unconstrained.

## Examples

### Bad (low-tier prompt at top-tier density)

> *"Extract only facts relevant to the sub-question. Skip adjacent topics. Return structured findings."*

Three sentences, three ambiguous words ("relevant", "adjacent", "structured"). A low-tier run will produce variable output across inputs.

### Good (low-tier senior-to-junior)

> For each paragraph of the fetched page:
> 1. **Topic test.** Does the paragraph contain at least one noun from `<sub_question>` (exact word or obvious synonym)? If no → skip.
> 2. **Claim test.** Does the paragraph state a specific claim (subject does/is/has object), or does it just describe a category / mention the topic in passing? If just category/passing → skip.
> 3. **Quote test.** Pick ONE sentence ≤ 200 chars that states the claim. Must be copy-paste-able verbatim. If no sentence fits → skip.
> 4. Record `{claim: <your paraphrase>, quote: <copy-pasted sentence>}`.
> Do NOT fabricate claims from context. If the paragraph is promotional fluff with no fact, skip.

### Bad (mid-tier prompt at top-tier density)

> *"Merge the claims appropriately and compute a score."*

### Good (mid-tier decomposed)

> 1. Extract every distinct claim across all sources. Merge near-duplicates into one claim.
> 2. For each claim, list supporting source IDs.
> 3. Check independence — same-vendor repeats count as one; transitive cites (A quotes B, both listed) count as one.
> 4. Detect contradictions between claims.
> 5. Compute `τ = |independent ≥ 2| / |claims|`.

Mid tier gets the sequence of passes; it doesn't need each pass broken into mechanical tests.

## When to violate

Tighten below the guideline only when you've load-tested the target agent. A low-tier agent shipped with a 500-token prompt should be verified on an ambiguous input before being called load-bearing. Over-sizing is safer than under-sizing — but keep an eye on high-frequency paths.

## Anti-patterns

- **Copy-paste a top-tier prompt to a low-tier agent.** Silent quality degradation.
- **"Just follow the plan" on a low-tier agent.** Low-tier doesn't bridge gaps; spec the plan step-by-step.
- **Vague failure modes on a low-tier prompt.** "Handle errors" — low-tier doesn't know which errors. List them.
- **Mixing algorithm exposition with instructions.** LaTeX formulas, "the intuition is…", derivation paragraphs — if the actual work is bash/awk/lookup-table, the math is context that low-tier can't distinguish from steps. Put the *command*, not the *derivation*. If the math must appear, isolate it in a `## Why` section marked as background.
- **Mid-tier prompt with top-tier-level abstract goals and no decomposition.** Mid tier will pick a decomposition; it may not be yours.
- **Running a mid-tier-sized task through low-tier "to save money".** It won't save, because the output will be wrong or partial and you'll retry.
- **Running a low-tier-sized task through top-tier "for safety".** Top-tier will do fine but at 10× the cost; pick the right tier.
- **Token-padding a top-tier prompt** with decomposition it doesn't need. Signals distrust; reasoning can degrade.
