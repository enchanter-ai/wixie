# ADR-0001 — Four-Layer Structure: conduct + engines + taxonomy + recipes

## Status

Accepted.

## Context

The framework needed a stable shape that could grow without colliding with itself. Three structural questions:

1. Should *behavior rules* and *algorithmic primitives* be co-located, or split?
2. Where do *failure codes* live — alongside conduct, or in their own surface?
3. Should *adoption guides* be in the README, or first-class folders?

The wrong answer to any of these would make the framework either unusable for newcomers (everything in one giant doc) or unmanageable for maintainers (each module mixing rules, math, and code).

## Decision

Four top-level surfaces, each with a single role:

- **`conduct/`** — behavior rules. What the agent should do or avoid.
- **`engines/`** — math-grounded primitives. What the agent should compute.
- **`taxonomy/`** — failure-code catalog. How the agent classifies what went wrong.
- **`recipes/`** — host-specific adoption guides. How a project picks the framework up.

Cross-cutting docs (`README.md`, `glossary.md`, `anti-patterns.md`, `CLAUDE.md`) live at the root.

Layering invariants (see [`../architecture/README.md`](../architecture/README.md) § Layering invariants):

- Conduct never embeds engine math.
- Engines never reference conduct decisions.
- Taxonomy never references project-specific paths.
- Recipes never invent new rules.

## Consequences

### Good

- **Each layer is auditable on its own terms.** A reviewer can validate engine math without knowing the conduct rules; a reader can adopt the conduct without learning the engines.
- **Growth is local.** New conduct modules don't conflict with new engines. New failure codes don't conflict with new recipes.
- **Cross-references are deterministic.** Always one folder up + sibling, or sibling. No deep nesting.
- **Renames are bounded.** Renaming an engine doesn't ripple into conduct (conduct mentions the engine *by topic*, not by file path beyond a single link).

### Bad

- **Some duplication.** A reader wanting "everything I need to know about destructive ops" reads `conduct/verification.md` (the rule), `taxonomy/f10-destructive-without-confirmation.md` (the failure mode), and `recipes/<host>.md` (the wiring). Three files, one topic. The aggregate `anti-patterns.md` and `glossary.md` mitigate this.
- **More folders to find your way around.** A flatter structure would be easier on day one but harder on month six.
- **The line between conduct and engines isn't always clean.** Some primitives (LCS-based drift detection, EMA-driven cooldowns) sit at the boundary. We pick one folder per primitive and document the choice in the doc itself.

### Neutral

- **Recipes are the most volatile.** As host platforms evolve (Claude Code, Cursor, the Agents SDK, Cline, etc.) recipes will need updates more often than the rest. Their separate folder makes that visible without polluting the stable layers.
- **No `lib/` or runnable code.** Reference implementations of engines are valuable but language-bound. Keeping them out of this repo keeps the framework portable; if demand grows, they ship in a sibling repo.

## Alternatives considered

1. **Two-layer (conduct + engines).** Merging taxonomy into conduct as a single failure-modes module. Rejected because the catalog wants to grow per-code with examples and adjacent-codes discussion that doesn't fit a single conduct module.
2. **Five-layer (add `evals/`).** Considered for evaluating whether agents under the framework actually obey it. Rejected for v1 because evals are language-bound and adopter-specific; revisit if a community-shared eval harness emerges.
3. **Flat: every doc at the root.** Rejected for discoverability — newcomers need folder names to navigate.

## Revisit when

- Reference implementations grow into a meaningful surface (consider `lib/` or a sibling repo).
- A new layer of artifacts emerges (e.g., per-host eval suites, prompt templates, agent benchmarks).
- A boundary between conduct and engines starts producing repeated arguments — that's a sign the layering is wrong, not that the contributor is.
