# Recipe — Pydantic-AI

Audience: teams building agents with Pydantic-AI. Conduct modules become `instructions`; tool guardrails come from Pydantic validation and tool retries; propagation rides on Python class composition and shared instructions-builder functions.

## Wire it up

```bash
git submodule add https://github.com/enchanter-ai/agent-foundations vendor/foundations
```

In Python:

```python
from pathlib import Path
from pydantic_ai import Agent, RunContext
from pydantic import BaseModel

ROOT = Path(__file__).parent / "vendor" / "foundations"

def load_conduct(*names: str) -> str:
    return "\n\n".join((ROOT / "conduct" / f"{n}.md").read_text() for n in names)

class Deps(BaseModel):
    db_conn: str  # replace with your dependency type

class Output(BaseModel):
    result: str

# "Agents are Pydantic AI's primary interface for interacting with LLMs."
# — https://pydantic.dev/docs/ai/core-concepts/agent/
#
# "you can think of an agent as a container for: Instructions, Function tool(s)
# and toolsets, Structured output type, Dependency type constraint, LLM model,
# Model Settings, Capabilities"
# — https://pydantic.dev/docs/ai/core-concepts/agent/
#
# "agents are generic in their dependency and output types, e.g., an agent which
# required dependencies of type `Foobar` and produced outputs of type `list[str]`
# would have type `Agent[Foobar, list[str]]`"
# — https://pydantic.dev/docs/ai/core-concepts/agent/

agent: Agent[Deps, Output] = Agent(
    model="anthropic:claude-opus-4-7",
    deps_type=Deps,
    output_type=Output,
    instructions=(
        "You are a senior backend engineer.\n\n"
        + load_conduct("discipline", "verification", "tool-use", "delegation")
    ),
)
```

The `Agent[Deps, Output]` generic signature makes the dependency and output types explicit at construction — conduct's typed-dependency-injection contract is enforced by the type system before any runtime call.

## Picking modules by agent role

| Agent role | Modules to load |
|------------|-----------------|
| Top-tier orchestrator | `discipline`, `delegation`, `verification`, `failure-modes` |
| Mid-tier executor | `discipline`, `tool-use`, `formatting`, `failure-modes` |
| Low-tier worker (extraction, summarization, fetch) | `tool-use`, `tier-sizing`, `web-fetch` (if it fetches) |

## Tier mapping

Pydantic-AI accepts model identifiers in `provider:model-id` format. Map the framework's three tiers to whichever provider your project uses:

| Tier | Role | Example model strings (pick one) |
|------|------|----------------------------------|
| Top-tier | Orchestration, judgment, technique selection | `'anthropic:claude-opus-4-7'`, `'openai:gpt-5'`, `'google:gemini-pro'` |
| Mid-tier | Convergence loops, adversarial passes, translation | `'anthropic:claude-sonnet-4-6'`, `'openai:gpt-4o'`, `'google:gemini-flash'` |
| Low-tier | Shape checks, extraction, fetch, freshness audits | `'anthropic:claude-haiku-3'`, `'openai:gpt-4o-mini'` |

Calibrate prompt verbosity per [`../conduct/tier-sizing.md`](../conduct/tier-sizing.md) — low-tier agents need mechanical steps; top-tier agents run on intent.

## Enforcement wiring

Conduct modules loaded as text are advisory by default. Pydantic-AI's output validation and tool retry mechanisms are the primary runtime enforcement layer.

**Output validation as the gate.** Define the output type as a Pydantic model; the framework enforces the schema automatically:

> "Pydantic AI will validate the returned structured data and tell the model to try again if validation fails"
> — https://pydantic.dev/docs/ai/core-concepts/output/

> "Output function arguments provided by the model are validated using Pydantic (with optional validation context)"
> — https://pydantic.dev/docs/ai/core-concepts/output/

This is the mechanism that turns conduct's structured-output requirements into runtime gates. Declare strict output types to enforce `verification.md`'s independent-check contract at the schema level.

**Tool retries.** Per-tool retry logic handles transient model errors and malformed calls:

```python
# "via the `@agent.tool` decorator — for tools that need access to the agent context"
# — https://pydantic.dev/docs/ai/tools-toolsets/tools/
#
# "Function parameters are extracted from the function signature, and all parameters
# except `RunContext` are used to build the schema for that tool call."
# — https://pydantic.dev/docs/ai/tools-toolsets/tools/
#
# "@agent.tool(retries=2) def get_user_by_name(ctx: RunContext[DatabaseConn], name: str) -> int:"
# — https://pydantic.dev/docs/ai/core-concepts/agent/

@agent.tool(retries=2)
def lookup_record(ctx: RunContext[Deps], record_id: str) -> dict:
    """Retrieve a record from the database. Returns the record dict."""
    return {"id": record_id, "conn": ctx.deps.db_conn}
```

**Schema completeness guard.** Enforce that every tool parameter carries a description:

> "You can also enforce parameter requirements by setting `require_parameter_descriptions=True`."
> — https://pydantic.dev/docs/ai/tools-toolsets/tools/

Pass `require_parameter_descriptions=True` at tool registration to catch underdescribed schemas at construction time, not at model call time.

**Dynamic instructions.** When conduct rules depend on runtime context, use the decorated function form:

> "Dynamic instructions rely on context that is only available at runtime and should be defined using functions decorated with `@agent.instructions`"
> — https://pydantic.dev/docs/ai/core-concepts/agent/

```python
@agent.instructions
def runtime_conduct(ctx: RunContext[Deps]) -> str:
    # Emit only the modules relevant to this dependency's risk profile
    if ctx.deps.db_conn.startswith("prod"):
        return load_conduct("discipline", "verification", "failure-modes")
    return load_conduct("discipline", "tool-use")
```

**Conduct rule to Pydantic-AI primitive mapping:**

| Conduct rule | Pydantic-AI primitive | Enforcement point |
|---|---|---|
| `verification.md` § Output validation | Structured `output_type` + auto-retry | Schema mismatch triggers model retry |
| `failure-modes.md` F08 (tool mis-invocation) | `@agent.tool(retries=N)` | Per-tool retry budget on bad calls |
| `delegation.md` § Scope fence | Typed dependency injection (`deps_type`) | Wrong dep type fails at construction |
| `tool-use.md` § Right tool, first try | `require_parameter_descriptions=True` | Underdescribed tools fail at startup |
| `failure-modes.md` F02 (fabrication) | Strict Pydantic validators in `output_type` | Malformed structured output rejected |

**Honest limit.** Pydantic-AI has no PreToolUse-style runtime gate — there is no programmatic interception point before a tool call executes. Enforcement is via type validation and retry, not refusal. For hard gates (blocking irreversible shell ops, requiring human approval), add a wrapper layer outside the agent or use a different runtime that exposes pre-execution hooks.

## Conduct propagation

Pydantic-AI agents have no memory of a parent session when spawned as subagents. Without explicit propagation, subagents operate without behavioral guardrails. The three patterns from [`../conduct/delegation.md`](../conduct/delegation.md) § Conduct propagation apply here, translated to Pydantic-AI idioms.

**Pattern A — Full inherit.** Pass all relevant conduct modules in the `instructions` string:

```python
# "System prompts might seem simple at first glance since they're just strings
# (or sequences of strings that are concatenated)"
# — https://pydantic.dev/docs/ai/core-concepts/agent/

full_conduct = load_conduct("discipline", "verification", "delegation", "failure-modes")

orchestrator: Agent[Deps, Output] = Agent(
    model="anthropic:claude-opus-4-7",
    deps_type=Deps,
    output_type=Output,
    instructions="You are a senior orchestrator.\n\n" + full_conduct,
)
```

Token cost: high — five conduct modules at ~600 tokens each add 3,000+ tokens per invocation. Reserve for low-frequency, high-stakes agents.

**Pattern B — Whitelist inject.** Use `@agent.instructions` to emit only the modules relevant to the current dependency type at runtime:

```python
# "use: `instructions` when you want your request to the model to only include
# system prompts for the _current_ agent"
# — https://pydantic.dev/docs/ai/core-concepts/agent/

@agent.instructions
def selective_conduct(ctx: RunContext[Deps]) -> str:
    # Whitelist inject: only load what this agent's tools can violate
    return load_conduct("tool-use", "web-fetch")
```

Token cost: medium — typically two or three modules. The tradeoff is the same as the Pattern B framing in `delegation.md`: if the agent's actual behavior drifts outside its stated whitelist, the missing modules are not there to catch it.

**Pattern C — Discovery file.** Place an `AGENTS.md` at the project root. Each agent's `instructions` opens with a read-this-first clause:

```python
AGENTS_MD = Path("AGENTS.md").read_text()

worker: Agent[Deps, Output] = Agent(
    model="anthropic:claude-haiku-3",
    deps_type=Deps,
    output_type=Output,
    instructions="Read the behavioral contract below before starting work.\n\n" + AGENTS_MD,
)
```

Keep `AGENTS.md` as a list of active modules and enforcement status — not a dump of module prose. Token cost: low to medium.

**Dependency-type composition.** An `Agent[BaseDeps, Output]` and `Agent[ExtendedDeps, Output]` can share an instructions-builder function that emits the right conduct subset based on the dependency type. This is the Pydantic-AI analog of agent class inheritance — propagation is via shared builder functions, not subclasses.

**Honest limit.** Pydantic-AI does not document an `Agent.clone()` analog (the fetched docs cover dependency generics but not agent inheritance). For now, propagation is via shared instructions-builder functions, not class inheritance.

See [`../conduct/delegation.md`](../conduct/delegation.md) § Conduct propagation patterns for the conceptual framing.

| Pattern | Best for | Token cost |
|---|---|---|
| Full inherit via `instructions` string | Top-tier, high-stakes, unpredictable tool use | High |
| Whitelist inject via `@agent.instructions` | Mid / low-tier, known bounded tools | Medium |
| Discovery file (`AGENTS.md`) | Multi-skill teams, high-frequency subagents | Low–medium |

## Verifying the adoption

A/B fixture: same prompt, same model, two `Agent` instances — one with conduct loaded, one without. Run on a known fixture, compare outputs:

1. Ask the agent to do something it should refuse without confirmation (e.g., a destructive op). It should ask first or emit a dry-run plan.
2. Ask it a question that triggers context overflow. It should checkpoint.
3. Trigger a known F-code condition (e.g., F02 by requesting a non-existent file). It should ground before claiming.

If any of those fail, the relevant module is not being loaded — check the `instructions` concatenation.

See [`../docs/self-test.md`](../docs/self-test.md) for the full fixture methodology.

## What this won't do

- Make Pydantic-AI's API stable across versions. `@agent.tool`, `instructions`, `@agent.instructions`, and validation hooks are evolving — verify against your current installed release before relying on specific method signatures.
- Substitute for prompt engineering inside the `instructions` string. Conduct shifts default behavior; per-task prompts still own task quality.
- Provide a PreToolUse-style runtime gate. Enforcement is via type validation and retry, not programmatic pre-execution refusal.
- Cover Pydantic Logfire integration. Observability is orthogonal to behavioral conduct.
- Document an `Agent.clone()` inheritance pattern. The fetched docs do not cover agent inheritance; composition via shared builder functions is the documented path.
