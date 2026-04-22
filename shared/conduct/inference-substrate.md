# Inference Substrate — Cross-Session Evidence Accumulation

Audience: Claude. How to write to, read from, and reason about the inference-engine substrate (internally codenamed Ufopedia) without corrupting its honest-numbers contract.

## What the substrate is

`flux/plugins/inference-engine/` is the ecosystem-wide learning surface. It accumulates evidence of recurring failures and elevates them to per-plugin briefings consumed at session start. It complements — never replaces — each plugin's local learning engine (F6, H6, M6, A7, W5, L5, R8).

Five file surfaces:

| File                                   | Role                                                  | Mutation contract                                                  |
|----------------------------------------|-------------------------------------------------------|-------------------------------------------------------------------|
| `state/artifacts-YYYY-MM.jsonl`        | append-only event stream, monthly rotation            | `inference-engine.py emit` appends; never edit in place            |
| `state/catalog.json`                   | pattern catalog (posteriors, LLR, verdicts, weights)  | `inference-engine.py reconcile` writes atomically; never edit     |
| `state/briefings/<plugin>.md`          | per-plugin top-of-context briefing                    | `inference-engine.py render-briefing` writes; never edit          |
| `state/.lock` (if present)             | reconcile mutual-exclusion lock                       | the engine takes and releases; never touch                        |
| `shared/scripts/inference-engine.py`   | all subcommands (emit, reconcile, render-briefing, query, backfill, status) | edit only with a matching convergence + test cycle                |

## The rule

**Every write to the substrate goes through the engine.** Never `echo >> catalog.json`. Never hand-edit a briefing. Never append to `artifacts-YYYY-MM.jsonl` without the engine's timestamp + fingerprint stamping.

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
  "tags": ["flux", "lifecycle", "convergence"],
  "scope": "flux | reaper | ...",
  "evidence": { "iterations": 7, "user_rounds_of_pushback": 5 }
}
```

Timestamps and `session_id` are stamped by the engine. Do not set them by hand.

## When to reconcile

- After a meaningful emit burst (more than one artifact in a session).
- Before a high-stakes consumer reads a briefing (`/converge`, `/mantis-review`, `/harden`).
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

`FLUX_INFERENCE_ENABLED=1` is the rollout switch. When unset:

- `emit` is a no-op.
- `reconcile` still runs (safe on empty state).
- `render-briefing` still writes the placeholder briefing.
- No plugin's skill is required to read any briefing.

Flip the gate only after Phase 1 backfill has been validated locally — running on a clean machine with a fresh precedent.jsonl.

## Anti-patterns

- **Writing directly to catalog.json** — breaks atomic-write contract, corrupts posteriors.
- **Editing a briefing by hand** — next reconcile overwrites your edit, so the correction is lost.
- **Emitting without a counter** — signals noise, not a pattern. The engine accepts it but the substrate's utility collapses.
- **Emitting without evidence recurrence counts when they exist** — understates SPRT observations, delays elevation.
- **Skipping reconcile before a high-stakes briefing read** — stale briefings lie to the consumer. Cheap to refresh; expensive to miss.
- **Claiming elevation for a pattern with LLR < 2.89** — DEPLOY-bar style honest-numbers violation.
- **Ignoring retirement** — a retired pattern's signal is a historical artifact, not current guidance.
- **Feeding the substrate synthetic or test artifacts from production runs** — use a disposable state dir (env override `FLUX_INFERENCE_STATE=/tmp/...`) for tests; never pollute `plugins/inference-engine/state/` from a test.
