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
              flux/plugins/inference-engine/agents/reconciler.md.")
```

### Step 2: Parse the agent's report

The agent returns one line:

```
reconciled <N> artifacts -> <P> patterns (<E> elevated, <R> retired)
```

### Step 3: Re-render briefings if verdicts changed

If the agent reports that verdicts changed (the agent diffs against the prior catalog internally), a fresh `state/briefings/flux.md` is already written. Otherwise re-render unconditionally — cheap and keeps the briefing timestamp current:

```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/inference-engine.py render-briefing flux
```

### Step 4: Report to caller

```
Reconcile complete: <N> artifacts, <P> patterns (<E> elevated, <R> retired)
Briefing: state/briefings/flux.md
```

If `FLUX_INFERENCE_ENABLED=0` the reconcile still runs (it's safe) but the emit pipeline is a no-op, so the catalog may not reflect recent sessions. Tell the caller honestly.

## Rules

- Do NOT edit `catalog.json` by hand at any step. The atomic write path in `inference-engine.py reconcile` is the only supported mutation.
- Do NOT claim elevation for patterns that did not cross SPRT. Honest numbers are the product.
- Do NOT skip the briefing refresh when verdicts change — stale briefings erode the substrate's value.
- If the engine script is missing or errors, report the error verbatim and stop. Do not invent a result.
