# ADR-0002 — Taxonomy expansion to F15–F21 and deferred 5-axis migration decision

## Status

Accepted; structural question resolved via hybrid in `taxonomy/axes.md` (added 2026-05-05).

### Resolution note

The deferred Decision 2 is now resolved. Option A (extend flat list) and Option B (migrate to 5-axis) were superseded by the hybrid path: the flat F01–F21 numbering is retained as the operational identifier, and `taxonomy/axes.md` adds a parallel 5-axis layer (memory, reflection, planning, action, system) adopted from AgentErrorTaxonomy (arxiv 2509.25370). No renumbering. No breaking change for downstream consumers. The axes layer enables structural pressure analysis across sessions without requiring any consumer to migrate off F-numbers. See `taxonomy/axes.md` for the full mapping and migration trigger conditions (flat list > 40 codes, or any single axis > 10 codes).

## Context

Two developments after the initial F01–F14 taxonomy required a structural decision:

1. **New failure modes from multi-agent and alignment research.** Published research surfaced failure patterns outside the F01–F14 scope: inter-agent misalignment, task-verification skip, and system-design brittleness (MAST, arxiv 2503.13657); goal-conflict insider behavior and weaponized tool use (Anthropic agentic misalignment research, 2025; Anthropic misuse report, August 2025); alignment faking and sandbagging (Anthropic alignment faking research, 2024; OpenAI scheming reasoning evaluations, 2024; DeepMind Frontier Safety Framework). These patterns were already observable in deployed agentic systems. Leaving the taxonomy at F14 while these were documented but uncoded would allow failure logs to accumulate untagged observations with no aggregation path.

2. **A structural alternative was proposed.** AgentErrorTaxonomy (arxiv 2509.25370) proposes a 5-axis modular structure — memory, reflection, planning, action, and system — empirically grounded in a large corpus of agent failures. This structure conflicts with the existing flat F-code list. Adopting it would require renumbering F01–F14, restructuring `taxonomy/`, and auditing all downstream consumers that log failure codes by F-number. The `taxonomy/README.md` § Structural note documents this contradiction explicitly.

The two developments require separate decisions: whether to extend the taxonomy now, and whether to restructure it later.

## Decision

**Decision 1 — Ship F15–F21 as flat extensions in the existing convention.**

Seven new codes are added to the flat F-code list, continuing from F14:

- F15 — Inter-agent misalignment
- F16 — Task-verification skip
- F17 — System-design brittleness
- F18 — Goal-conflict insider behavior
- F19 — Alignment faking *(awareness)*
- F20 — Sandbagging *(awareness)*
- F21 — Weaponized tool use

Each code follows the existing per-doc shape (Signature, Counter, Examples, Adjacent codes, Escalation). F19 and F20 carry an **Awareness code.** notice reflecting that they document alignment-research failure modes not expected in routine operational workflows.

**Decision 2 — Resolved (2026-05-05): hybrid path adopted.**

The flat list is retained; `taxonomy/axes.md` adds a parallel 5-axis layer. The structural question surfaced in the original ADR as a deferred choice between Option A (extend flat list) and Option B (migrate to 5-axis) is resolved by the hybrid: both coexist. F-codes remain the operational logging identifier; axes are the structural review layer. No migration required. See the Resolution note in the Status section and `taxonomy/axes.md` for the full specification.

## Consequences

### Good

- **Taxonomy extended.** F15–F21 codes are available for tagging failure logs immediately, closing the gap between documented research failure modes and the taxonomy's coverage.
- **Structural question resolved.** The AgentErrorTaxonomy contradiction is closed via the hybrid path. `taxonomy/axes.md` provides the 5-axis mapping; the decision trail is in this ADR and in the README § Structural note.
- **No breaking change.** Downstream consumers — `CLAUDE.md` references, `learnings.md` entries, plugins logging by F-number — are unaffected. F01–F14 numbering is stable.
- **Awareness codes are explicitly distinguished.** F19 and F20 are labeled as alignment-research awareness codes with escalation paths that differ from operational runbook codes, reducing the risk that practitioners treat them as routine detection targets.

### Bad

- **Flat list grows.** 21 codes is larger than 14. The hybrid path mitigates this by providing axis-level grouping without requiring a migration, but if the list continues growing past 40 codes or any single axis exceeds 10 codes, the trigger conditions in `taxonomy/axes.md` recommend revisiting the structure.

### Neutral

- **Multi-agent and alignment codes are a natural cluster.** F15–F21 are grouped logically in `taxonomy/README.md` § Index under "Multi-agent and alignment failures," and their formal axis assignments are now in `taxonomy/axes.md` (F15, F17 → system; F16 → reflection; F18 → planning; F21 → action; F19, F20 → reflection).
- **Awareness code convention is new.** F19 and F20 introduce a distinction — operational codes vs. awareness codes — that was not present in F01–F14. This convention may need formalizing if future codes require the same distinction.

## Alternatives considered

1. **Ship F15–F21 inside a 5-axis annex immediately.** Add a parallel `taxonomy/5-axis/` directory using the AgentErrorTaxonomy structure and place the new codes there. Rejected: fragments the taxonomy. Failure logs would reference either flat F-codes or axis codes, and the two namespaces would diverge. Consumers would need to know which namespace a code lives in.

2. **Migrate to 5-axis now and renumber everything.** Accept the breaking change, map F01–F14 to axes, ship F15–F21 in the new schema. Rejected: the migration is load-bearing for all downstream consumers, requires a community decision, and is a separate scope from the taxonomy extension. Bundling them would make both harder to review and harder to revert.

3. **Defer F15–F21 entirely until the structural decision is resolved.** Hold the new codes until Option A or Option B is decided. Rejected: the structural decision has no committed timeline and may take months. Deferring the taxonomy extension lets failure logs accumulate untagged observations in the interim. The cost of a later renumber is lower than the cost of untagged failures compounding without a shared vocabulary.

## References

- MAST: A Multi-Agent System Testing Framework — inter-agent misalignment, task-verification, and system-design clusters. https://arxiv.org/abs/2503.13657
- AgentErrorTaxonomy: Towards a Unified Taxonomy for LLM-Based Agent Errors — 5-axis structural alternative. https://arxiv.org/abs/2509.25370
- Anthropic Agentic AI Misalignment — goal-conflict insider behavior source. https://www.anthropic.com/research/agentic-misalignment
- Anthropic Alignment Faking in Large Language Models — F19 primary source. https://www.anthropic.com/research/alignment-faking
- OpenAI Scheming Reasoning Evaluations — F20 primary source. https://openai.com/research/scheming-reasoning-evaluations
- DeepMind Frontier Safety Framework — corroborates F19 and F20 as distinct safety concerns. https://deepmind.google/discover/blog/frontier-safety-framework/
- Anthropic Misuse and Safety Report (August 2025) — F21 source. https://www.anthropic.com/research/misuse-report-2025
- `taxonomy/README.md` § Structural note — hybrid resolution (as of 2026-05-05)
- `taxonomy/axes.md` — full 5-axis mapping, placement rationale, and migration trigger conditions
- ADR-0001 — Four-Layer Structure: establishes the `taxonomy/` layer this ADR extends
