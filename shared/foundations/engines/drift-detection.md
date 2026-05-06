# Drift Detection — Markov Patterns + EMA Tracking

**References:**
- Markov chains: any standard treatment, e.g., Kemeny J.G. and Snell J.L. (1960), *Finite Markov Chains*.
- EMA (exponentially weighted moving average): Roberts S.W. (1959), "Control chart tests based on geometric moving averages," *Technometrics* 1(3):239–250.

## Problem

Detect when an agent session enters an *unproductive loop* — the same action repeating without progress. Concrete patterns:

- **Read-loop:** the same file read ≥ 3 times without an intervening hash-changing write.
- **Edit-revert:** a write whose hash matches an earlier hash for that file (the agent undid recent work).
- **Test-fail-loop:** the same command fails ≥ 3 consecutive times with the same error.

Detection lets the runtime warn the user, force a checkpoint, or escalate to a different model.

## Formula — pattern detection

Maintain a fixed-window history `H = ⟨e₁, ..., eₙ⟩` of the last `n` events (default `n = 20`). Define a state extractor `s(e)` (e.g., `(tool, file_path, content_hash)`). Drift fires when:

```
| { i : s(eᵢ) = s(eⱼ) for some i ≠ j in current window } | ≥ θ
```

with `θ = 3` for read-loop, exact-match for edit-revert (`hash` collision), and `θ = 3` consecutive for test-fail-loop.

## Formula — EMA on pattern frequency

To avoid alert fatigue while still tracking trends, maintain an EMA of pattern frequency:

```
EMA_t = α · x_t + (1 - α) · EMA_{t-1}     where α ∈ (0, 1]
```

`α = 0.3` is a reasonable default (half-life ≈ 2 events). High `α` reacts fast; low `α` smooths out noise.

EMA serves two roles:
1. Inform whether the *current* drift is a one-off blip or a trend.
2. Calibrate the cooldown — if EMA is high (drift is chronic), increase the cooldown between alerts.

## Decision rule

```
1. On each new event eₜ:
   a. Append to ring buffer (drop eₜ₋ₙ₋₁).
   b. Test each pattern (read-loop, edit-revert, test-fail-loop).
   c. If any pattern triggers AND last alert was > cooldown ago:
        emit alert
        record alert timestamp
   d. Update EMA for each pattern's frequency.
2. If EMA exceeds saturation threshold (e.g., 0.5):
      escalate from soft alert to hard escalation
```

A 5-event cooldown between alerts of the same kind avoids flooding the user.

## Complexity

| Operation | Time | Space |
|-----------|------|-------|
| Append event | `O(1)` | `O(n)` ring buffer |
| Pattern test | `O(n)` per pattern (linear scan) | — |
| EMA update | `O(1)` | `O(p)` where `p` is pattern count |

For `n ≤ 20`, this is effectively constant per event.

## Implementation pattern

```python
from collections import deque
from dataclasses import dataclass

@dataclass
class Event:
    tool: str
    target: str
    content_hash: str
    timestamp: float

class DriftDetector:
    def __init__(self, window: int = 20, alpha: float = 0.3, cooldown_events: int = 5):
        self.events: deque[Event] = deque(maxlen=window)
        self.alpha = alpha
        self.cooldown = cooldown_events
        self.last_alert: dict[str, int] = {}   # pattern → event index
        self.ema: dict[str, float] = {}        # pattern → EMA frequency
        self.event_count = 0

    def record(self, e: Event) -> list[str]:
        self.events.append(e)
        self.event_count += 1
        triggered = []
        for pattern_name, predicate in self._patterns():
            x = 1.0 if predicate(self.events) else 0.0
            self.ema[pattern_name] = (
                self.alpha * x + (1 - self.alpha) * self.ema.get(pattern_name, 0.0)
            )
            last = self.last_alert.get(pattern_name, -10**9)
            if x and (self.event_count - last) > self.cooldown:
                self.last_alert[pattern_name] = self.event_count
                triggered.append(pattern_name)
        return triggered
```

The `_patterns()` method returns named predicates over the event window. Add new patterns without changing the engine.

## Failure modes

- **Window too small** — a 5-event window misses real loops separated by 8 unrelated events.
- **Window too large** — old events bias detection; the user notices a "loop" that ended 30 events ago.
- **State extractor too narrow** — using `(tool, file)` without content hash misses edit-revert. Using `(tool)` alone catches no useful pattern.
- **No cooldown** — alert spam after a single repeated event burns user trust.
- **Confusing EMA with frequency** — EMA is exponentially weighted; reporting it as "this pattern fires X% of the time" is wrong unless `α` is calibrated.

## When *not* to use

- Detecting *progress* (the opposite question) — for that, use a goal-directed metric, not pattern counting.
- Catching *correctness* errors — drift detection is about behavior shape, not correctness.
- Single-event signals (e.g., "agent destroyed a file") — those need an immediate guard, not a windowed detector.

## Composition

Pairs naturally with [`../conduct/context.md`](../conduct/context.md) (drift detection is what triggers the checkpoint protocol) and with [`./trust-scoring.md`](./trust-scoring.md) (drift events are negative-trust observations on the relevant tool / file).
