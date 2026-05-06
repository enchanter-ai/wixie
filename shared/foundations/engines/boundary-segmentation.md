# Boundary Segmentation — Jaccard + Cosine + Time-Decay

**References:**
- Jaccard P. (1912), "The distribution of the flora in the alpine zone," *New Phytologist* 11(2):37–50.
- Salton G. and Buckley C. (1988), "Term-weighting approaches in automatic text retrieval," *Information Processing & Management* 24(5):513–523 (cosine similarity).

## Problem

Given a stream of events (file edits, tool calls, prompt submissions), detect when one *task* ends and another begins. Use cases:

- Auto-commit when a coding task naturally completes.
- Open a new browser tab, journal entry, or memory checkpoint per task.
- Aggregate per-task metrics (time, edits, files).

The hard part: idle-time alone is a poor signal — a developer thinking deeply looks identical to one stepping away. A multi-signal score is more robust.

## Formula

For consecutive events `a` and `b`, the **distance**:

```
d(a, b) = w_J · (1 - J(files_a, files_b))
       + w_C · (1 - cos(embed_a, embed_b))
       + w_T · tanh((t_b - t_a) / τ)
```

with weights `w_J + w_C + w_T = 1` (default `0.4 / 0.4 / 0.2`).

- **Jaccard** on file sets: `J(A, B) = |A ∩ B| / |A ∪ B|`. High overlap → same task.
- **Cosine** on semantic embeddings of event content (or bag-of-tokens with L2 norm if no embedding model is available). High similarity → same task.
- **Time-decay** via `tanh(Δt / τ)`. With `τ = 300 s` (5 min), small gaps barely contribute; larger gaps saturate.

A **boundary** fires when:

```
d(a, b) > θ      (default θ = 0.55)
```

## Decision rule

| `d(a, b)` | Verdict | Action |
|-----------|---------|--------|
| `< 0.45` | Same task | Append to current cluster |
| `0.45–0.55` | Uncertain | Soft signal; can be promoted by an LLM judge or a downstream check |
| `> 0.55` | Boundary | Close current cluster; start new |

The `0.10` uncertainty band catches edge cases without blocking real boundaries.

## Complexity

| Operation | Time | Space |
|-----------|------|-------|
| Per-event distance | `O(|files| + |embed_dim|)` | — |
| Per-event boundary test | `O(1)` | — |
| Cluster maintenance | `O(1)` amortized | `O(n)` worst case (open cluster) |

For real-time hooks, this runs in single-digit milliseconds per event.

## Implementation pattern

```python
import math
from dataclasses import dataclass
from typing import Sequence

@dataclass
class Event:
    files: set[str]
    embed: Sequence[float]   # any vector; bag-of-tokens or model embedding
    timestamp: float

def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)

def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)

def distance(a: Event, b: Event,
             w_j: float = 0.4, w_c: float = 0.4, w_t: float = 0.2,
             tau: float = 300.0) -> float:
    return (
        w_j * (1 - jaccard(a.files, b.files))
        + w_c * (1 - cosine(a.embed, b.embed))
        + w_t * math.tanh((b.timestamp - a.timestamp) / tau)
    )

def is_boundary(a: Event, b: Event, theta: float = 0.55, **kw) -> bool:
    return distance(a, b, **kw) > theta
```

## Tuning the weights

| Setting | Adjustment |
|---------|-----------|
| Lots of false boundaries during deep coding sessions | Lower `w_T` to `0.1`; bump `w_J` to `0.5` |
| Missed boundaries when developer pivots to a new feature in same files | Bump `w_C` to `0.5`; lower `w_J` to `0.3` |
| Working in monorepo with massive file overlap on every change | Drop `w_J` to `0.1`; rely on cosine + time |
| No embedding model available | Use stdlib bag-of-tokens with L2 norm; the cosine is noisier but still useful |

## Failure modes

- **Idle-only segmentation.** Time-only thresholds fail when developers think before typing or batch keystrokes. Multi-signal exists exactly for this.
- **Boundary churn.** Setting `θ = 0.50` produces false boundaries on minor pauses; setting `θ = 0.65` misses real ones. Production sweet spot: `0.55` with the `±0.10` uncertainty band.
- **Stale embeddings.** If embeddings are computed once at session start and not updated, semantic similarity drifts. Recompute per event for non-trivial content changes.
- **No fallback when embed unavailable.** Cosine returns `0` if either vector is zero-norm; the distance then collapses to Jaccard + time. Document the fallback explicitly.
- **Mixed time scales.** Hours-long boundaries (developer goes to lunch) saturate `tanh` quickly; minute-scale `τ` is right for most coding work but wrong for batch-job monitoring.

## When *not* to use

- Hard task boundaries declared by the user (e.g., "I'm done with feature X") — trust the user, don't compute.
- Sub-second event streams (UI clicks, keystrokes) — segmentation at this granularity is meaningless.
- Strict-rule segmentation (every commit is a task) — explicit rules dominate; don't bring a probabilistic detector to a deterministic problem.

## Composition

Pairs with [`./drift-detection.md`](./drift-detection.md) (drift signals are within-task; boundary signals are between-task) and [`../conduct/context.md`](../conduct/context.md) (a boundary is a natural point to emit a checkpoint).
