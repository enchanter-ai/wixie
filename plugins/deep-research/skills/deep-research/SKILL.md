---
name: deep-research
description: >
  Deep research engine (E0) that produces a verified, cited claims artifact
  before prompts are engineered. Decomposes the query, fans out parallel
  Haiku fetchers, triangulates claims across independent sources, synthesizes,
  and verifies every claim traces to a fetched quote.
  Auto-fires inside /create when the topic depends on external or
  time-sensitive facts. Also callable standalone.
  Auto-triggers on: "/deep-research", "/research", "research this topic",
  "look up the current state of", "what's the latest on", "fact-check this",
  "find sources on", "before we craft the prompt, research".
  Do not use for static topics (pure logic, timeless writing tasks) or when
  a fresh brief already exists (freshness < 30 days) — reuse it.
  Do not use to render an existing brief — use /research-render for that.
allowed-tools: Read, Write, Grep, Glob, Agent, Bash(mkdir *)
---

# Deep Research (E0)

Produces the factual ground truth that E1–E6 score against. Every load-bearing claim in `claims.json` has at least two independent sources, or is explicitly flagged low-confidence.

Execute Phases 1–6 in order. Do not skip Phase 6.

## Inputs

- `<topic>` — slug or free-text topic
- Optional: `--depth quick` — single-round, skip gap-fill. Default: full depth.
- Optional: `--render` — also run `/research-render` at the end. Default: skip; render on demand.

## Output shape

```
state/briefs/<slug>/
├── claims.json       structured triangulated claims (machine-facing — /create reads this)
├── sources.jsonl     raw source-level findings
└── trace.json        per-phase execution trace + verdict
```

`report.md` is produced separately via `/research-render`.

## Agent tier map (summary)

| Phase | Tier | How it runs |
|-------|------|-------------|
| 1 Decompose | Opus (orchestrator, inline) | Direct — the caller is already Opus |
| 2 Cast | Haiku × N | Parallel `Agent` calls to `agents/fetcher.md` |
| 3 Triangulate | Sonnet | One `Agent` call to `agents/triangulator.md` per round |
| 4 Gap-fill | Opus decides, Haiku fetches | Orchestrator evaluates triangulator's `stop_recommended`; if continue, spawns more fetchers |
| 5 Synthesize | Opus (inline) | Direct — writes `claims.json` |
| 6 Verify | Haiku | One `Agent` call to `agents/verifier.md` |

---

## Phase 1 — Decompose (Opus, inline)

Opus expands the raw topic into sub-questions. No tools; judgment only.

1. Classify topic type: `model-capability` | `api-behavior` | `benchmark` | `library-usage` | `competitive-landscape` | `deprecation-status` | `other`.
2. Produce 3–7 sub-questions, each with a one-line acceptance criterion.
3. Produce 2–5 seed search queries per sub-question.
4. Write the decomposition to `trace.json` under `phase1`.

**Stop condition:** every sub-question has an acceptance criterion and ≥ 2 seed queries.

---

## Phase 2 — Cast (parallel Haiku fetchers)

One `Agent` call per seed query, all in a single message (parallel dispatch). Reference the fetcher agent:

```
Agent(subagent_type="general-purpose", model="haiku",
      prompt="Run the fetcher agent defined at
              ${CLAUDE_PLUGIN_ROOT}/agents/fetcher.md
              with query='<query>' and sub_question='<sq text>'.")
```

Aggregate all fetcher JSON returns into `sources.jsonl`, one source per line, assigning `id: S1..SN`.

**Stop condition:** every seed query has been dispatched and returned (or erred with `"unfetchable"`).

---

## Phase 3 — Triangulate (Sonnet)

```
Agent(subagent_type="general-purpose", model="sonnet",
      prompt="Run the triangulator agent defined at
              ${CLAUDE_PLUGIN_ROOT}/agents/triangulator.md
              with sources_path='<absolute path to sources.jsonl>',
              round=<N>, sub_questions=<json from phase1>,
              prior_claim_count=<N or 0>.")
```

Save the returned JSON to `trace.json` under `phase3_round<N>`.

---

## Phase 4 — Gap-fill (orchestrator decides)

Read the triangulator's `stop_recommended`. If `false`:

1. Generate new seed queries targeting `coverage_gaps` and `unresolved_contradictions` (2–3 new queries per uncovered sub-question).
2. Return to Phase 2 with the new queries.
3. Re-run Phase 3 with incremented `round` and updated `prior_claim_count`.

**Stop** when triangulator reports `stop_recommended: true` (τ ≥ 0.85 ∧ no contradictions, OR saturation_delta < 0.1, OR round ≥ 3).

Log each round to `trace.json`.

---

## Phase 5 — Synthesize (Opus, inline)

Opus writes `claims.json` from the final triangulator output. Structure:

```json
{
  "topic": "<slug>",
  "generated": "<today>",
  "freshness": "<today>",
  "triangulation_score": <0..1>,
  "verdict": "READY|PARTIAL|FAIL",
  "source_count": <N>,
  "claims": [
    {"id": "C1", "claim": "...", "sq": "sq1|sq2|sq3",
     "supporting": ["S1", "S3"], "independent_count": 2,
     "confidence": "high|medium|low", "contradicts": null}
  ],
  "unresolved_contradictions": [...],
  "coverage_gaps": [...],
  "sub_questions": [<from phase1>]
}
```

This is the machine-facing artifact. `/create` reads it and folds high-confidence load-bearing claims into the prompt's `<context>`. Human readers invoke `/research-render` to produce `report.md`.

---

## Phase 6 — Verify (Haiku)

```
Agent(subagent_type="general-purpose", model="haiku",
      prompt="Run the verifier agent defined at
              ${CLAUDE_PLUGIN_ROOT}/agents/verifier.md
              with target_path='<absolute path to claims.json>'
              and sources_path='<absolute path to sources.jsonl>'.")
```

If `verify_passed: false` → this is F02 fabrication. Delete the offending claims from `claims.json`, log to `state/precedent-log.md`, re-run Phase 6. Do not ship unverified briefs.

Update `claims.json` metadata with final `verdict` and `triangulation_score`.

---

## Verdict

| Verdict | Criteria |
|---------|----------|
| **READY** | verify_passed = true AND τ ≥ 0.85 AND no unresolved contradictions |
| **PARTIAL** | verify_passed = true AND (τ < 0.85 OR contradictions remain) — usable but flagged |
| **FAIL** | verify_passed = false — regenerate, do not ship |

PARTIAL is a valid hand-off. The `/create` caller folds the high-confidence claims into `<context>` and surfaces the low-confidence ones as constraints.

---

## Handoff to /create

`/create`'s Phase 2.7 reads `claims.json` directly and:
1. Filters to claims with `independent_count >= 2` (high-confidence).
2. Folds those as bullets into the prompt's `<context>` or sandwich-middle.
3. If `verdict: PARTIAL`, adds a one-line note to `<constraints>` listing the uncovered sub-questions.

Metadata passed forward:
```json
"research_claims": "plugins/deep-research/state/briefs/<slug>/claims.json",
"research_freshness": "<YYYY-MM-DD>",
"triangulation_score": <0..1>
```

If `freshness < 30 days`, `/create` reuses `claims.json` without re-running E0. Otherwise regenerates.

---

## Failure modes

| Code | Signature | Counter |
|------|-----------|---------|
| F02 | Claim in `claims.json` with no trace to `sources.jsonl` | Phase 6 blocks it; delete and regenerate |
| F11 | Triangulation gamed by transitive cites | Triangulator independence rule collapses them |
| F13 | Long page polluted findings | Fetcher returns quote + claim only |
| F14 | Brief cites retired API / deprecated flag | Source `date` weighted by triangulator |

Log occurrences to `state/precedent-log.md` per `@shared/foundations/conduct/precedent.md`.

---

## Anti-patterns

- **Shipping claims.json without Phase 6.** Self-certification is not verification.
- **Treating τ ≥ 0.85 as the only shippable state.** PARTIAL briefs are valid outputs, flagged.
- **Fetching the whole page.** Fetcher returns quote + claim. Page dumps pollute context.
- **Single-round research on a fact-heavy topic.** If τ < 0.85 on round 1 and saturation_delta is high, gap-fill.
- **Silent contradiction resolution.** If sources disagree, surface both. The developer decides.
- **Regenerating a fresh brief.** If `freshness < 30 days`, reuse. Re-running burns tokens without new signal.
- **Writing `report.md` from this skill.** Rendering is `/research-render`'s job — separation of concerns.
