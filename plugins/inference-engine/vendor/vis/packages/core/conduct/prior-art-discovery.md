# Prior-Art Discovery — Check Before You Author

Audience: any agent that is about to author a new tool, script, skill, conduct module,
workflow, or wrapper. How to confirm the capability does not already exist before
adding a new surface — without making reuse mandatory, but making *checking* mandatory.

## The failure shape

A principal asks for capability C (e.g., "replay challenges and grade outputs", "convert
HTML to PDF", "emit a learning entry", "draft a conduct module for case X"). The agent
immediately authors `<new-thing>.py` / `<new-skill>` / `<new-module>.md` — and an existing
file two directories over already did it, often better, often with a contract the new
thing now silently duplicates and diverges from.

This is **F28 skill-discoverability failure**. The work was genuinely requested — this
is not [F07 over-helpful substitution](./failure-modes.md), which is about solving an
unrequested problem. Here the request is real; the failure is that the agent treated
"author new" as the first move when the first move is "discover prior art."

The cost compounds quickly:

- Two implementations of the same capability drift; the next session can't tell which is
  canonical.
- The principal's mental model fragments — they now have to remember which sibling does
  what.
- Cross-session evidence (state, learnings, briefings) splits across two surfaces and
  loses statistical power.
- The original implementation's tests, harness wiring, and integration paths quietly rot
  because the new path bypasses them.

The adjacent principle is [`./discipline.md`](./discipline.md) § Surgical changes —
*touch only flagged lines, no parallel rewrites, no drive-by edits.* F28 extends that
stance one level out: before *adding* a surface, confirm one isn't already there. Surgical
changes govern editing; prior-art discovery governs authoring.

## The discovery protocol

Before the first `Write` of a new tool/script/skill/module, run a discovery pass in this
order. Each target has a rationale; do not skip.

### 1. `shared/scripts/` (or the repo's equivalent script bin)

Rationale: 80% of "I need a utility for X" requests collide here. Existing scripts are
the most-likely match and the cheapest to read. Do this first.

- `ls shared/scripts/` and read filenames. Then `Grep` script contents for the proposed
  capability's verbs (e.g., "replay", "score", "emit", "convert").

### 2. `packages/*/skills/` (or the plugin's skills directory)

Rationale: if the new work is skill-shaped (`/<command>`), an existing slash-command may
already dispatch the workflow. Authoring a parallel skill duplicates the dispatch surface
and splits the user-facing command space.

- `Glob` for `SKILL.md` files; read frontmatter `description` and `when_to_use` lines.

### 3. `state/vis-proposals/` and similar in-flight workspaces

Rationale: a sibling agent may be drafting the same module *right now*. Concurrent drafts
are F09 parallel-race in waiting. Catching this before write is much cheaper than
reconciling two drafts post-hoc.

- `ls` the proposal workspaces under `state/`; read any JSON / md drafts that share
  keywords with your slug.

### 4. `Glob` on slug variants across the repo

Rationale: the same capability may have been authored under a different naming
convention (kebab-case vs. snake_case, singular vs. plural, verb-first vs. noun-first).
The filename you chose is not the only filename it could have.

- For a proposed slug `<x-y-z>`: glob `**/*x*y*z*`, `**/*x_y_z*`, and the noun/verb
  permutations. Two minutes of globbing prevents two days of drift.

### 5. `Grep` on signature keywords across the repo

Rationale: implementations that match by *behavior* but not by *name* won't show up in
glob. The proposed capability has 1-3 load-bearing nouns and verbs (the request's
actual signature). Search for those, not for the slug.

- Pick the 2-3 most-specific keywords from the request. `Grep -r` across the repo.
  Read the first 5 hits.

The protocol terminates as soon as a clear prior-art match is found — proceed to the
decision rule. If all five steps return clean, authoring new is justified; record
"discovery: clean across 5 targets" in the artifact / commit message so the next session
knows the check was run.

## Decision rule — when to reuse, when to author new

Discovery returns one of three outcomes:

**Clean** — no prior art across all 5 targets. Author new. State the negative result in
the commit message: *"discovery: shared/scripts, packages/*/skills, state/proposals,
slug-glob, signature-grep — no prior art."*

**Match found, reuse appropriate** — extend, parameterize, or invoke the existing
capability. Surface a one-line note to the principal: *"`shared/scripts/foo.py` already
does this; extending it with --new-flag rather than authoring `bar.py`."*

**Match found, reuse NOT appropriate** — authoring new is correct when at least one of
these is true (state which, in the commit message):

| Reason to author new despite a match | What to write in the artifact |
|--------------------------------------|--------------------------------|
| Existing tool's contract doesn't match (different inputs, different invariants) | "prior art: `<path>`; contract mismatch on <field> — new tool needed" |
| Existing tool is deprecated / scheduled for removal | "prior art: `<path>`; deprecated per <commit/note> — replacement" |
| Existing tool's agent tier is wrong (Haiku-only when Opus needed, or vice versa) | "prior art: `<path>`; tier mismatch (<existing> vs. <required>) — new tool" |
| Existing tool is in a different scope (private to plugin A, request is vis-level) | "prior art: `<path>`; scope mismatch — promoting to <new scope>" |
| Existing tool's reuse cost (refactor, dependency, breaking change) exceeds new-author cost | "prior art: `<path>`; reuse cost <X>, new-author cost <Y> — new" |

The rule is **check first, then decide** — not *reuse first*. Reuse is sometimes wrong;
skipping the check is always wrong.

## Anti-patterns

- **Authoring `efficacy-replay.py` without checking `shared/scripts/` first.** Concrete
  recent failure: the agent wrote a new replay harness when a sibling script with a
  closely-related contract already existed. Two minutes of `ls shared/scripts/` would
  have surfaced it.
- **Drafting a new conduct module without searching `packages/*/conduct/`.** The
  module-space is small (~10 files); reading the directory listing takes seconds and
  often surfaces an adjacent module that should be extended rather than parallel-authored.
- **Building a `/new-command` skill that duplicates an existing `/command`'s workflow.**
  Skill names are user-facing; two skills doing similar work pollute the command palette
  and split user habit-formation.
- **Discovery-by-vibes ("I don't think anything like this exists").** Vibes are not
  evidence. Run the five targets or state "discovery skipped" honestly in the commit.
- **Treating discovery as overhead.** It's the cheapest insurance against repo
  fragmentation. The five targets together are < 2 minutes for a typical request.
- **Discovery after the new artifact is written.** Like recovery-after-substitute in
  F22, this is the wrong order. Discovery is a Step-1 gate, not a post-hoc rationalization.

## Cross-references

- [`./failure-modes.md`](./failure-modes.md) § F28 — taxonomic entry for this module.
- [`./discipline.md`](./discipline.md) § Surgical changes — adjacent principle for *editing*; this module governs *authoring*.
- [`./failure-modes.md`](./failure-modes.md) § F07 — distinct: F07 is solving an unasked problem; F28 is duplicating an asked-for capability.
- [`./tool-use.md`](./tool-use.md) § Right tool, first try — discovery is the upstream act that makes "right tool" knowable.
- [`./capability-fidelity.md`](./capability-fidelity.md) § Step 1 Probe and recover — same conceptual move (check before substitute) applied to the runtime-capability axis instead of the authoring axis.
