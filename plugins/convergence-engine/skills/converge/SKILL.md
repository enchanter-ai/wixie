---
name: converge
description: >
  Run the Convergence Engine on any prompt file. Iterates up to 100 times,
  automatically fixing clarity, completeness, efficiency, model fit, and
  failure resilience until the prompt reaches DEPLOY quality.
  Auto-triggers on: "/converge", "converge this prompt", "optimize until perfect",
  "iterate until deploy", "run convergence".
allowed-tools: Bash(python *) Read Write Edit Agent
---

# Convergence Engine

Autonomous prompt optimization. Like gradient descent for prompts — each iteration reduces deviation from perfection.

## Usage

The user provides a prompt file path or a prompt folder. Run the full pipeline.

## Pipeline

### Step 1: Locate the prompt

If the user provides:
- A file path → use that file directly
- A folder path → find `prompt.*` inside it
- A prompt name → look in `${CLAUDE_PLUGIN_ROOT}/../../prompts/<name>/prompt.*`
- Nothing → list available prompts from `${CLAUDE_PLUGIN_ROOT}/../../prompts/index.json` and ask user to pick

### Step 2: Run convergence

```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/convergence.py <prompt-file>
```

This runs up to 100 iterations:
- Scores the prompt on 5 axes (Clarity, Completeness, Efficiency, Model Fit, Failure Resilience)
- Identifies the weakest axis
- Applies targeted fix (hedge words, missing components, filler, format, fallbacks)
- Re-scores and repeats
- Exits on DEPLOY (overall ≥ 9, all axes ≥ 7) or plateau (3 identical scores)

### Step 3: Update artifacts

After convergence:

1. Run token count:
```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/token-count.py <prompt-file> --model <target-model>
```

2. Run self-eval for final scores:
```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/self-eval.py <prompt-file>
```

3. Update `metadata.json` with new scores.

4. Generate report:
```bash
python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/report-gen.py <prompt-folder>
```

5. Update `${CLAUDE_PLUGIN_ROOT}/../../prompts/index.json`.

### Step 4: Review

Validate the result:
- All files exist and are non-empty
- Metadata scores match self-eval output (tolerance ±1)
- Target model exists in registry
- Format matches model preference

If issues found, fix and re-run convergence (max 3 review cycles).

### Step 5: Report

Tell the user:
```
Convergence complete: X.X → Y.Y in N iterations
Verdict: DEPLOY / BEST EFFORT
[axis scores]
```

## Rules
- Do NOT ask for permission. Run everything autonomously.
- Do NOT modify the prompt's intent or domain content.
- The convergence script handles all text fixes. You handle artifacts and review.
- If convergence.py fails, fall back to manual: read self-eval, apply fixes yourself, re-score, repeat up to 10 times.
