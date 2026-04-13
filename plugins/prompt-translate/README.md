# prompt-translate

**One prompt. Every model. Zero rewrite.**

Converts a prompt optimized for one model into the optimal format for another. XML → Markdown, CoT → no-CoT, verbose → minimal. Preserves your intent and domain content — only changes the engineering.

## Why

You wrote a perfect Claude Opus prompt. Now the team wants to use GPT-4.1. Without translation, you're rewriting from scratch — restructuring XML to Markdown, replacing "think thoroughly" with "think step by step", adding the sandwich method. Prompt-translate does this automatically using the 64-model registry.

## Usage

```
/translate-prompt                              # interactive
/translate-prompt stocks-analysis --to gpt-4.1 # direct
"convert this prompt to work on o3"            # natural language
"adapt for Gemini"                             # natural language
```

## What Changes

| From → To | Format | Techniques | Special |
|-----------|--------|------------|---------|
| Claude → GPT | XML → Markdown | "think thoroughly" → "step by step" | Add sandwich method |
| Claude → o3 | XML → plain text | Remove ALL CoT | Strip to <200 words |
| GPT → Claude | Markdown → XML | "step by step" → "think thoroughly" | Remove sandwich, add XML tags |
| Any → Gemini | Keep or convert | Add few-shot examples | Note: temperature 1.0 |
| Any → image-gen | → descriptors | Strip all scaffolding | Extract visual description only |

## Output

```
TRANSLATION: stocks-analysis (Claude Opus → GPT-4.1)

  Source: prompt.xml (9.3/10, 1326 tokens)
  Target: prompt.md (8.9/10, 1280 tokens)

  Changes:
    ✓ XML → Markdown headers
    ✓ "Think thoroughly" → "Think step by step"
    ✓ Sandwich method added
    ✗ Slight score drop — run /converge to optimize
```

Saves the translated prompt as a new folder with full artifacts.

## Components

| Type | Name | Model |
|------|------|-------|
| Skill | translate | (main agent) |
| Agent | adapter | Sonnet — handles mechanical format conversion |
