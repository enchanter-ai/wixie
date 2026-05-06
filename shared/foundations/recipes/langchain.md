# Recipe — LangChain

How to adopt agent-foundations with [LangChain](https://python.langchain.com/) or [LangGraph](https://langchain-ai.github.io/langgraph/).

## What you get

LangChain exposes a system message (or `ChatPromptTemplate` system slot), a tool list, and — when using LangGraph — a stateful graph with interruptible nodes. Conduct modules slot into the system message; middleware wraps shared checks around tool calls; LangGraph interrupts provide human-in-the-loop gates for irreversible actions.

## Wire it up

```bash
git submodule add https://github.com/enchanter-ai/agent-foundations vendor/foundations
```

In Python, using LangChain's LCEL idioms:

```python
from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate
from langchain.agents import create_react_agent, AgentExecutor

ROOT = Path(__file__).parent / "vendor" / "foundations"

def load_conduct(*names: str) -> str:
    return "\n\n".join(
        (ROOT / "conduct" / f"{n}.md").read_text() for n in names
    )

conduct = load_conduct("discipline", "verification", "tool-use", "delegation")

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a senior engineer.\n\n" + conduct),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

# Substitute your chosen ChatModel class — see Tier mapping below.
agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
executor = AgentExecutor(agent=agent, tools=tools, middleware=middleware_list)
```

The conduct text loads once at construction; every invocation of this executor carries the behavioral defaults.

## Picking modules by agent role

| Agent role | Modules to load |
|------------|-----------------|
| Top-tier orchestrator | `discipline`, `delegation`, `verification`, `failure-modes` |
| Mid-tier executor | `discipline`, `tool-use`, `formatting`, `failure-modes` |
| Low-tier worker (extraction, summarization, fetch) | `tool-use`, `tier-sizing`, `web-fetch` (if it fetches) |

The `delegation.md` rules map directly to LangGraph's subgraph / map-reduce edges — every subgraph entry prompt should include the three non-negotiable clauses (structured return, scope fence, context briefing).

## Tier mapping

LangChain is model-vendor-neutral. Map the framework's three tiers to whichever provider your project uses:

| Tier | Role | Example classes (pick one) |
|------|------|---------------------------|
| Top-tier | Orchestration, judgment, technique selection | `ChatAnthropic` (Opus), `ChatOpenAI` (GPT-5), `ChatVertexAI` (Gemini Pro) |
| Mid-tier | Convergence loops, adversarial passes, translation | `ChatAnthropic` (Sonnet), `ChatOpenAI` (GPT-4o), `ChatVertexAI` (Gemini Flash) |
| Low-tier | Shape checks, extraction, fetch, freshness audits | `ChatAnthropic` (Haiku), `ChatOpenAI` (GPT-4o-mini), `ChatGroq` (Llama 3) |

Calibrate prompt verbosity per [`../conduct/tier-sizing.md`](../conduct/tier-sizing.md) — Haiku-class models need mechanical steps; Opus-class models run on intent.

## Enforcement wiring

Conduct modules loaded as text are advisory by default. LangChain and LangGraph offer two
mechanisms to promote rules from memorized defaults to runtime gates.

**Middleware (LangChain).** LangChain's prebuilt middleware layer wraps checks around every
tool action. Per the LangChain documentation: "add the middleware to the agent's middleware
list when creating the agent." This gives you a combined PreToolUse + PostToolUse surface —
one middleware class intercepts the call before execution, inspects it, and optionally
intercepts the result after. The prebuilt library includes, for example: "Model call limit
Limit the number of model calls to prevent excessive costs."

Concrete example — enforcing `verification.md` § Dry-run for destructive ops as a
middleware check before any tool call:

```python
from langchain_core.runnables import RunnableConfig

class DestructiveOpGuard:
    """Middleware: block destructive shell patterns without explicit confirmation."""

    DESTRUCTIVE = ["rm -rf", "git reset --hard", "git push --force", "DROP TABLE"]

    def before_tool(self, tool_name: str, tool_input: dict, config: RunnableConfig):
        if tool_name in ("bash", "shell", "terminal"):
            cmd = str(tool_input.get("command", ""))
            for pattern in self.DESTRUCTIVE:
                if pattern in cmd:
                    raise ValueError(
                        f"Conduct gate: destructive pattern '{pattern}' detected. "
                        "Emit a dry-run plan first (verification.md § Dry-run), then retry."
                    )

    def after_tool(self, tool_name: str, tool_output, config: RunnableConfig):
        # Scope fence audit: log tool name + output size for out-of-scope detection.
        return tool_output
```

Wire it:

```python
executor = AgentExecutor(
    agent=agent,
    tools=tools,
    middleware=[DestructiveOpGuard()],
)
```

**LangGraph tool-node interrupts.** For ops that need human review rather than outright
blocking, LangGraph's interrupt-in-tool mechanism provides a pause-for-approval flow. Per
the LangGraph documentation: "This makes the tool itself pause for approval whenever it's
called, and allows for human review and editing of the tool call before it is executed."
Interrupt at the tool node, route to a human-in-the-loop edge, then resume the graph on
approval. This is the LangGraph analog of the verification dry-run confirmation step.

Conduct rule to LangChain primitive mapping:

| Conduct rule | LangChain primitive | Enforcement point |
|---|---|---|
| `verification.md` § Dry-run for destructive ops | Middleware `before_tool` | Block before execution; raise on match |
| `delegation.md` § Scope fence | Middleware `after_tool` | Audit output for out-of-scope actions |
| `failure-modes.md` F10 (destructive without confirmation) | LangGraph interrupt in tool node | Pause graph; human approves before resuming |
| `tool-use.md` § Read before Edit | Middleware `before_tool` on write-class tools | Assert a prior read of the same path exists in graph state |
| `precedent.md` § Consult-then-act | Middleware `before_tool` on shell-class tools | Grep precedent log; inject warning if a hit is found |

**Honest limit.** LangChain's middleware API surface is evolving. Class names, hook
signatures, and lifecycle events may shift between LangChain Core, LangGraph, LangServe,
and LangSmith releases. Verify against the current release before relying on specific class
names or method signatures in production. Treat the patterns above as structural templates,
not copy-paste production code.

**What enforcement cannot cover.** Reasoning-level modules — `doubt-engine.md`,
`context.md`, `tier-sizing.md` — operate inside the model's forward pass. No middleware
hook or graph interrupt can intercept those. The table above covers actions (tool calls) only.

## Conduct propagation

Subgraphs and subagents spawned via LangGraph edges or `AgentExecutor` calls have no memory
of the parent session. Without explicit propagation, they operate without behavioral
guardrails. The three patterns from [`../conduct/delegation.md`](../conduct/delegation.md)
§ Conduct propagation apply here, translated to LangChain idioms.

**Pattern A — Full inherit.** Concatenate all relevant conduct modules into the subagent's
system prompt at construction time. For top-tier orchestrators or high-stakes subgraphs
(red-team, security audit, final convergence), pass the full module text directly:

```python
sub_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a security auditor.\n\n"
     + load_conduct("discipline", "verification", "delegation", "failure-modes")),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])
```

Token cost: high. Five conduct modules at ~600 tokens each add 3,000+ tokens per subagent
invocation. Reserve for low-frequency, high-stakes subgraphs.

**Pattern B — Whitelist inject.** For mid- or low-tier subagents with a bounded tool list,
inject only the modules whose rules those tools can violate. Pass the injected modules in the
system slot at construction — no need to load modules the agent's tools cannot trigger. Use
LangChain's `ChatPromptTemplate` variables to vary the injected subset per agent role:

```python
def make_agent(role_blurb: str, conduct_modules: list[str], llm, tools):
    conduct = load_conduct(*conduct_modules)
    prompt = ChatPromptTemplate.from_messages([
        ("system", f"{role_blurb}\n\n{conduct}"),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])
    return AgentExecutor(agent=create_react_agent(llm, tools, prompt), tools=tools)

# Low-tier fetcher: only needs tool-use + web-fetch
fetcher = make_agent(
    "You are a web-content fetcher.",
    ["tool-use", "web-fetch"],
    haiku_llm,
    [fetch_tool],
)
```

Token cost: medium — typically two or three modules instead of five. The tradeoff mirrors
Pattern B from `delegation.md`: if the subagent's actual behavior drifts outside its stated
tool whitelist, the missing modules are not there to catch it.

**Pattern C — Discovery file.** Place an `AGENTS.md` (or `CONDUCT.md`) at the project root
listing active conduct modules and their enforcement status. Each subagent's system prompt
opens with a read-this-first clause. LangChain has no native auto-read equivalent to Claude
Code's prompt-append mechanism — inline the discovery file content at agent construction:

```python
AGENTS_MD = Path("AGENTS.md").read_text()

sub_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "Read the behavioral contract below before starting work.\n\n"
     + AGENTS_MD),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])
```

Keep `AGENTS.md` as a list and metadata (module names, enforcement status, project
overrides) — not a dump of module prose. Token cost: low to medium, scaling with how much
content the file embeds vs. references.

Per [`../conduct/delegation.md`](../conduct/delegation.md) § Cross-vendor precedent: "LangChain
agent middleware … wraps shared checks around specific tool actions without injecting all
rules into every agent." That is the whitelist-inject pattern applied via the enforcement
layer rather than the system prompt. The two approaches compose: inject a short system-prompt
module list (Pattern B) and guard the tool boundary with middleware (§ Enforcement wiring).

| Pattern | Best for | Token cost |
|---|---|---|
| Full inherit | Top-tier, high-stakes, unpredictable tool use | High |
| Whitelist inject via `ChatPromptTemplate` | Mid / low-tier, bounded tool list | Medium |
| Discovery file (`AGENTS.md`) | Multi-skill teams, high-frequency subagents | Low–medium |

## Verifying the adoption

A simple A/B test:

1. Run a fixture prompt against your agent *without* any conduct loaded. Record responses.
2. Load the production starter pack (`discipline.md` + `verification.md` + `failure-modes.md`) and run the same fixture.
3. Compare: did the agent ask before a destructive op? Did unverified claims decrease? Did task-drift incidents drop?

If the deltas are zero, the modules are not being loaded — check the system slot concatenation.

Check middleware fires:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Add a logging shim to your middleware's before_tool method:
def before_tool(self, tool_name, tool_input, config):
    logging.debug(f"[conduct-gate] {tool_name} called with input keys: {list(tool_input)}")
    # ... rest of check
```

Count gate invocations across a session; if the count is zero on a run that should have triggered checks, the middleware is not wired in.

## What this won't do

- Make LangChain's middleware API stable. The framework loads as text; the middleware wiring
  is a code surface that adopters maintain against their installed LangChain version.
- Replace LangGraph's checkpointing or persistence — those are orthogonal to behavioral
  conduct and operate at the graph-state level.
- Cover every LangChain runtime variant (LangChain Core, LangGraph, LangServe, LangSmith).
  This recipe focuses on agent runtimes with a system-message slot and tool execution loop.
- Provide runtime enforcement for reasoning-level modules (`doubt-engine.md`, `context.md`,
  `tier-sizing.md`). Those operate inside the model's forward pass and cannot be intercepted
  by middleware or graph interrupts.
