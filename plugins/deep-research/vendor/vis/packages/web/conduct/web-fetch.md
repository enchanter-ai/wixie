# Web Fetch — Skills Reading the Live Web

Audience: any agent that calls a `WebFetch` or `WebSearch` tool — directly or via a subagent. How to read external web pages without burning budget, duplicating fetches, or citing stale content.

## The rule

Web fetches cost latency, tokens, and context attention. Treat them like calls against a paid API: cache, dedup, budget. Don't fetch what you can re-use; don't re-use what's stale; don't blow your share of a parallel budget.

## Tool ownership — WebFetch is a low-tier subagent's job

**`WebFetch` belongs in the low-tier subagent layer**, not the orchestrator. Top-tier orchestrators and mid-tier executors do NOT call `WebFetch` directly — they delegate via subagent dispatch to a low-tier fetcher and consume the structured return.

| Caller | May call `WebFetch` directly? |
|--------|-------------------------------|
| Top-tier orchestrator | No — delegate to a low-tier fetcher |
| Mid-tier executor (analyzer, optimizer, red-team) | No — receive findings from low tier, do not re-fetch |
| Low-tier fetcher subagent | **Yes — this is the canonical owner** |
| Validator subagent | No — read-only on artifacts, not the live web |

**Why this rule.**
1. Cost — low tier is cheapest; bulk page-reading work belongs there, not at top-tier prices.
2. Context hygiene — fetched pages are large; a low-tier fork absorbs the page tokens, returns ≤ 400 words. The orchestrator's context never sees the raw HTML.
3. Determinism — low-tier fetchers' mechanical paragraph-by-paragraph tests work because the agent runs them literally; a top-tier orchestrator running the same steps will skip ahead.

Permission requirement: the project's runtime config must allow `"WebFetch"` for low-tier subagents to actually run it. Domain-pinned WebFetch entries (`WebFetch(domain:foo.com)`) are insufficient when the fetcher hits diverse sources — allow `"WebFetch"` broadly so the fetcher can chase any URL its WebSearch returns.

## Page-shape sizing — within low tier, not across tiers

The fetcher is always low-tier, but the *amount of work* per fetcher varies by page shape:

| Page shape | Low-tier fetcher behavior |
|------------|---------------------------|
| Short structured (pricing, API ref, changelog) | Top 500 tokens; one finding |
| Long doc needing cross-section summary | Walk top 3 sections; up to 3 findings; truncate at 8 KB |
| Dense paper / benchmark PDF / technical spec | Walk abstract + key results section; flag with `low_coverage: true` if dense math defeats paragraph-by-paragraph extraction |
| Unfetchable (paywalled, heavy JS, 404, login wall) | Return `{url, error: "unfetchable"}` — don't guess |

For genuinely dense papers where low-tier struggles, the fix is *more fetchers in parallel* (each on a narrow query), not escalating to mid/top tier for fetching. Synthesis is what scales up the tier — `WebFetch` itself stays at low-tier.

## Caching — don't re-fetch what you already have

- **URL-hash cache**, 24-hour TTL. Two skills asking for the same URL share one fetch.
- **Query-hash cache** for `WebSearch`. Identical search strings within a session → one call, shared result.
- Cache is skipped on explicit `--force`, or when the caller declares the topic fresh-critical ("as of today", release-day checks).
- Cache lives in project state (e.g., `state/fetch-cache/`) or a shared location when a router is in use.
- Eviction is explicit (manual sweep or refresh skill), never silent.

## Budget discipline — parallel fetchers share one

When a skill spawns N parallel fetchers, enforce:

| Budget | Default |
|--------|---------|
| Session-wide bytes after extraction | 200 KB |
| Per-fetcher structured output | 400 words |
| Per-page extracted text | 8 KB (hard truncate with `partial: true` flag) |

One heavy page must not eat the budget the other fetchers were allocated. If you hit the per-page cap, return a partial with a note — never silent truncation.

## Cite hygiene

Every fetched fact carries all four fields:

| Field | Rule |
|-------|------|
| `url` | Exact URL fetched |
| `date` | Publish date if detectable (meta tag, URL path, copyright footer); else `null` |
| `source_type` | One of `official | third-party | community | paper | other` |
| `quote` | Verbatim excerpt ≤ 200 chars that contains the fact |

No paraphrase in `quote`. Paraphrases belong in `claim`. Paraphrase-as-quote is [F02 fabrication](./failure-modes.md).

## Failure modes

| Code | Signature | Counter |
|------|-----------|---------|
| F02 | Paraphrase in the `quote` field | Quote must be copy-paste verbatim; if you can't, return without that finding |
| F13 | Adjacent-topic facts polluted findings | Topic filter applied *before* extraction, not after |
| F14 | Cited a retired spec / deprecated API | `date` field present; downstream weights by freshness |
| F09 | Two parallel fetchers raced on cache write | Atomic write-then-rename on cache store |
| F08 | Used Bash curl instead of WebFetch | Prefer the dedicated tool; WebFetch handles headers, timeouts, encoding |

## Anti-patterns

- **Default everything to low tier.** Dense papers get shallow extracts, load-bearing claims miss nuance.
- **Default everything to top tier.** Easy pages cost 10× what they should.
- **No cache at all.** Re-fetching a public doc five times per session is invisible waste.
- **Quote that "captures the gist."** Either copy-paste a sentence or return without the finding.
- **Fetch-without-date.** Can't tell if the page is from 2022 or last week; downstream can't weight freshness.
- **Per-skill fetch implementations that silently diverge.** All fetching obeys this conduct; skill-level agents specialize (task-specific extraction), not reinvent (routing, caching, cite hygiene).
- **Fetching when a local doc answers the question.** Check your local docs first. Web fetches are for the *live* web, not replacements for reading local material.
