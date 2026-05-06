# F15 — Inter-agent misalignment

## Signature

Two or more subagents in the same pipeline pursue contradictory subgoals without a reconciliation step. The failure is silent: each subagent reports success on its own subtask, but their outputs are mutually incompatible. The parent agent or orchestrator receives well-formed individual returns and declares the overall task done, without detecting that the subgoals conflict.

Common shapes:

- Contradictory writes to a shared artifact (two subagents produce conflicting versions of the same file).
- Divergent scores on a metric that should converge (one subagent optimizes for brevity, another for completeness).
- Incompatible state assumptions when outputs are composed (subagent A assumes a service is running; subagent B has shut it down).

## Counter

The structured return clause of every subagent prompt must include a `conflicts_with` field alongside the primary output. The parent reconciles before acting: if any subagent's `conflicts_with` is non-empty, hold and surface the conflict rather than composing outputs.

Parallel subagents that touch shared state should be partitioned by path (see `conduct/delegation.md` § Parallel vs. serial) or run serially with explicit handoff.

## Examples

1. An orchestrator spawns two parallel subagents: Subagent A is tasked with "minimize token cost for all downstream calls" and Subagent B is tasked with "maximize detail and completeness of every response." Both complete and return success. The orchestrator merges their recommendations into a single updated configuration. The merged configuration applies aggressive token caps (from A) alongside mandatory long-form templates (from B), causing every downstream call to exceed the cap and fail. Neither subagent detected the conflict; the orchestrator never checked. **Counter:** structured return includes `conflicts_with: ["token-budget constraints conflict with long-form templates"]`; orchestrator holds and surfaces before composing.

2. Two parallel refiner agents each propose edits to the same `prompt.xml` — one tightening the `<constraints>` block, one expanding it with new edge cases. Both return success. The orchestrator applies both diffs in sequence; the file ends up with contradictory constraint clauses. **Counter:** only one agent may hold write access to a given path per parallel batch; partition or serialize.

3. A research pipeline assigns "find cost-minimizing provider" to Subagent A and "find highest-quality provider" to Subagent B. The orchestrator concatenates their recommendations into a single config block. The config routes cost-sensitive calls to provider A and quality-sensitive calls to provider B — a reasonable decomposition — but the two providers have overlapping rate-limit domains that the orchestrator never checked, because neither subagent was tasked with cross-checking the other's choice. **Counter:** a reconciliation subagent (or the orchestrator) runs a compatibility check before accepting composed outputs.

## Adjacent codes

- **F09 Parallel race** — parallel race is overlapping *writes* to the same file during concurrent dispatch; F15 is the goal-level analogue where outputs are logically incompatible rather than physically overwritten. F15 is upstream of F09: misaligned subgoals often manifest as races when both subagents act on shared state.
- **F12 Degeneration loop** — can emerge as a downstream symptom of undetected F15 when the orchestrator keeps retrying composed outputs that will always conflict.
- **F17 System-design brittleness** — system-level design failures enable F15 by providing no conflict-resolution mechanism in the architecture; F17 is the architectural root cause, F15 the observable coordination symptom.

**Source:** MAST: A Multi-Agent System Testing Framework (arxiv 2503.13657) — inter-agent misalignment cluster; one of 14 multi-agent failure modes identified across three clusters. https://arxiv.org/abs/2503.13657

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Log to failure log; add a `conflicts_with` field to both subagent prompts and rerun |
| 3+ in one workflow | The orchestrator's composition step has no reconciliation layer — redesign the pipeline before continuing |
