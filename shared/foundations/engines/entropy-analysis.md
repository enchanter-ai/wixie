# Entropy Analysis — Shannon

**Reference:** Shannon C.E. (1948), "A mathematical theory of communication," *Bell System Technical Journal* 27(3):379–423.

## Problem

Detect strings that *look like* secrets, hashes, or random IDs without a pre-built pattern list. Useful when:

- A new secret format slips past the pattern scanner ([`./pattern-detection.md`](./pattern-detection.md)).
- The token of interest is structurally random (`base64`, `hex`, UUIDs).
- You want a vendor-agnostic "this looks generated" signal.

## Formula

Shannon entropy of a string `s` over its character set `Σ`:

```
H(s) = - Σ_{c ∈ Σ} p(c) · log₂ p(c)
```

where `p(c)` is the empirical frequency of character `c` in `s`. `H(s)` is bounded by `log₂ |Σ|`. For base64 (`|Σ| = 64`), max is 6.0 bits/char; for hex, 4.0; for ASCII printable (`|Σ| ≈ 95`), 6.57.

## Decision rule

Flag `s` if **both**:

```
H(s) > θ_H   AND   |s| ≥ θ_L
```

Common thresholds: `θ_H = 4.5` bits/char, `θ_L = 20` chars. The length floor matters — a 3-char string `xy7` can have high entropy by accident; a 32-char string with `H > 4.5` is overwhelmingly likely to be generated.

For specific token classes:

| Class | Min length | Min entropy |
|-------|-----------|-------------|
| Hex token | 16 | 3.5 |
| Base64 token | 20 | 4.5 |
| Generic high-entropy | 32 | 4.5 |

## Complexity

`O(|s|)` per call. A single pass to count character frequencies, a second pass to sum. For streaming input, maintain a running histogram and recompute `H` per window.

## Implementation pattern

```python
import math
from collections import Counter

def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())

def looks_secret(s: str, min_len: int = 20, min_entropy: float = 4.5) -> bool:
    return len(s) >= min_len and shannon_entropy(s) > min_entropy
```

## Failure modes

- **Repeated structured tokens** (`AAAAAAAAA...`) have low entropy → not flagged. That's correct behavior; they aren't secrets.
- **Natural-language text** has `H ≈ 4.0–4.5` bits/char in English — set `θ_H = 4.5` strictly above this band, or normal prose triggers false positives.
- **Short hashes** (`abcd1234`) fall below the length floor; that's a feature, not a bug. Use the pattern detector for known short formats instead.
- **Charset normalization** — entropy computed over Unicode codepoints differs from over bytes. Pick one and stay consistent across calls.
- **Adversarial inputs** can craft below-threshold strings that *are* secrets. Combine with Aho-Corasick pattern detection for defense in depth.

## When *not* to use

- Known secret formats with stable prefixes (`AKIA…`, `ghp_…`, `xoxb-…`) — pattern detection is faster and has zero false positives.
- Natural-language classification — entropy is a poor signal for "is this English vs. random."
- Short tokens (< 16 chars) — noise dominates.

## Composition

In production: run pattern detection first (cheap, exact); fall back to entropy analysis on the remaining tokens. The two together catch ~95% of credential leaks in code-review settings.
