# LLM Bandit — Contextual Multi-Armed Bandit for Tier Routing

**References:**
- arxiv 2502.02743 — LLM Bandit: contextual multi-armed bandit for LLM tier selection by cost-quality threshold.
- RouteLLM (lm-sys) — production tier-router using cost-quality thresholds; confirms the bandit framing generalizes to deployment scale.
- arxiv 2602.16429 (TabAgent) — "a compact textual-tabular classifier trained on execution traces"; trace-trained classifier as an alternative formulation to online bandit updates.

## Problem

Given a stream of agent invocations, each with a task-feature context and a choice among model tiers (e.g., Opus / Sonnet / Haiku), select the tier that maximizes quality while minimizing cost — without knowing in advance which tier is best for a given task type. The challenge is the exploration-exploitation tradeoff: always choosing the historically best tier misses cases where a cheaper tier would have been sufficient; always exploring wastes budget.

This engine operationalizes the prescriptions of [`../conduct/tier-sizing.md`](../conduct/tier-sizing.md) — which specifies verbosity levels per tier — by adding a feedback loop: routing policy updates based on observed cost-quality outcomes. For teams that already run RouteLLM or a similar production router, this primitive describes the underlying mechanism.

## Formula

The bandit maintains a context-feature vector `x` (task type, estimated prompt size, toolset, latency requirement) and a per-arm value estimate `Q_a(x)` for each tier `a`. At each routing decision:

```
arm = argmax Q_a(x)      (exploitation)
arm = random choice       (exploration, with probability ε)
```

After the subagent completes, reward `r` is computed and the value estimate updated:

```
r      = quality_score - λ · cost
Q_a(x) = Q_a(x) + α · (r - Q_a(x))
```

where `quality_score` is the self-evaluation axis score (0–10), `cost` is the normalized token cost for the invocation (0–1), `λ` is the cost-sensitivity weight (default: 0.3), and `α` is the learning rate (default: 0.1).

## Decision rule

For each routing decision: with probability `ε` explore (uniform over arms); otherwise exploit (`argmax Q[arm]`). After the subagent returns, observe the cost-adjusted reward `r = quality − λ·cost` and update `Q[arm]` by incremental EMA. Persist `Q` across sessions to warm-start the next run; without persistence the bandit restarts cold every session and never converges.

## Reference implementation pattern

```
INPUTS:
  context x                       # task-feature vector
  Q[high, mid, low]               # per-arm value estimates, initialized to 0
  epsilon = 0.10                  # exploration rate (tune per project)
  alpha   = 0.10                  # learning rate
  lambda  = 0.30                  # cost-sensitivity weight

ROUTING DECISION:
  if random() < epsilon:
    arm = random_choice([high, mid, low])     # explore
  else:
    arm = argmax(Q[a] for a in [high, mid, low])  # exploit

  invoke subagent with tier = arm

REWARD UPDATE (after subagent returns):
  quality = self_eval_score(subagent_output)   # 0–10
  cost    = normalized_token_cost(invocation)  # 0–1
  r       = quality - lambda * cost
  Q[arm]  = Q[arm] + alpha * (r - Q[arm])

PERSIST:
  write Q to state/bandit-state.json at session end
  read Q from state/bandit-state.json at session start (warm start)
```

The state file enables cross-session learning. Without it, each session restarts cold; with it, the bandit converges on the project's cost-quality optimum over multiple sessions.

## Complexity

`O(1)` per routing decision and per reward update. Storage: one float per arm per context bucket (three floats for a three-tier system with a single context). Memory scales with the number of distinct context buckets tracked.

## Failure modes

- **No warm-start.** Without reading `state/bandit-state.json` at session start, every session explores from scratch and the quality-cost optimum is never reached.
- **ε too low.** An exploration rate near zero locks in an early suboptimal tier; task distributions shift and the bandit cannot detect it.
- **ε too high.** Exploration eats budget on every invocation; the bandit never converges to the best tier.
- **λ miscalibrated.** If `λ = 0`, cost is ignored and the bandit drifts to the highest-quality (most expensive) tier. If `λ` is too high, the bandit routes everything to the cheapest tier regardless of quality.
- **Context vector too coarse.** Using a single shared `Q` across all task types merges signals from tasks where mid-tier is optimal and tasks where low-tier is sufficient. Split by at least task category (research, code edit, validation).
- **TabAgent variant used zero-shot.** The TabAgent formulation (arxiv 2602.16429) replaces online Q-updates with a classifier pre-trained on execution traces. It is not a drop-in primitive — it requires a trace dataset for pre-training and converges faster only when that dataset is representative.

## When *not* to use

- **Single-invocation tasks.** The bandit amortizes over many invocations; for a one-shot task, the static tier rules in `conduct/tier-sizing.md` are sufficient.
- **Tasks with fixed compliance requirements.** If policy mandates a specific tier for certain task types (e.g., destructive ops always at mid-tier or above), override the bandit for those types rather than letting it explore them.
- **When the reward signal is unavailable.** The bandit requires a quality score after each invocation. If self-eval is not part of the workflow, there is no reward signal and the Q-estimates never update.

## Composition

Pairs with [`../conduct/tier-sizing.md`](../conduct/tier-sizing.md) (bandit operationalizes the static tier rules with a feedback loop), [`../conduct/cost-accounting.md`](../conduct/cost-accounting.md) (each invocation's cost-adjusted quality score feeds the session budget log and Gate 1), and [`../conduct/delegation.md`](../conduct/delegation.md) (exploration-arm invocations are subagent spawns that count against the spawn cap).
