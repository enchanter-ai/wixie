# Substrate Consumption — Read Prior Evidence Before You Act

Audience: any agent operating inside a project that has invested in cross-session evidence accumulation (briefings, MEMORY files, learnings logs, precedent logs, an inference substrate). How to consume that evidence at the start of a session — and again before risky steps — so prior failures do not recur for free.

The sibling module [`./precedent.md`](./precedent.md) covers *writing* self-observed failures to a precedent log. This module covers the inverse: *reading* the accumulated evidence the project has paid to produce. A substrate the agent only writes to is a diary, not a tool.

## The failure shape

A project has paid — in tokens, in human attention, in reconcile cycles — to accumulate cross-session evidence:

- Per-plugin briefings (`state/briefings/<plugin>.md`) rendered by an inference engine from elevated patterns.
- An auto-memory file (`MEMORY.md`) carrying user-taught preferences and live project pointers.
- Per-workflow `learnings.md` logs from convergence loops (E6, F6, H6, etc.).
- A `precedent-log.md` of self-observed operational failures.
- A pattern catalog (`plugins/inference-engine/state/catalog.json`) with posteriors, LLR scores, and verdicts.

Then a fresh session starts. The agent reads the user's message, dispatches tools, ships a result — and never opens any of the above. The pattern that was elevated three reconciles ago, that the substrate is *literally rendering at the top of a briefing file for this exact plugin*, fires again. The project pays a second time for evidence it already owned.

This is **F24 substrate-blindness**: the agent acted without first consuming prior-session evidence that was authored, indexed, and pre-placed for consumption.

It is distinct from two adjacent failures:

| Failure | What it names | Why F24 is different |
|---------|---------------|----------------------|
| F03 context-decay | Intra-session: the agent forgets earlier turns of the *current* session | F24 is cross-session: the evidence predates this session entirely |
| precedent.md (write side) | Failing to *log* a self-observed failure | F24 is the read side: logs exist, the agent never opened them |

The substrate's value compounds only when reads match writes. F24 is the failure that breaks the compounding.

## The read protocol

At session start, before the first non-trivial tool dispatch, consume in this order. Each step is a small read — seconds, not minutes. Skipping is the failure mode this module names.

### At session start (always)

1. **The plugin briefing.** `state/briefings/<plugin>.md` (or the project's analog). Rendered by the inference engine from elevated patterns. Treat as advisory per [`../../shared/conduct/inference-substrate.md`](../../shared/conduct/inference-substrate.md) — prefer patterns with EMA weight > 0.5 and observations ≥ 3. Place in the U-curve top-200-tokens slot per [`./context.md`](./context.md).
2. **The auto-memory.** `MEMORY.md` (typically under the user's harness directory). Carries user-taught guidance and live project pointers. Read once, hold the active links in working context.
3. **The local CLAUDE.md.** Already auto-injected by the harness — but verify it loaded; if missing or truncated, surface the gap before acting.

### Before a risky or load-bearing step

4. **The precedent log.** `state/precedent-log.md`. Grep by command verb (`git reset`, `python`, `find`) or by tag before running a non-trivial Bash sequence, per [`./precedent.md`](./precedent.md) § Consult-then-act.
5. **The workflow learnings.** `prompts/<name>/learnings.md` or the workflow's local equivalent — before resuming an iteration round on an artifact that already has a convergence history.
6. **The pattern catalog.** `plugins/inference-engine/state/catalog.json` only when the briefing is suspected stale (no recent reconcile, plugin briefing renders as placeholder, or a high-stakes consumer is about to read). Query through `inference-engine.py query`, not by hand — the catalog is engine-owned per the substrate's mutation contract.

### Refresh discipline

- If the briefing was rendered more than a session boundary ago and the session is high-stakes (`/converge`, `/harden`, `/lich-review`, a deploy-bar verdict), trigger a reconcile + re-render before reading — per [`../../shared/conduct/inference-substrate.md`](../../shared/conduct/inference-substrate.md) § When to reconcile. A stale briefing lies to the consumer; a fresh one is cheap.
- After consuming, do not transcribe the briefing back into chat — that wastes the context budget the U-curve placement was designed to protect. Hold the pointers, cite the patterns by code when they fire.

## What "consume" means

Reading is not the contract. Consuming is. Concretely:

```
□ For each elevated pattern in the briefing: noted the code, the signal, and the counter.
□ For each MEMORY.md link relevant to the current task: opened it or marked it as recheck-before-acting.
□ For each precedent entry tagged with the current task's verbs: scanned the signal line.
□ If any □ above was skipped because "the briefing was empty" or "MEMORY had nothing relevant": that is an honest no-op, not a substrate-blindness incident.
```

The contract distinguishes *no evidence existed* (acceptable; act) from *evidence existed and was not consulted* (F24; the failure this module names).

## Meta-irony, acknowledged

This module's own landing session may not consume prior briefings — the substrate may be empty, the plugin briefing may render as placeholder, the auto-memory may not yet carry pointers to the new modules. That is expected. The counter applies to *future* sessions: once F24 is wired into a plugin's CLAUDE.md, the next session inherits the read protocol whether or not this one followed it. Do not let the landing-session irony become a license for future sessions to skip.

## Anti-patterns

- **Starting work without first checking the briefing for the current plugin.** The named failure. The briefing is rendered to be read; not reading it is the substrate-blindness signal.
- **Treating the substrate as write-only.** Emitting an artifact then never opening a briefing or catalog is a diary entry, not a system. The compounding only works on the read side.
- **Skimming the briefing then ignoring its `signal` lines.** Signals are written to be reused verbatim; rephrasing them in your head is selection bias toward the path you already wanted.
- **Reading the briefing once per project lifetime.** Briefings drift as the catalog walks. If your last read was before the last reconcile, you are reading a stale snapshot.
- **Hand-reading the catalog instead of the briefing.** The engine elevates patterns through SPRT for a reason; reading raw posteriors invites confirmation bias and a depth-2 honest-numbers violation. Read the briefing first; query the catalog only when the briefing is suspected stale.
- **Conflating MEMORY.md with the briefing.** MEMORY is user-taught, cross-project, persistent. The briefing is engine-rendered, plugin-scoped, refresh-on-reconcile. Different surfaces, different refresh contracts; consume both.
- **"I remember this pattern from last session."** Across session boundaries, you don't. The harness reset state. Grep the log, read the briefing, then act.
- **Reading prior evidence after writing the substitute artifact.** Same shape as the F22 anti-pattern "loading the discovery tool only after writing the substitute artifact" — the read happens before the write, or the read was decorative.

## Cross-references

- [`./failure-modes.md`](./failure-modes.md) § F24 — the taxonomic entry this module operationalises.
- [`./precedent.md`](./precedent.md) — the write-side complement; this module is the read-side.
- [`./context.md`](./context.md) § U-curve placement — where in the context window prior-evidence reads belong (top-200-tokens slot).
- [`../../shared/conduct/inference-substrate.md`](../../shared/conduct/inference-substrate.md) — the substrate's mutation contract and briefing-read guidance (wixie-local; this vis module generalizes the read protocol across plugins).
- [`./capability-fidelity.md`](./capability-fidelity.md) § Anti-patterns — "loading the discovery tool only after writing the substitute artifact" is the same failure shape one layer down.
