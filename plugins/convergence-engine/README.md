# convergence-engine

**Autonomous prompt perfection. Zero user intervention.**

Like gradient descent for prompts. Each iteration scores the prompt, identifies the weakest axis, applies a targeted fix, and re-scores. Repeats up to 100 times until the prompt reaches DEPLOY quality.

## How It Works

```
Input: any prompt file (4.4/10 garbage one-liner)
  │
  ├── Iteration 1:  Score → Fix Clarity (remove hedge words) → 6.2/10
  ├── Iteration 2:  Score → Fix Completeness (add role, format) → 7.8/10
  ├── Iteration 3:  Score → Fix Resilience (add fallbacks) → 8.1/10
  ├── Iteration 4:  Score → PLATEAU
  │
Output: optimized prompt (8.1/10) + updated metadata + fresh report.pdf
```

## Skills

| Skill | Triggers on |
|-------|-------------|
| converge | `/converge`, "optimize until perfect", "run convergence" |

## Agents

| Agent | Role | Model |
|-------|------|-------|
| optimizer | Runs convergence.py, updates artifacts | Sonnet |
| reviewer | Validates result, checks metadata/registry alignment | Haiku |

## What It Fixes

| Axis | Fix Applied |
|------|-------------|
| Clarity | Remove hedge words, shorten long sentences, add imperatives |
| Completeness | Add missing role, output format, constraints, examples |
| Efficiency | Remove filler phrases, deduplicate, clean whitespace |
| Model Fit | Add/remove CoT, fix format for target model, add "think thoroughly" |
| Failure Resilience | Add fallbacks, edge case handling, input validation |

## Exit Conditions

- **DEPLOY:** overall ≥ 9.0, all axes ≥ 7.0
- **PLATEAU:** score unchanged for 3 consecutive iterations
- **MAX:** 100 iterations reached
