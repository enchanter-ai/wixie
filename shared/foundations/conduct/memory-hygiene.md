# Memory Hygiene — Working Memory Discipline Across Long Sessions

Audience: any LLM agent. How to manage the observations, intermediate results, and partial conclusions that accumulate in working memory during a long session, so recall stays accurate and the agent does not degrade under its own weight.

## The problem

Agent performance across long sessions degrades when working memory grows without discipline. The failure is not context-window overflow — it is **recall pollution**: new observations get weighted the same as old ones, superseded conclusions persist alongside their replacements, and the agent operates on a cluttered mental model it cannot distinguish from a clean one.

A 2025 study (arxiv 2505.16067) names the "All-Add" strategy — appending every observation to working memory unconditionally — as the dominant cause of this degradation. The problem is not that the agent forgets; it is that the agent *does not forget enough*. An agent that entered the session with a clean mental model exits it confused because everything it encountered is still present, competing for influence.

This is the cross-session complement to [`./context.md`](./context.md)'s within-session attention-budget rules. `context.md` governs what goes into the prompt; this module governs what the agent carries forward as accumulated state.

## Three memory strategies

| Strategy | Behavior | When to use | Risk |
|----------|----------|-------------|------|
| **All-Add** | Append every observation unconditionally | Never — this is the anti-pattern | Recall pollution, self-degradation over long sessions |
| **Selective-add** | Append only observations that pass a relevance gate | Default for most sessions | Requires a clear gate criterion; ambiguous observations leak through |
| **Checkpoint-and-prune** | At defined boundaries, summarize memory into a compact checkpoint; discard the raw entries | Long-horizon tasks crossing multiple goal boundaries | Prune must be disciplined; over-pruning discards needed context |

**Default to selective-add.** Apply checkpoint-and-prune at major goal-boundary crossings (see below). Never use All-Add as a standing strategy.

### The relevance gate (selective-add)

An observation passes the gate when **all three** hold:

1. It is directly about the current goal or a named sub-goal.
2. It is not already represented by a prior memory entry (dedup check).
3. It changes what the agent would do next — a redundant confirmation of a decided point fails this test.

An observation that passes only one or two tests is a candidate for the scratch pad (short-lived working state), not working memory.

## When to prune

Trigger a checkpoint-and-prune pass when **any** of these boolean conditions is true:

| Trigger | Test |
|---------|------|
| **Size** | Working memory exceeds 20 distinct entries (default; calibrate per workload) |
| **Relevance decay** | More than 40% of entries predate the most recent goal-boundary crossing |
| **Goal boundary** | The session transitions from one major goal to a successor goal (e.g., research → draft → review) |
| **Contradiction density** | Three or more entries directly contradict each other with no resolution logged |
| **Session age** | The session has crossed 50% of estimated context budget (see [`./context.md`](./context.md) § Checkpoint protocol) |

The prune pass produces a checkpoint block (same schema as `context.md` § Checkpoint protocol) plus a compact memory list — no more than 10 items, each one sentence. Items that do not survive the prune are either discarded or written to `state/` before disposal (see next section).

## Persistent state handoff

Not every pruned observation is worth discarding. Some must persist to `state/` for future sessions or downstream skills.

**Write to `state/` when:**

- The observation is a verified finding — a confirmed fact, a tested assertion, a committed decision.
- The observation is a failed hypothesis — a dead-end that a future agent or session should not re-explore.
- The observation names an open question that the current session cannot resolve.

**Discard when:**

- The observation is an intermediate step that was superseded by its result.
- The observation is a redundant confirmation of a point already recorded.
- The observation is scratch work — a temporary calculation or draft that served its purpose.

**State file discipline:** Write verified findings to the skill's canonical output artifact (e.g., `learnings.md`, `claims.json`), not to a raw scratch file. A scratch file in `state/` that accumulates without structure becomes the same All-Add problem at the filesystem level.

### Handoff entry format

When writing a memory entry to `state/`, use the minimal structure:

```
## <YYYY-MM-DD> — <one-line label>

**Finding / decision:** <one sentence>
**Evidence:** <source or test that verified it>
**Status:** verified | failed-hypothesis | open-question
```

Omit fields that are genuinely empty. Do not pad.

## Anti-patterns

- **All-Add as the default.** Never unconditionally append. Every observation must pass the relevance gate or go to the scratch pad.
- **Pruning without a checkpoint.** Discarding entries without writing the checkpoint block means the next step has no continuity anchor. Prune and checkpoint are one operation.
- **Checkpointing without pruning.** A checkpoint that includes all prior memory entries is not a prune — it is a rename. The checkpoint must be smaller than what it replaces.
- **Scratch files that become permanent.** A file in `state/` named `scratch-<date>.md` that persists session to session is All-Add at the filesystem level. If it is worth keeping, give it structure and a canonical name. If it is not, delete it.
- **Relevance gate that never rejects.** If every observation passes the gate, the gate is not calibrated. Periodically check: what was the last entry the gate rejected? If the answer is "nothing this session," tighten the test.
- **Treating working memory as a log.** Logs are append-only by design. Working memory is a model of current task state — it must be correctable, prunable, and compact.
- **Deferring the prune to "later."** The prune pass is triggered by boolean conditions (see above), not by a feeling of readiness. If the trigger fires, run the pass before the next major step.

## Relationship to `context.md`

[`./context.md`](./context.md) governs attention budget *within a prompt* — what goes into the context window and where. This module governs what the agent *decides to remember* across turns and sessions. They are complementary: `context.md`'s checkpoint protocol fires at 50% context budget; `memory-hygiene.md`'s checkpoint fires at goal boundaries. Both can fire in the same session; when they do, run the `memory-hygiene.md` prune first, then populate the `context.md` checkpoint from the pruned result.

For working-memory accumulation across sessions, the interaction point is the `state/` handoff: what `memory-hygiene.md` writes to `state/` is what a future session's `context.md` smallest-set rule will cite line-range excerpts from. Clean handoffs produce clean future contexts.
