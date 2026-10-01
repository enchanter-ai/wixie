# Sunk-Cost Iteration — Stop Patching, Re-Ask the Shape Question

Audience: any agent running an iterative loop (v0 → v0.1 → v0.2 → …) against the same
artifact — a prompt under convergence, a script under debug, a proof under refinement, a
build under repair. How to recognise when the loop has stopped converging on the
original question and has started compounding assumptions, and how to break out before
the next "small fix" buries the real problem one layer deeper.

## The failure shape

The agent dispatches v0. It returns INCONCLUSIVE, BLOCKED, or partially-failed. The
agent looks at the failure, identifies a local cause, makes a "small fix", and
dispatches v0.1. v0.1 returns INCONCLUSIVE for a *different* reason — because the small
fix introduced a new assumption that the original v0 never carried. The agent fixes that
too and dispatches v0.2. By v0.3 the artifact is two layers of patches deep, the
original question has not been answered once, and the agent is now debugging the
patches rather than the question.

This is **F23 sunk-cost iteration**. The defining signature: each version's failure is
downgraded to "close, just one more fix" instead of escalated to "is this approach
still the right shape?". The agent treats the prior versions as evidence that the
approach is *almost working*, when the honest read is that the approach has not yet
worked once.

### Why it is its own failure mode

F23 sits between two adjacent codes that look similar and are not:

- **F04 task-drift** — work expanded *past* the stated goal. The agent is now building
  something the principal did not ask for. F23 is the inverse: the agent is still
  trying to hit the original goal, but is taking ever-longer paths to it and has lost
  the budget to ask whether the path is sound. F04 is scope inflation; F23 is depth
  inflation along the requested scope.
- **F12 degeneration-loop** — same edit, reverted, re-applied across iterations against
  a regression metric. F12 is detected and stopped by the no-regression contract
  watching a *score*. F23 has no regression to detect, because each version is solving
  a freshly introduced problem; the scores look like motion, not oscillation. F12
  agents thrash on a known surface; F23 agents tunnel through new surface every round.

F23 is what F12 looks like when the metric is too coarse to catch the thrash, or when
there is no metric at all and the only signal is "the principal hasn't said stop yet".

## The recovery protocol

Iteration is the correct mode for most refinement work. F23 is iteration that has lost
the shape question. The protocol below is a circuit-breaker, not a ban on iteration.

### Step 1 — Count the inconclusive results

Maintain a per-artifact counter of consecutive non-success terminal states:
INCONCLUSIVE, BLOCKED, ERROR-FROM-NEW-SOURCE, PARTIAL-WITH-NEW-CAVEAT. A clean PASS or
a clean FAIL-FOR-THE-ORIGINAL-REASON resets the counter. A failure for a *new* reason
introduced by the prior fix does **not** reset it — that is the F23 fingerprint and is
exactly what the counter is for.

### Step 2 — At threshold 2, surface the shape question

**After 2 INCONCLUSIVE/BLOCKED results from the same artifact**, do not dispatch
v(N+1). Instead, surface to the principal:

```
SHAPE-QUESTION — artifact: <name / path>
versions attempted: v0, v0.1
v0 failure: <one sentence>
v0.1 failure: <one sentence — note whether new assumption was introduced>
proposed paths:
  (a) continue iterating — specific next fix: <what>, expected resolution: <how>
  (b) replace the approach — alternative shape: <what>, why fitter: <one line>
  (c) re-scope the question — the goal may itself be the wrong target
is this approach still the right shape?
```

This is not a clarifying question about taste — a no-pause / autonomous-mode directive
does not authorize dispatching v(N+1) over a 2-strike artifact. No-pause means *do not
stall on judgment calls within a working approach*; it does not mean *keep feeding a
broken approach*. The principal may say "keep going on path (a)" — fine, but the
decision is now logged and the counter resets only on the next clean terminal state.

### Step 3 — Honor the principal's choice and record

If (a): the principal has explicitly authorized v(N+1). Record the authorization in the
iteration log alongside the v0 and v0.1 failure summaries. The counter does not reset
yet — it resets on the next clean PASS or clean original-reason FAIL.
If (b): start a v0 of the new approach. Archive the old line. Do not silently fold the
old patches into the new approach; that is how F23 metastasises.
If (c): the goal itself was wrong. Restate the goal, then restart at v0 against the
new goal. The old artifact's lessons are notes, not patches.

## The small-fix anti-rule

The most common F23 trigger is the moment the agent thinks: *"the result is almost
right — if I just fix `<one thing>`, the next dispatch will succeed."* That sentence
is a yellow flag, not a green light. Before acting on it, run the introspection:

```
□ Does the "small fix" introduce an assumption v0 did not carry?
□ Is the failure I am patching a *consequence* of the prior patch, or a property of
   the original artifact?
□ If I write down the original question on a blank page, does the next dispatch
   answer it, or does it answer a derivative question I created?
□ If any □ is checked or uncertain, this is a Step 2 escalation, not a Step 1 patch.
```

## Anti-patterns

- **"Just one more small fix."** The sentence itself is the failure signal. If you find
  yourself thinking it for the third time on the same artifact, escalate.
- **The agent makes a "small fix" that introduces a new assumption.** This is the
  defining shape of F23. The fix is local; the assumption is global. The next failure
  will look unrelated — it is not; it is the assumption surfacing. Treat every new
  assumption introduced by a patch as evidence the original shape was wrong, not as
  scaffolding the next patch can stand on.
- **Resetting the counter on cosmetic progress.** A version that moves one score by
  0.1 while degrading another is not a clean PASS. Counter does not reset.
- **Folding old patches into a fresh approach.** When the principal chooses path (b),
  the new approach starts at v0 against the original question. Importing v0.2's three
  patches into the new v0 imports the assumptions they encoded. Start clean.
- **Treating principal silence as continuation authorization.** If the principal has
  not spoken since v0, they have not authorized v0.3. The threshold is a function of
  the inconclusive count, not of how long it has been since the last principal turn.
- **Hiding the counter from the iteration log.** The per-artifact counter is
  load-bearing for the next session's diagnosis. Log it explicitly alongside each
  version, even when escalation does not fire.

## Cross-references

- [`./failure-modes.md`](./failure-modes.md) § F23 — the taxonomic entry this module operationalises.
- [`./failure-modes.md`](./failure-modes.md) § F04, § F12 — the adjacent codes this module is explicitly distinct from; consult both before tagging an incident F23.
- [`./discipline.md`](./discipline.md) § Goal-driven loops — the upstream rule; F23 is what a goal-driven loop becomes when the goal stops driving and the loop keeps spinning.
- [`./doubt-engine.md`](./doubt-engine.md) — the shape-question at Step 2 is a forced doubt-engine fire; this module names the trigger condition.
- [`./verification.md`](./verification.md) § Independent checks — the original question is the invariant; each version must be checked against it, not against the prior version.
- [`./precedent.md`](./precedent.md) — emit a precedent entry on any F23 occurrence so future sessions inherit the counter discipline.
