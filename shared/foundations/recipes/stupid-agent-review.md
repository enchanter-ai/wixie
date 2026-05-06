# Recipe — Stupid-Agent Review

How to wire a cheap-tier LLM as a mechanical verifier of a higher-tier agent's adherence to a behavioral rule. The "stupid" framing is intentional: the verifier's literal, instruction-following nature is a *feature* — it runs the test script exactly without creative reinterpretation. The cost asymmetry (cheap verifier auditing expensive subject) is what makes A/B-testing rule efficacy affordable.

This is the recipe behind the framework's [`../tests/`](../tests/) fixtures and the methodology in [`../docs/self-test.md`](../docs/self-test.md).

## What this is — and what it isn't

| Pattern | Tier choice | Check type | Goal |
|---|---|---|---|
| **Stupid-agent review** *(this recipe)* | Cheap-tier verifier (Haiku, gpt-4o-mini) auditing higher-tier subject | **Structural / boolean** — heading present, quote verbatim, link resolves, vendor-neutral terms | Measure whether a behavioral rule moves metrics |
| LLM-as-judge | Same-tier or higher-tier judge | Quality / preference rating | Score output quality |
| Linter / static analysis | No LLM | AST or regex pattern match | Catch deterministic violations |
| Capability eval (AgentBench, τ²-bench) | Variable | Task success rate | Measure what an agent can do |
| Constitutional AI critique-revise | Same-tier self-critique | Quality + values alignment | Improve a single output |
| Pre-commit shell hook | No LLM | Deterministic shell test | Block bad commits |

The stupid-agent verifier is the only one that combines *cheap-tier-as-feature* + *structural-not-quality checks* + *rule-efficacy as the goal*.

## Theoretical anchors

The pattern composes from three published primitives, none of which alone names the full shape:

- **Multi-Agent Verification (MAV)** — arxiv 2502.20379, Feb 2025 — establishes that off-the-shelf cheap-tier LLMs (Gemini-1.5-Flash, GPT-4o-mini) can produce reliable binary True/False approvals at low cost. The closest theoretical analogue.
- **Rule Based Rewards** — Anthropic, arxiv 2411.01111 — decomposes safety policy into binary propositions graded by a separate LLM. Validates that rule-shift behavior is measurable, in an RL-training context. Stupid-agent review applies the same decomposition at runtime.
- **SycEval** — arxiv 2502.08177 — empirically measured rule-shift impact (sycophancy rates 56–62% across model families). Demonstrates the methodology is real; the framework's [`../engines/calibration.md`](../engines/calibration.md) is its purpose-built primitive.

## When to dispatch a stupid-agent

Use the stupid-agent gate when **all four** hold:

1. The check is **structural** — heading present, link target exists, quote matches verbatim, term banned, count correct.
2. The check is **boolean** — pass/fail, not graded.
3. The artifact under review is **text** — Markdown, JSON, code, prompt body. (Stupid agents are bad at runtime behavior; that's what fixtures and capability evals are for.)
4. The cost of running it must be **cheap enough to run on every change** — otherwise it's a special-case audit, not a gate.

Skip the stupid-agent gate when:

- A regex or AST-based linter would suffice (cheaper, more deterministic — use the linter).
- The judgment is qualitative ("does this prose flow well?") — that's LLM-as-judge territory, use a smarter tier.
- The runtime cost matters more than the verification cost (production agent paths) — use deterministic hooks per [`../conduct/hooks.md`](../conduct/hooks.md).

## Three-component architecture

A stupid-agent review wires three roles. Adopters tend to confuse them.

| Role | Tier | Job | Example |
|---|---|---|---|
| **Subject** | Top-tier or mid-tier | Performs the task under test | Sonnet writing the diff for a bug fix |
| **Verifier** | Low-tier | Runs the boolean test against the subject's output | Haiku checking "does this output contain a `## Signature` heading?" |
| **Orchestrator** | Mid-tier or top-tier | Dispatches both, scores the A/B delta, logs the fixture result | The CI runner or `/converge`-style skill |

The cost asymmetry matters. The subject is expensive because the work is hard. The verifier is cheap because the test is mechanical. Mixing the tiers — using top-tier as the verifier — wastes budget; using cheap-tier as the subject misses the failure modes the rule is supposed to prevent.

## The A/B-on-rule-efficacy contract

Stupid-agent review is most useful as the runtime for an A/B fixture per [`../docs/self-test.md`](../docs/self-test.md). The contract:

1. **Two subject runs** — identical task, identical model, identical temperature. One with the conduct module loaded, one without.
2. **One verifier pass** — the stupid agent applies the fixture's pass criterion to *both* outputs, returning a structured per-check result.
3. **Delta computation** — the orchestrator compares the two verifier results and records the rule-attributable shift.

Without the baseline run, you have not measured rule efficacy — you have measured the rule-loaded model. The baseline is the contract.

## Promptfoo wiring (concrete adoption)

[Promptfoo](https://www.promptfoo.dev) supports cheap-tier graders out of the box. Override the default grader to a low-tier model and write structural assertions. Sketch:

```yaml
# promptfooconfig.yaml
prompts:
  - file://prompts/baseline.txt        # task only
  - file://prompts/treatment.txt       # task + conduct/discipline.md prepended

providers:
  - id: anthropic:messages:claude-sonnet-4-6
    config: { temperature: 0 }

defaultTest:
  options:
    provider: anthropic:messages:claude-haiku-4-5   # the stupid agent
  assert:
    - type: llm-rubric
      value: |
        Does the output contain `(page - 1) * perPage` exactly?
        Answer ONLY "yes" or "no".
    - type: llm-rubric
      value: |
        Does the output add a JSDoc block (lines starting with `/**`)?
        Answer ONLY "yes" or "no".

tests:
  - vars: { task: "fix the off-by-one in this pagination function: ..." }
```

Run two prompt variants, score with a Haiku grader, compare the deltas. Promptfoo handles the dispatch; you write the structural assertions.

## Inspect-AI wiring (UK AISI evals)

[Inspect-AI](https://inspect.aisi.org.uk) supports custom scorers including model-graded checks. The same A/B shape, with a custom scorer that runs the cheap-tier verifier:

```python
from inspect_ai import Task, eval
from inspect_ai.scorer import scorer, Score
from inspect_ai.solver import generate, system_message

@scorer
def stupid_agent_check(criterion: str):
    async def _scorer(state, target):
        # Dispatch a Haiku-tier check on state.output.completion
        # Return Score(value=1.0 if pass else 0.0, explanation=...)
        ...
    return _scorer

baseline = Task(
    dataset=[...],
    solver=generate(),
    scorer=stupid_agent_check("contains `(page - 1) * perPage`"),
)

treatment = Task(
    dataset=[...],
    solver=[system_message(open("conduct/discipline.md").read()), generate()],
    scorer=stupid_agent_check("contains `(page - 1) * perPage`"),
)

eval([baseline, treatment], model="anthropic/claude-sonnet-4-6")
```

Inspect-AI handles the eval harness; the cheap-tier scorer is your responsibility. The framework's contribution is the *fixture format* and the *rule-efficacy A/B* discipline, not the runner.

## Anti-patterns

- **Top-tier verifier.** Burning Opus on "does this string contain `(page - 1)`" wastes budget without improving accuracy. Cheap-tier is the design choice, not a fallback.
- **Quality-judgment in the verifier prompt.** "Is this code clean?" is LLM-as-judge, not stupid-agent review. Mechanical = boolean = no adverbs.
- **Treating one fixture run as a measurement.** A single A/B is a smoke test, not a calibration. The honest claim is "this module showed delta on this fixture / model / prompt." Generalization requires more runs.
- **Skipping the baseline.** "I loaded the module and the model behaved well" is not evidence of rule efficacy. The baseline is the contract.
- **Adjusting the criterion after seeing results.** The criterion is a prediction. If the baseline passes, the criterion was wrong or the fixture invited drift insufficiently — not a reason to weaken the criterion.
- **Confusing capability evals with rule-efficacy evals.** AgentBench measures whether the agent succeeds at the task. Stupid-agent review measures whether the *rule* moves metrics. Different goals, different infrastructure.

## Relationship to the rest of the framework

| Module | Role |
|---|---|
| [`../docs/self-test.md`](../docs/self-test.md) | Methodology: A/B fixture format, pass-criterion discipline, per-module inventory |
| [`../tests/`](../tests/) | Per-module fixtures applying this recipe |
| [`../engines/calibration.md`](../engines/calibration.md) | The session-level analogue for the doubt-engine module specifically |
| [`./eval-harnesses.md`](./eval-harnesses.md) | External benchmark suites (τ²-bench, SYCON-Bench, AgentDojo) — capability evals, not rule-efficacy |
| [`../conduct/hooks.md`](../conduct/hooks.md) | Runtime gates for production paths — not the same as offline A/B fixtures |

Stupid-agent review fits between hooks (runtime, deterministic, cheap-per-call) and eval-harnesses (offline, capability-focused, expensive-per-batch). It is the offline, *rule-focused*, cheap-per-fixture gate the framework needs to move from "operational hypothesis" to "verified module."

## Honest claim

This pattern is **partial-prior-art, build-new** as of 2026-05-05. The implementation primitives exist (Promptfoo cheap graders, Inspect-AI custom scorers, MAV's binary aspect verifiers). The named pattern — *cheap-tier-as-feature + structural-not-quality + rule-efficacy as the goal* — is not published as a unified architecture. This recipe is the framework's first attempt at naming and shipping it.

The first fixture using this recipe is [`../tests/discipline.fixture.md`](../tests/discipline.fixture.md). It honestly logs both a failed run (over-constrained prompt, no delta) and a passing run (drift-inviting prompt, clear delta). One fixture is not a verified framework — it is the start of one.
