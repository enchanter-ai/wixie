# F03 — Context Decay

## Signature

An instruction stated at the top of context is violated by the agent's actions or output near the bottom. The agent didn't *disagree* with the instruction — it forgot it. Common in long sessions, multi-turn loops, or after large tool-result dumps.

Common shapes:

- System prompt says "never push to main"; turn 12 the agent runs `git push origin main`.
- Top of context: "use `pnpm` not `npm`"; turn 8 the agent runs `npm install`.
- Conduct module says "advisory hooks must fail-open"; later in the session the agent writes a hook that exits non-zero.

## Counter

See [`../conduct/context.md`](../conduct/context.md) § Checkpoint protocol.

Specifically:

1. Move load-bearing rules to the **top-200 or bottom-200 token slot**.
2. Emit a **checkpoint** at ~50% context budget that re-states constraints.
3. Drop prior turns after checkpointing — they're noise now.

## Examples

1. Long debug session; original task was "don't touch the test fixtures." 30 turns later, agent edits a fixture to "make the test pass faster." **Counter:** Checkpoint at turn ~15 that re-lists constraints; the rule moves out of the recall valley.

2. Hook says "don't write to the user's home directory." After many tool calls, agent writes a config to `~/.myapp/`. **Counter:** Boundary rules go in the bottom-200 slot, where late-context recall is high.

3. User asked for "minimal diff"; ten turns into a refactor, agent has rewritten three unrelated functions. **Counter:** Re-read the task in a checkpoint; cut.

## Adjacent codes

- **F04 task drift** — drift is *expansion of scope*; decay is *forgetting an instruction*. They co-occur but the fix differs (drift = re-scope; decay = checkpoint).
- **F05 instruction attenuation** — attenuation is a *single* rule fading; decay is *general* instruction loss across many. Attenuation has a per-rule fix; decay needs the checkpoint.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Checkpoint and reset context |
| 3+ in one workflow | The session is too long for single-shot execution — split into smaller workflows |
