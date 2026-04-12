---
name: prompt-improver
description: >
  Improves existing prompts by re-selecting techniques, adapting
  format to the target model, and fixing weaknesses while preserving
  the user's intent and domain knowledge.
  Auto-triggers on: "make this prompt better", "improve this prompt",
  "refine this prompt", "fix this prompt", "optimize this prompt",
  "what's wrong with this prompt", "/refine".
---

# Flux — Prompt Refiner

Improve an existing prompt by diagnosing weaknesses, re-selecting techniques, and adapting format to the target model.

**Core rule:** Preserve the user's intent and domain knowledge. Only restructure, re-technique, and re-format — never rewrite their content.

Execute Phases 0–3 in order.

---

## Phase 0: Load the Prompt

Determine the source of the prompt to refine:

**Option A — User provides a prompt directly:** Use it as-is. Skip to Phase 1.

**Option B — User references a saved prompt:** Browse `${CLAUDE_PLUGIN_ROOT}/../../prompts/` for existing prompt folders. Each folder contains `prompt.<format>`, `report.html`, and `metadata.json`.

**Option C — User says "refine" or "improve" without specifying:** List available prompts from the `${CLAUDE_PLUGIN_ROOT}/../../prompts/` folder. Show each prompt's name, target model, overall score, and creation date (from `metadata.json`). Ask the user to pick one.

When loading a saved prompt:
1. Read `metadata.json` for context (model, domain, techniques, scores)
2. Read `prompt.<format>` as the input prompt
3. Read `report.html` for previous technique decisions — avoid re-applying techniques that were deliberately avoided unless the user's refinement goal changes the calculus

---

## Phase 1: Diagnosis

### 1A: Score the Original

Run `${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/self-eval.py` on the user's original prompt. Record scores for all 5 axes.

If the script is unavailable, score manually using the same 5 axes:
1. **Clarity** — Are instructions unambiguous?
2. **Completeness** — Does it cover the full task?
3. **Efficiency** — Minimal tokens for maximum effect?
4. **Model Fit** — Does the format match the target model?
5. **Failure Resilience** — Does it handle edge cases?

### 1B: Detect Target Model and Domain

1. Check if the prompt mentions a model explicitly.
2. Detect from formatting cues: XML tags → Claude, Markdown headers → GPT, minimal → o-series.
3. Read `CLAUDE.md` for project model preferences.
4. If ambiguous, ask the user which model this prompt targets.
5. Detect task domain: `coding` | `data-extraction` | `creative-writing` | `analysis` | `agent` | `conversational` | `image-gen` | `decision-making` | `other`

### 1B.5: Model Fit Check

After detecting the model and domain, read [models-registry.json](${CLAUDE_PLUGIN_ROOT}/../../shared/models-registry.json) and validate the model fits the task:

| Task Domain | Poor Fit Models |
|---|---|
| coding | Image/video/audio models, Haiku for complex code |
| data-extraction | Reasoning-native models (o-series waste budget) |
| analysis | Small models (Haiku, Phi), image/video models |
| creative-writing | Reasoning-native models (dry output), code-specialized |
| agent | Models without tool-use support |
| image-gen | Any text LLM |
| conversational | Heavy reasoning models (slow, expensive) |

If the model is a poor fit, present a warning with 2 recommended alternatives and ask the user to confirm or switch before proceeding.

### 1C: Identify Weaknesses

Based on the scores, list specific problems:
- Axes scoring below 6 are critical weaknesses
- Axes scoring 6-7 are improvement opportunities
- Note any anti-patterns for the detected model (e.g., CoT for o-series, no few-shot for Gemini)

Present the diagnosis to the user before proceeding:

```
## Diagnosis

**Original Score:** X.X/10
**Target Model:** [detected or asked]
**Weaknesses Found:**
- [specific weakness 1]
- [specific weakness 2]

Proceeding with refinement...
```

---

## Phase 2: Refinement

### 2A: Re-select Techniques

Read [technique-engine.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/technique-engine.md). Based on the diagnosed weaknesses and target model:

1. Identify which techniques the original prompt uses (implicitly or explicitly)
2. Check if any are anti-patterns for the target model
3. Select 1-3 techniques that would fix the diagnosed weaknesses
4. Keep techniques that are already working well

### 2B: Re-format and Restructure

Read [model-profiles.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/model-profiles.md) for the target model's format requirements.
Read [output-formats.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/output-formats.md) for the task type's optimal structure.

**Registry check:** Read [models-registry.json](${CLAUDE_PLUGIN_ROOT}/../../shared/models-registry.json) for context window and capabilities.

Apply fixes:
- **Format layer**: Convert to the target model's preferred format (XML for Claude, Markdown for GPT, minimal for o-series)
- **Technique layer**: Add missing techniques, remove harmful ones
- **Component layer**: Add missing mandatory components (fallbacks, expected output, success criteria) per [prompt-anatomy.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/prompt-anatomy.md)
- **Efficiency layer**: Remove filler phrases, redundant instructions, conflicting directives

**What NOT to change:**
- The user's domain-specific content and examples
- The core task description and intent
- Custom terminology or jargon the user chose deliberately
- The scope of what the prompt asks for

---

## Phase 3: Comparison & Delivery

### 3A: Score the Refined Prompt

Run `${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/self-eval.py` on the refined prompt. Compare before/after scores.

### 3B: Present the Refined Prompt

Always present the refined prompt inside a fenced code block (` ``` `).

### 3C: Save as a Folder

Save the refined prompt as a folder inside `${CLAUDE_PLUGIN_ROOT}/../../prompts/`. Append `-v<N>` to the folder name if a previous version exists (e.g., `invoice-extractor-v2`).

#### Delivery steps (execute ALL in order — do NOT skip any step)

1. **Create/reuse the folder:** `mkdir -p ${CLAUDE_PLUGIN_ROOT}/../../prompts/<prompt-name>`

2. **Save the refined prompt file:** Write `prompt.<format>` into the folder.

3. **Run token count on the refined prompt:**
```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/token-count.py <prompt-file> --model <target-model>
```

4. **Run self-eval on the refined prompt:**
```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/self-eval.py <prompt-file>
```

5. **Save metadata.json** with before/after scores and `"mode": "refine"`:
```json
{
  "created": "<original creation timestamp>",
  "refined": "<ISO 8601 timestamp now>",
  "task": "<one-line task description>",
  "target_model": "<model ID>",
  "task_domain": "<domain>",
  "format": "<prompt format>",
  "mode": "refine",
  "techniques": ["<final techniques>"],
  "techniques_avoided": ["<avoided>"],
  "tokens": {
    "original": "<before token count>",
    "refined": "<from token-count output>",
    "context_window": "<from token-count output>",
    "usage_percent": "<from token-count output>"
  },
  "scores": {
    "before": { "clarity": 0, "completeness": 0, "efficiency": 0, "model_fit": 0, "failure_resilience": 0, "overall": 0 },
    "after": { "clarity": 0, "completeness": 0, "efficiency": 0, "model_fit": 0, "failure_resilience": 0, "overall": 0 }
  },
  "status": "pass | needs_improvement",
  "version": "<incremented version>",
  "config": {
    "temperature": "<recommended>",
    "max_tokens": "<recommended>",
    "stop_sequences": [],
    "system_prompt": "<true/false>"
  }
}
```

6. **Update or keep tests.json** — add new test cases if refinement changed behavior.

7. **Generate report.pdf** (do NOT write the report manually):
```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/report-gen.py <prompt-folder-path>
```

8. **Update index.json:** Read `${CLAUDE_PLUGIN_ROOT}/../../prompts/index.json`, update the entry for this prompt, write it back.

#### Final folder contents

```
prompts/<prompt-name>/
├── prompt.<format>       # The refined prompt
├── metadata.json         # Before/after scores, config
├── tests.json            # Regression test cases
└── report.pdf            # Generated audit report (dark theme, single page)
```

**If the user says "just give me the prompt":** Output refined prompt only, no folder.

---

## Phase 4: Repeat Until Perfection

Two modes based on domain. Check and execute the matching one.

### Mode A: Text Prompts (all domains except image-gen)

**Fully autonomous.** Loop without user input. Up to 100 iterations.

1. Score the refined prompt via self-eval.
2. Check: overall ≥ 9, all axes ≥ 7, zero criticals → **DEPLOY. Exit.**
3. Score unchanged 3 consecutive iterations → **Plateau. Exit.**
4. Otherwise: read findings, apply fixes (see fix table in prompt-crafter SKILL.md), overwrite prompt, go to 1.
5. Progress update every 10 iterations.
6. On exit, save all artifacts (delivery steps 3-8) and generate report.pdf.

### Mode B: Image Prompts (image-gen)

**Collaborative.** You cannot see images. Force the user through a feedback loop.

1. Present the refined prompt in a code block. Ask the user to:
   - Generate the image with their chosen model/platform
   - Report what looks wrong, what looks right, and rate 1-10
2. Wait for feedback. Do NOT proceed without it.
3. Rating ≥ 9 → Save final prompt. **Exit.**
4. Rating < 9 → Adjust based on feedback:
   - Colors off → adjust color descriptors, add hex codes
   - Style wrong → strengthen/shift style keywords
   - Missing elements → add with explicit placement
   - Composition bad → add layout instructions
   - Elements merged wrong → separate descriptions, clarify spatial relationships
5. Present revised prompt. Go to 1.
6. No iteration limit. Keep going until user rates ≥ 9 or says "done."
7. Show what changed each round.
8. After 5+ iterations, summarize patterns and suggest trying a different model if issues persist.
