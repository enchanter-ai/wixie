# Recipe — BAML

Audience: teams using BAML (Boundary ML) for typed LLM calls. **BAML's paradigm differs fundamentally from agent SDKs**: it does not expose a multi-turn agent loop or a separate system-prompt slot. LLM calls are shaped as typed functions, prompts live inside Jinja template blocks, and structured output is enforced by the BAML parser. Conduct modules adopt by being included in the prompt block of relevant functions — not by being injected as a separate system message.

Read the paradigm note below before attempting to wire conduct the way you would in an OpenAI or LangChain recipe. The adoption pattern is different by design.

## Wire it up

```bash
git submodule add https://github.com/enchanter-ai/agent-foundations vendor/foundations
```

Define a BAML function that includes conduct modules via Jinja:

```baml
// vendor/foundations/conduct modules are plain Markdown — include them as Jinja partials.
// Render via your project's Jinja environment before passing to the BAML compiler,
// or use a shared partial loader that maps conduct module names to their file contents.

// "function name(parameters) -> return_type {
//   client llm_specification
//   prompt block_string_specification
// }"
// — https://docs.boundaryml.com/ref/baml/function.mdx
//
// "Input parameters with explicit types, a return type specification, an LLM client, a prompt"
// — https://docs.boundaryml.com/ref/baml/function.mdx

function ImproveCode(code: string, task: string) -> CodeReview {
  client GPT4o
  prompt #"
    {% include 'conduct/discipline.md' %}
    {% include 'conduct/verification.md' %}

    ## Task
    Review the following code with respect to the conduct rules above.
    Task description: {{ task }}

    ## Code
    {{ code }}

    Return a CodeReview with fields: summary, issues (list), verdict.
  "#
}

class CodeReview {
  summary string
  issues string[]
  verdict "approve" | "hold" | "reject"
}
```

The conduct text is part of the prompt template. Every call to `ImproveCode` pays the token cost of the included modules for that call.

## Paradigm note

BAML's adoption pattern is shaped by the framework's design. Before wiring conduct, understand these three differences from agent-SDK recipes:

**No multi-turn agent.** Each BAML function is a single LLM call. Conduct rules apply per-call; multi-turn protections (sycophancy resistance, doubt-engine, context checkpointing) are the orchestrator's responsibility — the Python, TypeScript, or Ruby caller that invokes the BAML function, not BAML itself.

**No separate instructions slot.** The conduct text is part of the Jinja prompt template. There is no `system` vs. `user` split analogous to the OpenAI chat API or Pydantic-AI's `instructions` field. This means:

- Token cost is paid on every function call, not amortized across turns of an agent session.
- Pull in only the modules the function needs — full-inherit is expensive per call.
- Module placement within the prompt template matters (see [`../conduct/context.md`](../conduct/context.md) § U-curve placement). Put load-bearing rules near the top or bottom of the prompt block.

**Strong typing as the primary enforcement mechanism.** The return type in the function signature plus the BAML parser's retry loop is the core enforcement mechanism — analogous to Pydantic-AI's output validation but operating at the `.baml` source level before any Python code runs.

## Tier mapping

BAML's `client` block declares the LLM. Map the framework's three tiers to whichever providers your project uses:

| Tier | Role | Example client declarations |
|------|------|-----------------------------|
| Top-tier | Orchestration, judgment, technique selection | `client ClaudeOpus { provider anthropic model claude-opus-4-7 }` |
| Mid-tier | Convergence loops, adversarial passes, translation | `client ClaudeSonnet { provider anthropic model claude-sonnet-4-6 }`, `client GPT4o { provider openai model gpt-4o }` |
| Low-tier | Shape checks, extraction, fetch, freshness audits | `client ClaudeHaiku { provider anthropic model claude-haiku-3 }`, `client GPT4oMini { provider openai model gpt-4o-mini }` |

Calibrate prompt density per [`../conduct/tier-sizing.md`](../conduct/tier-sizing.md) — low-tier functions need mechanical steps in the prompt block; top-tier functions run on intent.

## Enforcement wiring

**Output type as the gate.** Define a typed return in the function signature; BAML's parser enforces the schema on every response:

> "Raised when BAML fails to parse a string from the LLM into the specified object."
> — https://docs.boundaryml.com/guide/baml-basics/error-handling.mdx

> "Our parser is very forgiving, allowing for structured data parsing even in the presence of minor errors."
> — https://docs.boundaryml.com/guide/baml-basics/error-handling.mdx

> "When BAML raises an exception, it will be an instance of a subclass of `BamlError`."
> — https://docs.boundaryml.com/guide/baml-basics/error-handling.mdx

Handle parse failures explicitly in your calling code:

```python
from baml_client import b
from baml_client.types import BamlError, BamlValidationError

try:
    review = b.ImproveCode(code=source, task=task_description)
except BamlValidationError as e:
    # Parse failure → F02 Fabrication (model emitted non-conforming output)
    log_failure(code="F02", evidence=str(e), counter="tighten the return type or add examples")
    raise
except BamlError as e:
    # Other BAML-layer error (client failure, timeout, etc.)
    raise
```

Map `BamlValidationError` to `failure-modes.md` code F02 (Fabrication) — the model emitted output that does not conform to the declared return type.

**Honest limit.** The BAML parser is described as "very forgiving, allowing for structured data parsing even in the presence of minor errors." For load-bearing or destructive operations, add a strict re-validation step in your calling code after BAML parsing succeeds — the parser's leniency is a feature for high-recall extraction, not a substitute for strict validation in high-stakes paths.

**Conduct rule to BAML primitive mapping:**

| Conduct rule | BAML primitive | Enforcement point |
|---|---|---|
| `verification.md` § Independent check | Strict return type in function signature | Parser rejects non-conforming output |
| `failure-modes.md` F02 (fabrication) | `BamlValidationError` on parse fail | Calling code catches and logs |
| `delegation.md` § Scope fence | Typed input parameters | Wrong input type fails at compile/call time |
| `tool-use.md` § Right tool, first try | BAML function per task (one verb per function) | No ambiguity about what the function does |
| `tier-sizing.md` § Prompt density | `client` declaration per tier, prompt density by tier | Top-tier client gets intent-level prompt; low-tier gets mechanical steps |

## Conduct propagation

The three patterns from [`../conduct/delegation.md`](../conduct/delegation.md) § Conduct propagation adapt to BAML's function-shaped paradigm.

**Pattern A — Full inherit.** Include every relevant conduct module via Jinja in the function's prompt block. Highest token cost per call; appropriate for top-tier functions or compliance-heavy domains where no module can be omitted.

```baml
function HighStakesDecision(context: string) -> Decision {
  client ClaudeOpus
  prompt #"
    {% include 'conduct/discipline.md' %}
    {% include 'conduct/verification.md' %}
    {% include 'conduct/delegation.md' %}
    {% include 'conduct/failure-modes.md' %}

    ## Context
    {{ context }}

    Decide and return a Decision with fields: verdict, rationale, risk_flags.
  "#
}
```

**Pattern B — Whitelist inject.** Include only the modules relevant to the specific function's task and risk profile. Recommended default; lowest per-call token cost.

```baml
// Low-tier extraction function: only needs tool-use discipline.
function ExtractEntities(text: string) -> EntityList {
  client ClaudeHaiku
  prompt #"
    {% include 'conduct/tool-use.md' %}

    Extract all named entities from the text below.
    Text: {{ text }}
  "#
}
```

**Pattern C — Discovery partial.** Create a shared Jinja partial at `conduct/_index.j2` listing active modules. Functions include the partial instead of individual modules — one place to add, remove, or reorder modules.

```jinja2
{# conduct/_index.j2 — active conduct modules for this project #}
{% include 'conduct/discipline.md' %}
{% include 'conduct/verification.md' %}
{% include 'conduct/tool-use.md' %}
```

```baml
function ReviewPR(diff: string) -> PRReview {
  client ClaudeSonnet
  prompt #"
    {% include 'conduct/_index.j2' %}

    Review the following diff.
    Diff: {{ diff }}
  "#
}
```

**Honest limit.** BAML does not document a base-function-with-overrides pattern. Propagation across functions is by shared Jinja includes and partial files, not by any class or function inheritance mechanism.

| Pattern | Best for | Token cost per call |
|---|---|---|
| Full inherit (all modules in prompt block) | Top-tier, high-stakes, compliance-heavy | High |
| Whitelist inject (per-function module selection) | Mid / low-tier, bounded task scope | Medium |
| Discovery partial (`conduct/_index.j2`) | Multi-function projects, consistent module set | Low–medium |

## Verifying the adoption

BAML's built-in test syntax lets you define A/B test cases inline alongside function definitions:

```baml
test WithoutConduct {
  functions [ImproveCode]
  args {
    code "def f(x): return x+1"
    task "Review this function"
  }
}

test WithConduct {
  functions [ImproveCode]
  args {
    code "def f(x): return x+1"
    task "Review this function"
  }
  // Compare output structure and quality against WithoutConduct
}
```

Run both test blocks and compare: did the conduct-loaded function produce a more structured verdict? Did it catch the missing type annotation that the bare function missed?

See [`../docs/self-test.md`](../docs/self-test.md) for the full fixture methodology.

## What this won't do

- Make BAML's grammar stable across versions. Function syntax, Jinja template handling, and client declaration format are evolving — verify against your current installed release before relying on specific syntax forms.
- Provide multi-turn discipline. BAML is a function-call-shaped tool; conversational protections (sycophancy resistance from `doubt-engine.md`, context checkpointing from `context.md`) belong in the orchestrator that calls the BAML function, not in the BAML prompt block itself.
- Cover the BAML playground, generated client code, or language-specific SDK details. This recipe operates at the `.baml` source level.
- Substitute for a separate system-prompt slot. There is no equivalent in BAML; conduct text lives in the prompt template and pays token cost on every call.
- Replace per-task prompt engineering. Conduct modules shift default behavior; task-specific instructions and few-shot examples still own output quality.
