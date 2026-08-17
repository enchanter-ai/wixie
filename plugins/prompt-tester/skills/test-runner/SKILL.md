---
name: test-runner
description: >
  Runs a prompt's test suite (tests.json) by executing each test case,
  checking output against expected_contains assertions, and reporting
  pass/fail results. Use for regression testing after refinements.
  Auto-triggers on: "/test-prompt", "test this prompt", "run prompt tests",
  "check if the prompt works", "regression test".
allowed-tools: Read Write
---

# Prompt Test Runner

Execute a prompt's test suite by self-simulating the target model. Each test case in `tests.json` is run and the output is checked against `expected_contains` assertions.

**Not a real API call.** Step 3.2 has the executing Claude agent role-play as the target model rather than calling its API — so "Target model: claude-opus-4-6" in the report format means "simulated as," not "verified against a live call to." Use `shared/scripts/efficacy-replay.py` when a claim needs a genuine model-vs-model result.

## How It Works

### Step 1: Locate the Test Suite

If the user provides:
- A prompt folder path → read `tests.json` from it
- A prompt name → look in `${CLAUDE_PLUGIN_ROOT}/../../prompts/<name>/tests.json`
- Nothing → list available prompts from `${CLAUDE_PLUGIN_ROOT}/../../prompts/index.json` and ask

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

RESULT: 4/5 passed (80%)
FAILED TAGS: edge-case
```

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
Run tests, output results as JSON to stdout, exit with code 0 if all pass, 1 if any fail. No prompts, no color.

## Rules

- Execute EVERY test case. Do not skip any.
- Be honest about results. If a test fails, it fails.
- Do not modify the prompt to make tests pass — that's the convergence engine's job.
- If tests.json is missing or empty, report it and suggest running prompt-crafter to generate tests.
