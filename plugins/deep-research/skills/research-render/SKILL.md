---
name: research-render
description: >
  Renders claims.json into a human-readable report.md for an existing
  research brief. Pure transformation — no new research, no new verification.
  Use when a developer wants to review research without re-running the full
  loop, or when a brief needs to be presented as a readable document.
  Auto-triggers on: "/research-render", "render the brief", "show me the brief",
  "render the research report", "I want to read the brief on X",
  "make the brief readable".
  Do not use to modify claims, re-fetch sources, or re-verify — use
  /deep-research for that.
allowed-tools: Read, Write
---

# Research Render

**Contract (ships inside this plugin; WIX-DIST-002).** This skill relies on: `@${CLAUDE_PLUGIN_ROOT}/vendor/vis/packages/core/conduct/failure-modes.md` (failure-code taxonomy used for the F-codes below). Read them before acting; in a repo checkout they are the same sections of the root CLAUDE.md (or the pinned vis module).

Transform structured `claims.json` into a human-readable `report.md`.

## Inputs

- `<slug>` — brief slug (e.g., `deep-research-best-practices-2026`)
- Optional: `--sections <list>` to include only specific sections (`findings,contradictions,sources`)

## Preconditions

- `${CLAUDE_PLUGIN_DATA}/briefs/<slug>/claims.json` exists
- `${CLAUDE_PLUGIN_DATA}/briefs/<slug>/sources.jsonl` exists

(The brief store is the plugin data directory, never the installed plugin tree; WIX-SEC-WS-001.)

If either is missing → FAIL with: *"No brief found for `<slug>`. Run `/deep-research <topic>` first."*

## Execution

### Step 1: Load

Read `claims.json` and `sources.jsonl`. Extract:
- Metadata: `topic`, `freshness`, `triangulation_score`, `verdict`, `source_count`
- Claims grouped by `sq` (sub-question)
- Unresolved contradictions
- Coverage gaps

### Step 2: Render

Produce `report.md` with this structure:

```markdown
---
topic: <slug>
generated: <today>
freshness: <from claims.json>
triangulation_score: <0..1>
verdict: READY | PARTIAL | FAIL
source_count: <N>
---

# <Topic human-readable title>

<one-paragraph synthesized answer from the claim set>

## Key findings

### <sub-question 1 human-readable label>

- <claim> [S1, S3]
- <claim, confidence: low> [S2 — single source]

### <sub-question 2 ...>

...

## Contradictions surfaced

- <claim A> [Si] vs <claim B> [Sj]. <Status: narrowed | unresolved>. <Brief explanation.>

(Or: "None.")

## Out of scope / not found

- <coverage gap>

## Sources

- [S1] <url> — <source_type>, <date or "no date">
- ...
```

Rules for the render:
- Every claim has an inline cite.
- Single-source claims append `(confidence: low)`.
- Contradictions are named, not smoothed. If a contradiction was narrowed by round-2 evidence, say so.
- Write to `${CLAUDE_PLUGIN_DATA}/briefs/<slug>/report.md`.

### Step 3: Report

```
rendered ${CLAUDE_PLUGIN_DATA}/briefs/<slug>/report.md (<N> claims, <M> sources, verdict: <X>)
```

## Rules

- Do NOT re-verify. Rendering is pure transformation of `claims.json`.
- Do NOT add claims or cites not in `claims.json`.
- Do NOT modify `claims.json` or `sources.jsonl`.
- If `verdict` is `FAIL` → refuse to render. Surface: *"claims.json has verdict FAIL — do not render unverified briefs. Re-run /deep-research."*

## Failure modes

| Code | Signature | Counter |
|------|-----------|---------|
| F02 | Added a fact not in claims.json | Every sentence in report.md ties to a claim id |
| F11 | Smoothed a contradiction into a single narrative | Surface both sides with cites |
