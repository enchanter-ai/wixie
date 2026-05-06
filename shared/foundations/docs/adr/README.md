# Architectural Decision Records

Architectural decisions for agent-foundations live here, one file per decision, numbered sequentially.

## Format

Each ADR follows the [Michael Nygard format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions):

```markdown
# ADR-NNNN — <Title>

## Status

<Proposed | Accepted | Deprecated | Superseded by ADR-XXXX>

## Context

What is the issue we're addressing?

## Decision

What did we decide?

## Consequences

What follows from this decision — good, bad, and neutral?
```

## When to write an ADR

Write an ADR when:

- The decision shapes the framework's structure (folder layout, naming, layering invariants).
- The decision will be re-litigated by future contributors who don't have the context.
- The decision was *non-obvious* — multiple plausible options existed and one was picked.

Don't write an ADR for:

- Single-module edits (those go in the module's own anti-patterns / failure-modes section).
- Style preferences (those go in `CLAUDE.md` or contributor docs).
- Decisions whose justification is self-evident from the code.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| 0001 | [Layered structure: conduct + engines + taxonomy + recipes](./0001-four-layers.md) | Accepted |
| 0002 | [Taxonomy expansion to F15–F21 and deferred 5-axis migration decision](./0002-taxonomy-expansion.md) | Accepted; structural question resolved via hybrid in `taxonomy/axes.md` (added 2026-05-05) |

## Numbering

ADRs are numbered with a 4-digit zero-padded prefix. Skip nothing — if ADR-0007 is rejected, mark it Rejected, don't reuse the number. The history is more useful than tidy numbering.
