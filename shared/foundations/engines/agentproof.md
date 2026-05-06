# Agentproof — Pre-Execution Static Verification

**Status: concept.** The paper (arxiv 2603.20356) describes the algorithm and its application; public release of the tool itself is not confirmed in the abstract. This engine file presents the primitive at the pseudocode level. Teams adopting this engine are implementing the checks independently, not integrating a released library. If a public artifact is confirmed after this file is updated, revise to `status: available` and add the artifact URL to References.

**Reference:** arxiv 2603.20356 (Agentproof) — "applies six structural checks with witness trace generation, and evaluates temporal safety policies via a DSL compiled to deterministic finite automata, both statically."

## Problem

Given an agent workflow graph — a set of roles (orchestrator, subagents, tools), delegation edges, and tool-invocation edges — verify statically that the workflow satisfies structural constraints and temporal safety policies *before* any subagent is spawned. The goal is a pre-execution verdict: PASS (the workflow satisfies all checks) or FAIL (one or more checks did not pass), accompanied by a witness trace identifying the exact violation. A FAIL verdict is a signal to revise the delegation structure before spending execution budget.

## Formula

### Structural checks

The checks operate on a directed graph `G = (N, E)` where nodes `N` are agent roles and edges `E` are delegation or tool-invocation relationships:

| Check | What it verifies | Witness on failure |
|-------|-----------------|-------------------|
| **1. Scope containment** | Every subagent's tool whitelist is a strict subset of the delegating agent's whitelist | The specific tool(s) that exceed the scope fence |
| **2. Acyclicity** | The delegation graph has no cycles (no subagent that can re-invoke its own ancestor) | The cycle as a path `n₁ → n₂ → … → n₁` |
| **3. Reachability** | Every declared subagent is reachable from the orchestrator | The set of unreachable nodes |
| **4. Destructive-op guard** | No subagent with a destructive tool (delete, reset, force-push) lacks an explicit confirmation step in its prompt | The subagent node and the tool(s) without confirmation |
| **5. Return-clause presence** | Every delegation edge carries a structured return clause (per [`../conduct/delegation.md`](../conduct/delegation.md) § Structured return clause) | The edges missing the clause |
| **6. Termination bound** | Every loop in the workflow (including retry loops) has a finite bound declared in the prompt | The loop and the missing bound |

Checks 1–4 are property checks on the graph. Checks 5–6 require inspecting the content of delegation prompts. In a Markdown-only workflow, the "graph" is the set of delegation prompts read as a document; the checks are applied as structured yes/no questions against that document before the first subagent is spawned.

### Temporal policy evaluation

A temporal safety policy is a constraint of the form "event A must not occur after event B in any execution trace." Examples: "a destructive tool call must not occur before an explicit confirmation"; "a second subagent spawn must not occur while the first subagent is still active."

The DSL compiles each policy into a deterministic finite automaton (DFA) where:

- States represent progress through the policy's constraint.
- Transitions are triggered by events (tool invocations, subagent spawns, confirmation signals).
- A final rejecting state is reached if and only if the policy is violated.

Static evaluation walks the workflow graph's possible execution paths through the DFA. If any path reaches a rejecting state, the policy is violated and a witness trace (the path to the rejecting state) is returned.

## Decision rule

A workflow PASSES if and only if all six structural checks pass AND every temporal safety policy holds along every reachable execution path of the workflow graph. Any failure emits a witness trace (the smallest counter-example: failing edge, failing policy + path prefix) and halts evaluation; the workflow does not run until the cause is corrected. PASS is necessary but not sufficient — Agentproof verifies the *graph*, not the runtime behaviour of the agents the graph describes.

## Reference implementation pattern

```
INPUTS:
  G = agent workflow graph (nodes: roles, edges: delegations + tool calls)
  P = list of temporal safety policies (constraint strings)

STRUCTURAL CHECKS:
  for each check in [scope_containment, acyclicity, reachability,
                     destructive_op_guard, return_clause_presence,
                     termination_bound]:
    result = apply_check(check, G)
    if result.failed:
      emit FAIL with witness = result.witness_trace
      halt

TEMPORAL POLICY EVALUATION:
  for each policy p in P:
    dfa = compile_to_dfa(p)
    for each execution_path in enumerate_paths(G):
      state = dfa.initial_state
      for event in execution_path:
        state = dfa.transition(state, event)
        if state == dfa.reject_state:
          emit FAIL with witness = execution_path[:current_index]
          halt

emit PASS
```

In a dependency-free adoption, `enumerate_paths(G)` is replaced by manually tracing the delegation prompt chain and confirming each policy holds. The six structural checks and each policy are tested as yes/no questions before the first subagent is spawned.

## Complexity

For a graph with `V` nodes and `E` edges: structural checks 1–3 run in `O(V + E)` (standard graph traversal). Checks 4–6 require prompt inspection — `O(V)` read passes in a Markdown-only workflow. Temporal policy DFA evaluation: `O(|P| · |paths| · max_path_length)`, which is exponential in the worst case for graphs with many branches. In practice, agent workflow graphs are shallow (depth ≤ 3, width ≤ 10), making evaluation tractable. Graphs with combinatorial path counts need bounded-depth enumeration (e.g., depth ≤ 3).

## Failure modes

- **Graph not written down.** The checks require an explicit representation of the workflow. A workflow that exists only as informal prose cannot be checked. The first cost of agentproof is making the delegation structure explicit.
- **Checks 5–6 require prompt content inspection.** In automated form, this requires a prompt parser; in Markdown-only form, it is a manual trace. The manual trace is the correct entry point for teams without tooling.
- **Temporal policies not defined.** Without a policy list, temporal evaluation is a no-op. The PASS verdict in that case is vacuously true.
- **Naming mismatch.** The six check names used here (scope containment, acyclicity, reachability, destructive-op guard, return-clause presence, termination bound) are derived from the paper's abstract-level description. The paper's full text may use different terminology. The checks as described are framework-consistent regardless of naming.
- **Static PASS does not guarantee runtime safety.** The verifier covers structural and temporal properties of the *defined* workflow. Dynamic failures (a subagent exceeding its scope due to prompt drift, a tool call that wasn't in the whitelist at definition time) are not caught by static analysis.

## When *not* to use

- **One-off single-subagent invocations.** For a simple parent-child delegation with no loops and no destructive tools, running through six structural checks is overkill. Apply to multi-subagent workflows or workflows containing destructive ops.
- **Workflows that change structure at runtime.** Static verification applies to the *defined* structure; a workflow that dynamically generates subagent graphs cannot be fully verified beforehand.

## Composition

Pairs with [`../conduct/delegation.md`](../conduct/delegation.md) (checks 1–5 directly operationalize delegation module contracts), [`../conduct/verification.md`](../conduct/verification.md) (destructive-op guard and confirmation-before-destructive policy map to the dry-run protocol), and [`./scc.md`](./scc.md) (acyclicity check 2 is a special case of SCC detection — Tarjan's algorithm finds cycles in `O(V + E)`).

| Check | Conduct module | Failure code prevented |
|-------|---------------|----------------------|
| Scope containment (1) | `conduct/delegation.md` § Scope fence | F07 (over-helpful substitution through tool over-grant) |
| Acyclicity (2) | `conduct/delegation.md` § Anti-patterns | F09 (parallel race, indirectly) |
| Destructive-op guard (4) | `conduct/verification.md` § Dry-run for destructive ops | F10 (destructive without confirmation) |
| Return-clause presence (5) | `conduct/delegation.md` § Structured return clause | Missing handoff structure |
| Termination bound (6) | `conduct/delegation.md` § Anti-patterns | F12 (degeneration loop) |
| Temporal: confirmation before destructive | `conduct/verification.md` | F10 (destructive without confirmation) |
| Temporal: no ancestor re-invoke | `conduct/hooks.md` § Subagent-loop guard | F09 (parallel race) |

## References

- **Primary:** arxiv 2603.20356 (Agentproof) — "applies six structural checks with witness trace generation, and evaluates temporal safety policies via a DSL compiled to deterministic finite automata, both statically." No secondary production-validation source identified. **Status: concept.**
- Note: the six structural check names used in this file are inferred from the paper's abstract. The paper's full text may use different terminology. If the full text is accessible, verify names against the paper's own table and update accordingly.
