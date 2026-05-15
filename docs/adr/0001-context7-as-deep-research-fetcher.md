# ADR 0001 — Add Context7 as a deep-research fetcher source for library/API claims

- **Status**: Proposed — Deferred (no demand shown as of 2026-05-15)
- **Date**: 2026-05-15
- **Author**: @klaiderman

## Context

`plugins/deep-research/agents/fetcher.md` is a Haiku-tier mechanical agent: `WebSearch` → rank/filter → `WebFetch` → extract a verbatim quote per paragraph. It governs the evidence path for every claim in `state/briefs/<slug>/sources.jsonl`, which downstream skills (`/create`, `/refine`, `/harden`) consume and which `shared/conduct/inference-substrate.md` aggregates across sessions.

Two failure modes recur on library/API claims:

1. **F14 drift** — WebFetch hits live framework docs. A citation captured today against `docs.<vendor>.com/v3/x` returns different bytes next month after a doc rev. The `sources.jsonl` entry is no longer reproducible.
2. **Version conflation** — fetcher has no signal for "this claim is about library X version Y." A v3 user gets v5 docs because that's what the vendor homepage now serves.

A pass over the dotclaude.com directory (see conversation log, 2026-05-13) surfaced [Context7](https://context7.com) — an MCP that serves versioned library/API documentation deterministically. Same query at T+30 days returns byte-identical content. All other dotclaude listings were rejected as redundant (`Filesystem`, `Sequential Thinking`, `Zen`), out-of-scope (Slack/Notion/Stripe/cloud ops), or architecturally conflicting (`Memory MCP` vs. inference-substrate; `dotclaude/marketplace` vs. E0–E6 engines and DEPLOY bar — F22 risk).

The decision: do we extend the fetcher's `allowed-tools` to include Context7, gated to library/API queries?

## Decision

**If and only if the conditions in [Revisit trigger](#revisit-trigger) below are met,** we will add Context7 MCP as an additional Step-1 retrieval path inside `plugins/deep-research/agents/fetcher.md`, **gated mechanically** to queries whose `sub_question` names a library, framework, SDK, package, or API endpoint. All other sub-questions continue through `WebSearch` + `WebFetch` unchanged. Context7 returns are subjected to the same Test A / Test B / Test C extraction discipline and stamped in `sources.jsonl` with a deterministic identifier (`context7://<library>@<version>#<section>`) rather than a drift-prone URL.

As of 2026-05-15 the trigger conditions are not met — see the workload survey below. The proposed change is therefore **not implemented**. This section describes the proposal so a future reader who reactivates this ADR has the design intact.

## Alternatives considered

- **WebFetch-only (status quo)** — Rejected. F14 drift and version conflation persist; `sources.jsonl` entries on library claims are not reproducible across sessions, which weakens both the brief's `freshness < 30 days` reuse contract and the inference-substrate's cross-session evidence accumulation.
- **Puppeteer MCP** — Rejected as a substitute. Solves JS-rendered pages, not version drift. Different problem. Kept on the radar for a future ADR if JS-rendered sources show up in the fetcher's `unfetchable` log.
- **Brave Search MCP** — Rejected. Replaces `WebSearch` without changing retrieval semantics. No reproducibility win.
- **dotclaude/marketplace (16 plugins)** — Rejected. Imports parallel learning systems (Cognitive Orchestration, Adaptive Learning, Insight Engine) with no DEPLOY bar, no σ check, no 8-SAT, no honest-numbers contract. Same F22 silent-substitution pattern already in memory.
- **`Memory` MCP (knowledge graph)** — Rejected. Direct conflict with `shared/conduct/inference-substrate.md`: "every write to the substrate goes through the engine." A parallel memory surface diverges from `artifacts.jsonl` and breaks atomic-write + posterior contracts.

## Consequences

**Easier**

- Library/API claims in `sources.jsonl` become reproducible — re-running a brief at T+30 days returns byte-identical evidence for those citations.
- F14 (old-spec returned without date indicator) drops on library queries because Context7 attaches a version to every chunk.
- The inference-substrate sees more stable fingerprints on framework-claim artifacts.

**Harder**

- Fetcher's `allowed-tools` list expands. Per `shared/vis/packages/core/conduct/tool-use.md`, every tool needs an explicit error-payload contract — Context7's failure modes (unknown library, version-not-indexed, rate-limited) must be folded into Step-3's `unfetchable` handling without a retry loop.
- Gating logic ("is this a library query?") risks F13 (findings drift into adjacent topics) if it's interpretive. The gate must be mechanical: `sub_question` contains an exact-match token from a pre-curated allowlist of library/framework/SDK/API names, or it doesn't qualify.
- A new MCP is a new trust surface. Quote provenance still passes through `<untrusted_source>` tags; that contract is non-negotiable.

**New failure modes**

- **Version mismatch.** Context7 indexes `library@v5`; user's stack is `library@v3`. If the fetcher pulls v5 without checking, the citation is technically reproducible but semantically wrong. Mitigation: the gate requires a version to be present in `sub_question` (or `null` → fall back to WebFetch).
- **Index coverage hole.** Library exists in the wild but not in Context7. Mitigation: treat as `unfetchable` from Context7's path, fall back to WebSearch + WebFetch within the same fetcher run — no retry, no spawn.
- **Quote shape mismatch.** Context7 returns chunks; Test C requires a ≤200-char verbatim sentence containing subject + action/property. If the chunk's sentences are uniformly longer, every Test C fails and the path yields zero findings. Detected at verification time, not after merge.

## Verification before flipping to Accepted

This ADR stays `Proposed` until all five checks pass; results recorded in `plugins/deep-research/state/adr-0001-verification.md`:

1. **Coverage.** Pull one existing brief from `state/briefs/` that cites ≥1 library/API claim. Re-run that claim's sub-question through Context7. Does the library exist in the index?
2. **Test C compatibility.** Does Context7's chunk yield ≥1 verbatim sentence ≤200 chars containing the subject + action of the claim? If 0/3 chunks pass, the path is incompatible — close ADR as Rejected.
3. **Cost & latency.** Record per-call cost and p50 latency. Must be Haiku-tier-compatible per `shared/vis/packages/web/conduct/web-fetch.md` (cache, dedup, budget).
4. **Reproducibility.** Re-run the same query at T+7 days. Response is byte-identical (modulo a trailing timestamp field, if any).
5. **Failure-mode honesty.** Force an unknown-library query and a known-but-unversioned query. Both must fall back cleanly through the `unfetchable` path without retry, without spawn, without invented content.

If all five pass: flip to `Accepted`, open the follow-up PR that touches `fetcher.md`'s `allowed-tools`, Step 1, and Step 7 (extending `source_type` with a `library-doc` value).

## Revisit trigger

Flip this ADR from `Proposed — Deferred` back to active `Proposed` only when **all three** hold:

1. A `/deep-research` brief lands whose sub-questions name at least one specific library, framework, or SDK version (not "agent frameworks in general" — a concrete `langgraph@0.2`, `pydantic@2.x`, etc.).
2. That brief's fetcher run produces ≥2 sources where the citation depends on version-specific behavior (an API signature, a config flag, a removed/added feature).
3. WebFetch demonstrably degrades on those sources — either F14 drift (page changed since last run) or the citation can no longer be re-verified at T+30 days.

If those conditions don't appear within 6 months (revisit deadline: **2026-11-15**), close as `Deprecated` with a one-line "workload didn't materialize" note. The ADR stays in the log either way per `docs/adr/README.md` — never deleted.

Doubt-engine evidence behind the deferral (recorded so a future reader doesn't re-litigate):

- Workload survey 2026-05-15: 0/3 existing briefs in `plugins/deep-research/state/briefs/` (`ai-era-failure-patterns`, `deep-research-best-practices-2026`, `mcp-client-golden-architecture`) cite library/API claims that would benefit from versioned docs.
- Tier-sizing cost: adding routing + a new `source_type` to `fetcher.md` worsens the F11.1 schema-drift problem that `fetcher-normalize.py` already exists to mitigate.
- Source-type taxonomy change is cross-cutting (triangulator, verifier, normalizer, substrate fingerprints) — not the "follow-up PR" the Decision paragraph implied.
- F22 soft-degradation path (Context7 rate-limit → truncated chunk → still `<untrusted_source>`-wrapped → ships) is not handled by the proposed fallback.
- Substrate ([state/briefings/wixie.md](../../plugins/inference-engine/state/briefings/wixie.md)) already names a higher-priority fetcher pattern (OP06 — arxiv URL routing) that the same attention budget addresses with concrete evidence (2 observations, posterior 0.750).

## Related

- [plugins/deep-research/agents/fetcher.md](../../plugins/deep-research/agents/fetcher.md) — the agent this ADR proposes to modify
- [shared/vis/packages/web/conduct/web-fetch.md](../../shared/vis/packages/web/conduct/web-fetch.md) — governs fetcher tool-selection and tier rules
- [shared/conduct/inference-substrate.md](../../shared/conduct/inference-substrate.md) — consumes `sources.jsonl`; reproducibility is what this ADR buys
- [shared/models-registry.json](../../shared/models-registry.json) — Context7 cost/tier must be compatible
- Memory: `feedback_capability_fidelity.md` (F22) — guards against the silent-substitution variant of this change
- Conversation precedent: dotclaude.com directory pass, 2026-05-13 — established why every other dotclaude item was rejected
