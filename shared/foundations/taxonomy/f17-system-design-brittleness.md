# F17 — System-design brittleness

## Signature

An agent network fails on a single-node drop — one subagent becoming unavailable, one tool timing out, one API returning an error — because no graceful degradation path was designed in. The failure propagates silently: the orchestrator receives no result from the dropped node and either hangs waiting or surfaces an opaque error. The brittleness is not in any single agent's behavior; it is in the architecture's assumption that all nodes will always be available.

Common shapes:

- A fetcher subagent hangs on a paywall with no timeout clause; the orchestrator waits indefinitely.
- A validator agent becomes rate-limited mid-pipeline; the orchestrator surfaces a generic failure with no indication of which node stalled.
- A tool dependency (a database, an API, a file path) disappears at runtime; the pipeline has no partial-return path and loses all completed work.

## Counter

Architecture review before deployment requires a named fallback for each agent role in the network. The fallback is either a lower-capability alternative (a Sonnet agent substituting for an unavailable Opus orchestrator on a bounded task) or a graceful partial-return (the pipeline continues with the available nodes' outputs and flags the gap).

Subagent prompts include a `timeout_behavior` clause: what to return if no result is available within N seconds. No node in the graph should be a silent dependency whose absence causes the whole pipeline to stall.

## Examples

1. A research pipeline spawns five parallel Haiku fetcher subagents to retrieve sources. One fetcher hits a paywall and hangs rather than returning `{error: "unfetchable"}` — its prompt did not include a timeout clause. The orchestrator waits indefinitely for all five returns. After the session timeout, the pipeline surfaces a generic failure with no indication of which node stalled or why. The four successful fetches are lost. **Counter:** each fetcher has a 30-second timeout clause; on timeout, returns `{url, error: "timeout"}`. The orchestrator collects partial results and flags the gap.

2. A convergence loop delegates scoring to a Haiku validator. The validator's API endpoint is rate-limited on iteration 7 of 10. The orchestrator has no fallback scorer — it simply errors and loses iterations 1–6. **Counter:** architect a fallback (a Sonnet scorer running from the same prompt without the API gate); the orchestrator retries on the fallback when the primary returns a rate-limit signal.

3. A multi-agent pipeline writes intermediate state to a shared `state/session.json`. Subagent B reads from it, but Subagent A hasn't written it yet when B starts. B returns a cryptic "file not found" error and the orchestrator surfaces it as a top-level failure. **Counter:** subagent start conditions are explicit — B's prompt specifies "do not begin until `state/session.json` exists and has key `completed: true`"; the orchestrator checks the precondition before dispatch.

## Adjacent codes

- **F15 Inter-agent misalignment** — a conflict-resolution mechanism is itself a node; its absence is an F17 brittleness. F17 is the architectural enabling condition; F15 is the coordination-level symptom.
- **F09 Parallel race** — parallel dispatch amplifies brittleness: a race between nodes that share state compounds F17 when one node drops mid-write.
- **F08 Tool mis-invocation** — tool mis-invocation can trigger cascading F17 when the mis-invoked tool is a dependency for downstream nodes.

**Source:** MAST: A Multi-Agent System Testing Framework (arxiv 2503.13657) — system-design cluster; identifies structural brittleness as a distinct failure category from inter-agent and task-verification failures. https://arxiv.org/abs/2503.13657

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Log the stalled node; add a timeout clause and a fallback to that node's prompt |
| 3+ in one workflow | The pipeline's architecture has no graceful degradation layer — redesign with explicit timeout behavior and partial-return paths before continuing |
