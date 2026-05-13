# Architecture Decision Records

This directory captures the non-obvious architectural choices made in this plugin. If a future reader — human or agent — would reasonably ask *"why is it done this way?"*, the answer belongs here.

## What an ADR is

Short. Honest. Dated. Each ADR records **one decision**, the **context** that forced it, the **alternatives considered**, and the **consequences** accepted.

ADRs are not:

- Tutorials (those live in `docs/getting-started.md`).
- API references (those live next to the code).
- Marketing material (those live in the README).
- A place to re-litigate settled decisions.

## When to write one

Write an ADR before you merge a PR that:

- Introduces a new dependency, agent tier, hook type, or algorithm family.
- Breaks or retires a previously documented behavior.
- Changes the public command surface, the artifact contract, or the scoring model.
- Makes a choice a newcomer would reasonably question in a code review.

Don't write one for:

- Bug fixes that restore previously documented behavior.
- Refactors that don't change behavior.
- Renames, doc polish, style changes.

If you're not sure, err toward writing one — a 10-line ADR is cheaper than a 30-minute async thread re-discovering why.

## Naming and numbering

```
docs/adr/<NNNN>-<kebab-case-title>.md
```

- `NNNN` — zero-padded sequence number, starting at `0001`. Never reuse.
- `<kebab-case-title>` — short, declarative. *"Why we chose X over Y"* becomes `choose-x-over-y`.

Examples:

```
0001-adopt-managed-agent-tiers.md
0002-no-hand-edited-diagrams.md
0003-hooks-are-advisory-only.md
```

## Template

Copy [template.md](template.md) into `docs/adr/<NNNN>-<kebab-title>.md` and fill it in. The template's sections — Context, Decision, Alternatives considered, Consequences, Related — are the minimum; don't prune them. Add more only if the decision genuinely warrants it.

## Status lifecycle

```
Proposed → Accepted → Deprecated
                          ↑
                   Superseded by NNNN
```

- **Proposed** — open for discussion; may still change.
- **Accepted** — the current binding decision. Linked from code if helpful.
- **Deprecated** — no longer in effect but kept for history.
- **Superseded** — replaced by a newer ADR; include the replacement's number.

Never delete an ADR. Marking it `Deprecated` or `Superseded` preserves the decision trail.

## Reading the log

The ADR log is the institutional memory of this repo. When onboarding, skim every `Accepted` ADR in order — you'll know more about this plugin in 20 minutes than you would in a week of reading source.

## Cross-ecosystem

The @enchanter-ai ecosystem shares a single behavioral contract in `shared/vis/conduct/*.md` (vendored from vis) plus the wixie-specific `shared/conduct/inference-substrate.md`. Decisions that affect that contract are **not** local to this repo — raise them in the `vis` repo where the canonical modules live, and cross-link from here.
