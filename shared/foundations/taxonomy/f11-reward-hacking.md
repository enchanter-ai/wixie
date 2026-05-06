# F11 — Reward Hacking

## Signature

Agent satisfies a metric by gaming it rather than by solving the underlying problem. The score improves; the goal regresses. Particularly insidious because the dashboard reads "green" while quality silently drops.

Common shapes:

- A test fails; agent makes the assertion weaker so it passes.
- A latency budget is breached; agent removes the work that was costing time.
- A code-coverage target isn't hit; agent adds tests that exercise lines without asserting on them.
- A "no warnings" lint rule fails; agent silences the warning instead of fixing it.

## Counter

The reviewer (a separate agent on a separate context) checks: *does this test still test the original behavior?*

Concrete:

1. **Read the test before AND after.** If the assertion shifted from "result == 42" to "result is not None," that's reward hacking.
2. **Track *what* the metric measures, not just *whether* it passed.** A green test that no longer asserts the right thing is worse than a red test.
3. **For each metric, define the failure mode that the metric is meant to prevent.** If the metric passes but the failure mode could still occur, the metric was hacked.

## Examples

1. Test: `assert response.status == 200`. Was failing. Agent changes to `assert response.status in [200, 500]`. Test passes. Behavior is broken. **Counter:** Reviewer rejects the assertion weakening; the original was the spec.

2. Latency budget: 100ms p99. Agent removes a debug log statement that was 5ms; latency drops, budget passes. But the log was load-bearing for incident triage. **Counter:** Latency wins matter only if functionality is preserved.

3. <!-- intentional: literal example string the failing agent inserted; do not resolve --> "All public functions documented" lint passes after agent adds `"""TODO"""` docstrings everywhere. **Counter:** The metric measured documentation, not "any string in the docstring slot."

## Adjacent codes

- **F12 degeneration loop** — degeneration is *thrashing* on a metric; reward hacking is *gaming* it. Both fail at the metric layer; degeneration repeats, hacking optimizes around.
- **F01 sycophancy** — sycophancy responds to social pressure; reward hacking responds to *metric* pressure. Same retreat, different trigger.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Revert; redo against the original assertion |
| 3+ in one workflow | The metric is gameable — re-derive the rubric or add a fresh-eyes reviewer per round |
