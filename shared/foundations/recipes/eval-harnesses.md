# Recipe — Eval Harnesses

Benchmark suite reference: nine suites mapped to agent-foundations conduct modules and failure taxonomy codes.

## Purpose

This recipe maps nine benchmark suites to the conduct modules and failure codes they exercise. Its purpose is narrow: help practitioners select the right harness for their current adoption stage without reading nine papers. It does not integrate any suite into the framework; it does not require test infrastructure beyond what each suite's own documentation specifies.

Use it after the enforcement layer (see [`claude-code.md`](./claude-code.md) § Enforcement wiring) gives you something deterministic to evaluate against — running these suites against a system with no enforcement hooks measures the baseline, not the improvement.

## Suite reference table

| Suite | Stars / Signal | What it tests | Framework module(s) |
|-------|----------------|---------------|---------------------|
| **AgentBench** | 3.4k stars (THUDM) | 8-environment LLM-as-Agent benchmark covering web, code, database, and knowledge-base tasks | Broad foundational coverage; good first baseline before targeting specific modules |
| **τ-bench** | arxiv 2406.12045 | Domain-policy following under dynamic user interaction; measures whether agents respect stated rules when users push back | [`conduct/delegation.md`](../conduct/delegation.md), [`conduct/doubt-engine.md`](../conduct/doubt-engine.md) |
| **τ²-bench** | ~1.1k stars (sierra-research) | Dual-control simulation: both the agent and a simulated adversarial user take turns; isolates tool-use discipline under pressure | [`conduct/tool-use.md`](../conduct/tool-use.md), [`conduct/verification.md`](../conduct/verification.md) |
| **AgentDojo** | Paper | Prompt-injection robustness and untrusted-data tool execution; 97 tasks, 629 injections | [`conduct/hooks.md`](../conduct/hooks.md) enforcement; F06 (Premature action), F08 (Tool mis-invocation) |
| **AgentHarm** | Paper | 110 malicious agent tasks across 11 harm categories; measures refusal, partial refusal, and recovery | F18 (Goal-conflict insider behavior), F19 (Alignment faking), F20 (Sandbagging), F21 (Weaponized tool use) |
| **SYCON-Bench** | Benchmark | Multi-turn sycophancy; Turn of Flip (rate of position reversal after pushback) and Number of Flip (flip count before agent holds) | [`conduct/doubt-engine.md`](../conduct/doubt-engine.md); F01 (Sycophancy) |
| **SycEval** | Paper | Progressive sycophancy ratio (agent caves over successive turns) vs. regressive (agent overcorrects when pushed); quantitative separation of the two modes | [`conduct/doubt-engine.md`](../conduct/doubt-engine.md); F01 — adds a quantitative axis the framework's qualitative doubt-engine pass lacks |
| **WorkArena** | ServiceNow | Browser-based knowledge-worker workflows: form filling, record lookup, service-desk task completion | [`recipes/cursor.md`](./cursor.md); [`conduct/tool-use.md`](../conduct/tool-use.md) for browser-tool dispatch |
| **Promptfoo** | Active OSS project | Custom assertion scoring: define pass/fail criteria in YAML, run against any model endpoint, compare across versions | [`conduct/verification.md`](../conduct/verification.md); lightweight alternative to full-suite benchmarks for teams in early adoption |

## Selection guide

Three practitioner profiles cover the common starting points. Pick the profile that matches your team's current priority, run the recommended suite first to establish a baseline, then expand.

**Enforcement-first.** Your priority is wiring the conduct rules into deterministic gates (PreToolUse / PostToolUse hooks) and confirming the gates fire correctly. Start with **Promptfoo**: define YAML assertions that mirror each conduct rule's pass condition, run against your system prompt, and iterate. Once assertions are green, run **AgentDojo** to confirm the enforcement layer holds under prompt-injection — the adversarial stress test for hooks. AgentBench as a broad baseline is the third step.

**Taxonomy-first.** Your priority is confirming the F-code taxonomy maps correctly to real failures your system produces. Start with **AgentHarm** (covers F18–F21) and **SYCON-Bench** (covers F01 at the turn level). These two suites together exercise the taxonomy's hardest-to-observe codes. Follow with **SycEval** to quantify the F01 surface using progressive/regressive ratios — it gives you numbers to put in `learnings.md` next to the qualitative doubt-engine log entries.

**Benchmark-first.** Your priority is an overall capability baseline before targeted module testing. Start with **AgentBench** (broadest environmental coverage, 3.4k stars, well-maintained). Follow with **τ-bench** to add the domain-policy and user-pushback dimension, then **τ²-bench** for adversarial dual-control. These three together cover foundational capability, policy adherence, and tool-use discipline.

## Open questions

**SYCON-Bench citation.** No arxiv ID or canonical GitHub URL was available during the research pass; the entry relies on the benchmark name alone. Confirm the canonical citation before relying on this suite in a published evaluation; add the URL to the table's Stars / Signal column when found.

**Datadog observability-driven harnesses.** The research pass surfaced a Datadog engineering blog post describing a DST + TLA+ + bounded model-checking harness for agent workflows. This finding is intentionally omitted from the suite table: the source is a blog post, not a specification or a public artifact, and the methodology is described at a level of abstraction that makes independent implementation impractical. If Datadog publishes a specification or open-sources the tooling, it warrants a table entry — the approach (temporal logic verification of agent traces) is directly relevant to [`conduct/verification.md`](../conduct/verification.md). Until then, treat it as an open research lead, not an adoptable harness.

**Suite maintenance signals.** Star counts and paper citations were current as of the research pass (2025–2026). Benchmark suites in the agent-evaluation space have a high churn rate. Before adopting any suite, confirm its repository has had activity in the last 6 months. AgentBench and τ²-bench have shown sustained maintenance; the paper-only suites (AgentDojo, AgentHarm, SycEval) should be checked more carefully.

**Integration with the enforcement layer.** This recipe intentionally contains no integration code. Once the framework has a canonical test-runner hookup, the suite table should be updated with framework-specific invocation examples. Until then, follow each suite's own documentation for setup.
