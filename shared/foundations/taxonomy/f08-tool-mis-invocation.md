# F08 — Tool Mis-Invocation

## Signature

Wrong tool for the job, or right tool with wrong arguments. The mistake is *mechanical* — the agent had a better option available and didn't pick it.

Common shapes:

- `Bash` with `cat` to read a file when `Read` would do.
- `Bash` with `find` when `Glob` would do.
- `Bash` with `grep`/`rg` when `Grep` would do.
- `Edit` when `Write` is needed (file doesn't exist yet) or vice versa.
- `WebFetch` from a top-tier orchestrator instead of via a low-tier subagent.

## Counter

See [`../conduct/tool-use.md`](../conduct/tool-use.md) § Right tool, first try.

The reflex map:

| Reaching for | Use instead |
|--------------|-------------|
| `find` / `ls -R` | `Glob` |
| `grep` / `rg` | `Grep` |
| `cat` / `head` / `tail` | `Read` |
| `sed` / `awk` for edits | `Edit` |
| `echo > file` | `Write` |

Bash is for shell-only work — git, npm, test runners, build tools. Reaching for Bash to do what a dedicated tool does better is a smell; fix the reflex.

## Examples

1. Agent runs `Bash` with `grep -r "myFunction" .` to find usages. The `Grep` tool would do the same in one call with cleaner output and no shell-escape concerns. **Counter:** Use `Grep` when searching content.

2. Agent runs `Bash` with `find . -name "*.test.ts"`. **Counter:** Use `Glob` with `**/*.test.ts`.

3. Agent runs `Bash` with `cat src/foo.ts | head -50`. **Counter:** Use `Read` with `limit: 50`.

4. Agent calls `WebFetch` directly from the orchestrator on a 50-page paper, blowing context budget. **Counter:** Spawn a low-tier fetcher subagent; consume the structured return.

## Adjacent codes

- **F02 fabrication** — fabrication invents tools / flags that don't exist; mis-invocation uses real tools wrong.
- **F06 premature action** — premature action is right tool, wrong moment; mis-invocation is wrong tool entirely.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Use the right tool; note in failure log |
| 3+ in one workflow | The reflex needs explicit reinforcement — restate the tool-mapping table at the top of the prompt |
