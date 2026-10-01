# Formatting — Structured Output Tactics

Audience: any agent shaping prompts or responses for an LLM. How to format so the output is parseable on the first try. Format follows model — this module is the *how*.

## Format by target model

| Target | Format | Why |
|--------|--------|-----|
| Claude (any tier) | XML tags | Claude was trained on XML-heavy structured inputs |
| GPT-4 / GPT-5 | Markdown + sandwich method | GPT attends best to instructions at both ends |
| o-series (o1, o3) | Stripped minimal | Long CoT prompts degrade; keep instructions tight |
| Gemini | Always few-shot | Recall without examples is significantly weaker |
| Image models | Natural language + style keywords | Prompt grammar is flat; nesting doesn't help |

Do not ship a format to the wrong family without translating it. Cross-family format mismatch is a measurable quality loss.

## XML tagging (Claude)

### Consistency

One name per concept across the whole prompt. If it's `<context>` once, it's `<context>` everywhere — never `<ctx>`, never `<background>`. Drift breaks retrieval.

### Hierarchy via nesting

Flat lists lose grouping cues:

```xml
<examples>
  <example><input>…</input><output>…</output></example>
  <example><input>…</input><output>…</output></example>
</examples>
```

Not:
```
Example 1: …
Example 2: …
```

### Common tags

| Tag | Purpose |
|-----|---------|
| `<role>` | Agent persona / identity |
| `<task>` | The ask, one sentence |
| `<context>` | Reference material — excerpts, not dumps |
| `<examples>` / `<example>` | Few-shot demonstrations |
| `<constraints>` | Hard rules: must, must-not |
| `<format>` | Output shape |
| `<edge_cases>` | Named tricky inputs and their handling |

These tags align with common quality assertions (has_role, has_task, has_format, has_constraints, has_edge_cases). Using them is not decoration; it's how downstream graders pass.

## Prefill

Start the assistant turn with a leading token to skip preamble.

| Prefill | Effect |
|---------|--------|
| `{` | Assistant continues as JSON — no "Sure, here is…" |
| `<analysis>` | Assistant opens inside the tag, no scaffolding |
| `Step 1:` | Forces structured enumeration from the start |

**Compatibility:** prefill is unsupported on some newer models (verify against your model capability registry). When unsupported, fall back to structured-outputs API or a system-prompt clause: *"Begin your response with `{`."*

## Stop sequences

Pair prefill with a stop sequence on the closing tag:

- Prefill `<analysis>` + stop on `</analysis>` → the model stops *at* the close, no tail tokens, no drift into concluding remarks.
- Prefill `{` + stop on `}` → only safe for flat JSON; nested objects need a different strategy.

Stop sequences are the single cheapest way to prevent mode collapse into a summary paragraph.

## GPT sandwich method

For GPT targets:

```
<instruction>          ← top
<few-shot examples>    ← middle, where GPT attends less
<instruction restated> ← bottom
```

The bottom restatement is not redundancy; it's the recall anchor. GPT's top-of-context attention is high; the bottom anchor catches what the middle attenuated.

## o-series minimal

o1 / o3 reason internally at length. External CoT prompting hurts them. Contract for o-series:

1. Strip few-shot examples unless essential.
2. Strip "think step by step" — it's already doing that.
3. State the task, constraints, output format. Stop.
4. No role-play preambles.

A 200-token o3 prompt often outperforms a 2000-token one.

## Gemini few-shot

Gemini's zero-shot recall is the weakest of the major families on many tasks. Always include at least 2 examples. Prefer 3-5 for anything stateful.

## Markdown hygiene

Numbered lists when order matters or you reference by index. Bullets otherwise. Never mix in one list. Bold reserves for per-section rule anchors and verbatim tags — bold on every noun devalues the signal.

## Anti-patterns

- **Inconsistent tag names.** `<context>` once, `<background>` later. Breaks retrieval.
- **XML in a GPT prompt without translating.** Format-model mismatch.
- **Chain-of-thought in an o-series prompt.** Double-reasoning, worse output.
- **No-prefill, then complaining about preamble.** The tool exists; use it.
- **Bold on everything.** Emphasis → noise.
- **Few-shot examples that don't match the real task shape.** Teaches the wrong pattern.
