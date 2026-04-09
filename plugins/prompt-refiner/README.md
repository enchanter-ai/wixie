# prompt-refiner

**The prompt improvement engine.**

Takes an existing prompt, diagnoses weaknesses, re-selects techniques, adapts format to the target model, and delivers an improved version with a diff report showing what changed and why.

## Skills

| Skill | Triggers on |
|-------|-------------|
| prompt-improver | "make this prompt better", "improve this prompt", "refine this prompt", "fix this prompt", `/refine` |

## 3-Phase Workflow

| Phase | What happens |
|---|---|
| **1. Diagnosis** | Scores the original prompt, identifies weaknesses, detects target model |
| **2. Refinement** | Re-selects techniques, re-formats for model, preserves user's intent and domain knowledge |
| **3. Comparison** | Side-by-side diff, before/after scores, explains every change |

## Key Principle

Preserve the user's intent and domain knowledge. Only restructure, re-technique, and re-format — never rewrite their content.
