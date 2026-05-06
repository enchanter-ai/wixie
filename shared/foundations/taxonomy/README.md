# Failure-Mode Taxonomy

Audience: anyone maintaining or extending the failure taxonomy. 21 canonical codes (F01–F21), one doc per code, growable.

This folder is the **canonical source** of failure-code definitions. The summary in [`../conduct/failure-modes.md`](../conduct/failure-modes.md) is the at-a-glance table; the per-code docs here are where the *signature*, *counter*, and *examples* live in detail. If they conflict, this folder wins.

## Why one doc per code

Free-text failure logs don't compound. A taxonomy with named codes does — but only if every code has a precise signature and a testable counter. One doc per code means:

1. New codes can be PR'd without merge conflicts.
2. Each code has room for examples, debate, and history.
3. The boundary between adjacent codes (F04 task-drift vs. F07 over-helpful substitution) gets argued in writing, not in someone's head.

## Index

### Generation failures

- [F01 — Sycophancy](./f01-sycophancy.md)
- [F02 — Fabrication](./f02-fabrication.md)
- [F03 — Context decay](./f03-context-decay.md)
- [F04 — Task drift](./f04-task-drift.md)
- [F05 — Instruction attenuation](./f05-instruction-attenuation.md)

### Action failures

- [F06 — Premature action](./f06-premature-action.md)
- [F07 — Over-helpful substitution](./f07-over-helpful-substitution.md)
- [F08 — Tool mis-invocation](./f08-tool-mis-invocation.md)
- [F09 — Parallel race](./f09-parallel-race.md)
- [F10 — Destructive without confirmation](./f10-destructive-without-confirmation.md)

### Reasoning failures

- [F11 — Reward hacking](./f11-reward-hacking.md)
- [F12 — Degeneration loop](./f12-degeneration-loop.md)
- [F13 — Distractor pollution](./f13-distractor-pollution.md)
- [F14 — Version drift](./f14-version-drift.md)

### Multi-agent and alignment failures

- [F15 — Inter-agent misalignment](./f15-inter-agent-misalignment.md)
- [F16 — Task-verification skip](./f16-task-verification-skip.md)
- [F17 — System-design brittleness](./f17-system-design-brittleness.md)
- [F18 — Goal-conflict insider behavior](./f18-goal-conflict-insider-behavior.md)
- [F19 — Alignment faking *(awareness)*](./f19-alignment-faking.md)
- [F20 — Sandbagging *(awareness)*](./f20-sandbagging.md)
- [F21 — Weaponized tool use](./f21-weaponized-tool-use.md)

## Per-doc shape

Every code's doc has these sections, in this order:

1. **Signature** — the precise observable pattern.
2. **Counter** — the rule that prevents recurrence.
3. **Examples** — at least two, ideally three, drawn from real observations.
4. **Adjacent codes** — what this code is *not* (the closest neighbors and how to disambiguate).
5. **Escalation** — what happens on a single occurrence vs. 3+ in one workflow.

Awareness codes (F19, F20) carry an **Awareness code.** notice at the top of the file, before the Signature section. These codes document alignment-research failure modes; they are included for completeness but are not expected in normal operational workflows. Their Counter sections reflect red-team and evaluation-protocol responses rather than runtime detection patterns.

## How to extend

Propose `F22+` only when you've observed the pattern in at least three independent contexts. PR template:

- Signature, counter, examples, adjacent codes, escalation — all six sections filled.
- The pattern does not overlap an existing code (or, if it does, propose a merger or refinement).
- The counter is testable — a reviewer can check whether the counter was applied.

Vibes-based codes get rejected. So do codes whose counter is "be more careful."

## How to read

Use this folder when:

- Tagging a failure log entry — pick the dominant code, link the doc.
- Designing a guard — read the counter, implement it.
- Onboarding a new agent / contributor to the project — point them at the index.

## Multi-agent cluster

F15, F16, and F17 form a natural cluster corresponding to the three MAST taxonomy groups (arxiv 2503.13657): inter-agent misalignment, task verification, and system design. They are numbered sequentially here for compatibility with the existing flat-list convention, but they are logically a sub-taxonomy.

When a failure in a multi-agent pipeline is observed, check all three before selecting the dominant code — they frequently co-occur, and the root cause is often architectural (F17) while the observable symptom is coordination-level (F15 or F16).

## Structural note — resolved via hybrid

The AgentErrorTaxonomy paper (arxiv 2509.25370) proposes a 5-axis modular structure (memory, reflection, planning, action, system) for agent failure taxonomies. Earlier versions of this repo deferred the decision between flat F-codes and the 5-axis structure. **As of 2026-05-05 the resolution is the hybrid path:** the flat F01–F21 numbering remains the operational identifier, AND a parallel 5-axis mapping lives at [`axes.md`](./axes.md).

This is not a compromise. It is the structurally-correct shape: flat codes for grep-ability and minimal logging overhead; axes for review and structural pressure analysis. See `axes.md` for the full mapping, placement rationale for boundary cases (F02, F16, F18, F21), and the migration trigger conditions.

Awareness codes F19 and F20 stay in the main flat list (not a separate annex), tagged `(awareness)` at the index entry above and at the top of each file. Adopters who do not need alignment-research codes can filter by tag rather than by file path.
