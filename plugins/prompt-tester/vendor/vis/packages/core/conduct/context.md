# Context — Attention Budget Hygiene

Audience: any LLM agent. How to spend the context window so recall stays sharp across long iterative loops and multi-stage workflows.

## The problem

LLM effective recall is not uniform across the window. Middle-of-context recall drops 30%+ on long inputs (context rot). Every byte you paste costs attention on every other byte. A 1M-token window is not a license to fill it.

## U-curve placement

Instructions the agent must obey go in the **first ~200 tokens** or the **last ~200 tokens** of the request. The middle is a recall valley.

| Slot | Put here |
|------|----------|
| First 200 tok | Role, task, hard constraints, output format |
| Middle | Reference material, examples, excerpts |
| Last 200 tok | Reminders of the hard constraints, stop conditions |

Anything important that appears *only* in the middle has a measurably lower chance of being respected.

## Smallest-set rule

1. **Cite line ranges, not whole files.** Use `Read` (or equivalent) with `offset` and `limit`. A 40KB file dump to answer a 5-line question wastes 39KB of attention.
2. **Excerpt, don't attach.** When referencing a doc, paste the 400-token snippet you actually need. Full attachment is rare and deliberate.
3. **Never inline what the model already knows.** No `package.json` schema lessons, no "HTTP status codes are…". Reference, don't teach.
4. **Collapse repeated structures.** If ten test cases follow the same shape, show two and say "...8 more of the same shape."

## Delegate bulky reads

Subagents protect the parent context. Use them when the raw material is large but the answer is small.

| Task | Runs where | Why |
|------|-----------|-----|
| Scanning 50 log files for one error | Subagent | Parent only needs the verdict |
| Grepping a 10k-file repo for symbol use | Subagent | Parent only needs the matches |
| Running a test suite and triaging failures | Subagent | Parent only needs the failure summary |
| Reading three specific files you already identified | Parent | No point delegating |

Subagent prompts always end with a **structured return clause** — see [`./delegation.md`](./delegation.md).

## The checkpoint protocol

At ~50% of context budget, emit a checkpoint and drop prior turns:

```
<checkpoint>
goal: <one line>
decisions: <bulleted>
open-questions: <bulleted>
next-step: <one line>
</checkpoint>
```

After the checkpoint, continue the conversation treating the checkpoint as the source of truth. Do not re-derive from earlier turns — they're noise now.

## Stale-context detection

Memory and prior-session summaries decay. Before acting on a recalled fact:

1. **If the memory names a path** — verify the file exists.
2. **If the memory names a function or flag** — grep for it.
3. **If the user is about to act on your recommendation** — verify the fact is still current.

A memory saying "X exists" is a claim about when the memory was written, not about now.

For working-memory accumulation across long sessions — when observations are piling up across turns rather than within a single prompt — see [`./memory-hygiene.md`](./memory-hygiene.md). The two modules are complementary: `context.md` governs what enters the prompt window; `memory-hygiene.md` governs what the agent decides to carry forward as accumulated state.

## Anti-patterns

- **Shotgun `Read` at session start.** Reading ten files "in case they're relevant" — pick the one or two that actually are.
- **Paste-the-whole-log debugging.** Filter first: grep for the error, show 20 lines of surrounding context, not 10k lines.
- **Re-quoting the prompt.** Restating the user's request in your reply burns tokens and signals nothing.
- **Stacking instructions mid-context.** Adding a new rule in turn 8 means it lives in the recall valley. Surface it up or it will be ignored.
- **Treating 1M like 1M.** Budget like it's 50k; you get better answers and lower cost.

## Success signal

A well-managed context has:
- Top of window → concrete, current task definition.
- Middle → the specific excerpts you're reasoning over.
- Recent turns → small, high-signal, no re-reads of the same file.
- Bottom → the constraint you must not violate.

If you can't describe the top, middle, and bottom of your current context in one line each, the context is too noisy to trust.
