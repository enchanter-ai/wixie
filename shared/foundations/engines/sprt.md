# Sequential Probability Ratio Test — Wald

**Reference:** Wald A. (1947), *Sequential Analysis*. Wiley. The SPRT achieves the minimum expected sample size for a specified pair of error rates `(α, β)` against simple hypotheses.

## Problem

Given a stream of binary observations under one of two hypotheses `H₀` (default / "noise") vs. `H₁` (signal / "this pattern is real"), decide between them with the **minimum number of observations** for fixed Type I and Type II error rates.

Use cases:

- "Is this user-reported failure mode real, or is one observation a fluke?" (elevate to a learning entry only when SPRT crosses the upper threshold).
- "Has this experiment converged?" (stop when SPRT crosses either bound).
- "Is this anomaly recurrent enough to alert?"

A fixed-N test (collect N samples, then decide) wastes data: if the truth is obvious after 5 samples, you've collected 95 unnecessary ones.

## Formula

For each observation `xₜ` with likelihood `f₁(xₜ)` under `H₁` and `f₀(xₜ)` under `H₀`, accumulate the **log-likelihood ratio**:

```
LLR_t = LLR_{t-1} + log(f₁(xₜ) / f₀(xₜ))
```

Decision boundaries from `(α, β)`:

```
A = log((1 - β) / α)         (upper — accept H₁)
B = log(β / (1 - α))          (lower — accept H₀)
```

For `α = β = 0.05`: `A ≈ 2.94`, `B ≈ -2.94`. For `α = β = 0.025`: `A ≈ 3.66`, `B ≈ -3.66`. Common production choice: `A = 2.89` (≈ 95% confidence H₁), `B = -2.25` (≈ retire pattern).

## Decision rule

```
After each new observation:
  Update LLR_t.
  If LLR_t ≥ A → accept H₁ (signal is real; elevate / promote)
  If LLR_t ≤ B → accept H₀ (signal is noise; retire / suppress)
  Otherwise → continue collecting
```

The expected sample size to decide is provably lower than any fixed-N test for the same error rates.

## Complexity

`O(1)` per observation. State: a single float (`LLR_t`). No need to keep individual observations once incorporated.

## Implementation pattern

```python
import math

class SPRT:
    """
    Bernoulli SPRT for "is the success rate p >= p1 (signal) vs p <= p0 (noise)".
    """
    def __init__(self, p0: float, p1: float, alpha: float = 0.05, beta: float = 0.05):
        if not (0 < p0 < p1 < 1):
            raise ValueError("Require 0 < p0 < p1 < 1")
        self.p0, self.p1 = p0, p1
        self.A = math.log((1 - beta) / alpha)
        self.B = math.log(beta / (1 - alpha))
        self.llr = 0.0
        self.n = 0
        self.verdict: str | None = None

    def update(self, success: bool) -> str | None:
        if self.verdict is not None:
            return self.verdict
        x = 1 if success else 0
        # Bernoulli log-likelihood ratio
        self.llr += (
            x * math.log(self.p1 / self.p0)
            + (1 - x) * math.log((1 - self.p1) / (1 - self.p0))
        )
        self.n += 1
        if self.llr >= self.A:
            self.verdict = "H1"
        elif self.llr <= self.B:
            self.verdict = "H0"
        return self.verdict
```

For non-Bernoulli observations (Gaussian, Poisson), substitute the appropriate likelihood ratio. The update stays `O(1)`.

## Choosing `(p₀, p₁, α, β)`

| Setting | Rule of thumb |
|---------|---------------|
| `p₀` | The "this is noise" rate. For pattern elevation, `p₀ = 0.10` (only 10% of one-off observations should elevate). |
| `p₁` | The "this is signal" rate. Often `p₁ = 0.50` or higher — patterns worth elevating recur in at least half their opportunities. |
| `α` | Type I (false elevate) tolerance. Production: `0.05` or stricter. |
| `β` | Type II (miss real signal) tolerance. Equal to `α` is the default; raise to `0.10` if elevating is cheap, lower to `0.025` if elevating is expensive. |

## Failure modes

- **Choosing `p₀` and `p₁` post-hoc** to match observed data — invalidates the test. Pick before observing.
- **Re-using the same SPRT after a verdict** — once decided, start a fresh SPRT for any continued monitoring.
- **Non-stationary data** — SPRT assumes observations are IID under each hypothesis. If the underlying rate drifts mid-test, decisions are unreliable. Use sliding-window SPRT or restart after detected change.
- **Truncating the test** — most production SPRTs add a maximum N (e.g., never run beyond 100 observations). The formal error rates change slightly when truncated; either accept the small bias or use a truncated SPRT variant.

## When *not* to use

- Estimating the rate itself (not just deciding) — use [`./trust-scoring.md`](./trust-scoring.md) (Beta-Bernoulli).
- Multi-arm experiments (>2 hypotheses) — use a multi-arm bandit or Bayesian posterior selection.
- Single-shot decisions where you must decide *now* — SPRT only stops when evidence is conclusive.

## Composition

SPRT pairs with [`./trust-scoring.md`](./trust-scoring.md): use Beta-Bernoulli for the live posterior, SPRT for the elevation/retirement decision. SPRT also pairs with `../conduct/precedent.md` — only entries that crossed the upper SPRT bound get promoted to the long-lived precedent log.
