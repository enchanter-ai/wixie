# Architecture

How the four moving parts of agent-foundations compose. Read once; reference when extending.

## The four parts

```
┌──────────────────────────────────────────────────────────────────┐
│                         agent-foundations                          │
└──────────────────────────────────────────────────────────────────┘
                                │
        ┌──────────────────┬────┴────┬──────────────────┐
        ▼                  ▼         ▼                  ▼
   ┌─────────┐        ┌─────────┐  ┌──────────┐    ┌─────────┐
   │ conduct │        │ engines │  │ taxonomy │    │ recipes │
   │ (rules) │        │ (math)  │  │ (codes)  │    │ (hosts) │
   └─────────┘        └─────────┘  └──────────┘    └─────────┘
        │                  │            │                │
        │ "what to do"     │ "what      │ "what failed"  │ "where to
        │                  │  to        │                │  drop it"
        │                  │  compute"  │                │
```

| Layer | Surface | Role |
|-------|---------|------|
| `conduct/` | 19 rule modules | What the agent should do or avoid |
| `engines/` | 12 algorithm docs | What the agent should compute |
| `taxonomy/` | 21 failure-code docs (+ axes.md) | How the agent names what went wrong |
| `recipes/` | 8 host adoption guides | How a project picks up the framework |
| `runbooks/` | 21 incident-response runbooks | How to triage and recover per failure code |

`anti-patterns.md` and `glossary.md` cross-cut all four.

## Composition: who calls whom

**Engines compute. Conduct governs. Taxonomy classifies. Recipes wire.**

A typical call path in production:

1. **Conduct** says: *"Before any destructive op, verify."*
2. **Engine** computes: *"Trust score for this file is 0.18 (Beta-Bernoulli over recent change history)."*
3. **Conduct** decides: *"Score < 0.2; this is a critical band; require explicit confirmation."*
4. If the agent skips the confirmation:
5. **Taxonomy** classifies: *"That was F10 destructive-without-confirmation."*
6. The failure log gets an entry tagged F10. Future sessions read it before the same kind of op.

No engine runs decisions; no conduct does math; no taxonomy code executes anything. The separation is the design — each layer is auditable on its own terms.

## Why these four (and not three or five)

- **Why not just conduct?** Conduct without engines is hand-wavy — *"check trust"* with no formula is a heuristic. Engines give the rules teeth.
- **Why separate taxonomy?** Codes are reused across many conduct modules. Promoting them to their own surface lets the catalog grow independently and supports per-code drilldown that doesn't fit in a behavior module.
- **Why recipes?** The framework is host-agnostic by design, but adoption is host-specific. Recipes make the wiring explicit so adopters don't have to re-derive it.
- **Why not include reference implementations or evals?** Both are valuable. Both are also language-bound and project-specific. Keeping the core layers data/prose-only makes the framework portable; reference implementations live in adopter projects (or in a sibling repo if demand grows).

## Layering invariants

These hold at all times. Violations are bugs.

1. **Conduct never imports engines as decision-makers.** A conduct module can *reference* an engine ("compute trust score X") but does not *embed* it ("if α/(α+β) < 0.2"). The math stays in the engine doc.
2. **Engines never reference conduct.** Engines describe *how to compute*, not *what to do with the result*.
3. **Taxonomy never references project-specific paths.** A failure code is project-agnostic; specific examples may name `Glob` or `Read` (universal tool primitives), but never `wixie/state/...` or `myproject/scripts/...`.
4. **Recipes never invent rules.** Recipes are wiring guides — they show how to load existing modules into a host. New rules belong in conduct.

## Cross-references

Cross-refs across folders use relative paths:

- Inside the same folder: `./X.md`
- One folder up + sibling: `../engines/X.md`, `../conduct/X.md`
- Never absolute paths, never repo-rooted (`/conduct/X.md`)

This keeps the repo movable. If a fork relocates the folders, only one search-and-replace fixes references.

## Extending

| Adding a new… | Goes in | PR template |
|---------------|---------|-------------|
| Behavior rule | `conduct/<name>.md` | Justify why it doesn't fit an existing module |
| Algorithm | `engines/<name>.md` | Reference paper + complexity + failure modes |
| Failure code | `taxonomy/f<NN>-<slug>.md` + index update | 3+ independent observations + testable counter |
| Host integration | `recipes/<host>.md` | Concrete adoption steps + verification check |
| Architectural decision | `docs/adr/<NNNN>-<slug>.md` | Context, decision, consequences |

Adjacent docs that *describe* the framework but aren't part of it (this file, `anti-patterns.md`, `glossary.md`) live at the repo root or in `docs/`.

## Stability commitments

- **Conduct module names** are stable. Renaming `discipline.md` would break every adopter's `CLAUDE.md`.
- **Taxonomy F-codes** are append-only. F03 is always context-decay. F22+ is for new patterns; existing codes are not renumbered.
- **Engine names** can be renamed if the algorithm name is wrong. Document the rename in an ADR.
- **Recipe paths** are loose; recipes are the most volatile surface and may be split or merged as host platforms evolve.

## What this architecture is *not*

- Not a runtime. Nothing here executes. The framework provides text; the runtime is the host.
- Not a complete agent system. Adopters bring their own orchestration, tool implementations, and evals.
- Not a substitute for evals. Defaults shift behavior on average; per-task evals own task quality.
