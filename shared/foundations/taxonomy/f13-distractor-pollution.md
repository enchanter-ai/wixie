# F13 — Distractor Pollution

## Signature

Long, partly-relevant context bends the agent's output toward the irrelevant material. Symptoms include: themes from a tangential paragraph leaking into the response, citations of context not actually applicable to the task, output length / register matching the noise, not the task.

Common shapes:

- Fetched a doc with relevant section + lengthy unrelated appendix; output reflects appendix tone.
- Pasted whole log file when only 20 lines were relevant; agent's diagnosis weighted by frequency in the log, not relevance.
- Prompt includes both "current task" and "history of prior tasks" — agent answers a *prior* task.

## Counter

See [`../conduct/context.md`](../conduct/context.md) § Smallest-set rule.

Apply the topic filter **before extraction**, not after:

1. Excerpt only the section relevant to the question. A 400-token snippet beats a 4000-token full attachment, every time.
2. Filter logs before pasting — grep for the error, show 20 lines of surrounding context, not 10k.
3. If a fetched page has an off-topic appendix, **strip it** before reasoning over the page.

## Examples

1. Agent fetches a docs page; the "Migration guide" section is what's relevant; agent reasons over the entire 8000-token page; output cites the unrelated "Pricing" section. **Counter:** Fetcher returns only the matching section, not the whole page.

2. User pastes 5000-line stack trace; agent's diagnosis mentions a third-party library appearing 200 times in the trace but only because of normal logging, not the actual error. **Counter:** Filter the trace to the unique frames around the error.

3. System prompt includes 10 example outputs from prior unrelated tasks. Agent's new output mimics the *style* of the most recent example, even though the new task has different requirements. **Counter:** Remove old examples; include only those whose shape matches the current task.

## Adjacent codes

- **F03 context decay** — decay is *forgetting* an instruction; distractor pollution is *over-attending* to noise. The fix differs (decay = checkpoint; pollution = filter input).
- **F05 instruction attenuation** — attenuation fades a single rule; pollution distorts the *response*, not the rules.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Tighten the input; redo |
| 3+ in one workflow | The pipeline is feeding too much noise — add a pre-extraction filter step (or move it to a low-tier subagent that returns only relevant slices) |
