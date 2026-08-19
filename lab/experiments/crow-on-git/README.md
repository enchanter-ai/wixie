# crow-on-git — free-ground-truth change-durability experiment

**lab experiment #1.** The first experiment of `enchanter/lab`, the measurement
instrument that consolidates `wixie/shared/scripts/efficacy-replay.py`.

## The load-bearing question

> Does a candidate change-quality signal actually separate git commits that were
> later **reverted / rewritten** from those that **survived**?

This is the proof-of-concept for lab (can we get a real, honest verdict from
**free** ground truth?) and the evidence that would justify — or kill —
re-founding **crow** on git survival (**crow-B**). crow today scores each change
statelessly from its own content; crow-B would instead learn a trust model from
whether changes *stick* in git history. That only makes sense if change-quality
signals demonstrably predict durability. This experiment tests exactly that.

Ground truth is **free**: it comes entirely from `git log` / `git blame`. No
human labels, no model API calls.

## What it measures

For every matured commit in the target repo(s):

- **Label (ground truth, y):**
  - `y=0` **bad / did-not-stick** — the commit was *reverted* (message `^Revert`,
    or a later commit's body says `This reverts commit <sha>`), **or** the lines
    it introduced were *mostly rewritten/deleted* within the maturity window
    (line-survival ratio `< --survival`).
  - `y=1` **durable** — its introduced lines survive to the window horizon
    (survival ratio `>= --survival`).
  - Commits younger than `--window-days` are **excluded** (not enough time to
    have a fair chance to be reverted/rewritten).

- **Line survival** is measured with `git blame --line-porcelain` at a fixed
  per-commit **horizon ref** (the newest commit dated `<= commit_date +
  window_days`). A line the commit added counts as surviving iff blame at the
  horizon still attributes it to that commit. `survival_ratio =
  surviving_lines / lines_the_commit_added`, aggregated over the commit's
  non-binary, non-generated files.

- **Candidate signals (predictors, each a per-commit boolean):**
  - **crow content detectors**, ported from
    `crow/plugins/trust-scorer/hooks/post-tool-use/score-change.sh`, run over the
    commit's **added diff lines**: `gutted_test`, `trivial_assertions`,
    `weak_crypto`, `wildcard_cors`, `exposed_secrets`, `debug_enabled`,
    `very_short_file`, plus rollups `crow_critical`, `crow_high`, `crow_flag_any`.
  - **structural features**: `big_diff` (>150 lines churn), `many_files` (>5),
    `is_test_change`, `is_config_change`, `is_source_code`.

- **Scoring:** a fired signal is a positive prediction of "bad" (`y=0`). Per
  signal we report the confusion matrix and **precision / recall / F1**, with a
  **Wilson 95% CI** (copied verbatim from `shared/scripts/efficacy-replay.py`) on
  precision and recall. A signal only "separates" if its precision CI
  lower-bound clears the dataset base rate `P(bad)` — i.e. it beats guessing.

## Files

| file                | role                                                          |
|---------------------|--------------------------------------------------------------|
| `label_commits.py`  | walk `git log`, label each matured commit's durability (y)   |
| `score.py`          | compute crow content detectors + structural features         |
| `confusion.py`      | confusion matrix + precision/recall/F1 + Wilson 95% CIs      |
| `run.py`            | orchestrate label -> score -> confusion -> written verdict   |
| `output/`           | committed run: `dataset.jsonl`, `verdict.txt`, `confusion.json` |
| `output-sensitivity/` | robustness run at a different window/threshold             |

## How to run

```bash
# single repo
python label_commits.py --repo /path/to/repo --window-days 60 --survival 0.5

# pooled across repos, full pipeline + verdict
python run.py --repos /path/to/repoA /path/to/repoB ... \
              --window-days 60 --survival 0.5 --out-dir output
```

Stdlib only. `python` on Windows / Git Bash. Requires `git` on PATH and read
access to the target repos' history (this experiment never writes to them).

## Honest limitations (read before quoting any number)

- **revert ≠ bad, survival ≠ good.** A revert can undo a *good* change that
  exposed a latent bug elsewhere; long-surviving lines can be dead code nobody
  dared touch. Line survival is a *proxy* for durability, not a truth oracle.
- **The explicit-revert channel is empty in this corpus.** Across all 10 target
  repos (1,461 commits) there are **zero** `git revert`s. Every `y=0` label
  therefore comes from the churn/rewrite proxy alone — the stronger, less-noisy
  revert signal contributes nothing here.
- **Small classes / wide CIs.** Even pooled, per-signal true-positive counts are
  tiny; Wilson intervals are correspondingly wide. Point estimates are
  indicative, not conclusive.
- **Self-authored benign history.** These are clean single-author repos. crow's
  detectors target adversarial security regressions (leaked secrets, gutted
  tests, weak crypto) that essentially don't occur here, so their firing rate is
  near-floor — this corpus under-tests them by construction.
- **Horizon confound.** Survival is measured at a per-commit horizon to hold the
  window roughly constant, but blame attribution is defeated by later
  reformatting/moves that are not semantic rewrites (false `y=0`), and by
  copy-paste survival of trivial lines (false `y=1`).
- **Thresholds are arbitrary.** `--survival` and `--window-days` are choices; see
  `output-sensitivity/` for a second operating point. The qualitative verdict
  should survive threshold changes to be trustworthy.

## Verdict (this run)

See `output/verdict.txt` for the machine-generated verdict. Summary: with free
git ground truth the harness runs and produces honest numbers, but on this
benign, revert-free, self-authored corpus **no candidate signal separates bad
from durable** above the base rate. The org has the measurement machinery and
**thin ground truth** — which is itself the key lab lesson. crow-B is **not yet
justified** on this evidence; validate it on a large multi-contributor OSS repo
with real reverts before building.
