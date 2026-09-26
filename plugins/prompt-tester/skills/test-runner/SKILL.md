---
name: test-runner
description: >
  Runs a prompt's test suite (tests.json) by executing each test case,
  checking output against expected_contains assertions, and reporting
  pass/fail results. Use for regression testing after refinements.
  Auto-triggers on: "/test-prompt", "test this prompt", "run prompt tests",
  "check if the prompt works", "regression test".
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/vendor/wixie/shared/scripts/efficacy-replay.py *) Read Write
---

# Prompt Test Runner

Execute a prompt's test suite in **two layers**: (1) a fast self-simulation over `tests.json`
`expected_contains` assertions as a cheap pre-check, then (2) a **measured** run against a fixed eval
corpus with real `claude -p` calls. The measured step is the pass/fail signal that matters; the
self-simulation is a proxy pre-check only.

**Layer 1 is not a real API call.** Step 3.2 has the executing Claude agent role-play as the target
model — "Target model: claude-opus-4-6" means "simulated as," not "verified against a live call to."
Layer 2 (Step 3.5) is a genuine model call via `shared/scripts/efficacy-replay.py corpus` and is the
result to trust. When a pass/fail claim needs to be real, it comes from Layer 2, not Layer 1.

## How It Works

### Step 1: Locate the Test Suite

If the user provides:
- A prompt folder path → read `tests.json` from it
- A prompt name → look in `${CLAUDE_PROJECT_DIR}/prompts/<name>/tests.json`
- Nothing → list available prompts from `${CLAUDE_PROJECT_DIR}/prompts/index.json` and ask

### Step 2: Load the Prompt

Read `prompt.*` from the same folder. Read `metadata.json` for target model and config.

### Step 3: Execute Each Test Case

For each test in `tests.json`:

```json
{
  "name": "test-name",
  "input": "sample input to feed the prompt",
  "expected_contains": ["string1", "string2"],
  "tags": ["tag1"]
}
```

1. **Combine** the prompt with the test input. The prompt is the system/instruction, the input is the user message.
2. **Execute** by generating a response using YOUR OWN capabilities (you ARE a language model — run the prompt yourself as if you were the target model). This is a self-simulation, not a call to the target model's own API — treat pass/fail as a proxy signal, not proof the target model itself behaves this way.
3. **Check assertions**: verify every string in `expected_contains` appears somewhere in the output (case-insensitive).
4. **Record** pass/fail per assertion, per test case.

### Step 3.5: Measure against the eval corpus (the real pass/fail signal)

Run the prompt against the fixed corpus with **real** `claude -p` calls and accept/reject on the
Wilson 95% CI — this is the measured result, not a self-simulation.

```bash
python ${CLAUDE_PLUGIN_ROOT}/vendor/wixie/shared/scripts/efficacy-replay.py corpus deploy-bar \
  --prompt <prompt-file> -n 5
```

- Reads `shared/eval-corpus/deploy-bar/corpus.json`. Each case scores PASS/FAIL on expect/reject
  regexes over real model output; pass rate gets a Wilson 95% CI, computed only over trials that
  actually measured something (see WIX-EFF-001 below) — never over transport failures.
- **ACCEPT** (exit 0) = treatment CI lower bound ≥ `rate_floor` (0.75). **REJECT** (exit 1) = the
  bar was applied and not met. **NO_MEASUREMENT** (exit 3) = the bar was never applied — see below.
- Fold the measured verdict into the report below (see the "Measured" line). In `--ci` mode, the
  overall exit code must reflect the **measured** ACCEPT/REJECT/NO_MEASUREMENT, not only the
  Layer-1 assertions.
- Honest-numbers: if the `claude` CLI is unavailable, say the measure step could not run and report
  only the Layer-1 self-simulation as a proxy — do NOT present it as a measured pass.

**WIX-EFF-001 — transport failure is never a measured rejection.** `efficacy-replay.py` records
each trial's TRANSPORT outcome (did `claude -p` reach the provider and return a parseable
envelope — auth failure, empty output, an invalid/garbled envelope, a hung trial, a rate-limit or
provider error) separately from its TASK outcome (did the model do what the corpus case expects).
A trial whose transport failed is excluded from the Wilson counts entirely — it is never scored
as a rejection. When an arm ends up with **zero valid measurements** (every trial in it failed
transport), the run reports `decision.verdict == "NO_MEASUREMENT"` in both stdout and
`verdict.json` and `efficacy-replay.py corpus` exits **3**, not 1. **Read NO_MEASUREMENT as "the
bar was never applied," not as a failing/REJECT result** — do not report it as `RESULT: FAIL` or
`OVERALL: FAIL` in Step 4; report it as measure-unavailable (the same honest-numbers treatment as
"the `claude` CLI is unavailable" above) and fall back to the Layer-1 result. A **mixed** run
(some trials transport-fail, others measure) is NOT NO_MEASUREMENT as long as at least one trial
per arm produced a real measurement — ACCEPT/REJECT is computed only over the trials that did.

Full artifact: `shared/eval-corpus/deploy-bar/verdict.json`.

### Step 4: Report Results

```
PROMPT TEST RESULTS: stocks-analysis
Target model: claude-opus-4-6

  PASS  single-stock-output-structure (6/6 assertions)
  PASS  data-labels-present (2/2 assertions)
  PASS  risk-disclaimer-included (1/1 assertions)
  PASS  multi-stock-ranking (3/3 assertions)
  FAIL  invalid-ticker-edge-case (0/1 assertions)
        ✗ expected "not recognized" — not found in output

RESULT (Layer 1, self-sim proxy): 4/5 passed (80%)
FAILED TAGS: edge-case

Measured (Layer 2, deploy-bar corpus, real claude -p, n=5): ACCEPT / REJECT / NO_MEASUREMENT
  treatment pass rate 0.90, Wilson CI [0.78, 0.96], floor 0.75
OVERALL: PASS (measured ACCEPT) / FAIL (measured REJECT) / Layer-1-only (measure unavailable or NO_MEASUREMENT)
```

The measured Layer-2 verdict is the authoritative pass/fail. Layer 1 is a proxy pre-check.
NO_MEASUREMENT (exit 3) is not a measured FAIL — it means the measure step ran but every trial
failed transport, so the bar was never actually applied; report `Layer-1-only`, not `FAIL`.

### Step 5: Save Test Results

Save results to `test-results.json` in the prompt folder:

```json
{
  "run_at": "<ISO timestamp>",
  "target_model": "<model>",
  "total": 5,
  "passed": 4,
  "failed": 1,
  "pass_rate": 0.8,
  "results": [
    { "name": "test-name", "passed": true, "assertions_passed": 6, "assertions_total": 6 },
    { "name": "test-name", "passed": false, "assertions_passed": 0, "assertions_total": 1, "failed_assertions": ["expected 'not recognized'"] }
  ]
}
```

## Modes

### Interactive Mode (default)
Run tests, show results, ask user if they want to fix failing tests.

### CI Mode (`--ci` flag or when run non-interactively)
Run both layers, output results as JSON to stdout. Exit code follows the **measured** Layer-2
verdict: `0` = ACCEPT, `1` = REJECT, `3` = NO_MEASUREMENT (every trial in an arm failed transport —
see WIX-EFF-001 above; this is `efficacy-replay.py corpus`'s own exit 3, passed through unchanged,
never remapped to 1). If the `claude` CLI is unavailable, or the measured verdict is
NO_MEASUREMENT, fall back to the Layer-1 assertion result for the exit code and mark the run
`layer1_only: true` in the JSON (NO_MEASUREMENT additionally sets `no_measurement: true`). No
prompts, no color.

## Rules

- Execute EVERY test case. Do not skip any.
- Be honest about results. If a test fails, it fails.
- Do not modify the prompt to make tests pass — that's the convergence engine's job.
- If tests.json is missing or empty, report it and suggest running prompt-crafter to generate tests.
