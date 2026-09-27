---
name: research-query
description: >
  Searches across existing research briefs for claims, sources, or
  contradictions matching a query. Read-only — returns matching claims with
  cites, does not regenerate or re-fetch. Use to check whether a topic has
  already been researched, to pull specific facts from a prior brief, or to
  cross-reference claims across multiple briefs.
  Auto-triggers on: "/research-query", "do we have research on X",
  "what did the brief on Y say about Z", "find claims about",
  "search the briefs for", "have we already looked into".
  Do not use to run new research — use /deep-research for that.
allowed-tools: Read, Grep, Glob
---

# Research Query

**Contract (ships inside this plugin; WIX-DIST-002).** This skill relies on: `@${CLAUDE_PLUGIN_ROOT}/vendor/vis/packages/core/conduct/failure-modes.md` (failure-code taxonomy used for the F-codes below). Read them before acting; in a repo checkout they are the same sections of the root CLAUDE.md (or the pinned vis module).

Search existing briefs without regenerating.

## Inputs

- `<query>` — free-text question or keyword
- Optional: `--slug <slug>` — limit to one brief
- Optional: `--min-confidence high|medium|low` — filter by confidence tier

## Execution

### Step 1: Scope

If `--slug` given → read only `${CLAUDE_PLUGIN_DATA}/briefs/<slug>/claims.json`.
Else → glob `${CLAUDE_PLUGIN_DATA}/briefs/*/claims.json` (the brief store; WIX-SEC-WS-001).

### Step 2: Match

For each brief, scan claims. Match `<query>` against:
1. `claim` text — direct substring and semantic overlap
2. `sub_question` label (via trace.json if available)
3. Source URLs in `supporting`

Rank matches: direct claim-text > source URL > sub-question.

### Step 3: Return

Group by brief slug. For each match:

```
[<slug>] (freshness: <date>, verdict: <X>)
  C<id>: <claim text> [S1, S3] (confidence: <tier>)
    sources: <url>, <url>
```

If no matches → `no matching claims across <N> briefs searched`.

Cap total output at 600 words; if over, return the top 10 matches and append `(<K> more matches hidden — run with --slug to narrow)`.

## Rules

- Do NOT fetch new sources.
- Do NOT re-verify.
- Do NOT modify any brief.
- Stale briefs (`freshness > 30 days`) are still returned but tagged `(stale)` — caller decides whether to re-run `/deep-research`.
- If a brief's `verdict` is `FAIL`, tag `(unverified)` and do not surface its claims as authoritative.

## Failure modes

| Code | Signature | Counter |
|------|-----------|---------|
| F02 | Returned a "match" that isn't in any claims.json | Every returned line cites a real claim id from a real brief |
| F13 | Returned adjacent-but-irrelevant claims | Rank by direct match; drop below a relevance floor |
