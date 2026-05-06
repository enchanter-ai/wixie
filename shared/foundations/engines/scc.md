# Strongly-Connected Components — Tarjan

**Reference:** Tarjan R.E. (1972), "Depth-first search and linear graph algorithms," *SIAM Journal on Computing* 1(2):146–160.

## Problem

Given a directed graph `G = (V, E)`, find every maximal subset `S ⊆ V` such that for all `u, v ∈ S` there exists a directed path from `u` to `v`. Use cases:

- Detect circular module dependencies.
- Find prompt/skill chains where step A calls B which transitively calls A.
- Identify clusters of co-evolving files (rename together, change together).
- Detect deadlock-prone patterns in a workflow DAG.

## Formula

A strongly-connected component (SCC) is a maximal mutually-reachable subset. The graph contracted to its SCCs is a directed acyclic graph (the "condensation"); each SCC becomes a single super-node.

Tarjan's algorithm performs one depth-first traversal, maintaining for each node `v`:

```
index[v]   — DFS visit order
lowlink[v] — smallest index reachable from v's DFS subtree (including v itself)
```

When `lowlink[v] == index[v]`, every node currently above `v` on the DFS stack belongs to one SCC rooted at `v`.

## Complexity

```
T(V, E) = O(V + E)
```

Linear time, single pass. Space `O(V)` for the DFS stack and metadata.

This beats the alternative (Kosaraju's two-pass DFS, also `O(V + E)`) by a constant factor and uses a single graph traversal — useful when the graph is constructed lazily.

## Decision rule

| SCC size | Interpretation | Action |
|----------|----------------|--------|
| 1 (trivial SCC) | No cycle through this node | None |
| 2 (mutual recursion / two-node cycle) | Mild — common in healthy code (parser-AST pairs) | Log, monitor |
| 3–10 | Notable cycle — investigate ownership | Refactor candidate |
| > 10 | Architectural smell — modules over-coupled | Block merge or escalate |

The thresholds are heuristics; they belong in conduct, not in the engine.

## Implementation pattern

Iterative DFS to avoid Python's recursion limit on large graphs:

```python
def tarjan_scc(adj: dict[str, list[str]]) -> list[list[str]]:
    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    sccs: list[list[str]] = []

    def strongconnect(start: str) -> None:
        # Iterative DFS using a work-stack of (node, child_idx) pairs.
        work = [(start, 0)]
        call_path = []
        while work:
            v, ci = work[-1]
            if ci == 0:
                indices[v] = lowlinks[v] = index_counter[0]
                index_counter[0] += 1
                stack.append(v); on_stack.add(v)
            children = adj.get(v, [])
            if ci < len(children):
                work[-1] = (v, ci + 1)
                w = children[ci]
                if w not in indices:
                    work.append((w, 0))
                    call_path.append((v, w))
                elif w in on_stack:
                    lowlinks[v] = min(lowlinks[v], indices[w])
            else:
                if lowlinks[v] == indices[v]:
                    component = []
                    while True:
                        w = stack.pop(); on_stack.discard(w)
                        component.append(w)
                        if w == v:
                            break
                    sccs.append(component)
                work.pop()
                if call_path:
                    parent, child = call_path.pop()
                    lowlinks[parent] = min(lowlinks[parent], lowlinks[child])

    for v in adj:
        if v not in indices:
            strongconnect(v)
    return sccs
```

For graphs with ≤ 10k nodes, the recursive version is cleaner if `sys.setrecursionlimit` is raised appropriately. Iterative is safer for unknown-depth real-world graphs.

## Failure modes

- **Edges missing from `adj`** — nodes appearing only as targets but not as sources. Pre-pass: insert empty lists for all referenced nodes.
- **Self-loops** — `v → v` makes `{v}` a non-trivial SCC. Decide whether to treat that as a cycle or filter out.
- **Multiple edges** — Tarjan tolerates multi-graphs, but performance and reasoning are easier on simple graphs. Dedup edges before running.
- **Dynamic graphs** — Tarjan computes SCCs for a snapshot. If edges are added/removed mid-run, results are undefined. Re-run on each snapshot.
- **Confusing SCC with weakly-connected components.** WCC ignores edge direction (use union-find); SCC respects it. Pick the right one.

## When *not* to use

- Undirected graphs — use a simple BFS/DFS for connected components.
- Topological sort on a DAG — use Kahn's algorithm or a single DFS post-order.
- Graphs that are obviously DAGs (build dependencies after a known good build) — running SCC just confirms what you know; skip it unless the graph might have cycles.

## Composition

SCC analysis pairs with [`./tree-edit.md`](./tree-edit.md) (cycles often hide structural drift between modules) and with `../conduct/verification.md` (the SCC report is one signal in a multi-signal verdict on a refactor).
