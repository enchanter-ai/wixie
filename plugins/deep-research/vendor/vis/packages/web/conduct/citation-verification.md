# Citation Verification — Confirming Claims Trace to Live Web

**Governing rule: self-coherence is not verification.** Every cited artifact must pass two mechanical checks — trace check (claim ↔ source shape) and re-fetch check (quote still on the live page) — before `verify_passed: true` is emitted. Neither check is optional at full depth.

Audience: any agent producing a cited artifact (`claims.json`, `report.md`, dossier, briefing) and the **verifier** subagent that confirms each cite is real.

## The rule

A claim with `supporting: ["S3", "S7"]` proves the synthesizer cross-referenced two source IDs — it does not prove the cited *sources* actually back the claim, and it does not prove the cited URLs still exist on the live web.

Verification therefore runs **two mechanical checks**, neither optional at full depth:

1. **Trace check** — every cite resolves to a finding whose subject AND action match the claim
2. **Re-fetch check** — a sample of cited URLs is re-fetched live and the quote substring is confirmed present

Both must pass for `verify_passed: true`.

## Trace check (Step 1) — claim ↔ source matching

For each `(claim, cited_source_id)` pair, apply two boolean tests against the source's `findings`:

| Test | Pass condition |
|------|----------------|
| **A — Subject match** | The finding's `claim` OR `quote` field contains the cited claim's main subject (first non-article noun) — exact string OR obvious synonym |
| **B — Action/property match** | The finding's `claim` OR `quote` field mentions the cited claim's verb or property (paraphrase counts if meaning is clearly the same) |

A cite **PASSES** if at least one finding in the cited source passes BOTH A AND B. A cite **FAILS** if no finding does. Failed cites are violations.

Both tests are mechanical. Boolean only: pass or fail. If the verifier asks "is this fact interesting?" or "is this fact true?" it has lost the contract. Trace check is shape-checking, not judgment.

## Re-fetch check (Step 2) — quote still on the live page

At full depth, the verifier re-fetches `≥ 10%` of cited URLs (random sample, minimum 3 URLs):

```
For each sampled URL:
  1. WebFetch the URL.
  2. If HTTP error / paywall / < 500 words → mark refetch_status: "unreachable", continue.
  3. Otherwise: check if the source's recorded `quote` (verbatim, ignoring the <untrusted_source> wrapper) appears as a substring in the fetched body.
     - Allow whitespace collapsing.
     - No paraphrase tolerance.
  4. Pass = quote present. Fail = quote missing.
```

`refetch_pass_rate` = passes / (passes + fails). Unreachables are excluded from the denominator (inconclusive, not failures) but flagged in `refetch_unreachable`.

Quick depth (`refetch_pct = 0`) skips Step 2 entirely. Quick briefs ship as `PARTIAL_QUICK` and never satisfy a freshness-reuse window.

## Wayback Machine fallback — recovering from source rot

When Step 2 marks a URL `unreachable`, the verifier **probes the Internet Archive** before declaring loss. Empirical operating envelope (validated BG-15, 2026-05-16):

- **WebFetch refuses** the `web.archive.org` host (`Claude Code is unable to fetch from web.archive.org`). Do not attempt WebFetch on archive snapshot URLs — that path is hard-blocked at the harness.
- **The legacy wildcard form** `https://web.archive.org/web/2026*/<url>` returns the Wayback **calendar HTML page**, not a snapshot body. It is a UI accessor, not a content accessor — abandon it.
- **The plain snapshot form** `https://web.archive.org/web/<TS>/<URL>` returns the snapshot wrapped in Wayback chrome/banner JS, mixing archive UI with archived content.
- **The Memento aggregator** (`timetravel.mementoweb.org`) was NXDOMAIN at validation time; do not rely on it.
- **The CDX search API** (`web.archive.org/cdx/search/cdx?...`) works but is slow (~45 s p50) — use only as last-resort fallback when the availability API returns no snapshot.

The validated two-step protocol uses the `archive.org/wayback/available` availability API (Step A, reachable from WebFetch) **then** rewrites the returned URL to `id_/` raw-content form and fetches with `curl --compressed` (Step B, requires Bash):

```
Primary fetch fails →
  Step A — availability probe (reachable from WebFetch OR Bash/curl):
    GET https://archive.org/wayback/available?url=<original-url>&timestamp=2026
    Parse JSON. If `archived_snapshots.closest.available === true`,
    extract `archived_snapshots.closest.url` as <PLAIN_SNAPSHOT_URL>
    and `archived_snapshots.closest.timestamp` as <TS>.

  Step B — raw snapshot fetch (requires Bash/curl):
    Construct <RAW_URL>: insert "id_" between the timestamp and the original URL.
      Plain:  https://web.archive.org/web/<TS>/<URL>
      Raw:    https://web.archive.org/web/<TS>id_/<URL>
    Bash: curl -sS -L --max-time 30 --compressed -A "Mozilla/5.0 (compatible)" "<RAW_URL>"
    The --compressed flag is REQUIRED; without it the body is returned in
    brotli/zstd encoding and substring matching fails.
    If body ≥ 500 words AND the recorded quote substring is present
      → refetch_status: "pass-via-archive"
    Else if body ≥ 500 words but quote absent
      → refetch_status: "archive-body-recovered-quote-missing"  (likely paraphrase
        in original source; do NOT count toward refetch_pass_rate numerator)
    Else
      → refetch_status: "unreachable"

  If Step A returns `archived_snapshots: {}` (no snapshot ever taken):
    refetch_status: "unreachable"
    archive_status: "no-snapshot-exists"
```

Archive bodies that pass (`pass-via-archive`) count toward `refetch_pass_rate` numerator but are **flagged separately** so consumers see that the live web has rotted away even if the citation was historically real.

Same fallback applies in the fetcher's Step 3 — if a primary `WebFetch` is `unfetchable`, run Step A + Step B before recording `error: unfetchable`. Published evidence (Rao et al., *urlhealth*, arxiv/2604.03173) reports 6-79× recovery of dead URLs when the snapshot body is re-read. **Validated recovery on BG-15's 5-URL sample: 3/5 (60%) body-verified; the remaining 2/5 had no snapshot in the archive at all (URL never crawled), not a protocol failure.** Snapshot-availability is the bound, not protocol soundness.

### Tool-scope requirement (production gate)

Step A is reachable from WebFetch (host `archive.org`, not `web.archive.org`). Step B requires `Bash(curl:*)` because (a) WebFetch is hard-blocked from `web.archive.org`, and (b) `--compressed` is needed to handle Wayback's brotli/zstd-encoded responses. The fetcher and verifier sub-agents must therefore have `Bash(curl:*)` in `allowed-tools`. If the agent runs WebFetch-only, it can only emit `archive_snapshot_available: true` from Step A and MUST NOT claim `pass-via-archive` — that would be a capability-fidelity violation (F22): silently substituting a metadata signal for a body verification.

### CDX last-resort fallback

If the availability API returns no snapshot but the URL is suspected to have one (rare; cdx indexes lag the availability cache by hours), the agent MAY query the CDX search API:

```
Bash: curl -sS -L --max-time 90 --compressed \
  "https://web.archive.org/cdx/search/cdx?url=<URL>&output=json&limit=1&filter=statuscode:200"
```

The response is `[[header_row], [urlkey, timestamp, original, ...]]`. Extract the timestamp from row 1, construct `<RAW_URL>` as above, and proceed to Step B. CDX is the slow path (~45 s); reserve it for cases where availability-API is empty but the URL has plausible crawl history.

## 4-class support taxonomy

Independence-count (in [source-discipline.md](./source-discipline.md)) tells you how *many* sources back a claim. The `support_class` field tells you how *fully* the wording is supported:

| `support_class` | Criterion |
|---|---|
| `Supported` | ≥ 1 cited source contains the claim's subject AND action verbatim or near-verbatim |
| `Partially Supported` | Cited sources back a weaker/narrower version (subject matches; action paraphrased OR scoped down OR qualified) |
| `Unsupported` | Sources only mention the subject area; no specific backing for the claim's action/property |
| `Uncertain` | Cited sources disagree; pair with high `dissemination_score` |

`support_class` is **orthogonal to `confidence`**. A claim can be `high`-confidence (cited well) but `Partially Supported` (the sources back a narrower version than the claim states). Surface both fields downstream; `/create` Phase 2.7 should filter on `support_class = "Supported"` when folding into `<context>`, and surface `Partially Supported`/`Uncertain` as constraints instead of context.

## Support-weighted τ (provenance-aware triangulation)

The base τ formula in [`source-discipline.md`](./source-discipline.md) counts independent supports equally regardless of *how* the supporting source was obtained. That under-punishes degraded supports — snippet-only retentions, pass-via-archive recoveries, summariser paraphrase-extracts — which back a claim less robustly than a raw primary-fetch quote does.

The provenance-aware τ extends the base formula with a per-source `support_weight ∈ (0.0, 1.0]` multiplier. Fetchers record it on `sources.jsonl`; the triangulator ingests it in Step 7a.

### `support_weight` tiers

| Tier | Weight | When it applies |
|------|--------|------------------|
| `raw` | **1.0** | Bash `curl` raw-extract from the primary URL; full body parsed; quote verified as a verbatim substring of the fetched body |
| `summariser` | **0.85** | WebFetch summariser output; quote came through the harness summariser, not raw HTML char-offsets |
| `degraded` | **0.7** | `snippet_only: true` (WebSearch snippet retained because direct fetch was 4xx/blocked), `pass-via-archive` (live URL dead; quote verified against a Wayback snapshot body), or any source flagged with `refetch_status` other than `pass` |

Default when the field is absent on `sources.jsonl`: `support_weight = 1.0` (back-compat; legacy briefs are read as raw). Fetchers SHOULD emit the field explicitly going forward; older briefs are unaffected.

### Extended formula

For each claim, compute a per-claim `claim_support_weight` as the **mean** of `support_weight` across its `supporting[]` sources (mean, not min — a single degraded source out of three should not collapse the whole claim's weight to 0.7). Then:

```
τ = Σ_claims (claim_support_weight × is_cross_confirmed) / |total claims|

where is_cross_confirmed = 1 if independent_count ≥ 2 else 0
```

Equivalent for the partial-support variant used in the wixie triangulator:

```
τ = Σ_claims (claim_support_weight × support_contribution) / |total claims|

where support_contribution = 1.0  if Supported            AND independent_count ≥ 2
                           = 0.5  if Partially Supported  AND independent_count ≥ 2
                           = 0.0  otherwise
```

This collapses to the base formula when every source is `raw` (weight 1.0).

### Calibration anchor (DR-V3, 2026-05-19)

The tier weights are calibrated against DR-V3 (`validation-computer-use-2026-05-19`), where the operator hand-downgraded τ from **0.81 → 0.71** (a 0.10 absolute drop) to honour two degraded supports: S7 (VentureBeat 429 → WebSearch snippet only) and one other F22-adjacent paraphrase-extract.

With the formula above, on a corpus of 13 claims where ~2 contributions trace through one or both degraded sources, applying `degraded = 0.7` to those contributions reproduces a τ-delta in the **0.05–0.11 range** (depending on whether the degraded source backs a `Supported` or `Partially Supported` claim, and on the per-claim mean across its supporting set). The 0.10 hand-downgrade falls squarely inside that envelope. The tiers are honest within ±0.05 of the operator's manual call — tight enough to be useful, loose enough to not pretend it's exact arithmetic.

Calibration error is acknowledged, not papered over: future runs that produce per-source provenance reliably will let us tighten the bracket from ±0.05 to ±0.02 or replace the weighted-mean with a min-over-supports variant if the mean turns out to under-punish single-source degradation.

## Multi-aspect interrogation (CIBER)

Trace check + re-fetch confirm a claim is *attributable* to its cited source. They do not confirm the claim is *stable* under re-framing. A claim that survives the original phrasing but collapses when paraphrased or negated is a consistency failure — the sources support a narrower or different proposition than the claim states. CIBER (arxiv 2503.07937, "Cross-aspect Inter-Behavior Evaluation of Reliability") is the second-pass interrogation that catches this class.

**What it does.** For the top-N high-confidence claims emerging from triangulation + verification, generate K paraphrased and negated re-framings per claim and re-check each re-framing against the *existing* `sources.jsonl` evidence pool. If a paraphrased framing surfaces contradicting evidence — i.e., evidence in the brief's own source set that supports the negation — the claim is flagged as inconsistent.

**When it fires.** After Step 5b re-fetch passes, *before* the verdict is computed. Full depth only; skipped at quick depth. Fixed defaults: `N = 10` top-confidence claims, `K = 3` re-framings per claim (≥ 1 negation, ≥ 1 paraphrase). N is configurable; the floor of N = 10 is the binding constraint.

**What it emits.** A `consistency_failures: [...]` array per claim with:

| Field | Meaning |
|------|---------|
| `claim_id` | The original claim's ID |
| `failed_reframing` | The paraphrase or negation that surfaced contradiction |
| `contradicting_source_ids` | Source IDs whose findings back the negation/alternative |
| `severity` | `negation_supported` (sources back the opposite) \| `paraphrase_split` (sources split across re-framings) \| `temporal_scope_shift` (sources back the claim at *different points in time* — same factual ground, different effective dates) |

**`temporal_scope_shift` distinguished from `paraphrase_split`.** Both surface as a non-negation re-framing finding backing the original claim's negation or alternative. The discriminator is **date-mismatch** between the backing source's `date` (publish date) and the claim's effective date (most recent verified-effective date among supporting sources, or the brief's `generated` date if unspecified): when the backing source pre-dates the claim's effective date AND the re-framing represents a *scope shift over time* (e.g., "X is in effect" → "X was postponed"), severity is `temporal_scope_shift`, not `paraphrase_split`. The factual ground is the same; the wedge is the timeline. Severity precedence remains `negation_supported > paraphrase_split > temporal_scope_shift`.

**Verdict consequence.** Severity drives the demotion (and the verdict-mapping at the SKILL level):

| Severity | `confidence` action | `dissemination_score` | Brief verdict impact |
|---|---|---|---|
| `negation_supported` | `high` → `medium-contested` | +0.25 | brief → PARTIAL (CIBER override) |
| `paraphrase_split` | `high` → `medium-contested` | +0.25 | brief → PARTIAL (CIBER override) |
| `temporal_scope_shift` | `high` → `medium-contested` | +0.25 | **does NOT force PARTIAL**; brief verdict unaffected by this severity alone |

`temporal_scope_shift` demotes the claim's confidence (the wording isn't stable across time) but does NOT flip `ciber_passed` to `false` for the verdict-gate — pre-reversal evidence supporting a now-reversed state is *historically* accurate, not paraphrase-fragile. Surface both positions in the brief (under `contests:` and `unresolved_contradictions`) and let `/create` consume the temporal qualifier. The brief drops to `PARTIAL` only when `negation_supported` or `paraphrase_split` fires.

**What failure modes it catches.**

- **F11.2 — paraphrase-fragile claim.** Original phrasing tags as `Supported`; a negation re-query surfaces ≥ 1 source supporting the opposite. The triangulator's independence count was right; the wording was load-bearing on phrasing that the sources don't actually back.
- **F11.3 — survivor-biased synthesis.** Synthesis kept only the supporting evidence; CIBER's paraphrased re-query pulls the contradicting findings back into view. Complements the round-2 adversarial pass (which generates *new* queries) by re-using the *existing* corpus under different framings.
- **F02.2 — agreement illusion.** ≥ 2 cited sources back the original claim but back *different* propositions under paraphrase — the sources don't actually agree, they appear to because the original query forced a single framing.

**Paraphrase quality contract.** Paraphrases must differ on ≥ 1 of: verb, scope, or explicit negation. Synonym-swap rewording is a no-op — if all K re-framings share the same verb and scope as the original, regenerate. The Haiku-tier agent follows three mechanical patterns and produces exactly one output per pattern: (a) swap the action verb; (b) negate the predicate; (c) widen or narrow the scope.

**Boundary with Phase 6 trace check.** Trace check asks *"does any finding pass tests A+B for the original claim?"* CIBER asks *"does any finding pass tests A+B for the *negated* or *paraphrased* claim?"* If yes for both, the claim is contested — sources support multiple framings. Same mechanical match logic, different query.

**Boundary with Phase 6b re-fetch.** Re-fetch confirms the live web still hosts the quote. CIBER confirms the claim is robust across framings. Re-fetch is about source rot; CIBER is about wording precision. They run in series, both required for a `READY` verdict.

## Code citations — interval arithmetic

When the cited source is a code chunk (a finding from a local repo audit — `lich` review, `hydra` security finding, `gorgon` repo sweep) rather than a web page, substring matching on a quote is the wrong shape. Code chunks identify themselves by file path and line range, not by a verbatim sentence. We instead assert that the cited line range overlaps the retrieved-chunk's line range — a single boolean test, interval arithmetic.

Adapted from arxiv 2512.12117 — "requiring LLMs cite specific line ranges that must overlap retrieved chunks, enforced through interval arithmetic" — which reported zero false negatives across 1,080 verified responses.

**Citation format expected.** A code citation is detected when the source's `findings[].quote` (or the cite itself, for inline `[Sn]` style) contains a `path:line-range` indicator in one of these shapes:

- `path/to/file:start-end` (colon form — e.g., `src/runner.py:42-58`)
- `path/to/file#L<start>-L<end>` (GitHub anchor form — e.g., `src/runner.py#L42-L58`)
- `path/to/file:line` or `path/to/file#L<line>` (single-line form — treated as the degenerate interval `[line, line]`)

The retrieved-chunk range comes from the source record itself — fetchers that surface a code chunk MUST record `chunk_start_line` and `chunk_end_line` on the source. If either field is absent, the interval test cannot run; the verifier records `inconclusive` for that cite and falls back to the subject/action trace check.

**Overlap test.** Let cited range = `[c_start, c_end]` and retrieved-chunk range = `[r_start, r_end]`. The cite passes the interval check iff:

```
c_start <= r_end  AND  c_end >= r_start
```

If both halves hold, the intervals overlap (touching at a single line counts as overlap). If either fails, the cite is outside the retrieved chunk — record violation `F02.3`.

**When this fires.** Only when the cited source's `findings[].quote` includes a `path:line-range` indicator (or the source carries explicit `chunk_start_line` / `chunk_end_line` fields). Otherwise skip — web citations use the existing subject/action match (trace check) and substring re-fetch test. Briefs whose `claims.json` cites web URLs only will never trigger this branch.

**No re-fetch coupling.** Code citations live in a local repository, not the live web. The interval check is purely local arithmetic against the source record — Phase 6b re-fetch / Wayback fallback do not apply. A failed interval check is a fabrication signal (the cite invented or hallucinated a range outside what was retrieved), not source rot.

## Synthesis-prose validation (pre-Phase-6)

Phase 6's trace check is a Haiku-tier semantic match against `findings[].claim` and `findings[].quote`. It's also a paid dispatch. When the synthesizer (Phase 5) emits narrative prose with inline `[S<n>]` cites, a mechanical pre-flight runs **between Phase 5 and Phase 6**, before paying for the Haiku verifier. It catches the same class of failure — cite-ID misattributions in narrative prose — at zero marginal cost.

**What it is.** A mechanical cite-to-source trace test: for every `S<n>` token in the dossier, locate the cited source in `sources.jsonl`, then run a substring/synonym variant of Tests A + B against the surrounding sentence. No semantic judgment, no LLM call, no fuzzy matching beyond a small built-in synonym table (e.g., "uses X" ↔ "employs X"; "5-stage" ↔ "five-stage"). Stdlib-only; reproducible across machines.

**When it runs.** After Phase 5 synthesis writes `report.md` / dossier prose, **before** the Phase 6 verifier is dispatched. The orchestrator runs the validator inline, reads the JSON output, and either (a) accepts the prose and dispatches Phase 6, or (b) rewrites the flagged sentences before dispatching. The pre-check shortens the synth → Phase 6 → re-synth loop by catching the obvious misattributions without paying for a Haiku round-trip.

**What it catches.** Cite-ID misattributions in narrative prose — the exact failure class Phase 6 catches, but at write-time. Empirically (BG-18 validation, 2026-05-16) the mechanical superset reproduces 6/6 violations a Haiku verifier had already flagged on a real dossier AND surfaces 6–7 additional real misattributions the verifier missed under its sampling depth.

**Tool.** The wixie-side implementation is [`wixie/shared/scripts/dossier-cite-validator.py`](../../../../../wixie/shared/scripts/dossier-cite-validator.py) — stdlib Python, no external dependencies. Other plugins that consume the deep-research dossier surface MAY implement their own validator following the same protocol (extract `S<n>` tokens from prose, locate source by ID, run substring/synonym Tests A+B against `findings[].claim` and `findings[].quote`, emit `{total_cites_checked, violations, pass_rate}`). The wixie script is the reference implementation; the protocol is the contract.

**Honest-numbers framing — advisory, not a verdict gate.** The pre-check is a **strict-mechanical superset**: it has zero paraphrase tolerance beyond the built-in synonym table, while Phase 6 Haiku accepts some flagged sentences as legitimate paraphrase or scope-narrowing. Treat the pre-check's `violations` list as a **rewrite worklist for the orchestrator**, not a verdict. Phase 6 is the verdict gate. A passing pre-check does not waive Phase 6; a failing pre-check does not block Phase 6 — but the correct sequence is rewrite first, dispatch after.

If the orchestrator skips the rewrite step and dispatches Phase 6 anyway, record the divergence in `trace.json#phase5_5`. Do not suppress pre-check output — suppression is an honest-numbers violation.

## Refetch pass-rate thresholds — verdict consequences

| Threshold | Verdict consequence |
|---|---|
| `refetch_pass_rate ≥ 0.9` | Verifier passes the re-fetch check |
| `0.7 ≤ refetch_pass_rate < 0.9` | Re-fetch flagged; verdict drops to PARTIAL even if τ ≥ 0.85 |
| `refetch_pass_rate < 0.7` | Verdict is FAIL — F02 fabrication at the source level; regenerate `sources.jsonl` from a fresh Phase 2 |

The threshold is not arbitrary. Below 0.7, the live-web disagreement with our recorded quotes is too high to call the brief honest; the fetcher run is poisoned.

## Failure modes

| Code | Signature | Counter |
|------|-----------|---------|
| F02 | Claim cites a source whose findings don't pass Tests A+B | Trace check fails; delete the offending claim or regenerate |
| F02.1 | Quote not present at the cited URL when re-fetched | Step 2 catches; block verdict, regenerate from fresh fetch |
| F11 | Passed a cite via lexical overlap only (shared word, different meaning) | Tests A+B require BOTH subject AND action match; one isn't enough |
| F11.2 | Paraphrase-fragile claim — original wording passes trace, negation surfaces backing | CIBER multi-aspect interrogation; demote to `medium-contested`, brief drops to PARTIAL |
| F11.3 | Survivor-biased synthesis — contradicting findings dropped in synthesis | CIBER re-frames query against existing corpus, pulls contradiction back |
| F02.2 | Agreement illusion — sources back *different* propositions under paraphrase | CIBER detects paraphrase_split; bump dissemination_score |
| F02.3 | Cited line range outside retrieved chunk — code citation `[c_start, c_end]` does not overlap `[r_start, r_end]` | Interval arithmetic per "Code citations" section; record violation, regenerate cite from fresh code-chunk retrieval |
| F02.4 | Synthesis-prose cite-misattribution caught by mechanical pre-check (Phase 5.5) — sentence with `[S<n>]` does not pass substring/synonym Tests A+B against the cited source's findings | Orchestrator rewrites the affected prose before Phase 6 dispatch; pre-check is advisory (strict-mechanical superset), Phase 6 Haiku remains the verdict gate |
| F14.1 | Cited URL died since first fetch — content drift or removal | Wayback fallback recovers `pass-via-archive`; flag freshness window shorter for this brief |
| F14.2 | Source published date is older than the brief's freshness budget | `date` field present on every source; downstream filters on it |

## Anti-patterns

- **Do NOT ship `claims.json` without Phase 6.** Self-check: is `verify_passed` set by the verifier, not the synthesizer? If no, the artifact is invalid.
- **Do NOT skip the re-fetch at full depth, regardless of how recently the fetcher ran.** Re-fetch is the fabrication firewall against content drift between fetch and synthesis time. Self-check: is `refetch_pct > 0`? If no and depth is full, the check was skipped illegally.
- **Do NOT stretch subject/action matching to "feel right."** Tests A+B are boolean; lexical overlap without both subject AND action match is a fail. Self-check: did both A and B pass independently? If only one, the cite fails.
- **Do NOT omit unreachable URLs from `refetch_unreachable`.** Unreachables are a separate signal from pass/fail — exclude them from the denominator but flag them explicitly. Self-check: is `refetch_unreachable` present and non-null?
- **Do NOT treat `pass-via-archive` and `pass` as equivalent.** `pass-via-archive` signals live-web rot; surface it to the developer or downstream skill. Self-check: are archive passes flagged separately in the output?
- **Do NOT run re-fetch at orchestrator tier.** Re-fetch is a low-tier verifier subagent's job. Self-check: is the caller a verifier subagent, not the orchestrator? See [web-fetch.md](./web-fetch.md).

## Hard rules (U-curve close)

1. `verify_passed: true` requires BOTH trace check (Tests A+B) AND re-fetch check to pass.
2. Quick depth (`refetch_pct = 0`) ships as `PARTIAL_QUICK` only — never satisfies a freshness-reuse window.
3. `refetch_pass_rate < 0.7` → verdict is FAIL; `0.7 ≤ rate < 0.9` → verdict drops to PARTIAL.
4. CIBER fires after re-fetch, before the verdict, at full depth only; `negation_supported` or `paraphrase_split` severity → brief drops to PARTIAL.
5. WebFetch-only agents MUST NOT claim `pass-via-archive` — that claim requires `Bash(curl:*)` for Step B body verification.
6. The synthesis-prose pre-check (Phase 5.5) is advisory; Phase 6 Haiku is the verdict gate. Do not suppress pre-check output.
7. Code citations use interval arithmetic, not substring re-fetch — live-web rot checks do not apply to local repository cites.
