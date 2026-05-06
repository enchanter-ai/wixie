# LCS Alignment — Hunt-Szymanski

**Reference:** Hunt J.W. and Szymanski T.G. (1977), "A fast algorithm for computing longest common subsequences," *Communications of the ACM* 20(5):350–353.

## Problem

Given two token sequences `A` and `C` (e.g., the original task description and the current turn's task description), compute how much of `A` survives in `C`. Use cases:

- Detect task drift: how much of the user's anchor goal is still being respected in turn N.
- Detect file-edit preservation: did a refactor preserve the comment/docstring sequence.
- Compute a "fidelity score" between an intent and an outcome.

## Formula

The Longest Common Subsequence `LCS(A, C)` is the longest sequence appearing in both, preserving order but not contiguity. Formal:

```
LCS(A, C) = arg max { |S| : S is a subsequence of A AND S is a subsequence of C }
```

The **preservation ratio** (Ratcliff-Obershelp over LCS):

```
ratio(A, C) = 2 · |LCS(A, C)| / (|A| + |C|) ∈ [0, 1]
```

`ratio = 1` means `A ≡ C`; `ratio = 0` means no shared tokens.

## Decision rule

Bands for "is the agent on-task":

```
ratio ≥ 0.7   → ON_TASK    (no concern)
0.4 ≤ ratio < 0.7 → SIDEQUEST (drift; feed into deeper analysis)
ratio < 0.4   → LOST       (reset, escalate, or checkpoint)
```

A drop below `0.5` in a single turn is a constraint refresh signal — append the new turn's tokens to the anchor.

## Complexity

| Algorithm | Time | Space |
|-----------|------|-------|
| Wagner-Fischer DP | `O(m · n)` | `O(min(m, n))` |
| Hunt-Szymanski | `O((r + n) · log n)` | `O(r + n)` |

where `m = |A|`, `n = |C|`, `r` = number of matching pairs.

Hunt-Szymanski beats DP when `r ≪ m · n` (sparse matches). For agent task tokens (typically 10–100 tokens, mostly distinct), DP is simpler and the constant factor wins.

## Implementation pattern

```python
def lcs_length(a: list[str], b: list[str]) -> int:
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return 0
    # Space-optimized: keep two rows.
    prev = [0] * (n + 1)
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, prev
    return prev[n]

def preservation_ratio(a: list[str], c: list[str]) -> float:
    if not a and not c:
        return 1.0
    return 2 * lcs_length(a, c) / (len(a) + len(c))
```

For real-time hooks where `m, n ≤ 50`, the DP version runs in microseconds — Hunt-Szymanski is overkill. Switch when sequences exceed ~500 tokens.

## Tokenization choices

The ratio is sensitive to how you split into tokens.

| Tokenization | Pros | Cons |
|--------------|------|------|
| Whitespace split | Cheap, deterministic | "running" vs "ran" → 0 match |
| Lemmatized words | Robust to inflection | Requires NLP dep |
| Character n-grams (n=3–5) | Robust, language-agnostic | Sequences grow; costs more |
| Subword (BPE / sentencepiece) | Native to LLM tokenizers | Implementation-dependent |

For task-anchor preservation, lemmatized words tend to give the cleanest signal. For code-symbol preservation, exact tokenization with the language's lexer is best.

## Failure modes

- **Stop-word dominance** — common words (`the`, `and`) inflate the ratio. Filter before LCS or use TF-IDF weighting.
- **Order matters** — LCS preserves order. Two paragraphs with the same words rearranged score lower than expected. If order is irrelevant, use Jaccard instead.
- **Length asymmetry** — `|A| = 5`, `|C| = 500` with `LCS = 5` gives `ratio = 0.04`, which under-weights the fact that all of `A` survived. Use a side metric `|LCS| / |A|` (recall) when appropriate.
- **Tokens that are themselves long substrings** — if a "token" is a 200-char line, character-level edits inside it produce zero LCS where Levenshtein would show high similarity.

## When *not* to use

- Diff visualization for humans — Myers-diff is what `git diff` uses; it's optimized for readable hunks, not similarity score.
- Tree comparison — for ASTs or nested structures, use [`./tree-edit.md`](./tree-edit.md) (Zhang-Shasha).
- Set similarity (no order) — use Jaccard or cosine.

## Composition

LCS pairs with [`./tree-edit.md`](./tree-edit.md) (LCS for token sequences, tree-edit for structures) and feeds [`./drift-detection.md`](./drift-detection.md) (a sustained low ratio over consecutive turns is a drift pattern).
