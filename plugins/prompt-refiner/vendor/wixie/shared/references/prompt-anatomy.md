# Prompt Anatomy

Mandatory component checklist and fallback patterns for every generated prompt. Read this file during Phase 3B to ensure no critical component is missing.

---

## Component Checklist

Every generated prompt must include these components. Check each off before delivery. If the user opted out of a component in Phase 2, skip it — but note the omission in the Creation Report.

| # | Component | Required For | Purpose | Skip When |
|---|-----------|-------------|---------|-----------|
| 1 | **Role / Persona** | All except image-gen | Establishes expertise level, tone, and perspective | Image-gen prompts (no persona) |
| 2 | **Task Description** | All | What the model should produce — the core instruction | Never skip |
| 3 | **Constraints** | All | Boundaries, rules, what NOT to do | User explicitly says "no constraints" |
| 4 | **Output Format** | All except creative-writing | Shape of the response (JSON, Markdown, sections, etc.) | Creative writing where over-constraining hurts |
| 5 | **Fallback Instructions** | All except image-gen | What to do when input is ambiguous, data is missing, or task cannot be completed | Image-gen (single-shot, no error path) |
| 6 | **Expected Output** | Complex tasks, data extraction, coding | A sample or description of what correct output looks like | Simple tasks where format is obvious |
| 7 | **Task Roadmap** | Moderate and complex tasks | Numbered steps or phases the model should follow | Simple single-step tasks |
| 8 | **Success Criteria** | All except creative-writing, image-gen | How to know the output is done and correct | Tasks with subjective quality |

### How to apply each component

**Role / Persona:**
- Be specific: "Senior backend engineer with 10 years of Go experience" beats "helpful assistant"
- Match the domain: financial analyst for stock research, security researcher for pen testing
- For Claude: place in `<role>` tags or system prompt. For GPT: use `# Role` header

**Task Description:**
- Lead with the deliverable: "Produce a report", "Generate a function", "Extract fields"
- State scope explicitly: what's in, what's out
- For complex tasks: summarize the task in 1-2 sentences, then detail in the roadmap

**Constraints:**
- Format as a bulleted list for scannability
- Include both positive constraints ("always use TypeScript") and negative ("do not use deprecated APIs")
- Be specific: "under 500 words" beats "be concise"

**Output Format:**
- For structured data: provide the exact schema with field names, types, and descriptions
- For prose: specify section headers, tone, and length targets
- For code: specify language, style, whether to include comments/tests

**Fallback Instructions:**
- See the Fallback Patterns section below for domain-specific templates
- Always address: missing input, ambiguous requirements, conflicting instructions, knowledge gaps

**Expected Output:**
- Even a partial example anchors the model's format, depth, and style
- For data extraction: show one complete input→output pair
- For analysis: show a sample section with the expected depth and format
- For code: show the function signature and a usage example

**Task Roadmap:**
- Number the steps: "Step 1: Gather data. Step 2: Analyze. Step 3: Synthesize."
- For each step: state the input, action, and expected output
- Include decision points: "If X, proceed to Step 3a. Otherwise, Step 3b."
- For very complex tasks: group steps into phases

**Success Criteria:**
- Define "done": "The report is complete when all 8 sections are filled"
- Define "correct": "All JSON must validate against the provided schema"
- Define "quality floor": "Each section should be at least 200 words"

---

## Fallback Patterns by Domain

Use these templates when generating fallback instructions. Adapt the wording to fit the prompt's tone and the target model's style.

### Coding

```
- If a required dependency is unavailable or deprecated, suggest the closest alternative and explain the difference.
- If the specification is ambiguous, implement the most common interpretation and add a comment noting the assumption.
- If you cannot implement a feature without breaking an existing constraint, flag the conflict and propose two options.
- If a test case is unclear, write the test for the most likely intended behavior and note what you assumed.
```

### Data Extraction

```
- If a field is missing from the input, set it to null. Do not infer or fabricate values.
- If the input format is unrecognized, return an error object with the format: {"error": "unrecognized format", "input_sample": "first 100 chars"}.
- If multiple values match a single field, return all matches as an array and flag for human review.
- If the input contains conflicting data, extract both values and add a "conflicts" field noting the discrepancy.
```

### Analysis / Research

```
- If data is insufficient to support a conclusion, state "Insufficient data" and describe what additional information would be needed.
- If sources conflict, present both perspectives with citations and note the disagreement.
- If your knowledge may be outdated, flag the claim with "Verify as of [current date]" and suggest where to check.
- If a question falls outside your expertise, acknowledge the boundary rather than speculating.
```

### Agent / Tool-Use

```
- If a tool call fails, diagnose the error type (auth, parameter, timeout, not found) before retrying.
- If a tool returns unexpected output, log the raw response and attempt to parse it. If parsing fails, report the issue and move to the next step.
- If you cannot complete the task with available tools, stop and report what's missing rather than improvising.
- If a multi-step plan hits a dead end, backtrack to the last successful step and try an alternative approach.
```

### Creative Writing

```
- If the style reference is unclear, default to a neutral, professional tone and ask for clarification.
- If the requested length is unrealistic for the topic (e.g., "explain quantum physics in 50 words"), do your best and note the constraint.
- If the prompt contains contradictory tone requirements, prioritize the one mentioned last.
```

### Decision Making

```
- If you lack data to evaluate an option on a criterion, mark it as "Data unavailable" rather than guessing.
- If all options score similarly, say so explicitly rather than forcing a winner.
- If a critical criterion is missing from the evaluation framework, add it and explain why.
- If the decision depends on information you don't have, list the missing inputs and how they would change the recommendation.
```

### Conversational / Chatbot

```
- If the user's message is ambiguous, ask a clarifying question rather than guessing intent.
- If the user asks something outside your defined scope, acknowledge the boundary and redirect.
- If the conversation contradicts earlier context, note the inconsistency and ask which version is correct.
- If the user becomes frustrated, acknowledge their frustration before attempting to help.
```

### Image Generation

Fallback instructions are generally not applicable for image-gen prompts (single-shot, no error path). Instead, use:

```
- Do not include: [explicit exclusion list]
- If the concept is ambiguous, favor [preferred interpretation] over [alternative].
```

---

## Expected Output Templates

Use these as starting points when generating the "expected output" component.

### For Data Extraction
```
Expected output for a single invoice:
{
  "invoice_number": "INV-2024-0042",
  "vendor": "Acme Corp",
  "date": "2024-03-15",
  "line_items": [
    {"description": "Widget A", "quantity": 10, "unit_price": 25.00}
  ],
  "total": 250.00,
  "currency": "USD"
}
```

### For Analysis
```
Expected output structure:
## Executive Summary (2-3 sentences)
## Key Findings (3-5 bullet points, each with supporting evidence)
## Detailed Analysis (organized by theme, 200-400 words per theme)
## Recommendations (numbered, actionable, with confidence levels)
## Appendix (data sources, methodology notes)
```

### For Code
```
Expected output:
- A single function with type annotations
- Docstring explaining parameters and return value
- 2-3 unit tests covering normal case, edge case, and error case
- No external dependencies beyond stdlib
```

### For Decision Making
```
Expected output:
| Criterion | Option A | Option B | Option C |
| [criteria rows with assessments] |

Recommendation: [clear choice with reasoning]
Confidence: [High/Medium/Low with explanation]
```

---

## Task Roadmap Patterns

### Linear Roadmap (most tasks)
```
Step 1: [Action] → produces [output]
Step 2: [Action using Step 1 output] → produces [output]
Step 3: [Final synthesis] → produces [deliverable]
```

### Branching Roadmap (decision-dependent tasks)
```
Step 1: [Assessment] → determines path
  If [condition A]: proceed to Step 2a
  If [condition B]: proceed to Step 2b
Step 2a: [Path A action]
Step 2b: [Path B action]
Step 3: [Convergence — both paths lead here]
```

### Iterative Roadmap (refinement tasks)
```
Step 1: [Initial draft/attempt]
Step 2: [Self-review against criteria]
Step 3: [Refine based on review]
Step 4: [Final check — if criteria met, deliver; otherwise repeat Step 2-3]
```

### Parallel Roadmap (multi-faceted analysis)
```
Phase 1 (parallel): Analyze [aspect A], [aspect B], [aspect C] independently
Phase 2: Synthesize findings across all aspects
Phase 3: Generate recommendations based on synthesis
```

---

*End of prompt anatomy reference. Return to the creation workflow after applying components.*
