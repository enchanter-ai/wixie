## DEPLOY bar

| Verdict | Criteria | Action |
|---------|----------|--------|
| DEPLOY | σ < 0.45 **and** overall ≥ 9.0 **and** all 5 axes ≥ 7.0 **and** 8/8 SAT assertions pass | Ship. Save artifacts. |
| HOLD | σ ≥ 0.45 or any axis < 7.0 | Re-run `/converge`. Do not hand back weak prompts. |
| FAIL | Reviewer flags registry mismatch / stale technique / format drift | Fix the flagged issue, then retry. |

σ = standard deviation of the 5 axis scores from 10. 8 SAT assertions: `has_role`, `has_task`, `has_format`, `has_constraints`, `has_edge_cases`, `no_hedges`, `no_filler`, `has_structure`.

**Scoring provenance — read before quoting a verdict.** The 5-axis scores, σ, and the 8 SAT assertions are all produced by `shared/scripts/output-eval.py` and `convergence.py` — stdlib regex/structure heuristics that make **zero model API calls**. `/test-prompt` and `/harden` likewise have the executing agent role-play as the target model rather than calling it. A DEPLOY verdict means "the heuristic linter and the agent's own simulation are satisfied," not "a real target-model API call confirmed this." The one component that genuinely exercises a model is `shared/scripts/efficacy-replay.py` (real `claude -p` calls, Wilson confidence intervals) — reach for it when a claim needs model-verified evidence rather than heuristic score.

