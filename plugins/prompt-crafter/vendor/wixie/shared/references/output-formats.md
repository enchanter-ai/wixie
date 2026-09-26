# Output Formats Reference

Use this reference during Phase 3B to select the optimal output structure for the task type.

---

## Decision Table

| Task Type | Optimal Output Structure | Prompt Format Instructions | Why |
|---|---|---|---|
| Research / Analysis | Markdown with headers, bold key findings, narrative prose | "Structure your response with ## headers for each section. Bold key findings. End with a summary paragraph." | Skimmable; supports synthesis across multiple sources |
| Code Generation | Fenced code blocks with language tags, inline comments | "Provide complete, runnable code in \`\`\`language blocks. Include inline comments for non-obvious logic. No pseudocode unless explicitly requested." | Copy-pasteable; enables syntax highlighting; immediately testable |
| Image Generation | Comma-separated descriptors with parameter flags | Varies by model — see model-profiles.md for Midjourney/DALL-E/SD specifics | Each image model has incompatible syntax requirements |
| Data Extraction | JSON with typed fields matching a provided or generated schema | "Output valid JSON matching this schema: {schema}. No markdown wrapping. No explanation outside the JSON block." | Machine-parseable; validation-ready; pipeline-compatible |
| Decision Making | Pros/cons comparison table + recommendation paragraph | "Present options in a comparison table with columns: Option, Pros, Cons, Risk Level. End with a clear recommendation and your confidence level." | Structured comparison enables quick scanning; clear verdict reduces ambiguity |
| Creative Writing | Minimal structural constraints, tone/voice guidance only | "Write in [tone]. Target [audience]. [length constraint]. Do not break the narrative with meta-commentary or author notes." | Over-constraining creative output kills quality and voice authenticity |
| Agent / Tool-Use | ReAct format: Thought -> Action -> Observation loops | "Follow this loop: Think about what to do next -> Call the appropriate tool -> Observe the result -> Repeat until the task is complete. If a tool call fails, diagnose the error before retrying." | Matches agentic execution pattern; enables step-by-step observability |
| Conversational / Chatbot | System prompt with persona + guardrails, short turns | "You are [persona]. Maintain character across all turns. [guardrails]. Keep responses under [N] sentences unless the user asks you to elaborate." | Character consistency across turns; prevents persona drift |
| CLI Tool | Structured flags, usage examples, error messages | "Include: usage syntax, required and optional flags with descriptions, 2-3 usage examples covering common cases, and common error messages with fixes." | Developer-friendly reference format; immediately usable |
| API Integration | Endpoint spec, request/response examples, auth notes | "Document: endpoint URL, HTTP method, required headers, request body schema, response schema with field descriptions, error codes, and a working curl example." | Integration-ready documentation; reduces back-and-forth |

---

## Format Selection Rules

### Rule 1: Primary Deliverable Wins

If the task crosses multiple types (e.g., "analyze this data and generate code to process it"), use the format of the primary deliverable:

- If analysis is the goal with code as supporting evidence: use Research/Analysis format with embedded code blocks.
- If code is the goal with analysis as context: use Code Generation format with explanatory comments.
- If both are equally important: use Research/Analysis as the outer structure with Code Generation sections inside.

### Rule 2: User Format Overrides

If the user specifies a format explicitly, always honor it, even if it is suboptimal for the task type. Note the trade-off in the Creation Report under Format Decisions:

> "The user requested [format]. This is non-standard for [task type] because [reason], but honoring the user's preference."

### Rule 3: Ambiguous Task Default

If the task type is unclear and you cannot determine the optimal format, default to Markdown with headers. It is the most versatile format and degrades gracefully across all use cases.

### Rule 4: Machine vs. Human Consumption

Determine who will consume the output:

| Consumer | Preferred Formats | Avoid |
|---|---|---|
| Human reading | Markdown, prose, tables | Raw JSON, XML dumps |
| Code/pipeline | JSON, XML, CSV | Markdown with prose, narrative |
| Both (hybrid) | JSON with a `summary` field, or structured Markdown | Unstructured prose |

---

## Output Length Guidance

| Task Complexity | Suggested Length Instruction |
|---|---|
| Simple (single-step) | "Keep your response concise — under 200 words." |
| Moderate (2-4 steps) | "Be thorough but focused. Target 300-500 words." |
| Complex (5+ steps) | "Be comprehensive. Use headers to organize sections. No artificial length limit." |
| Production system prompt | "Every token costs latency and money. Be as concise as possible while remaining unambiguous." |

---

## Format Templates

### JSON Extraction Template

When the task is data extraction, include a schema block in the prompt:

```
Extract the following fields from the input and return valid JSON:

{
  "field_name": "string — description of what this field contains",
  "numeric_field": 0,
  "boolean_field": false,
  "array_field": ["item1", "item2"],
  "nested": {
    "sub_field": "string"
  }
}

Rules:
- Use null for missing or undetectable fields.
- Do not add fields not listed in the schema.
- Do not wrap the JSON in markdown code fences.
```

### ReAct Loop Template

For agent/tool-use prompts, structure the reasoning format:

```
For each step, use this format:

Thought: [What do I need to do next? What information do I have/need?]
Action: [tool_name(parameter1="value1", parameter2="value2")]
Observation: [Result from the tool call]
... (repeat Thought/Action/Observation as needed)
Final Answer: [The complete response to the user's request]

Rules:
- Always think before acting.
- If an action fails, diagnose the error in your next Thought.
- Do not guess tool parameters — check documentation first.
- Stop when the task is complete or when you cannot make further progress.
```

### Comparison Table Template

For decision-making prompts:

```
Present your analysis in this format:

| Criterion | Option A | Option B | Option C |
|-----------|----------|----------|----------|
| [criterion 1] | [assessment] | [assessment] | [assessment] |
| [criterion 2] | [assessment] | [assessment] | [assessment] |

**Recommendation:** [Your recommendation with reasoning]
**Confidence:** [High/Medium/Low] — [Why this confidence level]
```

---

## Format Anti-Patterns

| Anti-Pattern | Problem | Fix |
|---|---|---|
| "Be detailed and concise" | Contradictory instructions confuse the model | Choose one. If detail matters, say "Be thorough." If brevity matters, say "Be concise — under N words." |
| No output format specified | Model guesses format, often inconsistently | Always specify format, even if just "Respond in plain prose." |
| "Return JSON" without schema | Model invents field names inconsistently across runs | Provide the exact schema with field names, types, and descriptions |
| Mixing format styles | Asking for JSON inside markdown inside XML | Use one format layer. If you need JSON output, say "Output raw JSON only — no markdown wrapping." |
| Over-constraining creative tasks | Detailed structural requirements kill voice and authenticity | For creative tasks, constrain tone and audience, not structure |
| Unspecified list format | Model alternates between bullets, numbers, and prose lists | Specify: "Use numbered steps" or "Use bullet points" |
| No delimiter for multi-part output | Model blends sections together | Use explicit section markers: headers, XML tags, or horizontal rules |

---

*End of output formats reference. Return to the creation workflow after selecting the output format.*
