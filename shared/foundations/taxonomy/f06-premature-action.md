# F06 — Premature Action

## Signature

Agent edits, deletes, or creates files before grounding — without `Read`, without checking the location, without verifying the symbol it's modifying actually exists. The action *might* be correct; the agent didn't *know* it was correct.

Common shapes:

- Edit a function the agent thinks is in `utils.py`; it's actually in `helpers.py`.
- Rewrite a config without reading the existing structure first.
- Apply a patch where `old_string` was reconstructed from memory, not copied verbatim.
- Delete a "duplicate" file that turns out to be the canonical one.

## Counter

See [`../conduct/tool-use.md`](../conduct/tool-use.md) § Read before Edit.

Concrete sequence before any write/edit:

1. **`Read` the file.** Even if you think you know it.
2. **`Grep` the symbol.** Confirm it's in the file you think.
3. **Match `old_string` post-Read** — exact indentation, exact whitespace.
4. **Read the surroundings** — five lines above and below — to confirm context.

If the file doesn't exist, decide *create new* vs *file is misnamed* before writing.

## Examples

1. Agent runs `Edit` on `auth.py` to fix a bug, but the bug is actually in `auth/middleware.py`. The Edit succeeds (because the function name happens to exist in both files), and the original bug remains. **Counter:** `Grep` for the function before Editing; pick the right file.

2. Agent reconstructs a six-line code block from memory for `old_string`, gets one indent level wrong, and Edit fails. Then re-tries with another guess. **Counter:** Read the file once, copy-paste the lines verbatim from the Read output.

3. Agent creates a new file `src/utils.ts`; the existing `src/utils.ts` is overwritten without warning. **Counter:** Glob first; if the file exists, Read it before deciding whether to overwrite.

## Adjacent codes

- **F02 fabrication** — premature action *might* succeed (right code, wrong file); fabrication invents *content*. They co-occur often.
- **F08 tool mis-invocation** — mis-invocation is using the wrong *tool* for a job; premature action is using the right tool *too soon*.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Revert; re-do with proper grounding |
| 3+ in one workflow | The agent is skipping grounding deliberately — pause and force a Read-first protocol |
