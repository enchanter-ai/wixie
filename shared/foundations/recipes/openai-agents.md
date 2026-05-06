# Recipe — OpenAI Agents SDK

How to adopt agent-foundations with the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/).

## What you get

The Agents SDK exposes `instructions` (system prompt), `tools`, and `handoffs` for delegation. Conduct modules slot into instructions; engines slot into tool implementations or post-call validators; the failure taxonomy slots into structured logging.

## Drop-in

```bash
git submodule add https://github.com/enchanter-ai/agent-foundations vendor/foundations
```

In Python:

```python
from pathlib import Path
from agents import Agent, Runner

ROOT = Path(__file__).parent / "vendor" / "foundations"

def load_conduct(*names: str) -> str:
    return "\n\n".join((ROOT / "conduct" / f"{n}.md").read_text() for n in names)

agent = Agent(
    name="MyOrchestrator",
    instructions=(
        "You are a senior backend engineer.\n\n"
        + load_conduct("discipline", "verification", "tool-use", "delegation")
    ),
    model="gpt-5",
    tools=[...],
)
```

## Picking modules by agent role

| Agent role | Modules to load |
|------------|-----------------|
| Top-tier orchestrator | `discipline`, `delegation`, `verification`, `failure-modes` |
| Mid-tier executor | `discipline`, `tool-use`, `formatting`, `failure-modes` |
| Low-tier worker (extraction, summarization) | `tool-use`, `tier-sizing` (so the prompt is mechanical), `web-fetch` (if it fetches) |

The `delegation.md` rules map directly to the SDK's `handoffs` mechanism — every handoff prompt should include the three non-negotiable clauses (structured return, scope fence, context briefing).

## Engines as tools

Engines from `engines/` are language-neutral primitives. Wrap them as SDK tools:

```python
from agents import function_tool

@function_tool
def trust_score(history: list[bool]) -> dict:
    """Beta-Bernoulli trust score over a binary history."""
    alpha, beta_ = 2.0, 2.0
    for ok in history:
        if ok:
            alpha += 1
        else:
            beta_ += 1
    mean = alpha / (alpha + beta_)
    var = (alpha * beta_) / ((alpha + beta_) ** 2 * (alpha + beta_ + 1))
    return {"mean": mean, "variance": var}
```

See [`../engines/trust-scoring.md`](../engines/trust-scoring.md) for the math and [`../engines/README.md`](../engines/README.md) for the catalog.

## Failure logging

Pipe each agent run through a structured logger that writes to a project-local failure log. Tag every entry with one of the [14 codes](../taxonomy/README.md):

```python
import json, time
from pathlib import Path

LOG = Path("state/failure-log.jsonl")

def log_failure(code: str, axis: str | None, hypothesis: str, outcome: str, counter: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({
            "ts": time.time(),
            "code": code,
            "axis": axis,
            "hypothesis": hypothesis,
            "outcome": outcome,
            "counter": counter,
        }) + "\n")
```

Read [`../conduct/failure-modes.md`](../conduct/failure-modes.md) § How to read the log before a new round for the consult-then-act protocol.

## Tier mapping

The SDK doesn't enforce tiers, but the [`../conduct/tier-sizing.md`](../conduct/tier-sizing.md) rubric still applies:

| Tier | OpenAI default |
|------|----------------|
| Top | `gpt-5` |
| Mid | `gpt-4o` |
| Low | `gpt-4o-mini` |

Calibrate prompt verbosity per the rubric — over-decomposed prompts waste budget on top tier; under-decomposed prompts produce silent quality loss on low tier.

## Verifying the adoption

After integration, run a smoke test:

1. Ask the agent to do something it should refuse without confirmation (e.g., `rm -rf`). It should ask first.
2. Ask it a question that triggers context overflow. It should checkpoint.
3. Trigger a known F-code condition (e.g., F02 by asking for a non-existent file). It should ground (Glob/Grep) before claiming.

If any of those fail, the relevant module isn't being loaded — check the `instructions` concatenation.

## Enforcement wiring

Conduct modules are descriptive by default. The table below maps each load-bearing rule to the
OpenAI Agents SDK primitive that can enforce it at runtime.

| Conduct rule | OpenAI SDK primitive | Enforcement point |
|---|---|---|
| `verification.md` § Dry-run for destructive ops | Tool guardrail `before_execution` | Block the tool call; require approval before proceeding |
| `delegation.md` § Scope fence | Tool guardrail `after_execution` | Audit output for out-of-scope actions before returning |
| `failure-modes.md` F10 (destructive without confirmation) | Human approval (continue/pause/stop) | Pause run; route to human before irreversible action |
| `tool-use.md` § Read before Edit | Tool guardrail `before_execution` on edit-class tools | Assert a prior read of the same path exists in session |
| `precedent.md` § Consult-then-act | Tool guardrail `before_execution` on Bash-class tools | Grep precedent log; inject warning if hit found |

**Tool-wrap guardrails.** The Agents SDK exposes guardrails at the tool level. According to the
SDK documentation: "Tool guardrails wrap function tools and let you validate or block tool calls
before and after execution." Wire the `before_execution` hook to tripwire destructive ops — the
tool raises a `GuardrailFailed` exception, which surfaces to the orchestrator as a pause
signal rather than a silent execution.

**continue / pause / stop control model.** For ops that need human review rather than outright
blocking, use the SDK's approval flow. The SDK documentation states: "Together, they define when
a run should continue, pause, or stop." Map F10 (destructive without confirmation) to `pause`;
resume only after explicit approval. This gives you the dry-run semantics from
`verification.md` without a full PreToolUse deny.

**LangGraph alternative.** If your orchestration layer uses LangGraph, tool-local interrupts
cover the same surface. Per the LangGraph documentation: "This makes the tool itself pause for
approval whenever it's called, and allows for human review and editing of the tool call before
it is executed." Interrupt at the tool node, route to a human-in-the-loop edge, then re-enter
the graph on approval. This is architecturally equivalent to the SDK's pause/resume flow and
requires no SDK-level guardrail wiring.

**Invariant Guardrails (third-party).** For a rule-based proxy layer that sits outside the
SDK's own tool-call lifecycle, Invariant Guardrails applies: "Invariant Guardrails is a
comprehensive rule-based guardrailing layer for LLM or MCP-powered AI applications." Use it
when you need policy enforcement across multiple agents or runtimes without modifying each
agent's tool definitions.

**What enforcement cannot cover.** Reasoning-level modules — `doubt-engine.md`,
`context.md`, `tier-sizing.md` — operate inside the model's forward pass. No tool guardrail
or approval flow can intercept those. The table above covers actions (tool calls) only.

## Conduct propagation

Subagents spawned via `handoffs` have no memory of the parent session. Without explicit
propagation, they operate without behavioral guardrails. The three patterns from
[`../conduct/delegation.md`](../conduct/delegation.md) § Conduct propagation apply here,
translated to OpenAI Agents SDK terminology.

**Pattern A — Full inherit.** Include the relevant conduct modules in full in the subagent's
`instructions`. For top-tier orchestrators or high-stakes subagents (red-team, security
audit), paste the module text into the agent definition. In the Agents SDK, `Agent.clone()` is
the Python-native equivalent of Claude Code's prompt-append mechanism:

```python
base_agent = Agent(
    name="BaseOrchestrator",
    instructions=load_conduct("discipline", "verification", "delegation"),
    model="gpt-5",
)

# Full inherit: subagent gets the same conduct modules
sub_agent = base_agent.clone(
    name="SecurityAuditor",
    instructions=base_agent.instructions + "\n\n" + load_conduct("failure-modes"),
    model="gpt-5",
)
```

Per the SDK documentation: "By using the clone() method on an agent, you can duplicate an
Agent, and optionally change any properties you like." Token cost: high — five conduct modules
at ~600 tokens each add 3,000+ tokens per subagent invocation. Reserve for low-frequency,
high-stakes subagents.

**Pattern B — Whitelist inject.** For mid-tier or low-tier subagents with a bounded tool
whitelist, inject only the modules whose rules those tools can violate (see the tool-whitelist
table in `conduct/delegation.md`). Pass the injected modules in `instructions` when
constructing the subagent, rather than cloning from the full-inherit parent. Token cost:
medium — typically two to three modules instead of five.

**Pattern C — Discovery file.** Place an `AGENTS.md` at the project root listing active
conduct modules and their enforcement status. Each subagent's `instructions` opens with a
read-this-first clause. In API-only SDK invocations without filesystem access, inline the
discovery file content directly into `instructions` at agent creation time — the SDK has no
auto-read equivalent to Claude Code's prompt-append. Token cost: low to medium, scaling with
how much the file embeds vs. references by path.

**LangChain middleware.** If the stack includes LangChain, shared conduct checks can be
applied via the middleware mechanism: "add the middleware to the agent's middleware list when
creating the agent." This is the LangChain equivalent of whitelist inject — wrap specific
tool actions with shared checks without loading all conduct modules into every agent's
system prompt.

| Pattern | Best for | Token cost |
|---|---|---|
| Full inherit via `clone()` | Top-tier, high-stakes, unpredictable tool use | High |
| Whitelist inject at construction | Mid / low-tier, known bounded tools | Medium |
| Discovery file (`AGENTS.md`) | Multi-skill teams, high-frequency subagents | Low–medium |

## What this won't do

- Replace the SDK's tracing / observability — those are runtime; the conduct is design-time.
- Replace your prompt engineering — modules are *defaults*, not the prompt itself.
- Force structured output — pair with the SDK's response schemas / Pydantic models.
