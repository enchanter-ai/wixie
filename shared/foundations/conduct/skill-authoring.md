# Skill Authoring — Frontmatter Discipline

Audience: any author writing skills (Claude Code skills, agent commands, slash commands, named workflows). How to write a skill manifest so the agent invokes it at the right moment. As a skill family grows past a few skills, trigger-collision becomes the #1 discovery failure.

## The discovery surface

Many agent runtimes select skills by matching the user's request against the `description` field of each available skill's frontmatter. **Body content is not used for selection.** A skill whose description is off will never fire, regardless of how well the body is written.

## Frontmatter contract

```yaml
---
name: refactor-module
description: >
  Refactors a module toward a named target metric via the optimizer loop.
  Use when: user runs /refactor, asks to improve a module's score,
  or references a HOLD verdict. Do not use for initial drafting (see /scaffold).
model: sonnet
tools: [Read, Edit, Write, Bash, Grep, Glob]
---
```

Required fields:

| Field | Rule |
|-------|------|
| `name` | kebab-case, matches the slash-command |
| `description` | ≤1024 chars; both **what** and **when**; third person |
| `model` | tier name appropriate to the runtime (e.g., `opus` / `sonnet` / `haiku`) |
| `tools` | whitelist; smallest set that works |

## Description: both what and when

A description answers two questions. Skills missing either get skipped.

- **What:** "Refactors a module toward the target metric via the optimizer loop."
- **When:** "Use when the user runs /refactor or asks to improve a module's score."

Bad (what only): *"Module refactoring."*
Bad (when only): *"For /refactor."*
Good: *"Refactors a module toward the target metric. Use when the user runs /refactor or references a HOLD verdict."*

Optionally add a **do-not-use** clause to prevent steal from adjacent skills:

> *"Do not use for initial drafting (see /scaffold) or for cross-target adaptation (see /translate)."*

## Third person, always

POV drift breaks discovery. The selector is matching against a description, not reading a memo.

- Good: *"This skill converges prompts…"*
- Good: *"Converges prompts…"* (implicit third person)
- Bad: *"I converge prompts…"*
- Bad: *"You should run this when…"*

## Length limit

Hard cap: 1024 characters on `description`. Target 300-600. Beyond that, the selector starts losing signal; under 100, discovery matches too loosely and the wrong skill fires.

## No XML in frontmatter

Frontmatter is YAML. XML tags inside `description` break the parser and silently disable the skill. Keep frontmatter plain prose.

## One skill per verb

Bundle-skills lose to split-skills. If a single skill manifest claims to do *craft* + *refine* + *converge*, the selector cannot disambiguate user intent.

| Bad | Good |
|-----|------|
| `prompt-lifecycle` (craft + refine + converge) | Three skills, each scoped |
| `review-and-fix` (review + edit) | `review`, plus the existing Edit tool |
| `deploy-anywhere` (translate + test + harden) | Three skills, composed by the user |

A skill's name, description, and behavior should each point at one verb.

## Cross-vendor schema alignment

The framework's SKILL.md frontmatter fields did not emerge in a vacuum. MCP Specification
2025-11-25, OpenAI's tool descriptor annotations, Claude Code's subagent frontmatter, and
Cursor's `.mdc` activation fields each define analogous structures. Understanding the mapping
prevents naming drift and makes it easier to translate a framework skill into an MCP-compatible
manifest or a Cursor rule without re-deriving the structure.

The table below maps framework fields to their closest external analogues. **Framework-unique**
marks fields with no external equivalent; **Framework-missing** marks external annotations the
framework does not yet capture.

| Field | agent-foundations | MCP 2025-11-25 | OpenAI SDK | Cursor |
|---|---|---|---|---|
| Identity / name | `name` (required, kebab-case) | `name` in `Tool` object | tool `name` string | rule filename |
| Discovery description | `description` (≤1024 chars, what + when) | `description` in `Tool` / `Prompt` object | tool `description` string | `description` in frontmatter |
| Target model | `model` (`opus` / `sonnet` / `haiku`) | not specified (model is caller's choice) | model specified at Agent level | not specified |
| Tool whitelist | `tools` array | `inputSchema` constrains inputs; no tool-grant list | tool list on `Agent` constructor | not applicable |
| Activation scope | `description` § when clause | `Prompt` vs. `Tool` vs. `Resource` type distinction | tool registered per-agent instance | `globs` + `alwaysApply` |
| Read/write intent | Framework-missing | Framework-missing | `readOnly: true/false` (tool annotation) | not specified |
| Destructive flag | Framework-missing | Framework-missing | `destructive: true/false` (tool annotation) | not specified |
| Idempotency | Framework-missing | Framework-missing | `idempotent: true/false` (tool annotation) | not specified |
| Open-world reach | Framework-missing | Framework-missing | `openWorld: true/false` (network/FS access) | not specified |
| Input schema | Framework-missing | `inputSchema` (JSON Schema) | `parameters` (JSON Schema) | not applicable |
| Permission mode | not in frontmatter (set at runtime) | not specified | `permission_mode` on subagent | not applicable |

### Reading the table

**Framework-unique fields.** `model` is framework-unique — the framework's tier system
(Opus / Sonnet / Haiku) has no direct analogue in MCP, OpenAI SDK, or Cursor because those
specifications leave model selection to the caller. The tier field is one of the framework's
strongest contributions; external schemas do not replicate it.

**Framework-missing fields.** The four OpenAI SDK annotations — `readOnly`, `destructive`,
`idempotent`, `openWorld` — are the highest-value additions the framework could adopt. They
are already implied by the conduct modules: `destructive: true` maps directly to
`conduct/verification.md` § Dry-run for destructive ops; `readOnly: true` maps to the
investigator tool whitelist in `conduct/delegation.md`. Adding these as optional frontmatter
fields would make the conduct rules machine-checkable without requiring a runtime dependency.
That extension is out of scope for this PR; it is noted here as a future candidate.

**MCP as the canonical reference.** The MCP Specification 2025-11-25 is specification-grade.
The OpenAI and Cursor entries are useful analogues, not specifications — they describe current
API surfaces that may change without formal notice. Align with MCP first; treat the others as
confirmatory.

**Do not add JSON Schema validation tooling.** The framework is dependency-free Markdown.
The table is the deliverable. Any validation tooling that consumes SKILL.md frontmatter belongs
in a separate recipe or engine, not in this conduct module.

## Tool whitelisting

List the minimum tools the skill needs. Over-granting lets the skill do things outside its lane and erodes the one-skill-per-verb contract.

| Skill role | Typical tool set |
|-----------|------------------|
| Investigator | Read, Grep, Glob |
| Red-team | Read, Grep, Glob — never Write |
| Crafter | Read, Write, Bash |
| Translator | Read, Write (target only) |
| Validator (cheaper-tier check) | Read, Grep |

If a skill needs Bash, narrow it to the specific commands via runtime permissions — don't pass free-form Bash on trust.

## Body structure

The body is the *runbook*, not the pitch. Structure:

1. **Preconditions** — what must be true before this skill runs.
2. **Inputs** — args the slash command accepts, their defaults.
3. **Steps** — numbered. Each step names the tool used and the success criterion.
4. **Outputs** — artifacts produced, where they land.
5. **Handoff** — what the next skill in the chain expects.
6. **Failure modes** — which [`./failure-modes.md`](./failure-modes.md) codes apply.

The body is read *after* selection, so optimize it for execution, not discovery.

## Testing a new skill's discovery

Before merging a new skill:

1. Write 5 user phrasings that *should* fire it.
2. Write 5 that *should not* (adjacent skills, wrong tool).
3. Invoke with each; verify the selector picks the right skill.

Ship only when 9/10 dispatches are correct.

## Anti-patterns

- **Description with only the what, no when.** Never fires at the right moment.
- **First-person description.** POV drift tanks recall.
- **Bundled skill (multi-verb).** Selector can't disambiguate.
- **Over-broad tool whitelist.** Skill edits files it shouldn't.
- **Body that explains *why* instead of *how*.** The body is a runbook.
- **Missing do-not-use clause on overlapping skills.** Siblings steal dispatches.
