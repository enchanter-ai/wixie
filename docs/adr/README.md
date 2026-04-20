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

Copy and fill out:

```markdown
# ADR NNNN — <title in declarative form>

- **Status**: Proposed | Accepted | Deprecated | Superseded by ADR-NNNN
- **Date**: YYYY-MM-DD
- **Author**: @handle

## Context

What forced the decision. Include the constraint, the observed failure mode, or the
cross-sibling alignment that made this a judgement call. 1-3 paragraphs.

## Decision

One paragraph, declarative: *"We will do X."* No hedging.

## Alternatives considered

- **Alt A** — why rejected.
- **Alt B** — why rejected.

## Consequences

What becomes easier because of this. What becomes harder. What new failure modes this
opens up. Be honest — if the decision has a real cost, name it.

## Related

- Links to relevant code, PRs, other ADRs.
- Cross-ref to `shared/conduct/*.md` if the decision rests on a behavioral contract.
```

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

The @enchanted-plugins ecosystem shares a single behavioral contract in `shared/conduct/*.md`. Decisions that affect that contract are **not** local to this repo — raise them in the `schematic` repo where the canonical modules live, and cross-link from here.
