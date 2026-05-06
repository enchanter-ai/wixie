# F12 — Degeneration Loop

## Signature

Agent makes an edit, reverts it, re-applies it, reverts again. Across iterations of an optimization or convergence loop, the same change toggles back and forth without progress. Or one axis of a multi-axis score keeps regressing despite repeated targeted attempts.

Common shapes:

- Iteration v3 → v4: tightens specificity, clarity drops. v4 → v5: loosens specificity, clarity recovers. v5 → v6: tightens specificity again. Loop.
- Convergence on a prompt: 5 iterations all targeting the same dimension, no net improvement, σ exploding.
- Refactor: function moves from `utils.ts` → `helpers.ts` → `utils.ts` across PRs.

## Counter

The **no-regression contract**: any iteration that reduces an axis below its baseline is auto-reverted, and the axis is logged as a dead-end for this prompt. Pick a different axis next round.

Concrete:

1. **Snapshot scores before each iteration.** Compare to baseline.
2. **If any axis dropped below its baseline → revert.** Don't ship.
3. **Log the failed hypothesis to the failure log** with code F12 + the dimension targeted.
4. **Read the log before next iteration.** Same dimension hit twice → that dimension is saturated; switch.

## Examples

1. Convergence run targeting "specificity" 4 times in a row, σ widening each time. **Counter:** After two F12s on the same axis, freeze that axis for this prompt; iterate on a different one.

2. Refactor PR moves a helper between modules; reviewer rejects; next PR moves it back; later PR re-moves it. **Counter:** The first revert is the signal; archive the dead-end and pick a different cleanup.

3. Code review pings: agent applies suggestion A, reviewer suggests B which conflicts with A; agent applies B, original reviewer comments back. **Counter:** Surface the conflict — escalate to the reviewer pair, don't keep flipping.

## Adjacent codes

- **F11 reward hacking** — hacking *games* the metric; degeneration *fights* it. Both end up with bad outputs; degeneration is the visibly thrashing version.
- **F09 parallel race** — race produces bad state in one turn; degeneration produces it across turns.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Revert; switch axis; log |
| 3+ in one workflow | Freeze the convergence on this artifact — the agent has saturated; further iteration won't help |
