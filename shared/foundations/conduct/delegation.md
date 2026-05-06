# Delegation — Subagent Contracts

Audience: any agent that can spawn subagents. How to delegate without poisoning the parent context or duplicating work. Your project may name the tier (e.g., Opus / Sonnet / Haiku for Anthropic; o-series / 4o / mini for OpenAI); this module defines the *contract* at the boundary.

## When to spawn a subagent

**Default: delegate by default.** For any substantive task — build, refactor, research, multi-file edit, scaffold run — execute via a subagent, not inline. The friction of a subagent is lower than the cost of doing work the user expected to be agent-dispatched. Spawn parallel agents (one message, multiple subagent calls) when slices are independent.

**Exceptions — keep these inline:**

1. Trivially small read-only ops the user can verify in one glance — reading a file they named, answering a direct factual question about repo state, confirming path existence.
2. Integration glue after a subagent returns — joining outputs, applying small fixes caught post-return, propagating a single edit across repos.
3. Cases where **all three** of these hold: raw material small, parent already has needed context, subtask not independent of ongoing reasoning.

When in doubt, delegate. The cost asymmetry favors delegation: a wasted subagent costs tokens; a missed delegation costs user trust.

## The three non-negotiable clauses

Every subagent prompt includes all three. Missing one is a contract violation.

### 1. Structured return clause

End the prompt with an explicit output shape. The subagent's final message *is* the hand-off; intermediate tool noise is invisible to the parent.

> *"Return one findings block per matching file as: `{path, line_range, finding, confidence}`. Skip unrelated files. Under 300 words total."*

No structure → parent gets a discursive paragraph → parent wastes a round re-extracting.

### 2. Scope fence

Name what's out of scope. Subagents over-help by default.

> *"Do not fix issues you find. Do not edit files. Read-only investigation."*
> *"Do not spawn sub-subagents. If the task is larger than expected, return early with a note."*

### 3. Context briefing

The subagent has no memory of the conversation. Brief it like a colleague who just walked in: goal, what's already ruled out, why this matters.

> *"I'm tracking down a score-inflation bug in the convergence loop. Already ruled out: the metadata writer and the self-eval path. Need to check: the reviewer's score-extraction regex. Files: …"*

A one-sentence command yields a shallow generic report. A briefing yields a useful one.

## Tool whitelisting per subagent

Match tools to the job. Over-granting is how subagents corrupt the parent repo state.

| Subagent role | Tools granted |
|---------------|---------------|
| Investigator (research, grep) | Read, Grep, Glob |
| Red-team (adversarial audit) | Read, Grep, Glob — never Write or Edit |
| Test-runner | Read, Bash (test commands only) |
| Format translator | Read, Write (target file only) |
| Validator (cheaper-tier check) | Read, Grep |

The parent runs the actual writes after consuming the subagent's summary.

## Parallel vs. serial

Parallel when independent. Serial when step 2 consumes step 1's output.

| Pattern | Rule |
|---------|------|
| Multiple independent reads | Parallel. One message, multiple Read/Grep calls. |
| Multiple independent subagent investigations | Parallel. One message, multiple subagent calls. |
| Subagent whose output feeds the next subagent | Serial. Wait, read result, then spawn. |
| Two writes to the same file | **Never parallel.** Race condition. |

A good heuristic: if two subagents could contradict each other, don't run them in parallel.

## Tier placement

Project-level docs name the canonical tier-to-task map. For delegation: high-tier orchestrators spawn (never spawned), mid-tier executors take long loops / attacks / translation / heavy search, low-tier validators take shape checks and freshness audits. Routing up or down the tiers breaks the cost-or-quality contract. See also [`./tier-sizing.md`](./tier-sizing.md) for prompt verbosity by tier.

## Conduct propagation

Subagents spawned by the parent have no memory of the session. The three non-negotiable
clauses (structured return, scope fence, context briefing) ensure the subagent knows its
task. They say nothing about which conduct modules the subagent should respect. That gap
is where practitioners fall back to one of two bad defaults: paste every conduct module into
every subagent prompt (token overhead that makes delegation expensive) or paste none of them
(the subagent operates without any behavioral guardrails).

Two open issues on the Claude Code tracker confirm this is the primary real-world pain point
with the framework: issue #6825 ("subagents always inherit ... huge token overhead") and issue
#8395 ("user-level rules ... optionally propagated to subagents"). The three patterns below
are the practical resolution.

### Pattern A — Full inherit

**When to use:** The subagent is long-lived, top-tier, or handles tasks where any missed
conduct rule has high cost — adversarial red-team, security audit, final convergence run.
Also appropriate when the parent cannot predict which modules the subagent will touch.

**Mechanism:** Include the relevant conduct modules in full in the subagent's system prompt,
using the briefing slot of the delegation contract. Claude Code's prompt-append mechanism
appends the definition body automatically when the subagent is defined via a SKILL.md file;
for ad-hoc subagents, paste the module text directly.

**Token cost:** High. Pasting five conduct modules at ~600 tokens each adds 3,000+ tokens
to every subagent invocation. On low-tier models this cost is significant; on top-tier it is
less so. Offset by the lower risk of a missed rule in a high-stakes subagent.

**Anti-pattern:** Full inherit on a low-tier investigator that runs dozens of times per
session. The token overhead accumulates faster than the benefit justifies. Use whitelist
inject instead.

---

### Pattern B — Whitelist inject

**When to use:** The subagent has a known, bounded tool whitelist. Most subagents do:
an investigator reads, a red-teamer reads and reasons, a validator reads and checks. The
tool whitelist determines which conduct modules are relevant.

**Mechanism:** Inject only the conduct modules whose rules the subagent's tools can violate.
The table below maps tool whitelists to their minimum required modules. Paste only those.

| Tool whitelist | Minimum conduct modules to inject |
|---|---|
| Read, Grep, Glob only | `conduct/tool-use.md` (right tool first try) |
| Read, Grep, Glob + Bash (read-only commands) | `conduct/tool-use.md` + `conduct/verification.md` § Baseline snapshot |
| Read, Write, Edit | `conduct/tool-use.md` + `conduct/verification.md` + `conduct/discipline.md` § Surgical changes |
| Read, Bash (arbitrary) | `conduct/tool-use.md` + `conduct/verification.md` (full) + `conduct/discipline.md` |
| Agent (spawns sub-subagents) | All of the above + `conduct/delegation.md` — this document |

**Token cost:** Medium. Injecting two or three module sections rather than five full modules
cuts overhead by 50–70% compared to full inherit. The tradeoff: if a subagent's actual
behavior drifts outside its stated tool whitelist, the missing modules are not there to catch it.

**Anti-pattern:** Injecting only one module to minimize tokens and then granting the subagent
a broad tool whitelist. The module mismatch means the subagent has tools it can misuse and no
conduct rules covering those misuses. Either restrict the tool whitelist to match the injected
modules, or inject more modules to match the granted tools.

---

### Pattern C — Discovery file

**When to use:** A shared repository of conduct rules is maintained at project root and
multiple subagents across multiple skills need to read the same behavioral contract without
each skill author maintaining their own injection logic. Best for team environments with
more than two skill authors or more than five active subagent types.

**Mechanism:** Place an `AGENTS.md` (or `CONDUCT.md`) file at the project root. The file
lists the active conduct modules, their enforcement status (advisory or enforcing), and any
project-level overrides. Subagents whose definition files include a clause such as:

```
Read `AGENTS.md` at project root before starting work. Follow the conduct rules listed there.
```

will load the shared contract on spawn. Claude Code's prompt-append mechanism makes this
natural: the SKILL.md definition body is appended to the subagent's system prompt, so the
read instruction arrives before any task-specific content.

This pattern maps directly to the `microsoft/skills` AGENTS.md convention and is
cross-vendor: it works in Claude Code, in Cursor (via `.mdc` `alwaysApply` rules), and
in any runtime where subagent definitions are files the agent can read.

**Token cost:** Low to medium. The discovery file itself is small (a list of module names
and their status). The subagent reads it once on spawn; actual module content is loaded
on-demand or summarized in the discovery file. The cost scales with how much content the
file embeds directly vs. references by path.

**Compatibility note:** This pattern assumes subagents can read files at project root. In
Claude Code this holds; in other runtimes (e.g., API-only OpenAI Agents SDK invocations
without file access), the discovery file must be inlined into the subagent prompt instead.
Confirm file-read capability before adopting this pattern in a new runtime.

**Anti-pattern:** A discovery file that is 2,000 tokens of embedded module prose. That is
full inherit with an extra read step. Keep the discovery file to a list and metadata; point
to module files by path, not by content.

---

### Choosing a pattern

| Factor | Full inherit | Whitelist inject | Discovery file |
|---|---|---|---|
| Subagent tier | Top | Mid or Low | Any |
| Tool whitelist predictability | Unknown / broad | Known, bounded | Known, managed |
| Session invocation frequency | Low (1–3 per session) | Medium (4–20) | High (20+) or multiple skill authors |
| Risk tolerance for missed rules | Low | Medium | Medium |
| Token budget concern | Low | High | High |

No pattern is universally correct. A single session may use full inherit for the orchestration
subagent, whitelist inject for a fleet of low-tier validators, and the discovery file for a
long-running monitoring subagent that checks in periodically.

### Cross-vendor precedent

The three patterns have external confirmation, used here as framing, not as requirements:

- **Full inherit** maps to OpenAI Agents SDK `Agent.clone()`, which propagates all parent
  agent configuration to a child agent.
- **Whitelist inject** maps to LangChain agent middleware, which wraps shared checks around
  specific tool actions without injecting all rules into every agent.
- **Discovery file** maps to the `microsoft/skills` AGENTS.md convention, where a single
  file describes available skills and their behavioral contracts to any agent that can read it.

These cross-vendor analogues confirm that the patterns are production-validated, not
framework-specific inventions. They are not prescriptions — the framework's three clauses
remain the minimum contract regardless of which propagation pattern is chosen.

## Trust but verify the subagent

The subagent's summary describes what it *intended to do*, not necessarily what it did.

1. **If the subagent wrote code:** read the diff before declaring the parent task done.
2. **If the subagent reported "all tests pass":** ask for the relevant test command output or re-run it.
3. **If the subagent's finding contradicts your prior belief:** don't blindly accept — check the underlying evidence.

## Anti-patterns

- **Delegating a task you could do in one tool call.** "Spawn a subagent to read one file" — just read the file.
- **Prompt that says "figure out what I need."** Subagent lacks conversation context. Brief it.
- **Parallel subagents with overlapping writes.** Race, lost work. Serialize or partition by path.
- **Sub-subagents.** Two-level delegation loses too much context. Flatten.
- **Trusting the subagent's "done" without reading its output.** The result is the contract, not the claim.
- **Subagent loop without a termination clause.** A fixed N-attack audit is bounded; an open-ended "keep finding issues" isn't.
