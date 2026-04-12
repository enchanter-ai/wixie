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

## Phase 4: Self-Evaluation

Run `${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/self-eval.py` on the generated prompt. The script scores 5 axes (1–10 each):

1. **Clarity**: Are instructions unambiguous? No conflicting directives?
2. **Completeness**: Does it cover the full task? Missing constraints?
3. **Efficiency**: Minimal tokens for maximum effect? No redundancy?
4. **Model Fit**: Does the format match the target model's preferences?
5. **Failure Resilience**: Does it handle edge cases? Unclear inputs?

**If any axis scores below 6**: State the weakness, suggest a specific fix, and ask "Want me to apply this fix?"

**If all axes ≥ 6**: Include scores in the Enchantment Report and deliver.

**If the script is unavailable or fails**: Perform the evaluation manually using the same 5 axes. Be honest about scores.

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
