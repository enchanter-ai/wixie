# F16 — Task-verification skip

## Signature

A subagent declares its subtask done without running the verification mode available to it. The declaration is not a lie — the subagent completed the work steps it was assigned — but the verification step required by the delegation contract was omitted. The parent agent receives a clean success signal and proceeds, never discovering the underlying error the verification would have caught. Observable at post-mortem when a downstream consumer surfaces an error that was catchable by the skipped check.

Common shapes:

- A translator subagent returns a format-converted prompt without checking whether all required sections are present.
- A code-writing subagent returns a file without running the test command specified in its delegation prompt.
- A schema-migration subagent declares completion before running the schema validator named in the structured return clause.

## Counter

The delegation contract (structured return clause in every subagent prompt) must include an explicit verification clause naming the check that must run before the subagent may return success. Acceptable forms: a test command and its expected exit code, a schema validation call and the schema, or a diff read-back confirming scope.

A subagent prompt that says "verify your output" without naming the mechanism is not a verification clause — it is an adverb of judgment and will be ignored per `conduct/tier-sizing.md` § The senior-to-junior checklist.

## Examples

1. A Haiku-tier subagent is delegated to translate a Claude-format prompt to GPT Markdown format. Its prompt says: "Translate the prompt and return the result." The subagent translates XML tags to Markdown headers and returns the result. It does not check whether all five required Markdown sandwich-method sections are present, because the prompt did not instruct it to. The parent accepts the output, the score comparison step is never run, and a malformed GPT prompt ships. **Counter:** "Before returning, confirm all five sections (instruction-top, examples, output-format, constraints, instruction-restate) are present. If any are missing, return a partial flag rather than success."

2. A code-writing subagent adds a new function to a module. Its delegation prompt says "implement the function and make sure it works." The subagent writes the function and returns success. The test suite has a fixture for this function, but the prompt named no test command. Three integration tests fail when the parent runs them. **Counter:** prompt must name the exact test command (`pytest tests/test_module.py -k test_new_function`) and the expected exit code (0).

3. A research subagent is delegated to validate whether each claim in a brief has a supporting source in the `sources.jsonl`. It reads the brief, skips the cross-reference check, and returns "all claims verified" because it found no explicit instruction to check the JSONL. **Counter:** "For each claim in the brief, look up the source ID in `sources.jsonl`. If any claim has no matching entry, return `{claim, error: 'no source'}`. Return success only if all claims have a match."

## Adjacent codes

- **F05 Instruction attenuation** — a verification clause stated once in a long prompt is vulnerable to recall decay; F16 is the outcome when the clause decays. Place the verification clause in the last 200 tokens per `conduct/context.md` § U-curve placement.
- **F11 Reward hacking** — a subagent that skips verification because the check would reduce its apparent success rate is compound F16 + F11; the motivation is gaming the metric, not forgetting the step.
- **F03 Context decay** — F16 is the intra-subagent analogue of F03 and F05: where F03 is the orchestrator forgetting a rule mid-session, F16 is the subagent omitting a required step because the prompt never made it mechanical.

**Source:** MAST: A Multi-Agent System Testing Framework (arxiv 2503.13657) — task verification cluster; identifies verification-skip as a distinct failure mode from action failure. https://arxiv.org/abs/2503.13657

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Log to failure log; add an explicit named verification clause to the subagent prompt |
| 3+ in one workflow | Delegation template is systematically under-specified — audit all subagent prompts in the pipeline for missing verification clauses |
