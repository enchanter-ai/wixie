---
name: inference-emit
description: >
  Append a single artifact (failure observation, correction, precedent) to the
  inference-engine's append-only stream. Use when a cross-session-relevant
  event occurs — a self-caught failure mode, a corrected misunderstanding, a
  precedent worth compounding. The emit is a no-op unless
  WIXIE_INFERENCE_ENABLED=1 is set.
  Auto-triggers on: "/inference-emit", "emit this to ufopedia", "log this
  as a precedent for future sessions", "record this failure pattern".
allowed-tools: Bash(python *) Read Write
---

# Inference Emit

**Contract (ships inside this plugin; WIX-DIST-002).** This skill relies on: `@${CLAUDE_PLUGIN_ROOT}/vendor/vis/packages/core/conduct/failure-modes.md` (failure-code taxonomy used for the F-codes below). Read them before acting; in a repo checkout they are the same sections of the root CLAUDE.md (or the pinned vis module).

Append one artifact to `${CLAUDE_PLUGIN_ROOT}/state/artifacts.jsonl`.

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
| `session_id`  | string | the session the event happened in (see precedence below) |
| `event_id`    | string | caller's id for this event; makes a retry idempotent |
| `ts`          | string | ISO-8601 time of the event; stamped from the clock if absent |

Field types are checked. A record that is not a JSON object, is not UTF-8, or has a wrongly
typed field (`code`, `title`, `category`, `signal`, `counter`, `session_id`, `ts`, `date` must be
strings; `tags` a list of strings; `evidence` an object; an evidence count may not exceed 1000)
is refused with exit 2 and nothing is written.

## Event identity

Every stored line carries `_identity`: a SHA-256 over the record minus the engine metadata keys
(`_identity`, `_session_source`, `_ts_clock`). The event's own coordinates are part of it:
`session_id`, `source_session`, a supplied `ts` or `date`, `event_id`, `source_ordinal`.

- A stored line whose `_identity` recomputes from the line is that event, so a copy of the log
  (plain, concatenated or duplicated) never adds evidence. Known limits are listed in
  `${CLAUDE_PLUGIN_ROOT}/vendor/wixie/shared/conduct/inference-substrate.md` (Event identity).
- Each emit is a new event: when the record has no `event_id` the engine mints one, so two
  genuine occurrences of the same payload in one session are two observations.
- To make a retry idempotent (a hook re-run after an ambiguous failure), supply your own
  `event_id`. A second emit with the same `event_id`, payload and session is reported as
  `duplicate` and adds nothing.
- The same payload in a different session is a different event.
- A `ts` the engine filled from its clock is flagged `_ts_clock` and is not part of the identity.

## Session identity

The engine stamps `session_id` from the first of these that is set, and records which one in
`_session_source`:

1. the record's own `session_id` (`record:session_id`)
2. the record's `source_session` (`record:source_session`)
3. `$CLAUDE_CODE_SESSION_ID` (`env:CLAUDE_CODE_SESSION_ID`, what Claude Code exports)
4. `$CLAUDE_SESSION_ID` (`env:CLAUDE_SESSION_ID`, legacy)
5. the literal `unknown` (`unknown`). It is never guessed.

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
WIXIE_INFERENCE_ENABLED=1 python ${CLAUDE_PLUGIN_ROOT}/vendor/wixie/shared/scripts/inference-engine.py emit <(cat <<'EOF'
<your JSON record>
EOF
)
```

The first word of stdout is the outcome token:

| Token       | Exit | Meaning |
|-------------|------|---------|
| `emitted`   | 0    | appended to `state/artifacts.jsonl` |
| `duplicate` | 0    | an event with this identity is already recorded; nothing added |
| `queued`    | 0    | the state lock stayed busy for `WIXIE_INFERENCE_EMIT_WAIT` seconds (default 1); the event was written to `state/pending/<identity>.json` and the next emit, backfill or reconcile folds it into the log exactly once |

Other exits: `0` with no stdout when `WIXIE_INFERENCE_ENABLED` is not `1` (documented no-op,
nothing recorded); `2` the record was refused (reason on stderr); `1` the event could not be
recorded or queued (reason on stderr). Report a non-zero exit verbatim; the event was NOT
recorded.

Hooks should call `shared/scripts/inference-emit.sh`, which exits `0` only when the event is
durably recorded (`emitted`, `duplicate`, `queued`) or the gate is off, and `1` otherwise
(never `2`, which Claude Code treats as a blocking hook error). It accepts `--event-id`.

**Hook timeout requirement:** a hook that emits (directly or through `inference-emit.sh`) must have a timeout greater than `WIXIE_INFERENCE_EMIT_WAIT` + 2 s (interpreter start-up and the queue write). Claude Code discards a hook that outlives its timeout, so the event would be lost. With the default wait of 1 s, a 3 s hook timeout (the smallest this plugin uses) is enough; raise the timeout before raising the wait.

### Step 3: Optional reconcile

If the artifact is high-confidence (existing pattern with fresh evidence), suggest running `/inference-reconcile`. Do not auto-trigger reconcile from emit — the brand contract says hooks inform, they don't decide.

### Step 4: Report

Tell the caller:

```
Emitted <code> to artifacts.jsonl (outcome: emitted | duplicate | queued)
Fingerprint: <first 16 chars of SHA-1>
Next: /inference-reconcile when ready to update the catalog.
```

## Rules

- Do NOT emit without `WIXIE_INFERENCE_ENABLED=1`. The engine's emit path short-circuits anyway; the skill reports the no-op honestly.
- Do NOT fabricate fields. If the caller's text is missing `signal` or `counter`, ask.
- Do NOT overwrite an existing artifact. The stream is append-only by design.
