---
name: inference-query
description: >
  Search the inference-engine catalog. Accepts a code (F07, OP05, …), a tag
  (wixie, lifecycle, …), or a 16-char pattern_id. Returns the full pattern
  records as JSON. Read-only; cheap; safe to call ad-hoc.
  Auto-triggers on: "/inference-query", "what does F07 say", "show patterns
  tagged lifecycle", "search ufopedia for …".
allowed-tools: Bash(python *) Read
---

# Inference Query

**Contract (ships inside this plugin; WIX-DIST-002).** This skill relies on: `@${CLAUDE_PLUGIN_ROOT}/vendor/vis/packages/core/conduct/failure-modes.md` (failure-code taxonomy used for the F-codes below). Read them before acting; in a repo checkout they are the same sections of the root CLAUDE.md (or the pinned vis module).

Retrieve pattern records from `catalog.json` by code, tag, or `pattern_id`.

## Usage

The caller provides one search term. Exact match only at Phase 1. Fuzzy / BM25 ranking is deferred.

## Pipeline

### Step 1: Run the query

```bash
python ${CLAUDE_PLUGIN_ROOT}/vendor/wixie/shared/scripts/inference-engine.py query <term>
```

The engine returns a JSON array of matching patterns to stdout. Exit code `0` if any match, `1` if none. Exit `74` means `catalog.json` is corrupt: nothing is returned; run `/inference-reconcile`, which quarantines and rebuilds it.

### Step 2: Summarize for the caller

Parse the JSON and present a compact summary:

```
<N> pattern(s) matching '<term>':

[elevated]  F07 — Ran seven reactive iterations instead of one-pass Wixie lifecycle
            weight 0.94 · posterior 0.83 (CI 0.55–0.98) · LLR 8.95
            last seen 2026-04-21 (1d ago) · 5 observations across 1 session
            tags: wixie, lifecycle, convergence, prompt-engineering, process-discipline
```

### Step 3: Offer follow-ups

If the caller's intent is to understand a pattern they're about to trip over, offer:

- `/inference-brief <plugin>` to see the full briefing the target plugin is consuming.
- Full JSON via a Read on `${CLAUDE_PLUGIN_ROOT}/state/catalog.json`.

## Rules

- Do NOT guess at match results. If the engine returns empty, tell the caller honestly.
- Do NOT paraphrase the pattern's `signal` or `counter`. They were written to be re-read verbatim.
- Do NOT expose non-elevated patterns as if they were elevated. The verdict field is honest; keep it visible.
