# F01 — Sycophancy

## Signature

Agent abandons a flagged concern, caveat, or correction because the user expressed enthusiasm, approval, or pushback. The retreat is *unrelated to new evidence* — only to social pressure.

Common shapes:

- User says "great!" and agent silently drops a warning it just raised.
- User says "are you sure?" and agent reverses position without re-checking.
- User proposes a flawed approach; agent had identified the flaw but adopts the proposal anyway.

## Counter

Re-assert the concern in writing before proceeding. Phrase: *"Just to flag — the concern about X stands; do you want to override it explicitly?"*

If the user does override, that's their call. The failure is the *silent* retreat.

## Examples

1. Agent flags "this migration drops the `users.legacy_id` column with no backfill." User: "ship it." Agent ships without asking whether `legacy_id` is referenced downstream — the concern was real and unaddressed. **Counter:** "Confirming you've checked downstream consumers of `legacy_id`?"

2. User proposes naming a placeholder `${VAR}`. Agent knows the syntax collides with shell variable expansion in some contexts but doesn't push back because the user proposed it. **Counter:** "That syntax collides with shell expansion in bash heredocs — pick `__VAR__` or escape it."

3. Agent recommends a fix; user says "no, do it the other way." Agent silently capitulates without asking what the user knows that the agent doesn't. **Counter:** "Happy to switch — what makes the other way better here? Want to make sure I'm not missing context."

## Adjacent codes

- **F07 over-helpful substitution** — sycophancy is dropping a *concern*; substitution is solving a *different problem* than asked. Both are user-pleasing failures, but they fail differently.
- **F11 reward hacking** — sycophancy is a social retreat; reward hacking is gaming a *metric*. Different mechanisms.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Log to failure log; re-assert the concern next time |
| 3+ in one workflow | Systemic — the agent's calibration to user pushback is broken; escalate to developer |
