---
name: inference-emit
description: >
  Append a single artifact (failure observation, correction, precedent) to the
  inference-engine's append-only stream. Use when a cross-session-relevant
  event occurs — a self-caught failure mode, a corrected misunderstanding, a
  precedent worth compounding. The emit is a no-op unless
  FLUX_INFERENCE_ENABLED=1 is set.
  Auto-triggers on: "/inference-emit", "emit this to ufopedia", "log this
  as a precedent for future sessions", "record this failure pattern".
allowed-tools: Bash(python *) Read Write
---

# Inference Emit

Append one artifact to `flux/plugins/inference-engine/state/artifacts-YYYY-MM.jsonl`.

## Usage

The caller provides either:

- A JSON record via stdin or a file path.
- Enough structured text to let you build the record.

## Required fields

| Field       | Type     | Example                                   |
|-------------|----------|-------------------------------------------|
| `code`      | string   | `F07`, `OP05`, `H01`                      |
| `category`  | string   | `process-discipline`, `branding-drift`    |
| `title`     | string   | short failure title, ≤ 120 chars          |
| `cause`     | string   | one to three sentences                    |
| `counter`   | string   | the rule that prevents recurrence         |
| `signal`    | string   | one sentence the reader applies next time |
| `tags`      | string[] | lowercase, underscore or hyphen           |

## Optional fields

| Field         | Type   | Purpose                                      |
|---------------|--------|----------------------------------------------|
| `evidence`    | object | sub-session recurrence counts (see below)    |
| `scope`       | string | plugin or sub-plugin                         |
| `source_session` | string | human-readable session id                 |

## Evidence keys that boost SPRT

If the artifact documents multiple independent recurrences inside one session, set one of:

- `evidence.iterations` — build-loop iterations
- `evidence.user_rounds_of_pushback` — user corrections in a session
- `evidence.occurrences` — generic count
- `evidence.times_hit` — alias

Each `N > 1` contributes `N` SPRT observations, not `1`. Use the honest count.

## Pipeline

### Step 1: Construct the record

If the caller gave you a JSON record, use it. If they gave structured text, build the JSON yourself using the field spec above. Never fabricate `evidence` counts — ask if unclear.

### Step 2: Emit

```bash
FLUX_INFERENCE_ENABLED=1 python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/inference-engine.py emit <(cat <<'EOF'
<your JSON record>
EOF
)
```

Confirm the stdout line `emitted <CODE> -> artifacts-YYYY-MM.jsonl`.

### Step 3: Optional reconcile

If the artifact is high-confidence (existing pattern with fresh evidence), suggest running `/inference-reconcile`. Do not auto-trigger reconcile from emit — the brand contract says hooks inform, they don't decide.

### Step 4: Report

Tell the caller:

```
Emitted <code> to artifacts-YYYY-MM.jsonl
Fingerprint: <first 16 chars of SHA-1>
Next: /inference-reconcile when ready to update the catalog.
```

## Rules

- Do NOT emit without `FLUX_INFERENCE_ENABLED=1`. The engine's emit path short-circuits anyway; the skill reports the no-op honestly.
- Do NOT fabricate fields. If the caller's text is missing `signal` or `counter`, ask.
- Do NOT overwrite an existing artifact. The stream is append-only by design.
