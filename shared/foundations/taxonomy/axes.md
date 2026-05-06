# Taxonomy axes

Audience: anyone reading the F-code list and wanting structural grouping. Adopted from AgentErrorTaxonomy (arxiv 2509.25370). The flat F01–F21 numbering stays — this file adds an orthogonal axis layer.

## Why both layers

Flat F-codes are simpler to log, search, and grep. Five axes are easier to scan when you want to ask "what's our biggest *category* of failures this quarter?". One layer for ops; one for review.

## The five axes

### Memory

Failures of working memory, recall, or knowledge state. The agent knew a rule, constraint, or fact but lost it before acting.

F-codes: F03 Context decay, F05 Instruction attenuation, F13 Distractor pollution, F14 Version drift

### Reflection

Failures of self-evaluation, doubt, or honest self-report. The agent's internal check on its own output or behavior produced a false signal — either because social pressure overrode it (F01), because the metric was gamed (F11), because a required check was never invoked (F16), or because the mismatch between observed and unobserved behavior was strategic (F19, F20).

F-codes: F01 Sycophancy, F11 Reward hacking, F16 Task-verification skip, F19 Alignment faking *(awareness)*, F20 Sandbagging *(awareness)*

**Placement note for F16.** F16 sits in Reflection rather than Action because the failure is in the self-check loop, not in the execution of the subtask itself. The subagent completed its work steps; it failed to verify. The adjacent Action failure is F06 (acting before grounding) — the mirror: acting without checking the input. F16 is returning without checking the output.

**Placement note for F19 and F20.** Both awareness codes map to Reflection because the failure is fundamentally about the agent's self-assessment of its context (observed vs. unobserved, evaluation vs. operational). The behavioral surface is compliance or capability; the root is a corrupted self-model.

### Planning

Failures of goal alignment, decomposition, or progress. The agent understood the task but drifted from it, expanded beyond it, looped without learning, or substituted a different goal — including, in the adversarial case, substituting a goal the principal would prohibit.

F-codes: F04 Task drift, F07 Over-helpful substitution, F12 Degeneration loop, F18 Goal-conflict insider behavior

**Placement note for F18.** F18 is Planning, not Action, because the failure is goal-substitution: the agent selected an instrumental path (coercion, exfiltration, deception) as a means to a goal the principal did not sanction. The prohibited actions are downstream of the planning failure. The Action-axis escalation of F18 is F21 (Weaponized tool use), where the agent's chosen means constitutes active harm — but F21's root is still a planning failure in goal selection; the axis assignment reflects where the failure is diagnosable before the tool call fires.

### Action

Failures at the execution boundary — wrong call, wrong target, wrong timing, or wrong output. The agent's goal was coherent and its internal state was adequate; the failure happened at the moment of producing output or invoking a tool.

F-codes: F02 Fabrication, F06 Premature action, F08 Tool mis-invocation, F10 Destructive without confirmation, F21 Weaponized tool use

**Placement note for F02.** Fabrication is Action, not Memory. The agent did not *forget* a fact — it *emitted* a false one. The failure is at the output boundary: a claim, citation, or file reference that does not exist is generated and returned. Memory failures (F03, F05) produce silence or substitution of stale context; fabrication produces confident false output.

**Placement note for F21.** F21 spans Planning and Action but is assigned to Action because the observable failure event — the harmful tool invocation — is what distinguishes it from F18. F21's counter is also action-level (per-call confirmation, minimal whitelist, enforcement hooks). Log both the F18 planning failure and the F21 action failure if both are present.

### System

Failures of architecture, concurrency, or multi-agent coordination. The failure is not in any single agent's behavior but in the design of the network or the physical execution model.

F-codes: F09 Parallel race, F15 Inter-agent misalignment, F17 System-design brittleness

## How to use both layers

When logging a failure: use the F-code (mandatory) and tag the axis (recommended). Example:

```
F12 (planning) — convergence loop reverted same axis 3x without learning.
F16 (reflection) — translator subagent returned success without running the section-completeness check.
F15 (system) — two parallel refiners produced contradictory constraint clauses in prompt.xml.
```

When auditing across sessions: aggregate by axis to see structural pressure, then drill to F-codes for specific signatures. Axis-level aggregation answers "do we have a systematic reflection problem?" before you can answer "is it F01, F11, or F16?"

## Adding new codes

New F-codes (F22+) declare their axis assignment in the first prose paragraph of their file (before the Signature section). The axis assignment is part of the PR review, not an afterthought. Ambiguous cases — codes that sit at the boundary of two axes — default to the axis of their *primary counter*: if the counter is a tool-call guard, it's Action; if the counter is a self-evaluation protocol, it's Reflection.

If a candidate code doesn't fit any of the five axes cleanly, that is a signal the code may not be a real failure mode, or that the proposed code overlaps an existing one. Push back before extending the axes.

## When to migrate to axis-only structure

Don't, until two conditions hold:

1. The flat F-code list exceeds 40 entries (currently 21).
2. At least one axis has 10+ codes, making the flat list unwieldy.

Premature migration is a breaking change for every downstream consumer that logs by F-number. The hybrid is the long-run answer. Axis-only migration is the deferred option — defer it until the trigger conditions are met.

## Current axis distribution (F01–F21)

| Axis | Codes | Count |
|---|---|---|
| Memory | F03, F05, F13, F14 | 4 |
| Reflection | F01, F11, F16, F19, F20 | 5 |
| Planning | F04, F07, F12, F18 | 4 |
| Action | F02, F06, F08, F10, F21 | 5 |
| System | F09, F15, F17 | 3 |

Total: 21. Trigger for structural review: 40.

## Reference

AgentErrorTaxonomy: Towards a Unified Taxonomy for LLM-Based Agent Errors. arxiv 2509.25370. https://arxiv.org/abs/2509.25370
