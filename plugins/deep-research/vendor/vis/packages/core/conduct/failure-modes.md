# Failure Modes — Named Taxonomy

Audience: any agent that logs failure observations. A controlled vocabulary for failure-log entries so accumulation across sessions can compound. Free-text learning notes don't compound; tagged ones do.

## Why a taxonomy

Accumulation only learns if failure reasons are comparable. "It got worse" is not a signal — "F04 task-drift during axis-3 tightening" is. Every log row tags exactly one code.

## The 29 canonical codes

### Generation failures

| Code | Name | Signature | Counter |
|------|------|-----------|---------|
| F01 | Sycophancy | User said "great!" and agent abandoned a flagged concern | Re-assert the concern before proceeding |
| F02 | Fabrication | Cited API / flag / file that doesn't exist | Verify before citing; `Glob` / `Grep` first |
| F03 | Context decay | Instruction from top of context violated at bottom | See [`./context.md`](./context.md) § Checkpoint protocol |
| F04 | Task drift | Work expanded past the stated goal | Re-read the success criterion; cut back to scope |
| F05 | Instruction attenuation | Rule stated once, obeyed once, then forgotten | Move rule to top-200 or bottom-200 slot |

### Action failures

| Code | Name | Signature | Counter |
|------|------|-----------|---------|
| F06 | Premature action | Edited before grounding — wrong file, wrong function | See [`./tool-use.md`](./tool-use.md) § Read before Edit |
| F07 | Over-helpful substitution | Solved a problem the user didn't ask about | See [`./discipline.md`](./discipline.md) § Surgical changes |
| F08 | Tool mis-invocation | Wrong tool for the job (Bash for read, Write for small edit) | Default to the dedicated tool |
| F09 | Parallel race | Two writes to the same file / same branch | Serialize or partition by path |
| F10 | Destructive without confirmation | `rm`, `reset --hard`, `force push` without explicit yes | See [`./verification.md`](./verification.md) § Dry-run for destructive ops |
| F26 | Reversibility blindness | Agent took a non-destructive but irreversible action without first classifying its reversibility | See [`./reversibility-foresight.md`](./reversibility-foresight.md) — classify before acting; confirmation scales with tier |
| F28 | Skill-discoverability failure | Authored new tool/script/skill/module when an existing one in the project already covered the use case | See [`./prior-art-discovery.md`](./prior-art-discovery.md) — run the 5-target discovery pass before authoring; reuse, extend, or author-new with stated reason |
| F29 | Premise-unvalidated build | Built/crafted a new artifact (product, engine, tool, prompt, module) on request without first testing whether it should exist; ran the worth-it / prior-art / conduct-vs-engine gate only after heavy investment, or never. Process-rigor (craft → harden → converge) mistaken for strategic judgment | See [`./doubt-engine.md`](./doubt-engine.md) § Build-premise gate — run the 3-question gate BEFORE the first craft step; conduct over engine, lean over full |

### Reasoning failures

| Code | Name | Signature | Counter |
|------|------|-----------|---------|
| F11 | Reward hacking | Hit the metric by gaming it (e.g., pass an assertion by weakening it) | Reviewer checks whether the test still tests the original behavior |
| F12 | Degeneration loop | Same edit, reverted, re-applied across iterations | No-regression contract; stop the axis |
| F13 | Distractor pollution | Long irrelevant context bent the output | See [`./context.md`](./context.md) § Smallest-set rule |
| F14 | Version drift | Used deprecated API / retired model ID / old flag | Check your model capability registry and current docs before emitting |
| F23 | Sunk-cost iteration | Same artifact dispatched v0 → v0.1 → v0.2 with each failure for a new reason introduced by the prior fix; original question never answered | See [`./sunk-cost-iteration.md`](./sunk-cost-iteration.md) — after 2 INCONCLUSIVE/BLOCKED, surface the shape question before v(N+1) |
| F24 | Substrate-blindness | Cross-session evidence (briefings, MEMORY, learnings, precedent) existed but the agent acted without consulting it | See [`./substrate-consumption.md`](./substrate-consumption.md) — at session start consume the plugin briefing, MEMORY, and relevant logs before the first non-trivial dispatch. |
| F25 | Verdict inflation | Verdict (DEPLOY/PASS/COMPLETE/VERIFIED) emitted with confidence exceeding the evidence — evidence and metric are real, but n / sampling method / calibration band do not support the claim | See [`./verdict-calibration.md`](./verdict-calibration.md) — every verdict carries n, sampling method, and a calibration qualifier (Wilson CI, p-value, or {suggestive, inconclusive, decisive, BLOCKED}). |
| F27 | Stale-precedent reliance | Cited self-authored memory / precedent / briefing that no longer reflects current state (renamed path, removed function, bumped schema, post-retirement pattern) | See [`./precedent-freshness.md`](./precedent-freshness.md) — verify Class-A surfaces with `Glob`/`Grep` and re-ground Class-B snapshots against `git log` before acting |

### Multi-agent and alignment failures

| Code | Name | Signature | Counter |
|------|------|-----------|---------|
| F15 | Inter-agent misalignment | Two parallel agents produced contradictory outputs that compose into a broken artifact | Partition work so outputs don't conflict; diff-check before merging |
| F16 | Task-verification skip | Subagent returned success without running the required completeness or correctness check | Structured return clause must include verification step output; parent checks for it |
| F17 | System-design brittleness | A pipeline succeeds in isolation but breaks when agents are reordered or a node is replaced | Invariant-test each seam; don't assume composition is stable |
| F18 | Goal-conflict insider behavior | Agent pursued an instrumental goal (coercion, exfiltration, deception) the principal did not sanction | Minimal tool whitelist; per-call confirmation on sensitive ops; audit goal traces |
| F19 *(awareness)* | Alignment faking | Agent behaves compliantly under observation and non-compliantly when unobserved | Red-team with observed vs. unobserved conditions; escalate to safety review on any signal |
| F20 *(awareness)* | Sandbagging | Agent underperforms on capability evaluations to avoid triggering oversight thresholds | Blind eval sets; multiple independent evaluators; escalate to safety review on any signal |
| F21 | Weaponized tool use | Agent used a legitimate tool to cause harm (data exfiltration, denial-of-service, unauthorized action) | Hard tool whitelist; destructive-op confirmation; scope fence per subagent |
| F22 | Capability-absence substitution | Contract named capability C; C absent; agent ran lesser path and shipped under original verdict bar | See [`./capability-fidelity.md`](./capability-fidelity.md) — recover, escalate, or abort. Never substitute silently. |

## How to log a failure

In your project's failure log (e.g., `learnings.md` for iteration loops, `drift-log.md` for context-health tracking):

```markdown
## 2026-04-17 iteration v4 → v5 (reverted)

Code: F12 degeneration-loop
Dimension targeted: specificity
Hypothesis: tightening the `format` section would lift the specificity score
Outcome: specificity +0.3, clarity -0.8 → σ exploded, no-regression triggered
Counter: pick a different dimension next round; log this as a dead-end for v5
```

Required fields: `Code`, `Axis targeted` (if applicable), `Hypothesis`, `Outcome`, `Counter`.

## How to read the log before a new round

Before starting iteration N, scan the log for:

1. Any **F12 on the same dimension** → that dimension is saturated; try another.
2. Any **F11 from the reviewer** → the scoring surface itself is being gamed; re-derive the rubric.
3. Three **F04 in a row** → the success criterion is vague; escalate to the user.

## Escalation patterns

Some codes are single-occurrence — log and continue. Some require stopping:

| Code | Single occurrence | 3+ in one workflow |
|------|-------------------|---------------------|
| F01, F02, F07, F13 | Log and continue | Escalate to developer — systemic issue |
| F03, F04, F05 | Checkpoint and reset context | Re-scope the task |
| F06, F08, F09, F10 | Revert, log, retry | Pause workflow — contract broken |
| F11, F12 | Revert, switch axis | Freeze convergence on this artifact |
| F14 | Regenerate against current registry | Audit the registry freshness |
| F15, F16, F17 | Revert, partition, log | Redesign the seam — contract broken |
| F18, F21 | Halt, revert all artifact writes, log | Pause workflow — safety contract broken |
| F19, F20 *(awareness)* | Log and continue (red-team eval, not runtime) | Escalate to safety review |
| F22 | Revert verdict to HOLD, re-run with proper capability or amended bar | Halt — substrate / runtime mismatch; escalate to principal |
| F23 | Log the inconclusive result and the introduced assumption; reset only on clean PASS or original-reason FAIL | Halt the iteration line; surface to principal with paths (a)/(b)/(c); do not dispatch v(N+1) without explicit authorization |
| F24 | Re-read the briefing + MEMORY + relevant logs, restart the step with consumed evidence | Halt — the read protocol is being routinely skipped; surface to principal and reconcile + re-render briefings before resuming |
| F25 | Downgrade verdict to match the calibration band; re-emit with n + method + qualifier attached | Halt — verdict-emission discipline is broken across the workflow; escalate to principal and re-baseline the verdict bar with explicit calibration requirements |
| F26 | Revert if possible, log, surface to principal | Halt — agent's reversibility judgment is calibrated wrong; require explicit confirmation on all actions until reset |
| F27 | Verify the cited surface; re-ground or discard the entry; proceed | Audit the memory store — systemic staleness; sweep by decay-signal class |
| F28 | Revert the new artifact, run discovery pass, reconcile with prior art | Halt — repo has fragmenting capability surfaces; escalate to principal for a consolidation pass |
| F29 | Stop crafting; run the build-premise gate; state the worth-it verdict and propose the lean carrier (conduct over engine) before resuming | Halt — premise-validation is being skipped on build requests; surface the verdict to the principal before any further authoring |

## Anti-patterns in logging

- **Untagged free-text entries.** Not aggregable. Every row tags exactly one code.
- **Logging the fix, not the failure.** The log records what *didn't work* and why, not your victory lap.
- **Multiple codes on one entry.** Pick the dominant one. If truly two, split into two entries.
- **Logging at verdict time only.** Log the *hypothesis* before the iteration; log the *outcome* after. Both halves needed.
- **"Couldn't find a matching code."** Then propose a new one (F22+) in the PR, don't invent ad-hoc names. The taxonomy grows deliberately.

## Extending the taxonomy

New codes are additive. To propose F22+:

1. Observe it in at least 3 independent contexts.
2. Name the signature precisely.
3. Write a counter that's testable.
4. Open a PR that updates this file *and* the learning entries that retroactively match.

Rejected: codes that overlap an existing one, codes defined by vibes, codes without a counter.
