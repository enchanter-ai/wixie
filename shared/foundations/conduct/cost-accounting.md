# Cost Accounting — Runtime Budget Discipline

Audience: any agent orchestrator. How to set, track, and gate session-wide costs without adding runtime services — so tier selection is not the only cost lever, and sessions do not silently run over budget.

## The problem

Tier routing reduces cost *per token*. It does not reduce total cost if the session runs more subagents, more tool calls, or more rounds than originally scoped. The two levers are complementary, not substitutes: [`./tier-sizing.md`](./tier-sizing.md) picks the cheapest tier for each task; this module caps the total number of tasks.

Without a budget ceiling, three failure patterns recur:

1. **Subagent sprawl.** The orchestrator spawns a new subagent for each perceived uncertainty, each spawning its own tool calls, until the session cost is an order of magnitude above the task's value.
2. **Tool-call inflation.** A single subagent loops on a tool (e.g., iterative search → fetch → re-check) without a hard stop, burning both tokens and latency.
3. **Silent overrun.** No budget signal exists, so neither the agent nor the developer knows the session went over until the invoice arrives.

Budget Tracker (arxiv 2511.17006) identifies accumulation across subagents as the primary untracked cost driver. LangChain's prebuilt middleware confirms that cap-as-condition — expressing the budget gate as a condition in the delegation prompt rather than a separate runtime process — is sufficient for production use.

## Cost signals to track

Track these signals. All can be captured in a Markdown-only workflow with no instrumentation tooling.

| Signal | How to capture (Markdown-only) | Default threshold |
|--------|-------------------------------|-------------------|
| **Session token estimate** | Orchestrator counts: prompt tokens per subagent spawn (model's stated context) × number of spawns + own turns | 200 k tokens |
| **Subagent spawn count** | Orchestrator maintains a counter in its internal state; increments on each subagent call | 10 subagents |
| **Tool-call count per subagent** | Each subagent prompt includes a cap in its delegation clause (see Budget gates below) | 15 tool calls |
| **Round-trip count** | Number of back-and-forth exchanges with the user on the same task scope | 8 rounds |
| **High-tier fraction** | Fraction of subagent spawns at the highest model tier; above 20% is a cost smell | < 20% top-tier |

Thresholds above are defaults. Set project-specific thresholds in the skill's metadata or in a leading comment in the delegation prompt. The default is a guardrail, not a contract.

## Budget gates

Three named gates. Each is expressed as a **condition in the delegation prompt**, not a runtime service. The orchestrator checks the condition before spawning a subagent or approving a next round. This is the dependency-free formulation.

### Gate 1 — Session-wide token cap

Include in the orchestrator's own system prompt or leading context:

```
BUDGET GATE — SESSION TOKENS
If cumulative estimated token spend across all subagents this session exceeds 200 k,
STOP spawning new subagents. Complete the current task with existing findings.
Report budget status at handoff: "Budget gate triggered at ~N k tokens."
```

Adjust 200 k to the project's cost tolerance. At 1M-token models, this is not a context limit — it is a cost limit.

### Gate 2 — Per-subagent tool-call cap

Include at the end of every subagent delegation prompt (see [`./delegation.md`](./delegation.md) § Three non-negotiable clauses):

```
TOOL-CALL CAP: You may invoke at most 15 tool calls in this subtask.
If you reach 15 without completing the task, return your partial findings
with a note: "Tool-call cap reached at 15. Partial findings below."
Do not exceed the cap by reframing tool calls as sub-steps.
```

This is the most effective single-subagent cost gate. Subagents that loop on search and fetch without a stop condition are the dominant source of tool-call inflation.

### Gate 3 — Spawn count cap

Include in the orchestrator's delegation logic, checked before each subagent call:

```
SPAWN COUNT CAP: This orchestrator may spawn at most 10 subagents per session.
Before each spawn, check the current count. If at 10, do not spawn.
Complete remaining sub-tasks inline or report them as out-of-scope.
```

At 10 subagents, the orchestrator itself becomes the bottleneck — which is the correct design. A session requiring more than 10 subagents to complete is mis-scoped, not under-resourced.

### Checking gates before acting

Before spawning a subagent, the orchestrator runs a three-line check:

```
1. Is the session token estimate below the session cap?       → if no, stop
2. Is the current spawn count below the spawn cap?            → if no, stop
3. Does this subagent's scoped work justify its expected cost? → if no, inline it
```

All three must pass. A subagent spawned when any check fails is a budget violation, not a judgment call.

## Logging

Write budget state to `state/` at session end for post-session review. This is the minimum viable log — it takes one minute and prevents the next session from repeating the same spend profile.

**File:** `state/budget-log.md` (append-only, one entry per session)

**Entry format:**

```markdown
## <YYYY-MM-DD> — <skill or task name>

| Signal | Actual | Threshold | Status |
|--------|--------|-----------|--------|
| Session token estimate | ~N k | 200 k | OK / OVER |
| Subagent spawns | N | 10 | OK / OVER |
| Max tool calls (any subagent) | N | 15 | OK / OVER |
| Top-tier fraction | N% | 20% | OK / HIGH |

**Notes:** <one line on what drove costs, if any gate was triggered>
```

Entries are append-only. Do not edit prior entries. If a gate was triggered, the note line is mandatory — it is the signal the next session reads.

## OTel alignment (optional)

If your team already runs OpenTelemetry with the GenAI semantic conventions, the following mapping lets you connect the framework's budget signals to your existing spans. This section is optional — it describes what to name spans if instrumentation exists, not a requirement to add instrumentation.

| agent-foundations signal | OTel GenAI attribute |
|--------------------------|---------------------|
| Session token estimate | `gen_ai.usage.input_tokens` + `gen_ai.usage.output_tokens` (sum across spans) |
| Per-subagent tool-call count | Span count for `gen_ai.operation.name = "tool"` under the subagent's trace |
| Subagent spawn count | Child span count for `gen_ai.operation.name = "agent"` under the orchestrator span |
| Session cost | `gen_ai.usage.total_cost` (if your provider emits it) |

The three budget gates above map to span attributes you can assert in your telemetry pipeline. No new spans are needed — the gates are conditions in prompts, not instrumented code.

## Anti-patterns

- **Tier routing as the only cost control.** A low tier at 30 subagents costs more than a high tier at 3. Both levers must be active.
- **No spawn cap.** The orchestrator that spawns freely until the task is done has no cost model. Set the cap before the first spawn.
- **Tool-call cap omitted from delegation prompts.** Every subagent delegation prompt must carry Gate 2. A prompt without it has no stop condition for tool loops.
- **Budget log written only on over-runs.** The log is useful only if it has baseline entries from sessions that went normally. Write it every session.
- **OTel as a prerequisite.** The cost-accounting module does not require instrumentation. The OTel alignment section documents the optional mapping; teams without OTel skip it entirely.
- **Cap set once and never revised.** A 200 k-token cap is a default. After two or three sessions, check the log and calibrate to the actual spend profile of the specific workflow.
- **Counting tool calls inside a subagent without telling the subagent.** The tool-call cap only works if it appears in the subagent's own delegation prompt. The orchestrator cannot enforce a cap on a subagent it never communicated the cap to.

## Relationship to `tier-sizing.md`

[`./tier-sizing.md`](./tier-sizing.md) sets the cost-per-token through model-tier selection. This module sets the ceiling on the total number of tokens the session is allowed to spend. They operate at different levels of the cost stack and are designed to be used together: tier selection first, budget gates second. A session that picks the right tier but has no budget gates is cost-disciplined at the unit level and undisciplined at the system level.
