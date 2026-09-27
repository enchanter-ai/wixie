# wixie-deep-research

**E0** of Wixie's engine stack — factual ground truth before prompts are engineered.

Decomposes a topic, fans out parallel web fetchers, triangulates claims across independent sources, synthesizes structured findings, and verifies every claim traces to a fetched quote. Auto-fires inside `/create` when the topic depends on external or time-sensitive facts.

## Skills

| Command | Role |
|---------|------|
| `/deep-research <topic>` | Full 6-phase loop. Produces `claims.json`, `sources.jsonl`, `trace.json` |
| `/research-render <slug>` | Transform `claims.json` into a human-readable `report.md` |
| `/research-query "<question>"` | Search existing briefs without regenerating |
| `/research-refresh` | Audit brief freshness; flag stale (>30d) briefs |

## Agents

| Agent | Tier | Role |
|-------|------|------|
| `fetcher` | Haiku | One WebSearch + 2-3 WebFetches per seed query; returns structured findings |
| `triangulator` | Sonnet | Merges claims across sources, checks independence, detects contradictions, computes τ |
| `verifier` | Haiku | Confirms every cite traces to a source finding; blocks shipping on F02 fabrication |

Opus is the orchestrator — it runs Phase 1 (decompose) and Phase 5 (synthesize) inline. No separate Opus agent exists because the caller is already Opus.

## Artifacts per topic

Briefs live in the plugin data directory, never in the installed plugin tree (WIX-SEC-WS-001):

```
${CLAUDE_PLUGIN_DATA}/briefs/<slug>/
├── claims.json       structured triangulated claims (machine-facing — /create reads this)
├── sources.jsonl     raw source-level findings
├── trace.json        per-phase execution trace + verdict
└── report.md         human-readable rendering (generated on demand via /research-render)
```

## Verdicts

| Verdict | Criteria |
|---------|----------|
| READY | verify_passed AND τ ≥ 0.85 AND no contradictions |
| PARTIAL | verify_passed AND (τ < 0.85 OR contradictions remain) — flagged, still usable |
| FAIL | verify_passed = false — regenerate, do not ship |

## Auto-fire

Inside `/create` at Phase 2.7 (Research Check), the prompt-creator's Opus orchestrator classifies whether the task depends on external or time-sensitive facts. If yes, it reuses `claims.json` if `freshness < 30 days`, else invokes `/deep-research` and waits for READY or PARTIAL before proceeding to Phase 3.

## Science

Derivation: `docs/science/README.md` § F0 Deep Research. Formally: decompose → cast → triangulate (τ score, independence check) → gap-fill (saturation criterion) → synthesize → verify (every cite traces to quote).
