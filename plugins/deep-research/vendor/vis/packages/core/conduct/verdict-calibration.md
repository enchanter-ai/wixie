# Verdict Calibration — Confidence Must Match Evidence

Audience: any agent that emits a verdict — DEPLOY, COMPLETE, VERIFIED, PASS, READY,
SHIP, GREEN, APPROVED — at the end of an artifact, a test run, a review, or a
convergence loop. How to attach a calibration band to every verdict so that the
confidence claim cannot exceed what the evidence supports.

## The failure shape

The agent ran a real test. The test produced a real number. The verdict bar in the
contract was real. The agent looked at the number, saw it cleared the bar, and wrote
the verdict. Nothing was fabricated. Nothing was metric-gamed. And the verdict is
still wrong — because the *evidence base under the number* was too thin to support the
confidence the verdict carries.

A canonical instance: a wixie convergence run scores a prompt at overall 9.2, σ = 0.31,
all five axes ≥ 7.4, 8/8 SAT assertions pass. Those numbers clear the wixie DEPLOY bar
(σ < 0.45, overall ≥ 9.0, all axes ≥ 7.0, 8/8 SAT). The agent writes DEPLOY. But the
run was n=1 — a single Haiku trial, one seed, one prompt-target pairing. The five-axis
scores are real; the σ across the axes within that one trial is real; what is *not*
real is the implied generalization that the next trial would land in the same place.
The agent has reported sample-internal variance and called it deployment-grade
confidence.

This is **F25 verdict inflation**. It is distinct from two adjacent failures:

| Failure | What is wrong | F25's difference |
|---------|---------------|------------------|
| F11 reward-hacking | The metric was gamed — the number does not measure what it claims to measure | F25's number is honest; the number's *coverage* is the problem |
| F02 fabrication | The evidence was invented — the number does not exist | F25's number exists and was honestly produced; the verdict over-reads it |

F25 sits between them: real evidence, real verdict, uncalibrated confidence claim.

## The calibration protocol

Every verdict statement — wherever it appears: the final line of a report, a metadata
field, a status badge, a commit message, a hand-off to the principal — must carry
three calibration fields. Not as decoration; as part of the verdict itself.

### Field 1 — n (sample size)

State the number of independent observations the verdict rests on. If the artifact is
a single trial, n=1. If the artifact is a regression suite of 12 cases, n=12. If the
artifact aggregates 4 sub-agent passes that each ran k seeds, n=4k. Do not collapse
composite n into a single integer without showing the decomposition. n is not a
rhetorical detail — it is the denominator everything else divides by.

### Field 2 — Sampling method

Name the method that produced the observations. Acceptable values include:

- `one-shot` — a single trial, single seed, single capability path. n=1 by
  construction.
- `replicated` — the same trial repeated k times with different seeds; reports k.
- `cross-validated` — observations split into train/eval folds; reports the fold
  count and which fold the verdict applies to.
- `adversarial-suite` — the artifact was exercised by a red-team battery of N
  attacks; reports N and the pass count.
- `held-out` — the evaluation set was disjoint from any tuning set; report the
  held-out size.
- `production-replay` — observations come from real principal interactions, not
  synthesized inputs.

When the method is `one-shot`, the verdict bar moves down regardless of how strong
the single observation looked. A one-shot pass is suggestive; it is not decisive.

### Field 3 — Confidence qualifier

Attach exactly one of two artifact types to the verdict:

1. A statistical band: Wilson confidence interval, Beta-Binomial bound, bootstrap
   percentile, or p-value against the null that the verdict bar was *not* cleared.
   The band must be reported with its α (e.g., Wilson 95%, p < 0.01). Bands without
   stated α are not qualifiers; they are decoration.
2. A named qualifier drawn from the four-tier ladder:
   - `suggestive` — single observation cleared bar; recurrence not yet established.
   - `inconclusive` — observations split or insufficient; verdict cannot be defended.
   - `decisive` — repeated independent observations cleared the bar with band tighter
     than the bar's own margin.
   - `BLOCKED` — the evidence base required to qualify the verdict at all is absent;
     no verdict should be emitted under this label.

The qualifier is part of the verdict line, not a footnote. `DEPLOY (suggestive,
n=1, one-shot)` and `DEPLOY (decisive, n=12, replicated)` are different artifacts
that travel under different downstream contracts.

## How this relates to existing project verdict bars

Projects set their own bar numbers — and they should, because verdict bars are
domain-specific. Wixie's DEPLOY bar (σ < 0.45, overall ≥ 9.0, all five axes ≥ 7.0,
8/8 SAT assertions) is the canonical instantiation of this module for prompt-engineering
artifacts. Hydra, Lich, and other plugins will set their own bar numbers for their own
artifacts. This module does not redefine those bars.

What this module adds is the contract that any project's verdict bar is incomplete
without calibration fields. A wixie prompt that clears σ < 0.45 on n=1 is not DEPLOY;
it is `DEPLOY (suggestive, n=1, one-shot)` — which under the wixie DEPLOY bar's
intended use is functionally HOLD pending replication. Vis sets the abstraction
(every verdict carries n + method + qualifier); the plugin sets the concrete bar
numbers and the rule for when `suggestive` is acceptable to ship versus when only
`decisive` qualifies.

## Anti-patterns

- **DEPLOY on n=1.** A single trial cleared the bar; the agent wrote DEPLOY without
  a qualifier. The fix is `DEPLOY (suggestive, n=1, one-shot)` if the project permits
  one-shot ship, or HOLD pending replication if it does not.
- **Extrapolating from a single Haiku trial.** One cheap-tier trial cleared all axes;
  the agent claimed cross-tier generalization. Tier mix is a stratification dimension;
  n=1 within a single tier does not entitle a claim across tiers. Report the tier
  explicitly in the sampling method.
- **Reporting σ without n.** A standard deviation across five axes within one trial
  is sample-internal variance, not run-to-run variance. Either report both (within-trial
  σ *and* between-trial σ across replications) or label the σ as within-trial only.
  An unqualified σ in a verdict statement is an inflation artifact.
- **Marking PASS when tied trials defaulted to FAIL.** Convention-driven defaults
  (e.g., "on tie, the more conservative verdict wins") are part of the qualifier. If
  the trial outcome was a tie and convention assigned FAIL, the verdict line cannot
  say PASS. The tie itself is the calibration signal.
- **Letting a regression test pass for the wrong reason.** The test produced a green
  output; the agent shipped the verdict. But the test green was load-bearing on a
  precondition the test did not check (e.g., the input fixture was empty, so every
  branch returned an empty-set match). A passing test under a degenerate precondition
  is not evidence of correctness; it is evidence of a missing check.
- **Citing run-internal variance as run-to-run variance.** Same shape as the σ
  anti-pattern at a different scale: within-run dispersion across sub-items is not
  evidence about how the run as a whole would land on replication.
- **Burying the qualifier in a footnote.** The qualifier is part of the verdict;
  it travels with the verdict downstream. A reader who sees only the verdict line
  must see the calibration fields too.

## Cross-references

- [`./failure-modes.md`](./failure-modes.md) § F25 — taxonomic entry.
- [`./failure-modes.md`](./failure-modes.md) § F02 — fabrication; F25's adjacent failure on the evidence-existence axis.
- [`./failure-modes.md`](./failure-modes.md) § F11 — reward-hacking; F25's adjacent failure on the metric-honesty axis.
- [`./capability-fidelity.md`](./capability-fidelity.md) — when a contract names verification stages that were not executed, F25 is the failure mode of shipping DEPLOY anyway.
- [`./verification.md`](./verification.md) — defines independent checks; F25 fires when the count of independent checks is insufficient for the qualifier claimed.
- [`./doubt-engine.md`](./doubt-engine.md) — adversarial self-check before agreement; should fire on the agent's own verdict line as well as on principal proposals.
- [`./precedent.md`](./precedent.md) — emit a precedent entry on any F25 occurrence; verdict inflation tends to recur within a session if uncalibrated once.
