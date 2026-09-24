# Inference Substrate — Cross-Session Evidence Accumulation

Audience: Claude. How to write to, read from, and reason about the inference-engine substrate (internally codenamed Ufopedia) without corrupting its honest-numbers contract.

## What the substrate is

`wixie/plugins/inference-engine/` is the ecosystem-wide learning surface. It accumulates evidence of recurring failures and elevates them to per-plugin briefings consumed at session start. It complements — never replaces — each plugin's local learning engine (F6, H6, M6, A7, W5, L5, R8).

Five file surfaces:

| File                                   | Role                                                  | Mutation contract                                                  |
|----------------------------------------|-------------------------------------------------------|-------------------------------------------------------------------|
| `state/artifacts.jsonl`                | append-only master log (rotation deferred)            | `inference-engine.py emit` appends; never edit in place            |
| `state/catalog.json`                   | pattern catalog (posteriors, LLR, verdicts, weights)  | `inference-engine.py reconcile` writes atomically; never edit     |
| `state/briefings/<plugin>.md`          | per-plugin top-of-context briefing                    | `inference-engine.py render-briefing` writes; never edit          |
| `state/.lock`                          | state mutual-exclusion lock (emit, backfill, reconcile) | the engine takes and releases; never touch                      |
| `state/pending/<identity>.json`        | events queued while the lock was busy                 | `emit` writes; the next lock holder folds and deletes; never touch |
| `state/catalog.json.corrupt-<stamp>`   | a corrupt catalog moved aside by reconcile            | kept for inspection; safe to delete once reviewed                 |
| `shared/scripts/inference-engine.py`   | all subcommands (emit, reconcile, render-briefing, query, backfill, status) | edit only with a matching convergence + test cycle                |

## The rule

**Every write to the substrate goes through the engine.** Never `echo >> catalog.json`. Never hand-edit a briefing. Never append to `artifacts.jsonl` without the engine's timestamp + fingerprint stamping.

Why: the engine is the only place the honest-numbers contract is enforced — atomic writes, SHA-1 fingerprints, Wald SPRT thresholds, Beta-Binomial bounds, EMA decay half-life. Going around it breaks cross-session comparability.

## When to emit

Emit an artifact when **all three** hold:

1. The event is cross-session relevant — could happen again to a future agent or session.
2. There is a counter — a rule that prevents recurrence.
3. The current session has evidence — an iteration count, user pushback count, or observed recurrence.

Do not emit for every local slip. Emit for patterns worth compounding.

## Artifact fields (required)

```json
{
  "code": "F07",
  "category": "process-discipline | operational-discipline | branding-drift | ...",
  "title": "short sentence, ≤ 120 chars",
  "cause": "one to three sentences",
  "counter": "the rule that prevents recurrence",
  "signal": "one sentence a reader applies next time",
  "tags": ["wixie", "lifecycle", "convergence"],
  "scope": "wixie | hydra | ...",
  "evidence": { "iterations": 7, "user_rounds_of_pushback": 5 }
}
```

Timestamps and `session_id` are stamped by the engine. Do not set them by hand, with two
exceptions: a caller that may retry supplies `event_id` (see Event identity), and records
re-imported with `backfill` keep the `session_id` / `source_session` / `date` / `ts` they
already carry.

## Contract details

### Event identity

Each stored line is one event with a stable `_identity`: SHA-256 over the record minus the
engine metadata keys (`_identity`, `_session_source`, `_ts_clock`). The basis includes the
event's own coordinates: `session_id`, `source_session`, a supplied `ts` or `date`, `event_id`,
and `source_ordinal`. This is not payload dedup: the pattern fingerprint (code + tags) is what
accumulates; identity only stops one event from being counted twice.

- `emit` mints an `event_id` when none is supplied, so each call is a new event; supply
  `event_id` to make a retry idempotent (the repeat reports `duplicate`).
- `backfill` stamps only values derived from the source line (session from `session_id` or
  `source_session`, `ts` from `date`, `plugin` from `scope`), so re-running an import,
  finishing an interrupted one, or importing a copy of an engine-written log adds only events
  not already recorded. The n-th repeat of an identical line in one source file gets
  `source_ordinal` n and counts as its own event.
- Identical content from different sessions, dates or supplied timestamps stays distinct.
- A `ts` taken from the engine's clock is flagged `_ts_clock` and left out of the identity.
- Reading the log applies the same rule, so a copy of the log left next to it
  (`artifacts-*.jsonl`) is not double-counted, and a pre-identity log keeps every line it
  counted before.

### Session identity precedence

First match wins, recorded in `_session_source`: record `session_id` > record `source_session` >
`$CLAUDE_CODE_SESSION_ID` > `$CLAUDE_SESSION_ID` > `unknown`. The environment is consulted by
`emit` only; `backfill` never takes the importing session's id.

### Exit codes

| Code | Meaning |
|------|---------|
| 0    | success, including the documented no-ops: gate-off `emit`, `reconcile` of an empty log, and the `emit` outcomes `duplicate` and `queued` |
| 1    | `query` found nothing, or an operational failure (one-line reason on stderr) |
| 2    | usage error, an input record refused by `emit`, or a refused `render-briefing` plugin name |
| 3    | partial: `reconcile` or `backfill` completed, but some input lines were rejected (listed on stderr with file:line and reason) |
| 74   | `status` / `query` / `render-briefing`: `catalog.json` is corrupt; run `reconcile` |
| 75   | `reconcile` / `backfill`: `state/.lock` busy past `WIXIE_INFERENCE_LOCK_TIMEOUT` (default 30 s); nothing changed |

`inference-emit.sh` exits 0 when the event is durably recorded or the gate is off, and 1 when
it is not (never 2, which Claude Code treats as a blocking hook error).

### Rejected records

Every non-empty line of the log is counted, recognised as a repeat of a counted event, or
rejected with file, line and reason (invalid UTF-8, invalid JSON, not an object, a wrongly
typed field, an evidence count over 1000, or a torn final line). `reconcile` reports rejected
lines on stderr, stores `outcome`, `accounting` and `rejected` in `catalog.json`, and exits 3.
Appends write a newline first when the log does not end in one, so a torn write cannot swallow
the next record.

### Corrupt catalog: quarantine and recovery

A catalog that cannot be read or lacks the catalog shape is moved by `reconcile` to
`catalog.json.corrupt-<UTC stamp>` and rebuilt from the log; first-crossing stamps from entries
that were still well-formed are kept and `last_recovery` is recorded. Read-only commands exit
74 until then. Catalog writes are atomic (unique temp file, fsync, rename).

### Emit-lock policy

`emit` waits at most `WIXIE_INFERENCE_EMIT_WAIT` seconds (default 5) for `state/.lock`. If the
lock is still busy, the fully stamped event is written to `state/pending/<identity>.json` by
atomic rename and `emit` exits 0 with outcome `queued`. The next `emit`, `backfill` or
`reconcile` folds pending events into the log: append unless the identity is already
recorded, fsync, then delete, so each is recorded exactly once even across a crash. An event
is never silently dropped.

## When to reconcile

- After a meaningful emit burst (more than one artifact in a session).
- Before a high-stakes consumer reads a briefing (`/converge`, `/lich-review`, `/harden`).
- Weekly, as a cron — reconcile is idempotent on identical streams.

Do not reconcile on every emit — SPRT needs multiple observations to elevate a pattern, and single-observation reconcile churn is noise.

## Reading a briefing

At session start, the target plugin's primary skill reads `state/briefings/<plugin>.md` as top-of-context material (U-curve top-200-tokens slot per `shared/conduct/context.md`).

- Treat the briefing as advisory, not mandatory. Honest numbers over blind compliance.
- Prefer elevated patterns with EMA weight > 0.5 and observations ≥ 3.
- Respect the pattern's `signal` and `counter` verbatim — they were written to be reused.

## Recursion bound

The substrate watches itself via its own artifacts: a failure in the inference engine (stale reconcile, corrupted catalog, briefing drift) can itself be emitted as an artifact with category `substrate-failure`. This is depth-1 recursion.

**Hard rule:** no depth-2 recursion. Never emit an artifact describing a failure in substrate-failure handling. That path escalates to the human owner via an explicit `inference.escape-valve` file touch — not through the substrate itself.

## Retired patterns

When a pattern's LLR falls below `-2.25` over multiple reconciles, the engine marks it `retired` and stops including it in briefings. Do not re-emit retired patterns with the same fingerprint — if the pattern genuinely recurs post-retirement, emit a new artifact with a narrower or reframed `code` (e.g., `F07.1`) so the new evidence gets a fresh SPRT walk.

## Opt-in gate

`WIXIE_INFERENCE_ENABLED=1` is the rollout switch. When unset:

- `emit` is a no-op.
- `reconcile` still runs (safe on empty state).
- `render-briefing` still writes the placeholder briefing.
- No plugin's skill is required to read any briefing.

Flip the gate only after Phase 1 backfill has been validated locally — running on a clean machine with a fresh precedent.jsonl.

## Anti-patterns

- **Writing directly to catalog.json** — breaks atomic-write contract, corrupts posteriors.
- **Treating exit 3 as clean or exit 75 as a data failure** — 3 means some records were rejected; 75 means busy, retry.
- **Deleting `state/pending/` files** — they are recorded events waiting to be folded in.
- **Editing a briefing by hand** — next reconcile overwrites your edit, so the correction is lost.
- **Emitting without a counter** — signals noise, not a pattern. The engine accepts it but the substrate's utility collapses.
- **Emitting without evidence recurrence counts when they exist** — understates SPRT observations, delays elevation.
- **Skipping reconcile before a high-stakes briefing read** — stale briefings lie to the consumer. Cheap to refresh; expensive to miss.
- **Claiming elevation for a pattern with LLR < 2.89** — DEPLOY-bar style honest-numbers violation.
- **Ignoring retirement** — a retired pattern's signal is a historical artifact, not current guidance.
- **Feeding the substrate synthetic or test artifacts from production runs** — use a disposable state dir (env override `WIXIE_INFERENCE_STATE=/tmp/...`) for tests; never pollute `plugins/inference-engine/state/` from a test.
