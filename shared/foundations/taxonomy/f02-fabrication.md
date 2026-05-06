# F02 — Fabrication

## Signature

Agent cites an API, function, file, flag, or behavior that does not exist. The citation is presented with confidence; the underlying check (grep, file read, doc lookup) was skipped.

Common shapes:

- "Use `os.fileExists()`" — there's no such Python stdlib function.
- "The repo's `migrate.sh` script handles this" — there's no such script.
- "Pass `--no-cache=true`" — the flag doesn't take a value, or doesn't exist.
- Quote field paraphrases the source text instead of copying verbatim.

## Counter

Verify before citing. Concrete:

- Function / API → run a docs lookup or check the import.
- File path → `Glob` or `Read` first.
- Flag → `--help` of the tool.
- Quote → copy-paste from the source; do not type from memory.

If verification fails or is impossible, say so explicitly: *"I'm not sure if that flag exists — can you confirm?"*

## Examples

1. Agent suggests `git reset --hard HEAD~1 --no-edit`. The `--no-edit` flag doesn't apply to `git reset`. **Counter:** Check `git reset --help` before suggesting unfamiliar flag combos.

2. Agent paraphrases a fetched page's claim into the `quote` field. Verbatim text says "the function returns null on EOF"; agent's quote says "returns null when input ends." **Counter:** Copy-paste from the source character-for-character, or omit the finding.

3. Agent says "the project's `state/precedent-log.md` already has an entry for this" — but the file doesn't exist in this project. **Counter:** Verify the path with `Glob` before claiming what the project has.

## Adjacent codes

- **F14 version drift** — fabrication is citing something that *never existed*; version drift is citing something that *used to exist*. The fix differs.
- **F08 tool mis-invocation** — fabrication invents a tool / flag; mis-invocation uses a real tool wrong.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Correct in place; log if the fabrication was load-bearing |
| 3+ in one workflow | The agent is reasoning from training data instead of repo state — force grounding tools (Glob/Grep/Read) before any factual claim |
