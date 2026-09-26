## Anti-patterns

- **Claude-to-GPT copy.** Dropping a Claude-formatted prompt into a GPT folder. GPT needs sandwich method and different emphasis conventions — run `/translate-prompt`.
- **Scratch in prompts/.** Leaving HTML, diff, or iteration artifacts in the prompt folder. They belong in `state/`; only `report.pdf` ships.
- **Unverified translation.** Handing back a translated prompt without a score comparison. Translation without verification is not translation.
- **Autonomous image loops.** Iterating an image prompt without visual feedback. Text prompts converge on assertions; image prompts converge on developer ratings.
- **DEPLOY claim with stale metadata.** Verdict comes from the current convergence run's scores, not `metadata.json` from a prior session. Re-run self-eval if unsure.
