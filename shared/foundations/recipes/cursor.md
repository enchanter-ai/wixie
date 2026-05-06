# Recipe — Cursor

How to adopt agent-foundations in [Cursor](https://cursor.com).

## What you get

Cursor reads `.cursor/rules/` (or legacy `.cursorrules`) at the workspace root for project-wide AI behavior. Conduct modules drop in as rule files. Cursor's chat and inline editing both pick them up.

## Drop-in

```bash
git submodule add https://github.com/enchanter-ai/agent-foundations .cursor/foundations
mkdir -p .cursor/rules
```

For each conduct module you want active, create a thin pointer rule. Example `.cursor/rules/01-discipline.mdc`:

```markdown
---
description: Coding discipline — think-first, simplicity, surgical, goal-driven
globs: ["**/*"]
alwaysApply: true
---

@.cursor/foundations/conduct/discipline.md
```

The frontmatter says when the rule applies; the body inlines the module via `@` syntax. Cursor's recent rules format (`.mdc`) supports both globs and conditional application.

## Recommended starter set

```
.cursor/rules/
├── 01-discipline.mdc
├── 02-context.mdc
├── 03-verification.mdc
├── 04-tool-use.mdc
└── 05-failure-modes.mdc
```

Five rules cover ~80% of the value. Add more as project complexity grows.

Sample `02-context.mdc`:

```markdown
---
description: Context budget hygiene — U-curve placement, checkpoint protocol
globs: ["**/*"]
alwaysApply: true
---

@.cursor/foundations/conduct/context.md
```

## Per-language scopes

Cursor rules support `globs` for selective application. Use this to load tier-sizing only for prompt files, formatting only for prompt-engineering folders, etc.:

```markdown
---
description: Tier-sizing for prompt files
globs: ["prompts/**/*.md", "agents/**/*.md"]
alwaysApply: false
---

@.cursor/foundations/conduct/tier-sizing.md
```

This avoids loading every module on every file edit — Cursor's effective context is finite.

## Engines as inline references

Engines are math-grounded primitives, not behavior rules — they don't belong in always-apply rules. Reference them on demand:

- In chat: *"Build a trust score for these N observations using @.cursor/foundations/engines/trust-scoring.md"*
- In a rule scoped to relevant files: e.g., scope `pattern-detection.md` to security-scanning code paths.

## Composer-mode considerations

Cursor's Composer mode generates multi-file changes. For composer:

- **Always-apply rules:** discipline, verification, tool-use, surgical-changes — these prevent unsolicited refactors across files.
- **Scoped rules:** delegation (only matters when composer dispatches to multiple parallel agents), formatting (only matters in prompt files).

## Failure logging

Cursor doesn't ship a structured failure log; add one to the project:

```bash
mkdir -p state
touch state/precedent-log.md
```

Reference the precedent protocol in your rules:

`.cursor/rules/06-precedent.mdc`:
```markdown
---
description: Self-observed failure log; consult before risky steps
globs: ["**/*"]
alwaysApply: true
---

@.cursor/foundations/conduct/precedent.md

Project precedent log: `state/precedent-log.md`. Grep before non-trivial Bash; append after unexpected failures.
```

## Verifying the adoption

1. Open Cursor's chat in the project.
2. Ask: *"What rules are currently active?"*
3. Cursor should list the rules you added.

If a rule isn't applying, check `globs` — `["**/*"]` matches everything; narrower patterns require an open file matching the pattern.

## Enforcement

Cursor has no PreToolUse-equivalent runtime gate — there is no programmatic interception
point before a tool call executes. Enforcement in Cursor runs through two mechanisms: rule
activation at the `.mdc` level, and git-layer hooks that run outside Cursor's process.

**`.mdc` activation as the gate.** Each `.mdc` rule file has three frontmatter fields that
control when the rule applies. Per the Cursor documentation: "Each .mdc file has three
frontmatter fields that control activation: description, globs, and alwaysApply." Use these
fields to enforce load-bearing conduct rules as broadly as needed:

| Conduct rule | `.mdc` setting | Rationale |
|---|---|---|
| `verification.md` § Dry-run for destructive ops | `alwaysApply: true`, `globs: ["**/*"]` | Must fire regardless of open file |
| `discipline.md` § Surgical changes | `alwaysApply: true` | Applies to every edit in every file |
| `tool-use.md` § Read before Edit | `alwaysApply: true` | Applies to any file operation |
| `tier-sizing.md` | `alwaysApply: false`, `globs: ["prompts/**/*.md", "agents/**/*.md"]` | Only relevant for agent definition files |
| `web-fetch.md` | `alwaysApply: false`, `globs: ["**/*.py", "agents/**/*"]` | Only relevant when code touches fetch paths |

Set `alwaysApply: true` for any rule where a missed activation has irreversible consequences.
Set `alwaysApply: false` with a `globs` pattern for rules that apply only in a specific
file domain — this keeps Cursor's effective context from being saturated with rules that don't
apply to the current file.

**Honest limit.** Cursor enforcement is weaker than Claude Code hooks or OpenAI Agents SDK
guardrails. A rule with `alwaysApply: true` is a memorized behavioral default, not a
programmatic gate. The model may still execute a destructive op if context pressure is high
(see F05 instruction attenuation). For hard gates — blocking a `git push --force`, preventing
a file deletion — use git-layer hooks instead.

**Git-layer hooks.** For conduct rules that Cursor itself cannot enforce (irreversible
operations, pre-push checks), add a `.git/hooks/pre-commit` or `pre-push` script. This runs
outside Cursor's process before the operation completes, regardless of whether the model
obeyed the rule. A pre-commit hook that rejects changes touching certain paths, or a pre-push
hook that runs a lint pass, gives you a deterministic gate that `.mdc` rules cannot provide.

## Conduct propagation

Cursor propagates conduct through `.mdc` rule activation rather than explicit subagent
delegation. The three patterns from [`../conduct/delegation.md`](../conduct/delegation.md)
§ Conduct propagation have direct analogues in the `.mdc` model.

**Pattern A analog — `alwaysApply: true`.** A rule with `alwaysApply: true` is the Cursor
equivalent of full inherit: every action the agent takes, in every file, is governed by that
rule. Use this for load-bearing modules (`discipline.md`, `verification.md`, `tool-use.md`).
The token cost is real — every chat and inline edit loads the rule — so limit the always-apply
set to the rules that must never be absent.

**Pattern B analog — globs-scoped activation.** A rule with `alwaysApply: false` and a
`globs` pattern is the Cursor equivalent of whitelist inject: the rule activates only when an
in-scope file is open. Use this for modules that are relevant only in specific file domains
(see the table above). The tradeoff is the same as whitelist inject: if the agent touches
files outside the glob, the rule is not in effect.

**Pattern C analog — pointer file.** A single index rule at `.cursor/rules/00-foundations.mdc`
can point to every other conduct module:

```markdown
---
description: Agent-foundations conduct index — load before any task
globs: ["**/*"]
alwaysApply: true
---

@.cursor/foundations/conduct/discipline.md
@.cursor/foundations/conduct/verification.md
@.cursor/foundations/conduct/tool-use.md
@.cursor/foundations/conduct/failure-modes.md
```

This is the Cursor equivalent of the discovery file pattern: one place to add, remove, or
reorder modules, consulted on every session. Individual pointer rules (`01-discipline.mdc`,
`02-context.mdc`, etc.) remain valid for granular control; the index rule is an alternative
when a flat list is easier to manage than a directory of single-module files.

See [`../conduct/delegation.md`](../conduct/delegation.md) § Conduct propagation patterns for
the conceptual framing behind all three patterns and their cross-vendor confirmation.

## What this won't do

- Cursor's selector is heuristic — many rules in the same scope can compete for attention. Keep rule descriptions sharp (see [`../conduct/skill-authoring.md`](../conduct/skill-authoring.md) for the description discipline that makes selectors work).
- Replace per-language linters / type checkers. Conduct + engines are about *how the agent behaves*, not *whether the code compiles*.
