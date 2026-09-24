---
name: inference-reconcile
description: >
  Reconcile the inference-engine catalog. Re-fingerprints every artifact,
  re-runs Wald SPRT and Beta-Binomial and EMA decay, elevates patterns that
  cross the SPRT threshold, retires patterns that fall below it, and
  atomically rewrites catalog.json. Safe to run repeatedly — fully
  idempotent on identical artifact streams.
  Auto-triggers on: "/inference-reconcile", "rebuild the catalog",
  "re-elevate patterns", "refresh ufopedia", "reconcile learnings".
allowed-tools: Bash(python *) Read Agent
---

# Inference Reconcile

Re-derive `catalog.json` from the full artifact history. Fully autonomous.

## Usage

The caller provides no arguments at Phase 1. Future phases may accept scope filters.

## Pipeline

### Step 1: Spawn the reconciler agent

Delegate to the Sonnet-tier reconciler. The agent runs the engine, validates output, and re-renders briefings when verdicts change:

```
Agent(subagent_type="general-purpose", model="sonnet",
      prompt="Run the reconciler agent defined at
              wixie/plugins/inference-engine/agents/reconciler.md.")
```

### Step 2: Parse the agent's report

The agent returns one line:

```
reconciled <N> artifacts -> <P> patterns (<E> elevated, <R> retired)
```

### Step 3: Re-render briefings if verdicts changed

If the agent reports that verdicts changed (the agent diffs against the prior catalog internally), a fresh `state/briefings/wixie.md` is already written. Otherwise re-render unconditionally — cheap and keeps the briefing timestamp current:

```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/inference-engine.py render-briefing wixie
```

### Step 4: Report to caller

```
Reconcile complete: <N> artifacts, <P> patterns (<E> elevated, <R> retired)
Briefing: state/briefings/wixie.md
```

## Exit codes and outcomes

| Exit | Meaning | What to tell the caller |
|------|---------|-------------------------|
| 0    | clean: every non-empty log line is counted (or is a repeat of a counted event). Also the no-op when the log is empty. | the summary line |
| 3    | partial: the catalog was rebuilt from every usable line, but some lines were rejected. stderr lists each as `<file>:<line>: <reason>`; `catalog.json` has `outcome: "partial"`, `accounting` and the full `rejected` list. | the summary line plus the rejected count; do not call it clean |
| 75   | busy: another inference-engine process held `state/.lock` for `WIXIE_INFERENCE_LOCK_TIMEOUT` seconds (default 30). Nothing was changed. | retry later |
| 1    | operational failure (one-line reason on stderr, no traceback) | the error verbatim |

`catalog.json` accounting always satisfies `nonempty_lines == events + duplicate_lines +
rejected_lines`. A rejected line stays in the append-only log, so later reconciles keep
reporting it (exit 3) until an operator deals with it; it is never silently dropped.

### Corrupt catalog: quarantine and recovery

`catalog.json` is derived state. If it cannot be read or does not have the catalog shape
(truncated or invalid JSON, not UTF-8, wrong top-level type, a wrongly typed top-level field
such as `accounting` or `rejected`, a pattern entry that is not an object or has a wrongly
typed field), reconcile moves it to `state/catalog.json.corrupt-<UTC
stamp>` (never deleted), rebuilds the catalog from the artifact log, keeps the first-crossing
stamps (`elevated_at` / `retired_at`) of prior entries that were still well-formed, records
`last_recovery` (`at`, `reason`, `quarantined_as`, `stamps_carried_from`) in the new catalog, and
exits 0 (or 3 if lines were also rejected). While the catalog is corrupt, `status`, `query` and
`render-briefing` exit 74 and point here. When the artifact log is empty or missing,
reconcile still quarantines a corrupt catalog (and writes none, the normal empty state), so
the 74 loop always ends. A catalog write is atomic (unique temp file, fsync,
rename): an interrupted write leaves the previous catalog, and stale temp files are removed by
the next reconcile.

### Concurrency

Reconcile, backfill and emit serialize on `state/.lock`. Queued emits in `state/pending/` are
folded into the log at the start of every reconcile.

If `WIXIE_INFERENCE_ENABLED=0` the reconcile still runs (it's safe) but the emit pipeline is a no-op, so the catalog may not reflect recent sessions. Tell the caller honestly.

## Rules

- Do NOT edit `catalog.json` by hand at any step. The atomic write path in `inference-engine.py reconcile` is the only supported mutation.
- Do NOT claim elevation for patterns that did not cross SPRT. Honest numbers are the product.
- Do NOT skip the briefing refresh when verdicts change — stale briefings erode the substrate's value.
- If the engine script is missing or errors, report the error verbatim and stop. Do not invent a result.
- Do NOT report exit 3 as a clean reconcile, and do NOT treat exit 75 as a failure of the data: it means "busy, retry".
