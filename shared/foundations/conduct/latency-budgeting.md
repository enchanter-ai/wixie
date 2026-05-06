# Latency Budgeting — Time-Budget Discipline for Agent Workflows

Audience: any agent orchestrator. How to set, track, and gate end-to-end latency so user-facing response time is predictable and degraded paths are handled explicitly — without adding runtime services.

## The problem

Token cost and latency are related but not identical. A session that picks the cheapest model tier and caps subagent spawns can still exceed its latency budget by serializing steps that could run in parallel, by fetching large pages when summaries suffice, or by running tool loops without a wall-clock stop condition.

Latency is a user-facing property. Cost overruns show up on the invoice; latency overruns show up as abandoned sessions. Both need explicit gates.

As Anthropic's demystifying-evals guide notes, "latency, token usage, cost per task, and error rates can be tracked on a static bank of tasks" — these four signals form a coherent observability surface. This module operationalizes the latency slice of that surface using the same dependency-free, condition-in-prompt pattern as [`./cost-accounting.md`](./cost-accounting.md).

## Latency signals to track

Track these signals. All can be captured in a Markdown-only workflow with no instrumentation tooling.

| Signal | How to capture (Markdown-only) | Default threshold |
|--------|-------------------------------|-------------------|
| **Total wall-clock estimate** | Orchestrator sums per-step latency estimates before starting; tracks actual at session end | 60 s (interactive) / 300 s (batch) |
| **Serialized-step count** | Count steps that block on the prior step's output; each adds sequential latency | ≤ 5 serial steps before a parallel fan-out |
| **Fetch count per step** | Number of external fetches (web, API, file) in a single step | ≤ 3 per step |
| **Tool-call round-trips per subagent** | Subagent tracks its own round-trips; returns with a latency note when over budget | ≤ 8 round-trips per subagent |
| **Retry count** | Number of times a step was retried after failure | ≤ 2 retries before escalating |

Thresholds above are defaults. Set workflow-specific thresholds in the delegation prompt or the skill's metadata. The interactive default (60 s) is a human-attention threshold; adjust for batch workflows where the user is not waiting.

## Latency gates

Three named gates. Each is expressed as a **condition in the delegation prompt** — not a runtime service. This is the same pattern as `cost-accounting.md` § Budget gates.

### Gate 1 — Total session wall-clock cap

Include in the orchestrator's system prompt or leading context:

```
LATENCY GATE — SESSION WALL-CLOCK
Before starting each major step, estimate its wall-clock contribution (seconds).
If the cumulative estimate exceeds 60 s (interactive) or 300 s (batch),
STOP adding serial steps. Fan out remaining steps in parallel or report them as
out-of-scope with a note: "Latency gate triggered at ~N s estimate."
```

The estimate is an admission of uncertainty — round generously. A 5 s step followed by ten 8 s steps is already a 90 s session without any model invocation time.

### Gate 2 — Per-subagent round-trip cap

Include at the end of every subagent delegation prompt:

```
LATENCY CAP: You may complete at most 8 tool-call round-trips in this subtask.
If you reach 8 without completing the task, return your partial findings
with a note: "Round-trip cap reached at 8. Partial findings below."
Do not exceed the cap by batching calls that are logically separate.
```

This gate is the latency twin of `cost-accounting.md` Gate 2 (tool-call cap). A subagent that loops on fetch → parse → re-check without a stop condition burns both tokens and seconds.

### Gate 3 — Retry budget

Include in any step that can fail and retry:

```
RETRY BUDGET: You may retry this step at most 2 times.
On the third failure, return the error verbatim and stop.
Do not retry with the same inputs — change at least one parameter or escalate.
```

Uncapped retries are a latency black hole. Two retries is a reasonable upper bound; if a third attempt would be needed, the failure mode requires human judgment, not another iteration.

### Checking gates before acting

Before starting a major step, the orchestrator runs a two-line check:

```
1. Is the cumulative wall-clock estimate below the session cap?  → if no, fan out or stop
2. Does this step's retry budget have capacity?                  → if no, escalate
```

Both must pass. A step that starts when Gate 1 is already over budget will compound the overrun.

## Logging

Write latency state to `state/` at session end — one entry per session, same file as the cost log or a sibling:

**File:** `state/latency-log.md` (append-only, one entry per session)

**Entry format:**

```markdown
## <YYYY-MM-DD> — <skill or task name>

| Signal | Actual | Threshold | Status |
|--------|--------|-----------|--------|
| Wall-clock estimate | ~N s | 60 s / 300 s | OK / OVER |
| Serial step count | N | 5 | OK / OVER |
| Max round-trips (any subagent) | N | 8 | OK / OVER |
| Max retries (any step) | N | 2 | OK / OVER |

**Notes:** <one line on what drove latency, if any gate was triggered>
```

If a gate was triggered, the note line is mandatory. It is the signal the next session reads when deciding whether to restructure the step graph.

## OTel alignment (optional)

If your team already runs OpenTelemetry with the GenAI semantic conventions, the following mapping connects the framework's latency signals to your existing spans. The OTel GenAI spec covers "model names, token counts, latency, and cost metrics across different LLM providers" — the signals in this module map directly to span attributes in that specification.

| agent-foundations signal | OTel GenAI attribute / span |
|--------------------------|----------------------------|
| Total wall-clock estimate | Span duration on the root orchestrator span |
| Per-subagent round-trips | Child span count under `gen_ai.operation.name = "agent"` |
| Fetch count per step | Child span count for `gen_ai.operation.name = "tool"` where tool is a fetch |
| Retry count | Span events with `exception` tag, grouped by parent span |

The three latency gates above map to span-level assertions you can add to your telemetry pipeline. No new spans are needed.

## Anti-patterns

- **Treating latency as a cost proxy.** Cheap model tiers are fast in isolation; a pipeline of 15 cheap steps can be slower than 3 expensive ones in parallel. Model tier and step graph are separate dimensions.
- **No serial-step count.** The biggest latency driver in agent workflows is unnecessary serialization — steps that wait for a prior step's output when they could have been parallel. Count serial steps before you run them.
- **Uncapped retries.** A step that retries indefinitely on a persistent failure is not resilient — it is a latency sink. Two retries, then escalate.
- **Latency log written only on over-runs.** Baseline entries from sessions that finished on time are necessary to calibrate the thresholds. Write the log every session.
- **OTel as a prerequisite.** This module does not require instrumentation. The OTel alignment section documents the optional mapping; teams without OTel skip it entirely.
- **Setting the interactive threshold at batch levels.** A 300 s wait is acceptable in a nightly pipeline. It is not acceptable when a user is waiting for a response. Default to 60 s for interactive tasks and override explicitly for batch.

## Relationship to `cost-accounting.md`

[`./cost-accounting.md`](./cost-accounting.md) caps the total tokens the session may spend. This module caps the total time the session may take. They are complementary: a session can be within token budget but over latency budget (many cheap calls serialized), or within latency budget but over token budget (a few fast but expensive calls). Both modules use the same pattern — conditions in delegation prompts, logs in `state/`, OTel alignment optional — so they compose without duplication. When both logs exist, review them together: a session consistently over latency budget is a candidate for parallelization; a session consistently over token budget is a candidate for tier downsizing.
