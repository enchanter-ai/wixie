# Trust Scoring — Beta-Bernoulli Conjugate Prior

**Reference:** Gelman A. et al. (2013), *Bayesian Data Analysis*, 3rd ed., Ch. 2 (single-parameter models). The Beta–Bernoulli pair is the canonical conjugate update for binary outcome streams.

## Problem

Given a stream of binary observations (success/failure, trustworthy/untrustworthy, pass/fail), maintain an online estimate of the underlying probability `θ` such that:

- Each new observation updates the estimate in `O(1)`.
- The estimate is bounded `[0, 1]` and well-behaved with zero observations (uninformative prior).
- The estimate has natural credible intervals (mean + variance), not just a point.

Examples: per-file change-trust scoring, per-tool reliability tracking, per-source citation reliability, per-author commit-quality estimate.

## Formula

The Beta distribution `Beta(α, β)` is conjugate prior to the Bernoulli likelihood:

```
P(θ | D) ∝ P(D | θ) · P(θ)
P(θ)     = Beta(α, β)   ∝ θ^(α-1) · (1-θ)^(β-1)
```

After observing `s` successes and `f` failures, the posterior is:

```
α' = α + s
β' = β + f
```

The **posterior mean** (the score):

```
trust = α' / (α' + β')
```

The **posterior variance** (uncertainty):

```
var = α' · β' / [ (α' + β')² · (α' + β' + 1) ]
```

## Decision rule

| Score band | Interpretation | Default action |
|------------|----------------|----------------|
| `trust < 0.2` | Critical — strong evidence against | Block or escalate |
| `0.2 ≤ trust < 0.4` | Low — leans against | Warn, request review |
| `0.4 ≤ trust < 0.8` | Neutral / uncertain | Proceed with normal scrutiny |
| `trust ≥ 0.8` | High — strong evidence for | Auto-allow |

Action thresholds belong in [`../conduct/verification.md`](../conduct/verification.md), not in the engine itself.

## Choice of prior

| Prior | Use when |
|-------|----------|
| `Beta(1, 1)` (uniform) | No domain knowledge, want maximum responsiveness to data |
| `Beta(2, 2)` (mildly informative) | Default for production — centered at 0.5 with moderate confidence; a single observation doesn't catastrophically swing the score |
| `Beta(α₀, β₀)` calibrated to historical base rate | When you have prior data: set `α₀ / (α₀ + β₀) = base_rate` and `α₀ + β₀ = effective_prior_sample_size` |

`Beta(2, 2)` is the "do no harm" choice. Avoid `Beta(1, 1)` in production unless you genuinely have no prior — a single bad observation flips the score below 0.5, which surprises users.

## Complexity

`O(1)` per observation. Constant memory: store `(α, β)` per scoring target, two floats.

## Implementation pattern

```python
class BetaBernoulli:
    def __init__(self, alpha: float = 2.0, beta: float = 2.0):
        self.alpha = alpha
        self.beta = beta

    def update(self, success: bool, weight: float = 1.0):
        if success:
            self.alpha += weight
        else:
            self.beta += weight

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        a, b = self.alpha, self.beta
        return (a * b) / ((a + b) ** 2 * (a + b + 1))
```

For weighted observations (e.g., a high-severity failure counts as 3× a normal one), pass `weight > 1` to `update`. The Beta update remains conjugate as long as weights are positive reals.

## Failure modes

- **Forgetting the prior choice.** `Beta(0, 0)` is improper and produces NaN on the first observation; `Beta(1, 1)` over-reacts. Pick `Beta(2, 2)` unless you have a reason.
- **Treating posterior mean as ground truth.** With few observations, variance is high. Display a credible interval, or downstream consumers will mis-trust.
- **No decay.** A file that was untrustworthy 6 months ago dominates the posterior forever. For time-sensitive trust, apply EMA-style decay: `α ← γ·α + s`, `β ← γ·β + f` with `γ ∈ (0, 1)` per period.
- **Aggregating across categories.** A single Beta over "all changes" hides per-category variance. Score per category (test files, source, config, schema) and combine if needed.

## When *not* to use

- Multi-class outcomes (success / partial / fail) — use Dirichlet-Multinomial.
- Continuous outcomes (latency, error rate) — use Normal-Inverse-Gamma or similar.
- When you need a calibrated probability for downstream Bayesian inference — pass the full `(α, β)` pair, not the mean.

## Composition

Beta-Bernoulli pairs naturally with [`./drift-detection.md`](./drift-detection.md) (EMA on the same stream gives a fast-moving signal alongside the slow-moving posterior) and with [`./sprt.md`](./sprt.md) (when you need to *decide* between two trust hypotheses, not just estimate).
