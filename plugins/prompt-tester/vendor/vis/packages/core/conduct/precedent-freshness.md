# Precedent Freshness — Verify Before You Cite Yourself

Audience: any agent that reads its own prior outputs across sessions — auto-memory entries (`~/.claude/.../memory/*.md`), `state/precedent-log.md`, `learnings.md`, per-plugin briefings under `state/briefings/<plugin>.md`, prior roadmaps, prior trace artifacts. How to consult self-authored state without treating it as ground truth, and how to detect when an entry has rotted past the half-life of usefulness.

## The failure shape

The agent recalls a prior memory or precedent that names a concrete project surface — a file path, a function name, a flag, a script, a directory, a repo name — and acts on it without checking whether that surface still exists in the form recorded. Or the agent generalises from a snapshot memory (architecture summary, activity log, repo inventory) without re-grounding against current state. The cited evidence was honest *at write time*; by the time it is read it no longer reflects reality. The artifact produced under it inherits the staleness silently.

This is **F27 stale-precedent reliance**. It is adjacent to but distinct from [`./failure-modes.md`](./failure-modes.md) § F14 version-drift — F14 covers *external* surfaces (deprecated APIs, retired model IDs, obsolete vendor flags). F27 covers *internal, self-authored* surfaces: the agent's own memory, precedent, briefings, and prior session traces.

The canonical example for this project: the `foundations` → `vis` repo rename. Memory entries, lock files, and CLAUDE.md @-imports that referenced the old path all became stale in a single commit; 9 sibling repos required lock refreshes. Any agent that cited a memory containing `foundations/` after the rename without verifying the path was running on stale precedent.

The auto-memory system already warns operators that *"memory records can become stale"*. This module operationalises that warning: it specifies when to verify, what to verify, and how — so the warning has teeth instead of being a passive disclaimer.

## The verification protocol

Classify the memory or precedent entry before consuming it. The required check depends on the entry's *shape*, not its age.

### Class A — Concrete-surface entries (path, function, flag, script, repo name)

The entry names a specific filesystem or codebase surface. Before acting on it, verify the surface still exists in the cited form.

- **Path** (`shared/scripts/inference-engine.py`, `plugins/wixie/state/...`) → `Glob` the path. Hit → proceed. Miss → the entry is stale; do not extrapolate, re-discover via `Grep` for the file's likely new name.
- **Function or symbol** (`reconcile()`, `emit_artifact()`) → `Grep` for the definition (`def reconcile`, `function reconcile`, `fn reconcile`). Hit → proceed. Miss → re-discover or escalate.
- **Flag or env var** (`WIXIE_INFERENCE_ENABLED`, `--no-verify`) → `Grep` for the literal token in the relevant config or script. Hit → proceed. Miss → flag was renamed or removed; do not assume the new name.
- **Repo name** (`vis/...`, `wixie/...`) → check the current org structure (e.g., look for `c:/git/enchanter-ai/<name>/` on disk). Miss → repo was renamed; treat all sibling references in the same memory as suspect.

### Class B — Snapshot-summary entries (architecture diagram, inventory, activity log, briefing)

The entry summarises a moving target as it stood at a point in time. Before generalising, check freshness.

- Read the entry's date or session_id.
- Run `git log --since=<entry-date> --oneline` against the directories the summary describes. If non-trivial commits have landed since, the snapshot is no longer a reliable generalisation — re-derive against current state before quoting it.
- For briefings under `state/briefings/<plugin>.md`, prefer to reconcile (`inference-engine.py reconcile`) before consuming if the briefing's last-reconcile timestamp is more than a week old.
- Generalising from a 6-month-old activity log without checking `git log` is the canonical F27 anti-pattern in this class.

### Class C — Feedback-rule entries (user preference, policy, convention)

The entry encodes a rule the user taught the agent ("prefer `uv` over `pip` in this project", "always include a test plan in PRs"). Rules don't rot the same way facts do — they remain valid until the user explicitly retracts them or the context changes.

- Trust the rule unless the current context contradicts it (e.g., the rule was scoped to a different project, or the user has issued a more recent counter-instruction in this session).
- Do not re-verify on every read; that's noise.
- If the rule's *target* (a file, a tool, a script) is a Class-A surface, verify the target separately — but the rule itself stands.

### When to skip verification

Verification is cheap (one `Glob` or one `Grep`) but it is not free. Skip when:

- The entry is being consumed read-only for context, not as the basis for an action.
- The action is itself a verification step (you're about to read the file anyway).
- The memory was written within the current session.

Never skip when the entry will drive a destructive op, a commit, or a verdict claim.

## Decay signals

Concrete triggers that should raise suspicion on *any* memory written before the trigger:

- **File moved or renamed.** Any memory naming the old path is stale. `git log --follow --diff-filter=R` surfaces renames.
- **Function renamed.** Any memory naming the old symbol is stale.
- **Schema bumped.** JSON / YAML / proto schema changes invalidate memories that quote field names or shapes.
- **Version bump on a dependency** the memory's instructions assume. Adjacent to F14 but the rot is in the *internal* memory, not the external dep.
- **Repo renamed.** Project-wide invalidation — every memory referencing the old repo name should be treated as Class-A-suspect until verified. The `foundations` → `vis` rename is the worked example here; it invalidated 9 sibling locks and any memory that hard-coded the old path.
- **Hook or skill removed.** Memories that say "the X hook will fire on Y" are stale once X is deleted.
- **Briefing reconciled with a retirement event.** Patterns whose LLR fell below the retirement threshold should no longer be cited even if a stale memory still references them.

When any of these fire, sweep the relevant memory class proactively — don't wait for the next consumer to hit the stale entry.

## Anti-patterns

- **Citing a memory referencing `foundations/` after the rename to `vis/`.** Class-A surface change; one `Glob` would have caught it. The lock-refresh fan-out across 9 siblings is the cost of skipping the check.
- **Extrapolating from a 6-month-old activity log without checking `git log`.** Class-B snapshot rot; the summary was true once, but generalising from it now is fiction.
- **Relying on a feedback rule that was written for a different project context.** Class-C scope confusion; rules are durable but they are *not* unbounded — "always use `uv`" written under one project's memory does not necessarily transfer to a sibling repo with different tooling.
- **Treating the auto-memory disclaimer ("memory records can become stale") as sufficient.** The disclaimer is a warning, not a protocol. F27 fires when the warning is read and ignored.
- **Verifying once at session start, then trusting all subsequent reads.** Memories can be invalidated mid-session by your own edits — if you renamed a file 20 turns ago, a memory that named the old path is stale *now*, not just across sessions.
- **Logging the staleness as an F14 entry.** F14 is external-surface drift. Stale self-authored memory is F27. Wrong code defeats the taxonomy's compounding.

## Cross-references

- [`./failure-modes.md`](./failure-modes.md) § F27 — the taxonomic entry this module operationalises.
- [`./failure-modes.md`](./failure-modes.md) § F14 — version-drift on external surfaces; the sibling failure mode this one is distinguished from.
- [`./precedent.md`](./precedent.md) — covers *writing* precedent entries; this module covers *reading* them safely.
- [`./verification.md`](./verification.md) § Baseline snapshot — the verification habit this module specialises for self-authored state.
- [`./context.md`](./context.md) § U-curve placement — briefings consumed in the top-200-tokens slot are exactly the entries most likely to drive stale-precedent action; verify before slotting.
