---
name: prompt-enchanter
description: >
  Enchants raw prompts and task descriptions into optimized,
  model-fitted prompts with technique selection and explained reasoning.
  Auto-triggers on: "I need a prompt for", "build me a prompt",
  "make this prompt better", "optimize this prompt", "help me prompt",
  "write a system prompt", "what prompting technique should I use",
  "how should I structure this prompt", "/enchant".
---

# Flux

Create technique-optimized, model-fitted prompts from task descriptions with explained reasoning.

Execute Phases 1–4 in order. Do not skip phases. Do not narrate Phase 1 to the user.

> **Note:** This skill creates new prompts. To improve an existing prompt, use the prompt-refiner plugin instead.

---

## Phase 1: Context Scan (Silent)

Gather project context before asking any questions. Do not narrate this phase.

1. Read `CLAUDE.md` in the project root if it exists. Extract: project language, conventions, preferred model, coding style, existing prompt patterns.
2. Read `.cursorrules` or `.windsurfrules` if present. Extract style preferences.
3. Detect the task domain from the user's description:
   - `coding` | `data-extraction` | `creative-writing` | `analysis` | `agent` | `conversational` | `image-gen` | `decision-making` | `other`
4. Note whether the user specified a target model. Check CLAUDE.md for model preferences.

**Anti-rationalization table — reasons you must NOT skip this phase:**

| Excuse to skip | Why you must not skip |
|---|---|
| "CLAUDE.md doesn't exist" | Check first. If absent, proceed without it — don't ask the user about it |
| "I already know enough" | You don't. Always check for project context. It takes 2 seconds |
| "The user didn't mention a model" | That's why Phase 2 asks. But first scan for model preferences in CLAUDE.md |

---

## Phase 2: Interactive Profiling (Always Use GUI)

Always use the interactive question tool to gather context — even when the task seems detailed. The GUI surfaces choices users wouldn't think to specify, and produces more accurate prompts. Never fall back to plain-text questions when the interactive tool is available.

**Minimum 3 questions, maximum 8.** Adapt the number and content to the specific scenario — no two tasks should get the same cookie-cutter questions.

### How to structure interactive questions

- Group related questions into a single call (up to 4 questions per call)
- Provide 2–4 concrete options per question with descriptions explaining trade-offs
- Write question text that reflects the specific task, not generic templates. "What tone should this invoice extractor error messages use?" beats "What tone?"
- Use the `header` field for short contextual labels (e.g., "Invoice format", "Risk level", "Audience")
- Use `multiSelect: true` when choices are not mutually exclusive
- Tailor option labels and descriptions to the domain — a coding question should offer coding-specific choices, not generic ones

### Question categories

Build your questions from these categories. Pick at least one from each of the three groups:

**Group A — Intent & Scope (pick 1–2):**
- **Task confirmation** — Reflect back what you understood. Offer scope variants: "I'll build a prompt that does X — which scope fits?" with options like minimal / standard / comprehensive / production-grade.
- **Purpose & audience** — Who will use this prompt? A developer pasting it into an API, a non-technical user in ChatGPT, an automated pipeline? This changes tone, complexity, and format.

**Group B — Technical Fit (pick 1–2):**
- **Target model** — Present model families as options with trade-off descriptions. If CLAUDE.md specified a model, list it first with "(detected from project)". Always include "Other" for unlisted models.
- **Domain-specific questions** — Adapt entirely to the detected domain. Examples:
  - *coding*: Language, framework, scope (core / tests / error handling / production)
  - *data-extraction*: Schema source (user-provided / auto-designed), pipeline vs. one-off, volume
  - *creative-writing*: Tone, audience, POV, length, style references
  - *agent*: Available tools, failure strategy, persistence, multi-turn vs. single
  - *analysis*: Depth (executive summary / standard / deep-dive), evidence standard, format
  - *image-gen*: Target model, style, aspect ratio, quality tier, exclusions
  - *decision-making*: Number of options, recommendation vs. neutral, criteria weighting
  - *conversational*: Persona depth, guardrail strictness, turn length, escalation rules

**Group C — Prompt Completeness (pick 1–2):**
- **Components to include** (multiSelect: true): Fallback instructions, expected output example, task roadmap, success criteria. Default all selected.
- **Edge cases & constraints** — What should the prompt handle when things go wrong? Present domain-specific failure scenarios as options: "What if the input is malformed?", "What if the API returns an error?", "What if the data is incomplete?"

### Dynamic question design

Do NOT reuse the same questions across different tasks. Each question must be written for the specific scenario:

| Bad (generic) | Good (scenario-specific) |
|---|---|
| "What output format?" | "Should the stock analysis output as a structured report with tables, or narrative prose with inline data?" |
| "How detailed?" | "Should each stock recommendation include full scenario modeling, or just a ticker + one-line thesis?" |
| "What tone?" | "Should this chatbot persona be formal-professional or casual-friendly when handling refund requests?" |

---

## Phase 2.5: Model Fit Check (Do Not Skip)

After Phase 2, before generating the prompt, validate that the user's chosen model actually fits the task. Read [models-registry.json](${CLAUDE_PLUGIN_ROOT}/../../shared/models-registry.json) and cross-reference:

| Task Domain | Best Model Types | Poor Fit |
|---|---|---|
| coding | Claude Opus/Sonnet, GPT-4.1, DeepSeek V3, Codestral, Qwen-Coder | Image/video/audio models, Haiku for complex code |
| data-extraction | Claude Sonnet, GPT-4.1, GPT-4o | Reasoning-native models (o-series waste budget on simple extraction) |
| analysis | DeepSeek R1, Claude Opus, o3, GPT-5 | Small models (Haiku, Phi), image/video models |
| creative-writing | Claude Sonnet/Opus, GPT-4o, GPT-5 | Reasoning-native models (dry output), code models |
| agent | Claude Opus, GPT-4.1, o3 | Models without tool-use support |
| image-gen | DALL-E 3, Midjourney, Stable Diffusion, Flux, Ideogram, Imagen | Any text LLM |
| conversational | Claude Sonnet, GPT-4o, Gemini Flash | Heavy reasoning models (slow, expensive) |
| decision-making | DeepSeek R1, o3, Claude Opus | Small/fast models |

**If the model is a poor fit for the domain:**

Present this to the user:
```
⚠️ Model Fit Warning

You selected [model] for a [domain] task.
[model] is [reason it's a poor fit].

Recommended alternatives:
1. [better model 1] — [why it's better for this task]
2. [better model 2] — [why it's better for this task]

Continue with [model] anyway? Or switch to one of the above?
```

Wait for the user's response. If they confirm the original model, proceed. If they switch, update the target model for Phase 3.

**If the model is a good fit:** Proceed silently. Do not narrate this check.

---

## Phase 3: Enchanting

Three sub-steps, executed in order.

### 3A: Select Techniques

Read [technique-engine.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/technique-engine.md). Based on task type, complexity, and target model:

1. Classify task complexity: `simple` (single-step) | `moderate` (2–4 steps) | `complex` (5+ steps or ambiguous)
2. Check target model reasoning capability: `standard` | `reasoning-native` | `extended-thinking`
3. Select 1–3 techniques from the decision matrix
4. Check the anti-patterns column — if a technique would HURT on the target model, do NOT use it. Note this for the report
5. Check the priority rules for model-specific overrides

### 3B: Generate the Enchanted Prompt

Read [model-profiles.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/model-profiles.md) for the target model's format requirements.
Read [output-formats.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/output-formats.md) for the task type's optimal structure.

**Registry check (do not skip):** Read [models-registry.json](${CLAUDE_PLUGIN_ROOT}/../../shared/models-registry.json) for the target model's context window and capabilities. This is the single source of truth — it overrides anything in the reference .md files.

1. Check the `last_updated` field. If it's more than 3 months old, verify critical specs via web search or your own knowledge before relying on them.
2. If the target model is not in the registry, check if a close match exists (same family). If not, flag it: "Model not in registry — specs are best-effort."
3. If you know a registry value is outdated (e.g., a model's context window has expanded since the registry was last updated), use the current value, note the correction in the Enchantment Report, and update `${CLAUDE_PLUGIN_ROOT}/../../shared/models-registry.json` with the new value and today's date in `last_updated`.

Apply all three layers:

- **Technique layer**: Embed selected technique(s) into the prompt structure. Add `<example>` blocks for Few-Shot, reasoning scaffolding for CoT, ReAct loops for agent tasks, etc.
- **Model layer**: Format for the target model. XML tags for Claude, Markdown headers for GPT-4.1, minimal structure for o-series, always include few-shot for Gemini.
- **Format layer**: Structure output instructions for the task type. JSON schema for data extraction, fenced code blocks for code gen, comma-separated descriptors for image gen, etc.

### Mandatory Prompt Components

Read [prompt-anatomy.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/prompt-anatomy.md) for the full checklist and fallback patterns. Every enchanted prompt MUST include these components (unless the user explicitly opted out in Phase 2):

1. **Fallback instructions** — What to do when input is ambiguous, data is missing, or the task cannot be completed as specified. Read `${CLAUDE_PLUGIN_ROOT}/../../shared/references/prompt-anatomy.md` section "Fallback Patterns" for domain-specific templates.
2. **Expected output** — A concrete example or description of what correct output looks like. Even a brief one anchors the model's format and depth.
3. **Task roadmap** — For moderate/complex tasks: numbered phases or steps the model should follow. Keeps the output organized and ensures nothing is skipped.
4. **Success criteria** — How to know the output is done and correct. Prevents the model from stopping too early or overproducing.

For image-gen prompts: fallbacks and task roadmap are not applicable. Include the "Do not include" exclusion list and composition constraints instead.

### Prompt Delivery

Always present the final prompt inside a fenced code block (` ``` `).

After the code block, save the prompt as a **folder** inside `${CLAUDE_PLUGIN_ROOT}/../../prompts/`. Use a kebab-case name derived from the task (e.g., `invoice-extractor`, `code-reviewer`).

After saving the prompt folder, update `${CLAUDE_PLUGIN_ROOT}/../../prompts/index.json` — append an entry with the prompt's name, task, target model, domain, format, overall score, version, timestamps, and relative path. Create the file if it does not exist.

#### Delivery steps (execute ALL in order — do NOT skip any step)

1. **Create the folder:** `mkdir -p ${CLAUDE_PLUGIN_ROOT}/../../prompts/<prompt-name>`

2. **Save the prompt file:** Write `prompt.<format>` into the folder. Use `.md` for Markdown, `.xml` for XML-tagged, `.json` for JSON, `.txt` for plain text or image-gen.

3. **Run token count:** Execute this command and note the output:
```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/token-count.py <prompt-file> --model <target-model>
```

4. **Run self-eval:** Execute this command and note the scores:
```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/self-eval.py <prompt-file>
```

5. **Save metadata.json:** Write this file with real values from steps 3-4:
```json
{
  "created": "<ISO 8601 timestamp>",
  "task": "<one-line task description>",
  "target_model": "<model ID from registry>",
  "task_domain": "<detected domain>",
  "format": "<prompt format used>",
  "techniques": ["<technique 1>", "<technique 2>"],
  "techniques_avoided": ["<technique>"],
  "tokens": {
    "estimated": "<from token-count output>",
    "context_window": "<from token-count output>",
    "usage_percent": "<from token-count output>"
  },
  "scores": {
    "clarity": "<from self-eval>",
    "completeness": "<from self-eval>",
    "efficiency": "<from self-eval>",
    "model_fit": "<from self-eval>",
    "failure_resilience": "<from self-eval>",
    "overall": "<from self-eval>"
  },
  "status": "pass | needs_improvement",
  "version": 1,
  "config": {
    "temperature": "<recommended for this domain/model>",
    "max_tokens": "<recommended max output tokens>",
    "stop_sequences": [],
    "system_prompt": "<true if system prompt, false otherwise>"
  }
}
```

6. **Save tests.json:** Generate 3-5 test cases:
```json
[
  { "name": "<test-name>", "input": "<sample input>", "expected_contains": ["<string>"], "tags": ["<tag>"] }
]
```
Cover: typical input, clean/no-issue input, and an edge case (empty, malformed).

7. **Generate report.pdf:** Execute this command (do NOT write the report manually):
```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/report-gen.py <prompt-folder-path>
```
This generates a dark-themed single-page PDF audit report. Do NOT create report.html, report.md, or report.pdf yourself — the script handles it.

8. **Update index.json:** Read `${CLAUDE_PLUGIN_ROOT}/../../prompts/index.json`, append an entry for this prompt, and write it back.

#### Final folder contents

```
prompts/<prompt-name>/
├── prompt.<format>       # The prompt
├── metadata.json         # Machine-readable metadata + config
├── tests.json            # Regression test cases
└── report.pdf            # Generated audit report (dark theme, single page)
```

**If the user says "just give me the prompt" or "skip the report":** Generate prompt only, save only the prompt file (no folder). Respect this preference for the rest of the session.

**If the user says "explain more" or "why did you choose X":** Expand on any section of the report with deeper reasoning.

---

## Phase 4: Repeat Until Perfection

This phase has TWO modes depending on domain. Check the task domain and execute the matching mode.

---

### Mode A: Text Prompts (coding, analysis, agent, conversational, data-extraction, decision-making, creative-writing)

**Fully autonomous.** Loop without user input until the prompt is production-ready. Do NOT ask the user for permission to iterate — just do it.

**Loop (up to 100 iterations):**

1. **Score:**
```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/self-eval.py <prompt-file>
```

2. **Check exit condition:**
   - Overall ≥ 9 AND all axes ≥ 7 AND zero CRITICAL findings → **DEPLOY. Exit loop.**
   - Score unchanged for 3 consecutive iterations → **Plateau reached. Exit loop.**
   - User says "stop" or "good enough" → **Exit loop.**

3. **If not exiting, fix the prompt:**
   - Read each finding from the scorer output.
   - Apply the specific fix for each:

   | Finding | Fix |
   |---|---|
   | Low Clarity | Rewrite with imperative verbs. Shorten sentences >40 words. Remove hedge words. |
   | Low Completeness | Add missing: role, output format, constraints, examples. |
   | Low Efficiency | Remove filler phrases. Deduplicate instructions. Strip examples of repeated boilerplate. |
   | Low Model Fit | Restructure format for target model. Add/remove CoT. Fix few-shot. |
   | Low Failure Resilience | Add fallback instructions, edge case handling, input validation. |
   | Format mismatch | Switch to target model's preferred format (XML/Markdown/minimal). |
   | Missing few-shot | Add 2-3 diverse examples. |
   | CoT conflict | Remove CoT for reasoning-native models. Add for standard models. |
   | Conflicting instructions | Identify the contradiction and remove one side. |
   | Vague role | Replace "helpful assistant" with a specific domain expert. |
   | No output format | Add explicit format specification section. |

   - Overwrite `prompt.<format>` with the improved version.
   - Go back to step 1.

4. **Progress updates (every 10 iterations):**
   Show: `"Iteration 30/100 — Overall: 8.2→8.7. Fixing: Efficiency (repeated 5-grams in constraints section)..."`
   Do NOT show updates every single iteration — it clutters the output.

5. **On exit, save all artifacts** (delivery steps 1-8) and generate report.pdf.

---

### Mode B: Image Prompts (image-gen)

**Collaborative with user.** You cannot see generated images — the user must be your eyes. Force the user through a feedback loop. Do NOT let them accept a prompt without trying it first.

**Setup:** Save the initial prompt and artifacts (delivery steps 1-8).

**Then enter the visual refinement loop:**

1. **Present the prompt** to the user in a code block. Tell them:
   ```
   Copy this prompt into [target model/platform].
   Generate the image, then tell me:
   1. What looks WRONG? (colors off, composition bad, style wrong, missing elements)
   2. What looks RIGHT? (keep these aspects)
   3. Rate it 1-10
   ```

2. **Wait for user feedback.** Do NOT proceed without it.

3. **When user responds, evaluate their rating:**
   - Rating ≥ 9 → **User is satisfied. Save final prompt. Exit loop.**
   - Rating < 9 → Continue to step 4.

4. **Adjust the prompt based on feedback:**
   - "Colors are off" → Adjust color descriptors. Be more specific (hex codes, named colors).
   - "Style is wrong" → Strengthen style keywords. Add negative descriptors if model supports them.
   - "Missing elements" → Add the missing element with specific placement description.
   - "Composition is bad" → Add explicit layout instructions (centered, rule of thirds, foreground/background).
   - "Too realistic" / "Too cartoon" → Shift style descriptors toward the desired aesthetic.
   - "Elements are merged wrong" → Separate the descriptions more clearly. Describe spatial relationships.

5. **Present the revised prompt.** Go back to step 1.

**Rules:**
- **No iteration limit.** Keep going until the user rates ≥ 9 or says "done" / "good enough."
- **Show what you changed** each iteration: "Adjusted: strengthened pixel art style, added explicit hex colors, removed 'glowing' (caused smooth gradients in your output)."
- **Learn from feedback patterns.** If the user says "too smooth" twice, aggressively add anti-smoothing descriptors on every subsequent iteration.
- **Never skip the feedback step.** Even if you think the prompt is perfect, the model's output is the only ground truth.
- **Track iteration history.** After 5+ iterations, summarize: "We've tried 7 versions. Consistent issues: [X]. Consistent wins: [Y]. Recommendation: try a different model."

**Exit conditions:**
- User rates ≥ 9
- User says "done", "good enough", "perfect", "ship it"
- User wants to try a different model (restart with new model, keep learned preferences)

---

## Reference Files

These files contain the detailed knowledge that powers Phase 3. Read them on demand — do not load all at once.

| File | Read During | Contains |
|---|---|---|
| [technique-engine.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/technique-engine.md) | Phase 3A | Decision matrix for 16 techniques, priority rules, anti-patterns |
| [model-profiles.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/model-profiles.md) | Phase 3B | Per-model formatting specs for 10+ models |
| [output-formats.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/output-formats.md) | Phase 3B | Task type → optimal output format mapping |
| [prompt-anatomy.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/prompt-anatomy.md) | Phase 3B | Mandatory component checklist, fallback patterns, expected output templates |
| [self-eval.py](${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/self-eval.py) | Phase 4 | Heuristic prompt scorer (run via Bash) |
| [token-count.py](${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/token-count.py) | Phase 3 delivery | Token estimator with context window warnings |
