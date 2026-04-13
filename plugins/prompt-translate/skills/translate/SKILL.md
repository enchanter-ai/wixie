---
name: translate
description: >
  Converts a prompt from one model's format to another. Re-selects
  techniques, adapts structure, preserves intent and domain content.
  Auto-triggers on: "/translate-prompt", "convert this prompt to GPT",
  "adapt for Claude", "port this prompt to Gemini",
  "make this work on o3", "translate prompt".
allowed-tools: Bash(python *) Read Write Edit
---

# Prompt Translator

Convert a prompt optimized for one model into the optimal format for a different model. Preserve all intent and domain content — only change structure, techniques, and formatting.

## Step 1: Load Source Prompt

Accept: file path, folder path, prompt name, or pasted prompt text.

If loading from a saved prompt folder, read `metadata.json` to get the source model and techniques.

## Step 2: Identify Source and Target

- **Source model**: detected from metadata, format cues (XML → Claude, Markdown → GPT), or ask the user
- **Target model**: the user specifies which model to translate to. If not specified, ask.

Read both model entries from `${CLAUDE_PLUGIN_ROOT}/../../shared/models-registry.json`.

## Step 3: Diff the Models

Compare source and target across these dimensions:

| Dimension | Example diff |
|-----------|-------------|
| **Format** | XML tags → Markdown headers (Claude → GPT) |
| **Reasoning** | Extended thinking → standard (Opus → Sonnet: remove "think thoroughly", add explicit CoT) |
| **Reasoning** | Standard → reasoning-native (GPT → o3: remove ALL CoT, strip examples) |
| **Few-shot** | Required → avoid (Gemini → o3: remove all examples) |
| **Few-shot** | Not required → required (Claude → Gemini: add examples if missing) |
| **Tone** | Neutral → explicit (Claude → GPT-4.1: add sandwich method, repeat key constraints) |
| **Length** | Any → minimal (anything → o-series: strip to essentials, <200 words) |
| **Special** | Any → image-gen: restructure as descriptors, remove all instruction scaffolding |

## Step 4: Apply Translation

Read reference files for the target model:
- [model-profiles.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/model-profiles.md)
- [technique-engine.md](${CLAUDE_PLUGIN_ROOT}/../../shared/references/technique-engine.md)

Apply these transformations in order:

### Format Conversion
| From | To | Action |
|------|----|--------|
| XML (`<instructions>`, `<context>`) | Markdown | Convert tags to `# Role`, `## Instructions`, `## Examples` headers |
| Markdown (`# Role`, `## Task`) | XML | Wrap sections in `<instructions>`, `<context>`, `<constraints>`, `<examples>` tags |
| Any structured format | Minimal (o-series) | Strip all markup. Keep only the core instruction in plain text. Remove examples, CoT, and verbose constraints. |
| Any format | Descriptors (image-gen) | Extract visual description, style, and constraints as comma-separated descriptors |

### Technique Re-selection
| Source technique | Target model type | Action |
|-----------------|-------------------|--------|
| Chain-of-Thought | reasoning-native (o3, R1, QwQ) | REMOVE — built-in reasoning, explicit CoT hurts |
| Chain-of-Thought | extended-thinking (Opus) | REPLACE with "think thoroughly" |
| No CoT | standard (GPT, Sonnet) | ADD "Think step by step" for complex tasks |
| Few-Shot examples | o-series | REMOVE — zero-shot outperforms |
| No examples | Gemini | ADD 2-3 examples — required by Google guidance |

### Model-Specific Adaptations
| Target | Adaptation |
|--------|-----------|
| GPT-4.1 | Sandwich method: repeat critical constraints at the end |
| Claude | "Think thoroughly" not "step by step". Avoid MUST/ALWAYS. Use XML tags. |
| o-series | Developer messages, not system. "Formatting re-enabled" if markdown needed. <200 words. |
| Gemini | Temperature 1.0 note. Always include examples. |
| DeepSeek R1 | Treat like o-series. No explicit CoT. |

## Step 5: Validate Translation

Run self-eval on the translated prompt:
```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/self-eval.py <translated-prompt>
```

If the translated prompt scores LOWER than the source, warn the user and explain which dimensions degraded (e.g., "Model Fit improved 5→9 but Completeness dropped 10→7 because examples were removed for o-series").

## Step 6: Save

Save the translated prompt as a new folder: `prompts/<name>-<target-model>/`

Run the full delivery pipeline (token count, metadata, tests, report).

Present both prompts side-by-side in a comparison:

```
TRANSLATION: stocks-analysis (Claude Opus → GPT-4.1)

  Source: prompt.xml (Claude, XML, 1326 tokens, 9.3/10)
  Target: prompt.md (GPT-4.1, Markdown, 1280 tokens, 8.9/10)

  Changes applied:
    ✓ XML tags → Markdown headers
    ✓ "Think thoroughly" → "Think step by step"
    ✓ Added sandwich method (constraints repeated at end)
    ✓ Added explicit output format section
    ✗ Slight Completeness drop — GPT-4.1 needs more literal instructions

  Recommendation: run /converge on the translated prompt to push score higher.
```

## Rules

- NEVER change the prompt's intent, domain content, examples, or task description.
- Only change structure, format, technique scaffolding, and model-specific adaptations.
- If the source prompt has custom examples, translate the FORMAT of examples but keep the CONTENT.
- Always explain what changed and why in the comparison output.
- If translating to a fundamentally different domain (text → image-gen), warn the user that significant content loss is expected.
