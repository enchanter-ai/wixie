# Pattern Detection — Aho-Corasick

**Reference:** Aho A.V. and Corasick M.J. (1975), "Efficient string matching: an aid to bibliographic search," *Communications of the ACM* 18(6):333–340.

## Problem

Scan a text `T` for *any of* a fixed set of patterns `P = {p₁, ..., pₖ}` in a single pass. Examples:

- Secret-scanner across hundreds of regex prefixes (AWS keys, GitHub tokens, JWT prefixes).
- Forbidden-substring lint across a code blob.
- Profanity / banned-term filter on user input.

A naive `for p in P: text.find(p)` is `O(|T| · |P|)` and re-scans the text once per pattern.

## Formula

Build a trie from all patterns; add **failure links** via BFS so that on a mismatch at node `v`, scanning continues at the node representing the longest proper suffix of the path-to-`v` that is also a prefix of some pattern. Add **output links** so that whenever node `v` is visited, every pattern ending at `v` *or* at any node reachable via output links is reported.

```
T(n, m) = O(|T| + |P| + z)
```

where `n = |T|`, `m = Σ|pᵢ|` is total pattern length, and `z` is the number of matches.

## Decision rule

Return all `(position, pattern_id)` pairs where the automaton traversal of `T` lands on a node whose output set is non-empty. Decisions on what to *do* with matches (alert, redact, block) belong in conduct, not the engine.

## Complexity

| Phase | Time | Space |
|-------|------|-------|
| Construction | `O(|P|)` | `O(|P|)` |
| Scan | `O(|T| + z)` | `O(|P|)` |

Linear in input size, regardless of how many patterns. Adding a 201st pattern doesn't slow scanning per character.

## Implementation pattern

```pseudocode
class AhoCorasick:
    build(patterns):
        root = Node()
        for p in patterns:
            insert p into trie rooted at root
        bfs from root:
            for child c of node v:
                c.fail = longest proper suffix of path-to-c that is in the trie
                c.output = c.matched_patterns + c.fail.output
        return root

    scan(text, root):
        node = root
        for i, ch in enumerate(text):
            while node != root and ch not in node.children:
                node = node.fail
            if ch in node.children:
                node = node.children[ch]
            for pat in node.output:
                yield (i - len(pat) + 1, pat)
```

For real-time hooks where pattern set is small (~50 patterns) and rebuild is cheap, a **regex alternation** (`(p1|p2|...|pk)`) compiled by a modern regex engine is often within 2× of Aho-Corasick and far simpler. Switch to a hand-rolled automaton when pattern count crosses ~200 or scan throughput becomes a bottleneck.

## Failure modes

- **Patterns sharing common suffixes** — output links must be followed transitively, or you'll miss matches.
- **Overlapping matches** — Aho-Corasick reports them all by default; if you want only the leftmost-longest, post-process.
- **Patterns containing each other** (`abc` and `bc`) — both must be reported when their endpoints land in `T`. Forgetting transitive output is the #1 implementation bug.
- **Unicode** — build over codepoints, not bytes, or `\xc3\xa9` (`é`) splits across nodes and matches phantom prefixes.

## When *not* to use

- Single pattern → just use `text.find(p)` or a regex.
- Patterns that aren't fixed strings (regexes with quantifiers, lookahead) — use a regex engine; AC handles literal patterns only.
- High-entropy detection without a pattern list — use [`./entropy-analysis.md`](./entropy-analysis.md) instead.
