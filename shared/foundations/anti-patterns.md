# Anti-Patterns — A Cross-Cutting Catalog

Audience: anyone scanning for "what not to do" before they do it. Aggregates the anti-patterns called out across [`conduct/`](conduct/), [`engines/`](engines/), and [`taxonomy/`](taxonomy/) into one greppable surface.

This is **not the source of truth** — each pattern's home module is. But when you want to spot-check a design before shipping, this is the doc.

## Behavioral

- **"Let me also improve…"** — unsolicited scope expansion. ([discipline.md](conduct/discipline.md))
- **Defensive `try/except` on trusted internal calls** — validate at the boundary; trust inside. ([discipline.md](conduct/discipline.md))
- **Comments that restate the code** — `# increment counter` above `counter += 1`. ([discipline.md](conduct/discipline.md))
- **Renaming on the way through** — if the task isn't a rename, don't. ([discipline.md](conduct/discipline.md))
- **"For future flexibility"** — dead weight until the future arrives. ([discipline.md](conduct/discipline.md))
- **Going along with a flawed user proposal** — F01 sycophancy. ([f01-sycophancy.md](taxonomy/f01-sycophancy.md))

## Context

- **Shotgun `Read` at session start** — reading ten files "in case." ([context.md](conduct/context.md))
- **Paste-the-whole-log debugging** — filter first. ([context.md](conduct/context.md))
- **Re-quoting the prompt** — restating burns tokens, signals nothing. ([context.md](conduct/context.md))
- **Stacking instructions mid-context** — load-bearing rules belong top-200 or bottom-200. ([context.md](conduct/context.md))
- **Treating 1M like 1M** — budget like 50k. ([context.md](conduct/context.md))

## Verification

- **"Tests passed locally" without showing output** — show it or it didn't happen. ([verification.md](conduct/verification.md))
- **Reading the code you just wrote to decide if it's correct** — that's self-certification. ([verification.md](conduct/verification.md))
- **Skipping the baseline** — now you can't distinguish your regression from pre-existing. ([verification.md](conduct/verification.md))
- **Treating an advisory hook as a blocker you work around** — fix the underlying issue. ([verification.md](conduct/verification.md))
- **`--no-verify` / `--no-gpg-sign` bypass flags** — never, unless explicitly asked. ([verification.md](conduct/verification.md))

## Delegation

- **Delegating a task you could do in one tool call.** ([delegation.md](conduct/delegation.md))
- **Prompt that says "figure out what I need"** — subagent lacks context; brief it. ([delegation.md](conduct/delegation.md))
- **Parallel subagents with overlapping writes** — race, lost work. ([delegation.md](conduct/delegation.md))
- **Sub-subagents** — two-level delegation loses too much context. ([delegation.md](conduct/delegation.md))
- **Trusting "done" without reading the output.** ([delegation.md](conduct/delegation.md))
- **Subagent loop without termination clause.** ([delegation.md](conduct/delegation.md))

## Tools

- **Retry-with-tweaks on uninformative error** — diagnose first. ([tool-use.md](conduct/tool-use.md))
- **Parallel Writes to the same file** — race; one wins, one is lost silently. ([tool-use.md](conduct/tool-use.md))
- **Bash for what the dedicated tool does** — `cat` for read, `find` for glob. ([tool-use.md](conduct/tool-use.md))
- **Edit without a preceding Read.** ([tool-use.md](conduct/tool-use.md))
- **Unquoted paths with spaces** — intermittent failures. ([tool-use.md](conduct/tool-use.md))
- **Opaque handles in returns** — semantic IDs only. ([tool-use.md](conduct/tool-use.md))

## Formatting

- **Inconsistent tag names** — `<context>` once, `<background>` later. ([formatting.md](conduct/formatting.md))
- **XML in a GPT prompt without translating.** ([formatting.md](conduct/formatting.md))
- **Chain-of-thought in an o-series prompt** — double-reasoning. ([formatting.md](conduct/formatting.md))
- **No-prefill, then complaining about preamble.** ([formatting.md](conduct/formatting.md))
- **Bold on everything** — emphasis becomes noise. ([formatting.md](conduct/formatting.md))
- **Few-shot examples that don't match the real task shape.** ([formatting.md](conduct/formatting.md))

## Skill authoring

- **Description with only the what, no when** — never fires at the right moment. ([skill-authoring.md](conduct/skill-authoring.md))
- **First-person description.** ([skill-authoring.md](conduct/skill-authoring.md))
- **Bundled skill (multi-verb)** — selector can't disambiguate. ([skill-authoring.md](conduct/skill-authoring.md))
- **Over-broad tool whitelist.** ([skill-authoring.md](conduct/skill-authoring.md))
- **Body that explains *why* instead of *how*.** ([skill-authoring.md](conduct/skill-authoring.md))
- **Missing do-not-use clause on overlapping skills.** ([skill-authoring.md](conduct/skill-authoring.md))

## Hooks

- **Blocking hook masquerading as advisory** — exit non-zero to "warn." Use exit 0 + injection. ([hooks.md](conduct/hooks.md))
- **Hook that writes to stdout** — pollutes the conversation. ([hooks.md](conduct/hooks.md))
- **No matcher** — fires on every event. ([hooks.md](conduct/hooks.md))
- **Multiple parallel hooks for the same event** — order undefined. ([hooks.md](conduct/hooks.md))
- **Hook with side effects on the repo** — auto-commits, auto-renames. ([hooks.md](conduct/hooks.md))
- **Subagent-triggered loops** — no guard, infinite recursion. ([hooks.md](conduct/hooks.md))

## Precedent

- **Logging every first-try failure** — log becomes noise. ([precedent.md](conduct/precedent.md))
- **Never consulting the log** — diary, not a tool. ([precedent.md](conduct/precedent.md))
- **Paraphrasing the failing command** — breaks grep-ability. ([precedent.md](conduct/precedent.md))
- **Vague signal lines.** ([precedent.md](conduct/precedent.md))
- **Letting the log grow unbounded.** ([precedent.md](conduct/precedent.md))
- **Skipping the consult step "because I remember."** ([precedent.md](conduct/precedent.md))

## Tier sizing

- **Copy-paste a top-tier prompt to a low-tier agent** — silent quality degradation. ([tier-sizing.md](conduct/tier-sizing.md))
- **"Just follow the plan" on a low-tier agent** — spec the plan step-by-step. ([tier-sizing.md](conduct/tier-sizing.md))
- **Vague failure modes on a low-tier prompt.** ([tier-sizing.md](conduct/tier-sizing.md))
- **Mixing algorithm exposition with instructions.** ([tier-sizing.md](conduct/tier-sizing.md))
- **Mid-tier prompt with top-tier abstract goals and no decomposition.** ([tier-sizing.md](conduct/tier-sizing.md))
- **Running a mid-tier task through low-tier "to save money"** — won't save; you'll retry. ([tier-sizing.md](conduct/tier-sizing.md))
- **Running a low-tier task through top-tier "for safety"** — fine but at 10× cost. ([tier-sizing.md](conduct/tier-sizing.md))
- **Token-padding a top-tier prompt.** ([tier-sizing.md](conduct/tier-sizing.md))

## Web fetch

- **Default everything to low tier** — dense papers get shallow extracts. ([web-fetch.md](conduct/web-fetch.md))
- **Default everything to top tier** — easy pages cost 10× too much. ([web-fetch.md](conduct/web-fetch.md))
- **No cache at all.** ([web-fetch.md](conduct/web-fetch.md))
- **Quote that "captures the gist"** — copy-paste or omit. ([web-fetch.md](conduct/web-fetch.md))
- **Fetch-without-date** — downstream can't weight freshness. ([web-fetch.md](conduct/web-fetch.md))
- **Fetching when a local doc answers the question.** ([web-fetch.md](conduct/web-fetch.md))

## Failure logging

- **Untagged free-text entries** — not aggregable. ([failure-modes.md](conduct/failure-modes.md))
- **Logging the fix, not the failure.** ([failure-modes.md](conduct/failure-modes.md))
- **Multiple codes on one entry** — pick the dominant one. ([failure-modes.md](conduct/failure-modes.md))
- **Logging at verdict time only** — log hypothesis before, outcome after. ([failure-modes.md](conduct/failure-modes.md))
- **"Couldn't find a matching code"** — propose a new one (F22+) in a PR. ([failure-modes.md](conduct/failure-modes.md))

## Doubt engine

- **Agreeing then doubting** — doubt before yes, not after. ([doubt-engine.md](conduct/doubt-engine.md))
- **Doubt as preamble** — *"I want to push back here…"* with no actual pushback. ([doubt-engine.md](conduct/doubt-engine.md))
- **Hedging instead of disagreeing** — *"could possibly maybe perhaps"* — stand on the evidence or stand down. ([doubt-engine.md](conduct/doubt-engine.md))
- **Treating user proposals as exempt** — same doubt pass as your own ideas. ([doubt-engine.md](conduct/doubt-engine.md))
- **Skipping the pass under "just do it" license** — overrides clarifying questions, not safety pushback. ([doubt-engine.md](conduct/doubt-engine.md))
- **Outsourcing doubt to the next turn.** ([doubt-engine.md](conduct/doubt-engine.md))
- **Running the pass and hiding the result.** ([doubt-engine.md](conduct/doubt-engine.md))

## Engines

- **Patterns sharing common suffixes without transitive output links** — Aho-Corasick misses them. ([pattern-detection.md](engines/pattern-detection.md))
- **Treating posterior mean as ground truth without variance** — Beta-Bernoulli with few observations. ([trust-scoring.md](engines/trust-scoring.md))
- **Default unit cost on tree-edit when domain has weighted operations.** ([tree-edit.md](engines/tree-edit.md))
- **Choosing SPRT `(p₀, p₁)` post-hoc to match observed data** — invalidates the test. ([sprt.md](engines/sprt.md))
- **Idle-only segmentation in boundary detection** — multi-signal exists for a reason. ([boundary-segmentation.md](engines/boundary-segmentation.md))
- **Confusing simplified Wagner-Fischer with true Zhang-Shasha** — document which version you ship. ([tree-edit.md](engines/tree-edit.md))

## Conduct (recent additions)

- **All-Add as the default** — appending every observation to working memory without pruning, leading to self-degradation. ([memory-hygiene.md](conduct/memory-hygiene.md))
- **Spawn cap omitted from delegation prompts** — no per-subagent or session-wide token cap; total cost grows unbounded. ([cost-accounting.md](conduct/cost-accounting.md))
- **Speculative evals** — adding eval cases for hypothetical bugs that haven't been observed. ([eval-driven-self-improvement.md](conduct/eval-driven-self-improvement.md))
- **Sycophantic capitulation across turns** — flipping stance under sustained user pressure without new evidence. ([multi-turn-negotiation.md](conduct/multi-turn-negotiation.md))
- **Blanket topic refusals** — refusing benign requests adjacent to refused topics (false-refusal cycle). ([refusal-and-recovery.md](conduct/refusal-and-recovery.md))
- **Treating latency as a cost proxy** — assuming token cost and wall-clock latency move together; they don't. ([latency-budgeting.md](conduct/latency-budgeting.md))

## How to use this doc

- Before submitting work: scan the section for the kind of task you just did.
- During review: search this doc for the phrase that describes the smell you noticed.
- When extending the framework: a new pattern goes in its home module; update this aggregate.
