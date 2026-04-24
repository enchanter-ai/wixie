# Tier Sizing — Prompt Verbosity Scales Inversely with Model Tier

Audience: Claude. How much detail an agent prompt needs, by the tier of the model that will run it. A Haiku prompt written at Opus density is a silent quality loss.

## The principle

- **Opus** runs on *intent*. Give it the goal, constraints, output shape; trust it to pick the method.
- **Sonnet** runs on *decomposition*. Give it the goal plus the cross-unit passes it should run.
- **Haiku** runs on *mechanical steps*. Decompose every judgment into a boolean test.

Writing the same prompt for all three is a correctness bug on the lower tiers. Haiku doesn't bridge gaps — it follows what's written, literally. Sonnet bridges shallow gaps but silently picks a decomposition that may not be yours. Opus bridges deep gaps but burns budget when you over-specify.

> *"Extract facts relevant to the sub-question"* — fine for Opus, vague for Sonnet, broken for Haiku.

## The rubric

| Tier | Prompt density | What must be explicit |
|------|----------------|------------------------|
| **Opus** | Intent-level | Goal, hard constraints, output shape. Nothing more — let Opus pick the method. |
| **Sonnet** | Decomposed | Goal + the specific passes in order (e.g., "merge duplicates, then check independence, then detect contradictions"). Each pass is stated, but not further decomposed. |
| **Haiku** | Senior-to-junior | Each judgment split into yes/no tests. No step reads "appropriately", "relevant", "carefully". Stop conditions are explicit. |

A good heuristic: if a new junior engineer could execute the prompt without asking questions, it's Haiku-ready. If they need to infer intent, it's Sonnet-ready. If they have to reason about the whole task, it's Opus-ready.

## The senior-to-junior checklist (Haiku)

Every Haiku prompt passes these:

1. **No adverbs of judgment.** "Relevant", "appropriate", "clearly", "carefully", "reasonably" must be replaced by a test.
2. **Each step has a stop condition.** "Read the page" → "Read the top 2–3 main paragraphs; stop at the first heading whose text doesn't match the sub-question."
3. **Tests are boolean, not gradient.** Not "is this a good source" but "is `source_type` one of `{official, paper}`?".
4. **Format is literal.** Not "return JSON" but "return ONLY this JSON shape, no preamble, no markdown fences, no trailing text".
5. **Failure paths are enumerated.** Not "handle errors gracefully" but "if paywalled → return `{error: 'unfetchable'}`; if 404 → return `{error: 'not_found'}`".
6. **Length bounds are numeric.** "Under 400 words", not "concise". "≤ 200 chars", not "brief".
7. **Forbidden behaviors are named.** "Do NOT spawn sub-subagents", "Do NOT invent a date if absent", "NEVER paraphrase in the `quote` field".
8. **Explanatory math and theory prose are not instructions.** If a formula, algorithm derivation, or background paragraph appears, Haiku treats it as noise that competes with the actual steps. Strip it — or move it into a `## Why` section at the bottom that the agent is told to ignore. The *instruction* is the bash command, the decision table, the boolean test — not the math that motivates them.

## Density, measured

Rough target sizes for a well-written agent prompt (body only, excluding frontmatter + failure modes + anti-patterns tables):

| Tier | Prompt body | Total file |
|------|-------------|------------|
| Opus | 200–400 tokens of instruction | 400–700 tokens |
| Sonnet | 400–700 tokens | 700–1200 tokens |
| Haiku | 700–1200 tokens | 1200–1800 tokens |

Under-sizing produces wrong outputs silently. Over-sizing produces bloat, slower reads, and — for Opus specifically — signals distrust that can degrade the reasoning.

## Examples

### Bad (Haiku prompt at Opus density)

> *"Extract only facts relevant to the sub-question. Skip adjacent topics. Return structured findings."*

Three sentences, three ambiguous words ("relevant", "adjacent", "structured"). A Haiku run will produce variable output across inputs.

### Good (Haiku senior-to-junior)

> For each paragraph of the fetched page:
> 1. **Topic test.** Does the paragraph contain at least one noun from `<sub_question>` (exact word or obvious synonym)? If no → skip.
> 2. **Claim test.** Does the paragraph state a specific claim (subject does/is/has object), or does it just describe a category / mention the topic in passing? If just category/passing → skip.
> 3. **Quote test.** Pick ONE sentence ≤ 200 chars that states the claim. Must be copy-paste-able verbatim. If no sentence fits → skip.
> 4. Record `{claim: <your paraphrase>, quote: <copy-pasted sentence>}`.
> Do NOT fabricate claims from context. If the paragraph is promotional fluff with no fact, skip.

### Bad (Sonnet prompt at Opus density)

> *"Merge the claims appropriately and compute a score."*

### Good (Sonnet decomposed)

> 1. Extract every distinct claim across all sources. Merge near-duplicates into one claim.
> 2. For each claim, list supporting source IDs.
> 3. Check independence — same-vendor repeats count as one; transitive cites (A quotes B, both listed) count as one.
> 4. Detect contradictions between claims.
> 5. Compute `τ = |independent ≥ 2| / |claims|`.

Sonnet gets the sequence of passes; it doesn't need each pass broken into mechanical tests.

## When to violate

Tighten below the guideline only when you've load-tested the target agent. A Haiku agent shipped with a 500-token prompt should be verified on an ambiguous input before being called load-bearing. Over-sizing is safer than under-sizing — but keep an eye on high-frequency paths.

## Anti-patterns

- **Copy-paste an Opus prompt to a Haiku agent.** Silent quality degradation.
- **"Just follow the plan" on a Haiku agent.** Haiku doesn't bridge gaps; spec the plan step-by-step.
- **Vague failure modes on a Haiku prompt.** "Handle errors" — Haiku doesn't know which errors. List them.
- **Mixing algorithm exposition with instructions.** LaTeX formulas, "the intuition is…", derivation paragraphs — if the actual work is bash/awk/lookup-table, the math is context that Haiku can't distinguish from steps. Put the *command*, not the *derivation*. If the math must appear, isolate it in a `## Why` section marked as background.
- **Sonnet prompt with Opus-level abstract goals and no decomposition.** Sonnet will pick a decomposition; it may not be yours.
- **Running a Sonnet-sized task through Haiku "to save money".** It won't save, because the output will be wrong or partial and you'll retry.
- **Running a Haiku-sized task through Opus "for safety".** Opus will do fine but at 10× the cost; pick the right tier.
- **Token-padding an Opus prompt** with decomposition it doesn't need. Signals distrust; reasoning can degrade.
