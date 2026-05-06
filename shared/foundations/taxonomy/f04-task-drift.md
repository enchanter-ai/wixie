# F04 — Task Drift

## Signature

Work expands past the stated goal. The original task is still *technically* in scope, but the agent has accumulated unsolicited side-quests: refactors, cleanups, tangentially-related fixes. The diff includes lines the user did not ask for and would not have approved if asked.

Common shapes:

- Bug-fix PR includes an unrelated rename of three other functions.
- One-line config change spawns a "while I was here, I noticed…" cleanup.
- Investigation request becomes an investigation + speculative fix.
- Adding a new feature, agent also "improves" the surrounding code.

## Counter

See [`../conduct/discipline.md`](../conduct/discipline.md) § Surgical changes.

Concrete:

1. Re-read the success criterion before each major action.
2. After each tool call, ask: *"Does this advance the stated goal, or am I solving a different problem?"*
3. If the diff has lines that don't trace to (a) the change requested, (b) required by (a), or (c) pre-existing drift you flagged — **revert them**.

## Examples

1. Task: "fix the off-by-one in pagination." Agent fixes the bug *and* refactors the pagination helper into a class *and* adds JSDoc. **Counter:** Fix the off-by-one. File the refactor as a follow-up; don't ship it.

2. Task: "investigate why test X is flaky." Agent investigates, finds the cause, and *also* changes the test's mock to "make it more deterministic." **Counter:** Report the cause. Let the user decide on the mock change.

3. Task: "rename `getCwd` to `getCurrentWorkingDirectory`." Agent renames the function *and* "while there" rewrites three call sites that "could be cleaner." **Counter:** Rename only.

## Adjacent codes

- **F07 over-helpful substitution** — substitution is solving a *different* problem; drift is solving the *right* problem *plus* extras. Both are scope failures.
- **F03 context decay** — decay forgets instructions; drift remembers them but expands beyond them.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Revert the out-of-scope lines; submit only the requested change |
| 3+ in one workflow | The success criterion is vague — escalate to the user for a tighter spec |
