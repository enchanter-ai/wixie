# enchanter/lab — the measurement instrument

`lab` is where enchanter answers concrete, load-bearing questions with **honest
numbers and calibrated verdicts**, not vibes. It consolidates the existing
evidence harness (`wixie/shared/scripts/efficacy-replay.py` — real `claude -p`
runs with Wilson CIs) and grows it into a home for repeatable experiments.

A lab experiment must:

1. State one **load-bearing question** (something a build/kill decision hinges on).
2. Use the **cheapest trustworthy ground truth** available — free is best.
3. Report **honest numbers** — n, base rate, precision/recall/F1 with Wilson 95%
   CIs — and a **verdict that does not inflate**. "Inconclusive, n too small" is a
   valid, valuable result.

## Experiments

| # | experiment | question | ground truth |
|---|------------|----------|--------------|
| 1 | [`experiments/crow-on-git`](experiments/crow-on-git/) | Do change-quality signals separate reverted/rewritten commits from durable ones? | **free** — `git log` / `git blame` |

Each experiment is self-contained under `experiments/<slug>/` with its own
`README.md`, runnable scripts (stdlib only where possible), and a committed
`output/` holding the labeled dataset and the machine-generated verdict.
