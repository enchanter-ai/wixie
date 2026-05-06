---
name: freshness-check
description: >
  Runs the Wixie model-freshness aggregator over state/model-usage.ndjson
  and flags any models-registry.json entry whose sunset_date has elapsed.
  Use when the developer asks about model deprecation, registry staleness,
  retired models, sunset dates, F-006 closure, or wants a current
  freshness summary. Auto-triggers on: "model freshness", "registry stale",
  "deprecated models", "sunset", "F-006", "freshness report",
  "model usage telemetry". Do not use for emitting telemetry events
  (the SessionStart hook does that automatically) or for editing the
  registry itself (developer edits the JSON directly).
allowed-tools:
  - Read
  - Bash
---

<purpose>
Operator-facing skill for the model-freshness telemetry pipeline.
Surfaces the current freshness picture: registry age, models past
their declared sunset_date, and the most recent SessionStart event.
</purpose>

<preconditions>
- shared/models-registry.json exists at wixie root.
- state/model-usage.ndjson may be empty on a fresh install — the report
  handles that case.
</preconditions>

<runbook>

## Step 1 — Run the aggregator

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/model-freshness-report.py
```

Output is human-readable text. Pass `--json` for machine-readable form.

## Step 2 — Interpret

| Signal | Meaning |
|--------|---------|
| `usage_rows: 0` | No SessionStart hook has fired yet. Verify hooks/hooks.json includes the SessionStart entry. |
| `registry_stale: true` | `last_updated` is older than `stale_threshold_days` (default 90). Refresh the registry. |
| `flagged_today` non-empty | One or more models past their `sunset_date`. Replace in any active prompts. |

## Step 3 — Optional: emit a one-off telemetry event

If the SessionStart hook didn't fire (manual session, debugging), emit
a one-off event:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/model-freshness.py --print
```

The `--print` flag echoes the emitted event to stdout. The default mode
is silent — the SessionStart hook should not pollute the conversation.

</runbook>

<config_reference>

| Field | Source | Meaning |
|-------|--------|---------|
| `last_updated` | registry root | ISO date of most recent registry edit |
| `sunset_date` | per-model spec | Optional ISO date when the model retires |
| `stale_threshold_days` | flag default 90 | Days after which the registry is flagged stale |

To declare a sunset, add `"sunset_date": "YYYY-MM-DD"` inside any model
entry in `shared/models-registry.json`. The next SessionStart event will
pick it up; the daily report will flag it once today >= sunset_date.

</config_reference>

<failure_modes>

- **F02 fabrication**: never invent a sunset_date for a model. If a vendor
  hasn't announced one, leave the field absent — the report omits it
  rather than warning falsely.
- **F14 version-drift**: the whole point of this skill. If a flagged
  model appears in any prompts/<name>/metadata.json, replace it with a
  current alternative before /converge runs.
- **F13 distractor pollution**: the report is small by design. Don't
  paste full NDJSON history into the conversation — read the report,
  act on the verdict.

</failure_modes>

<contract>
Advisory. Telemetry is observability, not a gate. The SessionStart hook
fails open — a missing registry or a JSON parse error writes to stderr
and exits 0, never blocking the session.
F-006 closure: usage telemetry is captured per-session, sunset dates
are flagged daily, registry staleness is computed against a configurable
threshold.
</contract>
