# Research Pipeline — Multi-Phase Web Research Discipline

**Governing rule:** Every full-depth run MUST complete all six phases (**Decompose → Cast → Triangulate → Gap-fill/adversarial → Synthesize → Verify**, incl. sub-phase 6c CIBER), all work-budget floors, and ≥ 15 min wall-clock. A run that misses any single floor is HOLD — not a downgraded pass.

Audience: any agent or skill running a **multi-phase web-research operation** — decomposing a topic, dispatching parallel fetchers, triangulating findings, synthesizing claims, verifying citations. Sits above `web-fetch.md` (single-page hygiene): this one governs the *pipeline* across many fetches and many phases.

## The six-phase shape

| Phase | Tier | Output | What advances the run |
|-------|------|--------|------------------------|
| 1 Decompose | Orchestrator (Opus/top) | Sub-questions + seed queries | All SQs have acceptance criteria + ≥ N queries |
| 2 Cast | Parallel Haiku fetchers (≤ 8 concurrent) | Sources file (`sources.jsonl`) | All seed queries dispatched and returned/erred |
| 3 Triangulate | Sonnet (single) | Claim graph + τ + stop_recommended | Claims merged with independence checks |
| 4 Gap-fill + adversarial round | Orchestrator + Phase 2/3 dispatch | New seed queries + re-triangulation | Round ≥ 2 completed |
| 5 Synthesize | Orchestrator inline | Claims artifact (`claims.json`) | Triangulator output codified |
| 6 Verify | Haiku | Trace check + re-fetch sample | `verify_passed: true` |
| 6c CIBER (multi-aspect interrogation) | Haiku | Paraphrase / negation / scope-shift re-framing of top claims against the existing corpus | `ciber_passed: true` (mandatory at full depth; skipped at `--depth quick`, matching the Phase 6b re-fetch carve-out) |

`WebFetch` lives only in Phase 2 (fetcher) and Phase 6 (verifier re-fetch). See [web-fetch.md](./web-fetch.md) for who may call it. Phase 6c is read-only over the existing `sources.jsonl` — no new fetches.

## Work-budget floors (full depth — non-negotiable)

| Floor | Minimum | Why |
|---|---|---|
| Sub-questions emitted (Phase 1) | **≥ 5** | Topic decomposition that hides under 5 SQs is undercut, not deep |
| Seed queries per SQ (round 1) | **≥ 4** | Single-source-per-SQ collapses to non-independence at triangulation |
| Total round-1 fetcher dispatches | **≥ 20** | The multiplication is the floor |
| Sources persisted (`sources.jsonl`) | **≥ 30** | Independence checks need a deduplicated population with redundancy |
| Triangulation rounds | **≥ 2** | Round-1 cannot stop the loop regardless of τ — adversarial round is mandatory |
| Adversarial counter-queries (round 2) | **≥ 1 per SQ** | Round 2 hunts evidence *contradicting* round-1 high-confidence claims |
| Re-fetch sample (Phase 6) | **≥ 10% of cited URLs, min 3** | Verifier confirms the live web still says what we cited |
| Total wall-clock | **≥ 15 min** (full depth only — see below) | Sub-15-min full-depth runs didn't fetch real evidence — emit HOLD with `cause: wall-clock-floor-violation` |

**Wall-clock floor applies to `--depth full` only.** Quick-depth runs (`--depth quick`/`--depth shallow`) are wall-clock-**exempt**: their work-floor is enforced by the query/source counts in the quick-depth carve-out below, not by elapsed time. A 2–3 min quick-depth run that hits 6 fetchers × 1 round × ≥ 6 sources is legitimate; flagging `wall_clock_floor_met: false` on a quick-depth run is honest, not a HOLD trigger. F12.2 fires on full-depth violations only.

`quick` depth carve-out: 3 SQs × 2 queries = 6 fetchers, 1 round, no adversarial pass, no re-fetch sample, no Phase 6c CIBER pass, **no wall-clock floor** (work-floor enforced by query/source counts above). Quick briefs ship as `PARTIAL_QUICK` and never satisfy a freshness-reuse window.

## Round-2 protocol (the adversarial round)

Round-2 emission has two query families, both required:

1. **Gap-fill queries** — target `coverage_gaps` and `unresolved_contradictions` from round-1 triangulator (≥ 2 new queries per uncovered SQ).
2. **Adversarial counter-queries** — for each round-1 high-confidence claim, generate **≥ 1 query that actively hunts contradicting evidence**. Phrase as "is X false / disputed / outdated" or "counter-evidence against X". This is the round that catches survivor bias.

Round-1 stops are forbidden — even at τ = 1.0 and zero contradictions. The triangulator MUST emit `stop_recommended: false` on round 1. F12.1 covers round-1-stop violations.

Round 3 is optional. Run it only when round-2 triangulator reports `stop_recommended: false` AND `saturation_delta ≥ 0.1`. Otherwise stop and accept PARTIAL.

## Stop conditions

| Verdict | Criteria | Action |
|---|---|---|
| **READY** (full depth) | round ≥ 2 AND τ ≥ 0.85 AND no unresolved contradictions AND refetch_pass_rate ≥ 0.9 AND `verify_passed: true` AND `ciber_passed: true` AND all floors met | Ship |
| **PARTIAL** | round ≥ 2 AND (τ < 0.85 OR contradictions remain OR `ciber_passed: false`) AND floors met | Ship flagged — usable but qualified |
| **PARTIAL_QUICK** | quick depth completed | Ship flagged — never satisfies freshness-reuse |
| **HOLD** | Any floor violated (wall-clock, query count, source count, re-fetch sample, missing Phase 6c CIBER pass at full depth) | Re-dispatch the offending phase; do not ship |
| **FAIL** | verify_passed = false OR refetch_pass_rate < 0.7 | Regenerate; do not ship |

Phase 6c is mandatory at full depth: a full-depth brief missing a `ciber_passed` field (`true` or `false`) is a floor violation — verdict is HOLD until Phase 6c completes. Skipping Phase 6c requires one of three explicit conditions: `--depth quick`, fewer than 2 `confidence: high` claims, or Phase 6b hard-fail (`refetch_pass_rate < 0.7`). Each skip MUST be recorded in `trace.json` as `ciber_skipped: "<reason>"`.

## Failure modes

| Code | Signature | Counter |
|------|-----------|---------|
| F02 | Claim with no trace to sources | Phase 6 trace check blocks it; regenerate |
| F12 | Round 3 still below τ 0.85 — iterated indefinitely | Accept PARTIAL after round 3 hard cap |
| F12.1 | Round-1 triangulator reported `stop_recommended: true` skipping adversarial round | Round 1 stops are forbidden by contract; minimum 2 rounds at full depth |
| F12.2 | Wall-clock under 15 min on full-depth — synthesis happened without real fetching | Emit HOLD `cause: wall-clock-floor-violation`; investigate which phase short-circuited |
| F12.3 | Full-depth brief shipped without Phase 6c CIBER pass — paraphrase-fragile claims may be in the verdict | Re-dispatch Phase 6c against the existing `claims.json` + `sources.jsonl`; re-evaluate the verdict with `ciber_passed` set; downgrade to PARTIAL on any consistency failure (no re-fetching required — Phase 6c is read-only) |
| F11 | Triangulator counted vendor's blog + same vendor's docs as 2 independent sources | Same vendor → 1 source (see [source-discipline.md](./source-discipline.md)) |

## Cross-session memory

The six-phase pipeline is amnesiac by default — each run starts fresh. A research engine **may** wire a cross-session memory loop on top of the pipeline to accumulate evidence across runs (recurring contradictions, chronically unfetchable domains, claims prone to round-2 flips). The wiring is engine-agnostic; the shape is identical whether the substrate is wixie's inference-engine, a hydra learnings store, a lich review log, or a pech precedent file.

The pattern has two hooks bracketing the six phases:

| Hook | Position | Direction | Purpose |
|---|---|---|---|
| **Read-at-start** | Before Phase 1 (Decompose) | Substrate → engine | Surface elevated patterns from prior runs as **advisory** input to SQ generation and seed-query routing |
| **Emit-on-finish** | After Phase 6 (Verify) | Engine → substrate | Append artifacts that document this run's cross-session-worth-emitting patterns (contradictions persisting, domains rotting, claims with high inter-source disagreement) |

### Read-at-start contract

The briefing is **advisory, never load-bearing**. Two rules are absolute:

1. **Floors are unchanged.** Any briefing suggestion that would reduce a floor below its documented minimum (e.g., "three SQs is enough") is **ignored**. The work-budget floors (≥ 5 SQs, ≥ 20 round-1 dispatches, ≥ 30 sources, ≥ 2 rounds, ≥ 15 min) are the contract; the briefing influences *what to research* (SQ framing, domain selection, adversarial focus), not *how much*. Honest numbers over substrate compliance.
2. **Existence is optional.** If the substrate file is missing, empty, a placeholder, or the substrate's opt-in gate is off, the engine proceeds to Phase 1 without error. Absence is not a failure.

### Emit-on-finish contract

Every write to the substrate goes through the substrate's own engine entry point — never by appending to its raw log directly. The engine's honest-numbers contract (whatever the substrate enforces: atomic writes, fingerprints, SPRT walks, decay weights) is preserved only if its API is the sole writer.

A pattern is emit-worthy only when all three hold:

1. **Cross-session relevant** — a future run on a similar topic could re-encounter the pattern.
2. **Has a counter** — a rule that would prevent or mitigate recurrence.
3. **Has evidence** — an honest count from this run's trace, not a guess.

Typical emit categories for research pipelines:

- **Verdict stability** — same topic hit `PARTIAL` in N consecutive runs ⇒ topic is inherently contested; future runs should plan for PARTIAL up front.
- **Domain fetchability** — a domain showed ≥ 50% unfetchable rate across Phase 2 + Phase 6 ⇒ that domain needs a dedicated fetcher (MCP / Wayback / Playwright) or should be deprioritized.
- **Claim contestedness** — a load-bearing claim with high inter-source disagreement (`dissemination_score` per `source-discipline.md`) ⇒ flag for follow-up adversarial round.
- **Survivor-bias catches** — round-2 adversarial counter-queries that flipped a round-1 high-confidence claim ⇒ track which SQ shapes are most prone to it.
- **Link rot** — Wayback fallbacks that rescued unreachable URLs ⇒ that source-class is link-rot-prone; preflight similar URLs next time.

Engines should publish a small **code prefix taxonomy** (e.g. wixie deep-research uses `DR01`–`DR05`) so emitted artifacts compound under stable SPRT walks rather than fragmenting.

### Recursion bound (depth-1 hard rule)

The memory loop watches itself: a poisoned briefing — one that biases the next run's SQ generation toward the wrong conclusion — looks like an emit-worthy pattern. **It is not.**

**No depth-2 recursion.** Never emit an artifact describing a failure in the read-at-start/emit-on-finish hook itself. If the briefing is actively biased — ≥ 2 high-weight patterns all pointing one direction on a topic the current evidence contradicts — escalate to the human owner via the substrate's documented escape valve (e.g. wixie's `inference.escape-valve` file touch). Do **not** override or counter-emit through the substrate.

The escape-valve trigger is conservative: fire it only when the loop is provably poisoning itself (bias criterion above met), not on routine disagreement. Routine disagreement downgrades the pattern over time via the substrate's own decay mechanism.

### Engine-portability

The hook shape is the same across plugins. Hydra, lich, pech, robit research loops can adopt this pattern by:

1. Pointing the read-at-start hook at their own briefing surface.
2. Pointing the emit-on-finish hook at their own substrate's engine.
3. Choosing their own DR-equivalent code prefix (e.g. `HR01`, `LR01`).
4. Keeping the floor-protection rule verbatim — the briefing advises *what*, never *how much*.

## Scheduled validation

The pipeline is amnesiac per-run (above), but the *engine itself* — fetchers, triangulator, verifier, schema — drifts over time as the web changes, models are revised, and the code is refactored. **Scheduled validation** is the read-only counter: a recurring quick-depth dispatch against a small set of canary topics whose answers are documented and stable, with baselined τ / sources_count / verdict / wall-clock thresholds. Drift from those baselines is an early-warning signal that something in the pipeline regressed before a real research run is affected.

### Why it exists

Research-pipeline regressions are usually silent. A fetcher routing change that downgrades arXiv source weighting still produces a brief — just with quieter, less-cited claims. A triangulator schema bump that drops `tau` from the trace still produces a brief — but every downstream consumer that reads `trace.json` for `tau` starts seeing `None`. Neither failure is visible from a single run; both are obvious from comparing successive runs of the same canary.

The validation routine doesn't replace the verifier (Phase 6). It complements it: the verifier confirms one run's claims trace to live sources; scheduled validation confirms one run's *pipeline shape* matches prior runs' shapes.

### What counts as drift (quick-depth canary contract)

A scheduled-validation run is drift-flagged if **any** of the following hold, against the canary's documented baselines:

| Signal | Drift threshold |
|---|---|
| Verdict | not `PARTIAL_QUICK` (quick-depth runs cannot satisfy READY/PARTIAL; anything else means a verdict-classification regression) |
| τ | drift > 0.15 absolute from `baseline_tau` |
| sources_count | below `baseline_sources_count_min` |
| claims_count | below `baseline_claims_min` |
| wall_clock_ms | below 60_000 (quick-depth floor — under one minute means a phase short-circuited) |
| Dispatch | status != "ok" (sub-worker blocked or errored) |
| Schema | `claims.json` parse error or `trace.json` missing the verdict/τ keys |

Baselines per canary live in `wixie/shared/scheduled-validation-canaries.json`; drift tolerances live in `wixie/shared/scripts/scheduled-validation.py`.

### Operator action on drift

1. Re-run the same canary manually in foreground: `python shared/scripts/scheduled-validation.py --canary <slug>`. Single transient runs sometimes flag (rate-limit retry burned the budget, a fetcher returned a 503 — none of which mean the pipeline regressed).
2. If the regression reproduces, read the drift report at `state/roadmaps/scheduled-validation-drift-YYYY-MM-DD.md` and diff the new `state/briefs/<slug>/claims.json` against the previous commit's version.
3. Identify the offending phase (Decompose / Cast / Triangulate / Synthesize / Verify) from `trace.json`.
4. Open a P1 against the offending phase. Suspend further scheduled-validation runs until the regression is fixed, otherwise the routine just emits the same drift report nightly.

### Cost envelope (honest)

Each canary run at `--depth quick` is ~6 Haiku fetchers + 1 Sonnet triangulator + 1 Haiku verifier. Via the `dispatch-via-cli.py` shim that's roughly **$1-3/run**. Full depth would be $5-15 and is explicitly disallowed for the routine — full-depth validation is a principal-initiated action, not a cron job.

A 5-canary rotation run daily costs $5-15/day; weekly costs $1-3/week. The 5-canary list shape and round-robin index are documented in the canary config.

### Operator wiring (cron/systemd is a follow-up)

The `scheduled-validation.py` script itself **does not install itself as a cron or systemd job**. That decision — frequency, alert routing, whether to gate on the `WIXIE_INFERENCE_ENABLED` env flag, where to surface drift reports — is intentionally left to the operator. The deliverable in this repo is the scaffold; the cron/systemd unit is a follow-up step the operator owns.

## Anti-patterns

- **Round-1 stop on high τ.** PROHIBITED. Self-check: `rounds_completed >= 2` before synthesis? If no, the adversarial round was skipped — re-dispatch.
- **Padding seed-query count with paraphrases.** PROHIBITED. Each query per SQ must differ in terms, framing, or source-type bias — synonym rewrites do not count toward the ≥ 4 floor.
- **Single-round full-depth research.** PROHIBITED. Self-check: `wall_clock_seconds >= 900` AND `rounds_completed >= 2`? If either fails, emit HOLD.
- **Skipping the adversarial counter-query pass.** PROHIBITED. Round-2 MUST include ≥ 1 counter-query per high-confidence claim hunting contradicting evidence, not more confirming evidence.
- **Silent contradiction resolution.** PROHIBITED. When round-1 and round-2 disagree, the disagreement MUST appear in `unresolved_contradictions` — never papered over in synthesis.
- **Calling top-tier `WebFetch` from the orchestrator.** PROHIBITED. Fetching belongs to Phase-2 Haiku fetchers. See [web-fetch.md](./web-fetch.md).
- **Citing without re-fetching at Phase 6.** PROHIBITED. Self-coherence ≠ verification. See [citation-verification.md](./citation-verification.md).
- **Relaxing work-budget floors on briefing advice.** PROHIBITED. A briefing influences SQ framing and domain selection only — never the floor values. Self-check: did any floor drop below its documented minimum due to briefing input? If yes, revert and rerun.
- **Appending directly to the substrate's raw log.** PROHIBITED. Every write goes through the substrate's engine entry point. Self-check: was `inference-engine.py emit` (or the equivalent substrate API) the sole writer? If no, the honest-numbers contract is broken.
- **Counter-emitting through the substrate to fix a bad briefing.** PROHIBITED. No depth-2 recursion. If the loop is poisoning itself (≥ 2 high-weight patterns contradicted by current evidence), escalate via the substrate's escape valve — never emit an artifact whose subject is a failure in substrate-failure handling.

---

## Hard rules (U-curve close)

1. Every full-depth run: all 6 phases (Phase 4 = adversarial round; Phase 6c = CIBER) + all floors + ≥ 15 min wall-clock. Miss any one → HOLD.
2. Round 1 never stops, even at τ = 1.0. Triangulator MUST emit `stop_recommended: false` on round 1.
3. Phase 6c (CIBER) is mandatory at full depth. Missing `ciber_passed` field → HOLD until dispatched.
4. The cross-session briefing advises *what* to research, never *how much*. Floors are immutable by the briefing.
5. All substrate writes go through the engine API. No direct log appends.
6. No depth-2 recursion in the memory loop. Substrate poisoning → human escalation, not counter-emit.
