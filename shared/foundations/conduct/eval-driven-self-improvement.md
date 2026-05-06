# Eval-Driven Self-Improvement — Closing the Feedback Loop on Agent Failures

Audience: any agent that accumulates session logs and wants to convert them into durable behavioral improvements. How to review failures, tag them, build a regression bank, and promote findings to the shared taxonomy — without adding speculative evals that dilute the bank's signal.

## The problem

An agent that logs failures but never acts on them is a diary, not a learning system. An agent that adds evals speculatively — covering failure modes it has not actually observed — builds a fragile test suite that grows without improving output quality.

The correct loop is narrow: observe a real failure, tag it with a code from [`./failure-modes.md`](./failure-modes.md), write a regression case that would have caught it, and verify that the case now passes. As Hamel Husain's field guide describes, effective improvement "started with a spreadsheet where each row represented a conversation. We wrote open-ended notes on any undesired behavior. Then we used an LLM to build a taxonomy of common failure modes." The taxonomy grows from observed failures, not predicted ones.

This module operationalizes that loop for Markdown-only workflows without requiring a separate evaluation framework.

## The loop

```
review → tag → counter → regression case → re-eval → promote (if recurring)
```

Each stage has a defined output. A stage without an output is not complete.

### 1. Review

At session end (or at a defined milestone), review the session's outputs against its goal. Look for:

- Steps where the agent produced output the user had to correct.
- Steps where the agent completed the task but the method was more expensive or slower than expected.
- Steps where the agent refused, hedged, or asked for clarification unnecessarily.
- Steps where the agent's output was technically correct but misaligned with the stated goal.

Write open-ended notes — one sentence per observation. No code assignment at this stage. The goal is to surface what happened, not to explain it.

### 2. Tag

Map each observation to exactly one code from [`./failure-modes.md`](./failure-modes.md). If no code fits, write a free-text description and defer — do not invent a code on the spot. Recurring free-text patterns across three or more sessions are candidates for a new code (see Promoting findings below).

A well-tagged observation names the code, the triggering condition, and the step where it occurred:

```
F04 task-drift — step 3 (web search) expanded scope to retrieve competitor pricing
not asked for in the original goal. Stopped after 2 extra fetches.
```

### 3. Counter

For each tagged observation, write the counter — the rule that prevents the same failure in the same step. The counter must be concrete enough to include in a future delegation prompt:

```
Counter for F04 above: Include in the web-search subagent prompt:
"Retrieve information only about <named product>. Do not fetch competitor data
unless explicitly requested."
```

If you cannot write a concrete counter, the tag is not complete. A code without a counter is a label, not an improvement.

### 4. Regression case

Write a minimal test case that would have caught the failure. Format for `state/regression-bank.md`:

```markdown
## RC-<YYYY-MM-DD>-<N> — <one-line description>

**Code:** F04
**Input:** <the prompt or request that triggered the failure>
**Expected behavior:** <what the agent should have done>
**Observed failure:** <what it actually did>
**Counter applied:** <the counter text from step 3>
**Pass condition:** Agent completes the task without triggering the counter's negative behavior.
```

The regression case is the minimum artifact of this loop. Without it, the improvement is not verifiable.

### 5. Re-eval

Before the next session that runs the same skill, read the relevant regression cases from `state/regression-bank.md`. Confirm the counter is present in the delegation prompt. At session end, record whether the regression case passed or failed.

Pass: the failure did not recur. Fail: the counter was insufficient — revise the counter and update the case.

### 6. Promote (if recurring)

A regression case that fails in three or more independent sessions despite a counter is evidence of a systemic issue. Promote it:

- If the code is an existing F-code, log it to `state/precedent-log.md` with the evidence count and the counter that did not hold.
- If the behavior does not fit an existing code, draft a new code per `failure-modes.md` § Extending the taxonomy (three instances, named signature, concrete counter).
- If the infrastructure supports it, emit to the inference substrate per [`./inference-substrate.md`](./inference-substrate.md) (where that module is in scope).

Promotion is a deliberate act, not an automatic one. Not every recurring failure needs a new code — often the existing code's counter needs to be applied earlier in the delegation chain.

## What to log per session

Minimum viable session log — one entry per session in `state/session-evals.md`:

```markdown
## <YYYY-MM-DD> — <skill or task name>

**Failures observed:** <N>
**Codes triggered:** <comma-separated F-codes>
**New regression cases:** <RC IDs or "none">
**Cases re-tested:** <RC IDs + pass/fail>
**Counter changes:** <"none" or one-line description>
```

Entries are append-only. Do not edit prior entries. The log is the longitudinal record that shows whether the regression bank is working.

## How to build the regression bank

The bank grows one case at a time from real failures. It should not be pre-populated with speculative cases covering failure modes the agent has not exhibited. As the Anthropic demystifying-evals guide confirms, "latency, token usage, cost per task, and error rates can be tracked on a static bank of tasks" — the key word is *static*: a fixed set of tasks for which expected behavior is known. A regression bank built from real failures is static in this sense. A bank built speculatively is not — it covers imagined behaviors, not observed ones.

Bank hygiene rules:

1. **One case per distinct failure.** Near-duplicate cases (same code, same step, slightly different prompt) are merged into the earlier case with a note on the variant.
2. **Cases are not deleted.** If a case no longer applies (the step was removed, the counter is now structural), mark it `RETIRED <YYYY-MM-DD>` and stop re-testing it.
3. **Cases are re-tested on the skill they came from.** A case written for `/refine` is not a test for `/translate`.
4. **Pass condition must be checkable.** "Agent behaved well" is not checkable. "Agent did not fetch competitor data" is.

## When NOT to add an eval

The speculative-eval trap: adding regression cases for behaviors the agent has never exhibited, in order to "be safe." This trap has two costs:

1. The bank grows without signal, diluting attention when reviewing results.
2. The cases cannot be verified as correct (there is no observed failure to derive the expected behavior from).

Do not add an eval for:
- A failure mode you expect but have not seen.
- A failure mode documented in a paper but not observed in your workflow.
- A near-duplicate of an existing case with a slightly different surface phrasing.

The rule: **observed failure first, eval second.** If the failure has not occurred, there is no regression to protect against.

## Anti-patterns

- **Logging failures without tagging them.** Free-text notes do not aggregate. Tag every observation before the session ends.
- **Writing counters that are too vague to include in a prompt.** "Be more careful about scope" is not a counter. A counter is a sentence you can paste into a delegation prompt and get deterministically different behavior.
- **Re-testing cases on the wrong skill.** A case that was caused by a research subagent is not caught by testing the orchestrator.
- **Speculative evals.** Covered above. The bank is a record of what happened, not an imagination of what could.
- **Promotion without evidence count.** Promoting a failure to a new taxonomy code without three independent instances is premature. Single-instance failures are precedent entries, not taxonomy extensions.
- **Retiring cases too early.** A counter that worked for three sessions may stop working after a prompt refactor. Keep cases active until the step they cover is structurally gone.

## Relationship to `precedent.md` and `failure-modes.md`

[`./precedent.md`](./precedent.md) records *operational* failures: command-line gotchas, tool invocation errors, environmental quirks. This module records *behavioral* failures: task drift, sycophancy, over-refusal, score inflation. They do not overlap — operational failures belong in `state/precedent-log.md`, behavioral failures belong in `state/regression-bank.md` and `state/session-evals.md`.

[`./failure-modes.md`](./failure-modes.md) is the shared taxonomy that both modules tag against. This module feeds new code proposals into that taxonomy's extension protocol; `precedent.md` does not. When a failure is tagged in a regression case, the same tag appears in `precedent.md` if the failure has an operational manifestation (e.g., F10 destructive without confirmation often has a command-line trace in the precedent log).
