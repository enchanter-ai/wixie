# Tree Edit Distance — Zhang-Shasha

**Reference:** Zhang K. and Shasha D. (1989), "Simple fast algorithms for the editing distance between trees and related problems," *SIAM Journal on Computing* 18(6):1245–1262.

## Problem

Given two ordered labeled trees `T₁` and `T₂` (e.g., ASTs, JSON configs, nested HTML), compute the minimum cost of transforming `T₁` into `T₂` via insert / delete / relabel operations on individual nodes. Use cases:

- Quantify how much an AST changed across a refactor.
- Detect structural drift between two config snapshots.
- Score "shape similarity" of two nested structures (XML, JSON).

## Formula

For trees with postorder-numbered nodes, define `δ(i, j)` as the edit distance between the subtrees rooted at `i` and `j`. The recurrence:

```
δ(∅, ∅)     = 0
δ(T_i, ∅)   = δ(T_i without i's subtree's last leaf, ∅) + cost(delete leaf)
δ(∅, T_j)   = δ(∅, T_j without j's subtree's last leaf) + cost(insert leaf)
δ(T_i, T_j) = min(
    δ(T_i \ leaf_i, T_j) + cost(delete),
    δ(T_i, T_j \ leaf_j) + cost(insert),
    δ(T_i \ leaf_i, T_j \ leaf_j) + cost(relabel(label_i, label_j))
)
```

Zhang-Shasha runs the DP over **keyroots** (nodes whose parent has a left sibling), reducing redundant work. Default unit cost: 1 per insert / delete / relabel.

## Complexity

```
O(|T₁| · |T₂| · min(depth(T₁), leaves(T₁)) · min(depth(T₂), leaves(T₂)))
```

For balanced trees, this is `O(n² log² n)`. For trees with bounded depth (typical ASTs), it's near-quadratic.

For most agent-system uses (ASTs of single functions, configs with < 1000 nodes), a **simplified Wagner-Fischer DP over postorder sequences** is fast enough and trivially correct. Full Zhang-Shasha is the optimization when profiling shows DP cost dominates.

## Decision rule

Normalize the raw distance to a similarity:

```
similarity = 1 - (distance / max(|T₁|, |T₂|))
```

Bands:

| Similarity | Interpretation |
|------------|----------------|
| `≥ 0.95` | Trivial change (formatting, whitespace, single-token rename) |
| `0.80–0.95` | Localized edit (one function modified) |
| `0.50–0.80` | Significant restructure (multiple functions, signature changes) |
| `< 0.50` | Whole-file rewrite |

## Implementation pattern

Pseudocode for the simplified Wagner-Fischer reduction:

```python
def postorder(tree):
    seq = []
    def visit(node):
        for c in node.children:
            visit(c)
        seq.append(node.label)
    visit(tree)
    return seq

def tree_edit_distance(t1, t2) -> int:
    a, b = postorder(t1), postorder(t2)
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,        # delete
                dp[i][j - 1] + 1,        # insert
                dp[i - 1][j - 1] + cost  # relabel
            )
    return dp[m][n]
```

The simplified version treats trees as label sequences and ignores structure; it's correct as a *lower bound* and a useful "shape signature" but not a true tree-edit distance. Adopt full Zhang-Shasha when correctness matters (e.g., precise structural diff for compliance auditing).

## Failure modes

- **Confusing the simplified DP with true Zhang-Shasha.** The sequence-based DP misses structural relationships. Document which version you ship.
- **Default unit cost** — for some applications, relabeling a leaf node is cheaper than deleting an entire subtree. Use a cost function `c(label_a, label_b)` if you have domain reason.
- **Unordered children** — Zhang-Shasha assumes ordered trees. JSON object keys are unordered; sort children by canonical key before comparison or use an unordered-tree-edit variant.
- **Anonymous nodes** — comparing trees that include synthetic IDs (e.g., temp variables) inflates distance artificially. Strip or canonicalize before comparison.

## When *not* to use

- Sequence comparison — use [`./lcs-alignment.md`](./lcs-alignment.md) instead.
- Set comparison — use Jaccard / cosine.
- Diff visualization — use Myers-diff (what `git diff` uses) for human-readable hunks.
- Very large trees (>10k nodes) — quadratic costs dominate; consider locality-sensitive hashing of subtrees first.

## Composition

Tree edit distance pairs with [`./pattern-detection.md`](./pattern-detection.md) (find patterns in code; tree-edit measures how much they shift over time) and with [`./trust-scoring.md`](./trust-scoring.md) (a single high-distance edit is one observation in a Beta-Bernoulli trust posterior).
