# F05 — Instruction Attenuation

## Signature

A specific rule is stated *once*, the agent obeys it *the first time*, then forgets it for subsequent applicable cases. Distinguished from F03 context decay by being *single-rule* — only this rule fades, the rest of the context is still respected.

Common shapes:

- "Always use `pnpm` not `npm`." Agent uses `pnpm install`. Three turns later, runs `npm install` for a different package.
- "Quote field must be verbatim." Agent obeys for the first finding; second finding has a paraphrased quote.
- "Always run the linter after edits." First edit: linter runs. Subsequent edits: skipped.

## Counter

Move the rule to a recall-friendly slot — top-200 or bottom-200 tokens (see [`../conduct/context.md`](../conduct/context.md)). For very high-stakes single rules, repeat the rule both at top *and* bottom. Repetition is not redundancy — it's the recall anchor.

For programmable rules (lint after edit, run tests on commit), use a **hook** (see [`../conduct/hooks.md`](../conduct/hooks.md)) so the runtime enforces it, not the agent's memory.

## Examples

1. Project rule: "branch names use kebab-case." First branch: `fix-pagination` ✓. Second branch: `fixSchemaValidation` ✗. **Counter:** Move the rule to the bottom of the system prompt; or wrap branch creation in a hook that validates.

2. Skill description says "always cite source URL with date." First fact: cited correctly. Subsequent facts: dates dropped. **Counter:** Repeat the requirement in the output-shape spec at the bottom of the prompt.

3. "After every Bash command, summarize what changed in one sentence." First command: summary present. Tenth command: summary absent. **Counter:** Use a PostToolUse hook to inject the requirement, instead of relying on memory.

## Adjacent codes

- **F03 context decay** — decay affects *general* instructions across the board; attenuation affects *specific* rules. Decay is solved by checkpointing; attenuation is solved by repositioning the rule.
- **F01 sycophancy** — sycophancy is dropping a rule under social pressure; attenuation is dropping it from memory drift.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Reposition the rule (top-200 / bottom-200) and reissue |
| 3+ in one workflow | The rule belongs in a hook or programmatic guard, not in prose |
