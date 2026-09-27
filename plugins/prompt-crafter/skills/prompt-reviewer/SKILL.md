---
name: prompt-reviewer
description: >
  Internal reviewer agent. Validates a completed prompt folder against
  metadata.json and models registry. Checks consistency, completeness,
  and production-readiness. Not user-invocable — triggered automatically
  by the prompt-creator after convergence completes.
user-invocable: false
---

# Prompt Reviewer

**Contract (ships inside this plugin; WIX-DIST-002).** This skill relies on: `@${CLAUDE_PLUGIN_ROOT}/vendor/wixie/claude-md.deploy-bar.md` (DEPLOY bar and scoring provenance); `@${CLAUDE_PLUGIN_ROOT}/vendor/wixie/claude-md.behavioral-contracts.md` (behavioral contracts); `@${CLAUDE_PLUGIN_ROOT}/vendor/wixie/claude-md.artifacts-per-prompt.md` (prompt-folder artifacts and folder hygiene). Read them before acting; in a repo checkout they are the same sections of the root CLAUDE.md (or the pinned vis module).

Validate a completed prompt folder for production-readiness. This skill runs automatically after convergence — do not wait for user input.

## Input

Read the prompt folder at the path provided. The folder contains:
- `prompt.<format>` — the prompt file
- `metadata.json` — scores, model, techniques, config
- `tests.json` — regression test cases
- `report.pdf` — generated audit report

## Validation Checks

Execute ALL checks. Report results as PASS/FAIL with details.

### 1. File Completeness
- [ ] `prompt.<format>` exists and is non-empty
- [ ] `metadata.json` exists and is valid JSON
- [ ] `tests.json` exists and has >= 3 test cases
- [ ] `report.pdf` exists and is > 0 bytes

### 1b. Editability (WIX-CONV-001)
- [ ] If `editable/<shipped filename>` exists: the shipped file is byte-equal to `strip(master)`
      (`prompt_regions.py strip --check <master> <shipped>`) and `metadata.editability.shipped_sha256`
      matches the shipped file
- [ ] No shipped file that has a master contains the text `wixie-editable`
- [ ] No `editable/` file is referenced as a model-facing prompt anywhere in the folder

### 2. Metadata Consistency
Read `metadata.json` and verify:
- [ ] `target_model` exists in `${CLAUDE_PLUGIN_ROOT}/vendor/wixie/shared/models-registry.json`
- [ ] `scores.overall` matches the average of the 5 axis scores
- [ ] `tokens.estimated` is a positive number
- [ ] `tokens.context_window` matches the registry value for the target model
- [ ] `status` is "pass" if overall >= 6, "needs_improvement" otherwise
- [ ] `version` is a positive integer
- [ ] `config.temperature` is appropriate for the domain (0-0.3 for coding, 0.7-1.0 for creative)

### 3. Prompt-Metadata Alignment
- [ ] Prompt format (file extension) matches `metadata.format`
- [ ] If target model prefers XML and format is XML, verify prompt contains XML tags
- [ ] If target model prefers Markdown and format is MD, verify prompt contains headers
- [ ] Techniques listed in metadata are actually reflected in the prompt structure

### 4. Score Validation
Run self-eval on the prompt and compare with metadata scores:
```bash
python -B ${CLAUDE_PLUGIN_ROOT}/vendor/wixie/shared/scripts/self-eval.py <prompt-file>
```
- [ ] Scores from self-eval match metadata.scores (tolerance: ±1 per axis)
- [ ] If scores diverged significantly, metadata is stale — flag for update

### 5. Registry Cross-Reference
Read the model entry from `${CLAUDE_PLUGIN_ROOT}/vendor/wixie/shared/models-registry.json`:
- [ ] If model has `reasoning: "reasoning-native"`, verify no CoT in prompt
- [ ] If model has `few_shot: "REQUIRED"`, verify examples exist in prompt
- [ ] If model has `few_shot: "AVOID"`, verify no examples in prompt
- [ ] If model format is `xml`, verify prompt uses XML tags
- [ ] If model format is `markdown`, verify prompt uses Markdown headers

## Output

Report in this format:
```
REVIEW: <prompt-name>
  PASS  File completeness (4/4 files)
  PASS  Metadata consistency (7/7 checks)
  FAIL  Prompt-metadata alignment: format is .md but model prefers XML
  PASS  Score validation (within tolerance)
  PASS  Registry cross-reference (4/4 checks)

VERDICT: PASS (4/5 checks) — 1 issue found
ACTION: Convert prompt format from Markdown to XML for Claude target model
```

If all checks pass: `VERDICT: APPROVED — prompt is production-ready`
If any FAIL: list the specific fixes needed. The convergence engine or main agent should apply them.
