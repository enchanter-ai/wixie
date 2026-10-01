---
name: research-refresh
description: >
  Audits freshness across all briefs. Lists briefs by age class — current
  (<30d), aging (30-90d), stale (>90d). Optionally re-runs stale briefs via
  /deep-research. Use for weekly or monthly maintenance, or before a big
  /create session where multiple topics will be referenced.
  Auto-triggers on: "/research-refresh", "check brief freshness",
  "which briefs are stale", "audit the research cache",
  "refresh stale briefs".
  Do not use for a specific topic — use /deep-research <topic> for that.
allowed-tools: Read, Glob, Bash(date *)
---

# Research Refresh

**Contract (ships inside this plugin; WIX-DIST-002).** This skill relies on: `@${CLAUDE_PLUGIN_ROOT}/vendor/vis/packages/core/conduct/failure-modes.md` (failure-code taxonomy used for the F-codes below). Read them before acting; in a repo checkout they are the same sections of the root CLAUDE.md (or the pinned vis module).

Audit and optionally refresh stale briefs.

## Inputs

- Optional: `--auto-refresh` — re-run briefs whose age exceeds the threshold. Default: report only.
- Optional: `--threshold <days>` — override the 30-day default for the stale classifier.

## Execution

### Step 1: Scan

Glob `${CLAUDE_PLUGIN_DATA}/briefs/*/claims.json` (the brief store; WIX-SEC-WS-001). For each, read the `freshness` field. Compute age = today − freshness.

### Step 2: Classify

| Age | Class | Default action |
|-----|-------|----------------|
| < 30 days | current | skip |
| 30 - 90 days | aging | flag |
| > 90 days | stale | flag; re-run only if `--auto-refresh` |

Also classify anything with `verdict: FAIL` as `failed` — surface these regardless of age.

### Step 3: Report

```
<N> briefs total:
  current: <count>
  aging:   <count>
    - <slug> (<age> days, verdict: <X>)
  stale:   <count>
    - <slug> (<age> days, verdict: <X>)
  failed:  <count>
    - <slug> (verdict: FAIL — re-run needed)
```

### Step 4: Conditional refresh

If `--auto-refresh` was passed:
- For each `stale` brief, invoke `/deep-research <slug>` sequentially (not parallel — avoid fetch storms).
- Report per-brief outcome: `<slug>: <old verdict> → <new verdict>`.

`failed` briefs are NOT auto-refreshed — they may have an underlying issue that re-running won't fix. Ask the developer.

## Rules

- Do NOT auto-refresh unless `--auto-refresh` is explicitly passed.
- Do NOT delete stale briefs. Retention is the developer's call.
- Do NOT re-run `aging` briefs automatically — 30-90 days may be an intentional snapshot window.
- Run refreshes sequentially, not in parallel — the fetcher's WebSearch budget is shared.

## Failure modes

| Code | Signature | Counter |
|------|-----------|---------|
| F10 | Auto-deleted a brief as "cleanup" | This skill never deletes; retention is manual |
| F09 | Parallel re-runs caused fetch races | Serialize auto-refreshes |
