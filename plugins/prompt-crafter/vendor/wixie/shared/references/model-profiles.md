# Model Profiles

> **Single source of truth for model specs: [models-registry.json](../models-registry.json).** This file contains detailed prompting guidance per model, but context windows and capabilities come from the registry. If a spec here conflicts with the registry, the registry wins. If the registry's `last_updated` date is more than 3 months old, verify critical specs via web search before relying on them.

Formatting and behavioral specifications for target models. Read this file during Phase 3B to adapt the generated prompt to the target model's requirements.

Select the profile matching the user's target model. If the exact model is not listed, use the closest family match.

---

## 1. Claude 4.x (Opus / Sonnet / Haiku)

### Format

Use XML tags for structure. Preferred tags: `<instructions>`, `<context>`, `<examples>`, `<example>`, `<input>`, `<output>`, `<constraints>`, `<format>`.

Nest tags logically. Claude responds well to hierarchical XML structure and uses it to parse prompt sections reliably.

```xml
<instructions>
  Your primary task description here.
</instructions>

<context>
  Background information the model needs.
</context>

<examples>
  <example>
    <input>Example input</input>
    <output>Example output</output>
  </example>
</examples>
```

### System prompt

Full support. Place the most critical behavioral instructions in the system prompt. Use the user turn for task-specific input and context. The system prompt persists across the conversation, so put identity, tone, and global constraints there.

### Reasoning

Use "think thoroughly" combined with the `effort` parameter to control reasoning depth. Do NOT use "think step by step" -- this phrase is associated with older prompting patterns and does not improve Claude 4.x performance.

- **Opus**: Extended thinking enabled by default. Most capable reasoning of the family. Excels at multi-step analysis, complex code generation, and nuanced writing. Use for tasks where depth matters more than speed.
- **Sonnet**: Best balance of speed and quality. Explicit chain-of-thought prompting helps on harder tasks. Add "think thoroughly before responding" for complex reasoning. Strong default for most use cases.
- **Haiku**: Fastest model in the family. Less capable on complex reasoning chains. Keep prompts simple and direct. Avoid deeply nested instructions. Best for classification, extraction, and straightforward generation.

### Few-shot

Provide 3-5 diverse examples wrapped in `<example>` tags. Include edge cases and boundary conditions. Claude uses examples to calibrate output format, length, and style more than to learn the task itself.

### Known gotchas

- Aggressive language ("CRITICAL: You MUST", "NEVER under any circumstances", "ABSOLUTELY REQUIRED") causes overtriggering on Claude 4.6 models. The model over-indexes on these phrases and may refuse valid requests or add excessive caveats. Use calm, direct instructions instead.
- Claude 4.x is more concise by default than the 3.x series. If you need verbose output, explicitly request it: "Provide a detailed, thorough response" or "Aim for at least N paragraphs."
- Overtriggers on tools when tools are available. Be specific about when NOT to use tools, not just when to use them. Add explicit instructions like "Only use the search tool when the user asks a factual question you cannot answer from context."
- Responds well to role assignment in the system prompt ("You are a senior backend engineer reviewing pull requests").
- Prefilling the assistant turn can steer output format reliably.

### Token budget

- Opus 4.6: 1M context window
- Sonnet 4.6: 200K context window (1M available)
- Haiku 4.5: 200K context window

All models support long-context retrieval, but place the most important instructions at the beginning of the prompt for best attention.

---

## 2. GPT-4.1 / GPT-4o / GPT-5.x

### Format

Use Markdown headers to structure the prompt. Recommended hierarchy:

```markdown
# Role
You are a ...

## Instructions
1. First instruction
2. Second instruction

## Examples
### Example 1
**Input:** ...
**Output:** ...

## Output Format
Respond in JSON with the following schema: ...
```

### System prompt

Full support. For long-context tasks, use the sandwich method: place the most important instructions at both the beginning AND the end of the system prompt. GPT models show recency bias in long contexts, so duplicating key constraints at the end prevents them from being lost.

### Reasoning

Explicit "Think step by step" is effective and often necessary. GPT-4.1 and GPT-4o do NOT default to chain-of-thought reasoning. Without explicit CoT prompting, the model may skip reasoning steps and jump to conclusions, especially on multi-step problems.

For GPT-5.x, reasoning is improved but explicit CoT still helps on complex tasks.

### Few-shot

Create a separate `# Examples` section with clearly delineated input/output pairs. Use consistent formatting across all examples. GPT models benefit from 2-4 well-structured examples that demonstrate the exact output format expected.

### Known gotchas

- GPT-4.1 follows instructions LITERALLY. Implicit intent is ignored. If you write "summarize the document," it will summarize -- it will not extract key insights, identify themes, or do anything you did not explicitly state. Be exhaustive in your instructions.
- For agentic workflows, three additions yield approximately 20% improvement on SWE-bench:
  1. **Persistence**: "Keep going until the problem is fully resolved. Do not stop at the first error."
  2. **Tool discipline**: "Do NOT guess file contents or outputs. Always use tools to verify."
  3. **Planning**: "Before each tool call, explain what you plan to do and why."
- GPT-4o is multimodal and handles image inputs natively. When targeting GPT-4o with image tasks, describe desired visual analysis explicitly.
- Temperature 0 produces deterministic output for GPT-4.1 but may reduce creativity. Use temperature 0.7-1.0 for creative tasks.
- JSON mode is available via `response_format: { type: "json_object" }` -- use it when you need structured output instead of relying on prompt instructions alone.

### Token budget

- GPT-4.1: 1M context window. Place critical instructions at beginning and end (sandwich method).
- GPT-4o: 128K context window.
- GPT-5: 1M context window. Check current documentation for updated limits.

---

## 3. o-series (o1, o3, o4-mini)

### Format

MINIMAL. Keep prompts short, clear, and direct. Do not use elaborate structural formatting. Simple plain text or very light Markdown is ideal. The model's internal reasoning handles complexity -- over-structured prompts add noise.

### System prompt

Use DEVELOPER messages, not system messages. The o-series models use a different message hierarchy:
- `developer`: Instructions from the application developer (replaces `system`)
- `user`: End-user input

Using `system` instead of `developer` may cause unexpected behavior or be ignored entirely.

### Reasoning

BUILT-IN. The o-series models perform internal chain-of-thought reasoning before responding. Do NOT add "think step by step" or any other CoT prompting. Adding explicit CoT instructions HURTS performance -- it interferes with the model's native reasoning process and can cause redundant or conflicting reasoning chains.

Use the `reasoning_effort` parameter to control depth:
- `low`: Quick responses, minimal internal reasoning. Good for simple lookups and classifications.
- `medium`: Balanced reasoning. Suitable for most tasks.
- `high`: Deep, thorough reasoning. Use for math, logic, complex code, and multi-step problems.

### Few-shot

AVOID. Few-shot examples consistently reduce effectiveness on o-series reasoning models. Zero-shot outperforms few-shot across benchmarks. The model's internal reasoning is sufficient to understand task requirements from clear instructions alone.

If you must provide an example, limit it to one and keep it simple.

### Known gotchas

- Markdown formatting is disabled by default in o-series output. If you need formatted output, add "Formatting re-enabled" as the first line of the developer message.
- Best architectural pattern: use o-series as "the planner" to decompose complex tasks, then hand subtasks to standard models (GPT-4.1, Claude Sonnet) as "the doers."
- Streaming is supported but the model may pause for extended periods during internal reasoning before any tokens appear.
- The model may refuse to show its reasoning process even if asked. Internal reasoning tokens are consumed but not displayed.
- Zero-shot outperforms few-shot consistently across math, code, and logic benchmarks.
- Cost is higher per query due to internal reasoning tokens. Use `reasoning_effort: low` for simple tasks to manage costs.

### Token budget

Varies by model. Keep prompts SHORT -- the model consumes significant tokens internally for reasoning. Long prompts compound the token cost because the model reasons over all provided context.

---

## 4. Gemini 2.5 Pro / Gemini 2.5 Flash / Gemini 3

### Format

XML-style tags OR Markdown headers are both effective, but you MUST be consistent throughout the entire prompt. Do not mix XML and Markdown in the same prompt -- this degrades output quality measurably.

XML style:
```xml
<role>You are a data analyst.</role>
<task>Analyze the following dataset.</task>
<constraints>Use only the provided data.</constraints>
```

Markdown style:
```markdown
# Role
You are a data analyst.

# Task
Analyze the following dataset.

# Constraints
Use only the provided data.
```

### System prompt

Supported via the `system_instruction` parameter in the API. Place persistent behavioral instructions here. Gemini respects system instructions well but may need reinforcement in the user message for complex constraints.

### Reasoning

Use "Plan before responding" for complex tasks. Adding a self-critique instruction improves output quality: "After drafting your response, review it for errors and inconsistencies, then provide the corrected version."

Gemini 2.5 Pro has strong native reasoning. Flash trades some reasoning depth for speed.

### Few-shot

ALWAYS REQUIRED. Google explicitly states that prompts without few-shot examples are less effective on Gemini models. Provide at least 2-3 examples that demonstrate the desired output format and style. Gemini uses examples heavily to calibrate its responses.

Place examples after instructions but before the actual task input.

### Known gotchas

- Temperature MUST stay at 1.0 for most tasks. Lower temperatures (0.0-0.5) cause output loops, repetition, and degraded quality on Gemini models. This is the opposite of most other model families.
- Consistency in formatting is mandatory. If you start with XML tags, use XML tags everywhere. If you start with Markdown, use Markdown everywhere. Mixed formatting confuses the model's parsing.
- Default behavior is concise. If you need detailed responses, request detail explicitly: "Provide a comprehensive analysis with at least 5 paragraphs."
- Gemini handles multimodal input (images, video, audio) natively. For multimodal tasks, place the media before the text instructions for best results.
- Grounding with Google Search is available as a tool -- use it for factual tasks to reduce hallucination.

### Token budget

- Gemini 2.5 Pro: 1M context window
- Gemini 2.5 Flash: 1M context window
- Gemini 3: Check current documentation for context limits

---

## 5. Llama 3 / Llama 4

### Format

Special tokens are required for proper prompt formatting. The model expects a specific token structure:

```
<|begin_of_text|><|start_header_id|>system<|end_header_id|>

You are a helpful assistant.<|eot_id|><|start_header_id|>user<|end_header_id|>

What is the capital of France?<|eot_id|><|start_header_id|>assistant<|end_header_id|>
```

When using hosted APIs (Together, Fireworks, Groq, etc.), the API typically handles tokenization and you can use standard message format. Only use raw special tokens when running the model directly.

### System prompt

Supported via the special token structure shown above. The system message must be placed between the system header tokens. Most API providers abstract this into a standard `system` message field.

### Reasoning

Explicit chain-of-thought helps significantly. Use "Let's work through this step by step" or "Break this problem down before answering." Llama models benefit from structured reasoning prompts more than Claude or GPT.

Llama 4 has improved reasoning over Llama 3, but explicit CoT remains beneficial.

### Few-shot

Helpful for calibrating output format and style. Format examples with clear delimiters:

```
Example 1:
Input: [example input]
Output: [example output]

Example 2:
Input: [example input]
Output: [example output]
```

2-4 examples are typically sufficient.

### Known gotchas

- Wrong special tokens silently degrade output. The model will not error -- it will simply produce lower-quality responses. Always verify the correct token format for your specific Llama version.
- Context windows vary dramatically by deployment: 8K (default Llama 3 8B), 128K (Llama 3.1), and varies for Llama 4. Always check the deployment configuration.
- Instruction following is weaker than Claude and GPT. Be more explicit and direct. Avoid subtle or implicit instructions. State constraints plainly and repeat important ones.
- Llama models are more sensitive to prompt ordering. Place the most important instructions first.
- Open-weight model, so behavior varies across quantizations and fine-tunes. A prompt that works on one deployment may not work on another.
- Llama 4 introduces a mixture-of-experts architecture. Performance characteristics differ from Llama 3 dense models.

### Token budget

- Llama 3 (8B/70B): 8K default context, extendable to 128K with Llama 3.1
- Llama 4: Check deployment-specific configuration. Scout and Maverick have different context limits.

---

## 6. Mistral Large / Mixtral

### Format

Markdown or plain text work well. For older Mistral models (pre-API), use `[INST]` tokens:

```
[INST] You are a helpful coding assistant. [/INST]
```

For newer API versions, standard message format is supported and preferred.

### System prompt

Supported in newer API versions via the standard `system` role in the messages array. For older deployments using raw completions, embed system-level instructions within the first `[INST]` block.

### Reasoning

Explicit chain-of-thought is helpful. "Think through this carefully before responding" or "Reason step by step" both work well. Mistral Large has stronger native reasoning than Mixtral but still benefits from explicit CoT on complex tasks.

### Few-shot

2-3 examples recommended. Mistral models use examples primarily for format calibration. Keep examples concise and representative.

### Known gotchas

- Instruction following is less precise than GPT-4.1 or Claude. Avoid subtle or nuanced instructions. State requirements plainly and directly. If a constraint is important, state it explicitly rather than implying it.
- Strong at code generation and multilingual tasks. Mistral models often outperform their size class on code benchmarks and handle European languages particularly well.
- Mixtral is a mixture-of-experts model. It is fast for its capability level but may show inconsistency on tasks that activate different expert combinations.
- Mistral Large is the flagship and handles complex instructions better than Mixtral. Prefer it for tasks requiring precise instruction following.
- Function calling is supported on newer models. Use the native tool-calling format rather than embedding function schemas in the prompt.
- JSON mode is available and reliable. Use it for structured output tasks.

### Token budget

- Mistral Large: 128K context window
- Mixtral: 32K context window (varies by deployment)

---

## 7. Image Generation Models (Midjourney / DALL-E / Stable Diffusion)

### Format

Comma-separated descriptors. NO conversational text. These models interpret prompts as descriptions, not instructions.

**Midjourney format:**
```
subject, style, medium, lighting, color palette, composition, mood --ar 16:9 --v 6 --style raw
```

**DALL-E format:**
```
A detailed natural language description of the desired image. Can be longer and more narrative in structure. Describe the scene, subjects, style, lighting, and mood in complete sentences.
```

**Stable Diffusion format:**
```
(subject:1.3), style, medium, (lighting:1.2), color palette, composition
Negative prompt: blurry, low quality, distorted, deformed, watermark, text
```

### System prompt

Not applicable. Image generation models do not have a system prompt mechanism. All instructions go in the prompt itself.

### Reasoning

Not applicable. These models do not reason. Prompt quality is about descriptive precision, not logical structure.

### Few-shot

Not applicable in the traditional sense. However, Midjourney supports image references (--iw for image weight), and Stable Diffusion supports img2img pipelines. These serve a similar calibration role.

### Known gotchas

- **Midjourney**:
  - `--ar` sets aspect ratio (e.g., `--ar 16:9`, `--ar 1:1`, `--ar 9:16`)
  - `--v` sets the model version (e.g., `--v 6`)
  - `--style raw` reduces Midjourney's default aesthetic bias for more literal interpretation
  - `--chaos` (0-100) controls variation between outputs
  - `--no` acts as a negative prompt (e.g., `--no text, watermark`)
  - Front-load the most important descriptors. Midjourney weights earlier terms more heavily.

- **DALL-E**:
  - Does NOT support negative prompts. You cannot tell it what to exclude. Instead, describe what you DO want with enough specificity to crowd out unwanted elements.
  - Supports natural language descriptions and is more forgiving of conversational phrasing.
  - Has content policy restrictions that may reject certain prompts. Rephrase rather than circumvent.

- **Stable Diffusion**:
  - Negative prompt is CRITICAL for quality. Always include at minimum: `blurry, low quality, distorted, deformed`
  - Parentheses with weights control emphasis: `(subject:1.5)` increases attention, `(element:0.5)` decreases it
  - Different checkpoint models (SD 1.5, SDXL, SD3) have different optimal prompt styles
  - Samplers and step counts affect output significantly. Prompt alone is not enough for quality control.
  - LoRA and embedding keywords must be included in the prompt to activate fine-tuned concepts.

### Token budget

- Midjourney: Approximately 60-word effective limit. Longer prompts are truncated or ignored.
- DALL-E: Up to 4000 characters, but concise prompts (50-200 words) typically perform best.
- Stable Diffusion: 75 token limit per CLIP chunk (standard). Longer prompts processed in 75-token segments with decreasing attention.

---

## 8. Coding Assistants (Cursor / Windsurf / Copilot)

### Format

Plain text instructions in a rules file placed in the project root:

- **Cursor**: `.cursorrules` file in the project root
- **Windsurf**: `.windsurfrules` file in the project root
- **Copilot**: `.github/copilot-instructions.md` in the repository

Rules files use plain text with optional Markdown formatting. Keep the structure flat and scannable.

```
You are a senior TypeScript developer working on a Next.js 14 application.

Code style:
- Use functional components with hooks
- Prefer named exports over default exports
- Use TypeScript strict mode
- Write unit tests for all new functions

Conventions:
- File names: kebab-case
- Component names: PascalCase
- Use Zod for runtime validation
- API routes use the app router pattern

Constraints:
- Only make changes that are directly requested
- Do not refactor unrelated code
- Do not add dependencies without asking
- Preserve existing patterns in the codebase
```

### System prompt

Via rules file in the project root. The rules file content is injected into every conversation as system-level context. There is no separate system prompt mechanism -- the rules file IS the system prompt.

Some editors also support per-folder rules and user-level global rules in addition to project-level rules.

### Reasoning

Keep rules concise. Rules files load on EVERY interaction, consuming context window budget. Long, elaborate rules reduce the space available for actual code context. Focus on what the model needs to know for every interaction, not edge cases.

Do not add chain-of-thought instructions in rules files. The coding assistant manages its own reasoning flow.

### Few-shot

Not typical in rules files. If you need to show a code pattern, keep it short:

```
When creating API routes, follow this pattern:
export async function GET(request: Request) {
  // validate, process, return Response
}
```

### Known gotchas

- Rules files have implicit token limits. Cursor rules are truncated around 6000 tokens. Keep rules under 3000 tokens for safety.
- Focus on conventions and constraints, not lengthy explanations. "Use kebab-case for files" is better than a paragraph explaining why.
- "Only make changes directly requested" prevents over-engineering. Without this, coding assistants tend to refactor surrounding code, add features not asked for, and change file structure.
- "Do not guess at implementations -- ask for clarification" prevents the assistant from making incorrect assumptions about business logic.
- Rules files are version-controlled. Keep them up to date as the project evolves. Stale rules cause confusion.
- Multiple rules files can conflict. If using per-folder and project-level rules, ensure they are consistent.
- Coding assistants have access to the full codebase via indexing. Rules should complement this context, not duplicate it. Do not paste large code samples into rules files.

### Token budget

- Cursor: ~6000 tokens effective limit for `.cursorrules`
- Windsurf: Similar limits for `.windsurfrules`
- Copilot: `.github/copilot-instructions.md` has a soft limit around 8000 tokens

---

## Quick Reference Table

| Model | Format | CoT Approach | Few-Shot | Key Constraint |
|---|---|---|---|---|
| Claude 4.6 (Opus 1M / Sonnet / Haiku) | XML tags | "Think thoroughly" + effort param | 3-5 examples in `<example>` tags | Avoid aggressive language; causes overtriggering |
| GPT-4.1 / 4o / 5 | Markdown headers | "Think step by step" (explicit) | Separate examples section | Follows instructions literally; use sandwich method |
| o-series (o1/o3/o4-mini) | Minimal plain text | BUILT-IN (do NOT add CoT) | Avoid (zero-shot is better) | Use developer messages, not system messages |
| Gemini 2.5 / 3 | XML or Markdown (consistent) | "Plan before responding" | Always required (2-3 min) | Temperature must stay at 1.0 |
| Llama 4 / 3 | Special tokens | Explicit CoT helpful | 2-4 with clear delimiters | Wrong tokens silently degrade; be very explicit |
| Mistral Large / Mixtral | Markdown or plain text | Explicit CoT helpful | 2-3 examples | Less precise instruction following; be direct |
| Image Gen (MJ/DALL-E/SD) | Comma-separated descriptors | Not applicable | Not applicable | Each tool has unique syntax and constraints |
| Coding Assistants | Rules file (plain text) | Not applicable | Minimal code patterns only | Rules load every interaction; keep under 3K tokens |
