# F09 — Parallel Race

## Signature

Two parallel tool calls (or two subagents) operate on the same target — same file, same branch, same cache key — without serialization. One write wins; the other is silently lost. Detection is hard because the side effect *looks like* the surviving call ran cleanly.

Common shapes:

- Two parallel `Edit` calls on the same file.
- Two subagents each write to `cache/results.json`.
- Parallel commit + rebase on the same branch.
- Two fetchers race on the same cache write key.

## Counter

See [`../conduct/tool-use.md`](../conduct/tool-use.md) § Parallel vs. serial and [`../conduct/delegation.md`](../conduct/delegation.md) § Parallel vs. serial.

Rules:

1. **Two writes to the same file → never parallel.** Serialize.
2. **Subagents whose outputs feed each other → serial.** Wait for step 1 before spawning step 2.
3. **Cache writes → atomic.** Write to a temp file, then rename. Filesystem `rename` is atomic on POSIX.
4. **Heuristic:** if swapping the order of two calls would change the result, they aren't independent — serialize.

## Examples

1. Agent spawns two parallel subagents to "edit `config.json`" — one to add a key, one to update another. Both Read the same starting state, both Write their version. The second write overwrites the first. **Counter:** Serialize: edit, then read the updated file, then edit again.

2. Two parallel fetchers hit the same URL; both compute the cache key, both write to `cache/abcd.json` simultaneously. One write is corrupted (interleaved bytes) or lost. **Counter:** Atomic write — `cache/abcd.json.tmp.<pid>` then `rename`.

3. Agent runs two parallel `git commit` calls in different work-trees of the same branch. Result depends on filesystem timing. **Counter:** Serialize git operations on a branch.

## Adjacent codes

- **F08 tool mis-invocation** — mis-invocation is wrong tool / args; parallel race is right tool dispatched in unsafe parallelism.
- **F12 degeneration loop** — both can produce edit thrash; parallel race is a *single* turn's fault, degeneration is *across* turns.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Revert to a known good state; redo serially |
| 3+ in one workflow | The agent is over-parallelizing; pause and require an explicit independence check before each parallel dispatch |
