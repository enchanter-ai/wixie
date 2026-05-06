# agent-foundations

**The foundations for building durable AI agents — conduct, engines, taxonomy, and the math behind all three.**

Most agent stacks ship with prompts, tools, and hopes. This repo gives you the missing layer: a model-agnostic framework of behavior rules, algorithmic primitives, a failure-mode taxonomy, and adoption recipes — battle-tested across production agent systems and packaged for drop-in adoption.

---

## Why this exists

Every team building agents rediscovers the same problems:

- *"Why did Claude push to main even though we said not to?"* — instruction attenuation in long contexts.
- *"Why does it keep refactoring code I didn't ask it to touch?"* — task drift, no surgical-changes rule.
- *"Why is this trust score swinging so wildly?"* — Beta-Bernoulli with no prior; one observation flips the verdict.
- *"Why is the same bug recurring across sessions?"* — no precedent log; the agent forgets what failed last week.
- *"Why did our test suite pass but the migration break in prod?"* — self-certification, no independent verification.
- *"Why does the subagent keep ignoring the rules we wrote?"* — descriptive prose doesn't enforce; conduct never reached the subagent.
- *"Why are two of our agents working at cross-purposes?"* — inter-agent misalignment, not in the original failure taxonomy.

The fixes for these are well-known to people who've shipped agents at scale. They're scattered across blog posts, internal docs, and folklore. **agent-foundations consolidates them into a single dependency-free framework.**

---

## What's in the box

```
agent-foundations/
├── conduct/      ← 19 behavior modules: discipline, context, verification,
│                   delegation, tool-use, formatting, skill-authoring,
│                   hooks, precedent, tier-sizing, web-fetch, failure-modes,
│                   doubt-engine, memory-hygiene, cost-accounting,
│                   refusal-and-recovery, latency-budgeting,
│                   eval-driven-self-improvement, multi-turn-negotiation
├── engines/      ← 12 algorithmic primitives: Aho-Corasick, Shannon entropy,
│                   Beta-Bernoulli, Markov drift, Hunt-Szymanski LCS,
│                   Zhang-Shasha tree edit, Tarjan SCC, Wald SPRT,
│                   Jaccard-Cosine boundary segmentation, LLM Bandit,
│                   Agentproof, Calibration
├── taxonomy/     ← 21 named failure codes (F01–F21) + axes.md (5-axis
│                   hybrid mapping: memory / reflection / planning /
│                   action / system) — flat for ops, axes for review
├── runbooks/     ← 21 incident-response runbooks (one per F-code) with
│                   Detect / Triage / Rollback / Post-incident steps
├── recipes/      ← 9 adoption recipes: Claude Code, OpenAI Agents SDK,
│                   Cursor, LangChain, Pydantic-AI, BAML, generic
│                   system prompt, eval-harnesses, stupid-agent-review
│                   (cheap-tier mechanical verifier for rule-efficacy A/B)
├── docs/         ← Architecture overview + ADRs (0001 four-layers,
│                   0002 taxonomy expansion — resolved via hybrid),
│                   plus self-test.md (A/B fixture methodology)
├── glossary.md   ← Unified terminology
├── anti-patterns.md  ← Cross-cutting catalog of what not to do
└── CLAUDE.md     ← Repo-level instructions for agents editing this repo
```

---

## Quickstart — 30 seconds

One-liner installer (vendored copy at `./shared/foundations`, no `.git` footprint):

```bash
curl -fsSL https://raw.githubusercontent.com/enchanter-ai/agent-foundations/main/install.sh | sh
```

Pick a smaller install if you want less surface:

```bash
curl -fsSL https://raw.githubusercontent.com/enchanter-ai/agent-foundations/main/install.sh | sh -s -- --mode starter   # conduct/ + taxonomy/
curl -fsSL https://raw.githubusercontent.com/enchanter-ai/agent-foundations/main/install.sh | sh -s -- --mode minimal   # conduct/ only
```

Or as a git submodule (history preserved, pinned via parent repo):

```bash
curl -fsSL https://raw.githubusercontent.com/enchanter-ai/agent-foundations/main/install.sh | sh -s -- --submodule
```

Full options: `install.sh --help`.

---

## Pick the modules that match your problem

Don't load everything. Start with the failure mode you're seeing, pull only the modules that counter it.

| You're seeing… | Pull these modules |
|---|---|
| Unsolicited refactors, scope creep | `discipline.md` |
| Rules ignored deep in long sessions | `discipline.md` + `context.md` |
| Test passes but prod breaks | `discipline.md` + `verification.md` |
| Subagents going rogue | `delegation.md` + `verification.md` |
| Same bug returns next week | `precedent.md` + `failure-modes.md` |
| Token costs spiraling | `tier-sizing.md` + `cost-accounting.md` |
| Working memory degrading across turns | `context.md` + `memory-hygiene.md` |
| Subagent doesn't inherit conduct | `delegation.md` (Conduct propagation) |
| Need runtime gates, not just rules | `hooks.md` (Starter patterns) + `recipes/claude-code.md` |
| Latency unpredictable in long workflows | `latency-budgeting.md` |
| Agent refuses benign requests / over-refuses | `refusal-and-recovery.md` |
| Want to learn from observed failures | `eval-driven-self-improvement.md` + `precedent.md` |
| User pressures across turns until you flip | `multi-turn-negotiation.md` + `doubt-engine.md` |
| Doubt-engine F01-counter prose isn't measurable | `engines/calibration.md` |
| Failure happened — need incident steps | `runbooks/F<NN>.md` |
| Want to A/B-validate a module's impact | `docs/self-test.md` |
| Evaluating agent conduct | `recipes/eval-harnesses.md` |

The **production starter pack** is `discipline.md` + `context.md` + `verification.md` + `failure-modes.md` — about 4k tokens, catches the long tail.

---

## Wire it up

### Claude Code

In your project's `CLAUDE.md`:

```markdown
- @shared/foundations/conduct/discipline.md
- @shared/foundations/conduct/verification.md
- @shared/foundations/conduct/tool-use.md
- @shared/foundations/conduct/failure-modes.md
```

For runtime enforcement (not just description), wire hooks per [`recipes/claude-code.md`](recipes/claude-code.md) § Enforcement wiring. The framework now includes copy-paste shell skeletons in [`conduct/hooks.md`](conduct/hooks.md) § Starter patterns — PreToolUse deny, PostToolUse inject, Stop notify.

### OpenAI Agents SDK

```python
from pathlib import Path
from agents import Agent

ROOT = Path("vendor/agent-foundations/conduct")
modules = ["discipline", "verification", "tool-use", "delegation"]
instructions = "\n\n".join((ROOT / f"{m}.md").read_text() for m in modules)

agent = Agent(name="MyAgent", instructions=instructions, model="gpt-5", tools=[...])
```

Full guide: [`recipes/openai-agents.md`](recipes/openai-agents.md).

### Cursor

Drop pointer rules into `.cursor/rules/`:

```markdown
---
description: Coding discipline — think-first, simplicity, surgical, goal-driven
globs: ["**/*"]
alwaysApply: true
---

@.cursor/foundations/conduct/discipline.md
```

Full guide: [`recipes/cursor.md`](recipes/cursor.md).

### Anything else (raw API, llama.cpp, Ollama, …)

```python
system_prompt = "\n\n".join(
    (foundations_root / "conduct" / f"{m}.md").read_text()
    for m in ["discipline", "verification", "tool-use"]
)
```

Full guide: [`recipes/system-prompt.md`](recipes/system-prompt.md).

---

## What you actually get

### Behavior rules that survive long contexts

[`conduct/`](conduct/) ships nineteen modules. The lightest pull-in is just `discipline.md` (~700 tokens) — four stances (think-first, simplicity, surgical, goal-driven) that catch the majority of unsolicited refactors, premature actions, and over-helpful substitutions.

A heavier pull-in adds `context.md` (U-curve placement, checkpoint protocol), `verification.md` (independent checks, dry-run for destructive ops), and `failure-modes.md` (the F-code taxonomy summary). That's the production starter pack.

For long-running multi-agent work, add `memory-hygiene.md` (selective-add over All-Add, prune triggers) and `cost-accounting.md` (budget gates expressed as delegation-prompt conditions, not runtime tooling).

### Subagents that actually inherit the rules

A conduct module the subagent never sees can't shape its behavior. [`conduct/delegation.md`](conduct/delegation.md) now documents three propagation patterns: **full inherit** (paste everything; safest, highest token cost), **whitelist inject** (only modules the tool whitelist touches; best signal-to-cost), and **discovery file** (a single `AGENTS.md` consumed at spawn; cross-tool portable). Pick by tier and lifetime.

### Cross-vendor schema alignment

[`conduct/skill-authoring.md`](conduct/skill-authoring.md) maps the framework's SKILL.md frontmatter against MCP, OpenAI Apps SDK, Cursor `.mdc`, and Claude Code subagent frontmatter. Adopters who already publish skills under one of those schemas can align without rewriting; adopters who don't get a recommended convention.

### Algorithmic primitives, with derivations

[`engines/`](engines/) is the math-grounded layer. Each engine has six required sections: Problem, Formula, Decision rule, Complexity, Implementation pattern, Failure modes. No vibe-coded scoring functions; if it ships in this folder, it has a paper reference and a Big-O.

| Engine | Use case |
|--------|----------|
| [`pattern-detection.md`](engines/pattern-detection.md) | Multi-pattern text scan in linear time (Aho-Corasick) |
| [`entropy-analysis.md`](engines/entropy-analysis.md) | Detect generated tokens / secrets without a pattern list (Shannon) |
| [`trust-scoring.md`](engines/trust-scoring.md) | Online posterior estimate of a probability (Beta-Bernoulli) |
| [`drift-detection.md`](engines/drift-detection.md) | Catch unproductive loops in event streams (Markov + EMA) |
| [`lcs-alignment.md`](engines/lcs-alignment.md) | Measure how much of an anchor sequence survived (Hunt-Szymanski) |
| [`tree-edit.md`](engines/tree-edit.md) | Quantify structural change between trees (Zhang-Shasha) |
| [`scc.md`](engines/scc.md) | Find dependency cycles in O(V+E) (Tarjan) |
| [`sprt.md`](engines/sprt.md) | Decide between two hypotheses with minimum samples (Wald SPRT) |
| [`boundary-segmentation.md`](engines/boundary-segmentation.md) | Cluster events into tasks (Jaccard + cosine + time-decay) |
| [`llm-bandit.md`](engines/llm-bandit.md) | Route each invocation to the optimal model tier by cost-adjusted reward (contextual MAB) |
| [`agentproof.md`](engines/agentproof.md) | Verify an agent workflow statically before execution — graph checks + temporal-policy DFA *(status: concept)* |
| [`calibration.md`](engines/calibration.md) | Sycophancy-rate calibration via progressive/regressive ratios — turns `doubt-engine.md` F01 prose into a measurable axis (SycEval) |

### A failure taxonomy that compounds

Free-text learning notes don't compound. Tagged ones do. [`taxonomy/`](taxonomy/) ships 21 canonical codes with precise signatures, testable counters, and escalation rules:

**Generation failures**
- F01 Sycophancy · F02 Fabrication · F03 Context decay · F04 Task drift · F05 Instruction attenuation

**Action failures**
- F06 Premature action · F07 Over-helpful substitution · F08 Tool mis-invocation · F09 Parallel race · F10 Destructive without confirmation

**Reasoning failures**
- F11 Reward hacking · F12 Degeneration loop · F13 Distractor pollution · F14 Version drift

**Multi-agent and alignment failures** *(new)*
- F15 Inter-agent misalignment · F16 Task-verification skip · F17 System-design brittleness · F18 Goal-conflict insider behavior · F19 Alignment faking *(awareness)* · F20 Sandbagging *(awareness)* · F21 Weaponized tool use

Tag every entry in your failure log with one code. Now you can aggregate. Now you can learn.

The multi-agent cluster (F15–F17) maps to the MAST taxonomy (arxiv 2503.13657); the alignment cluster (F18–F21) draws from Anthropic, OpenAI, and DeepMind safety research. F19 and F20 are awareness codes — log them if observed; the counter is red-team probes and blind capability evaluation, not runtime detection.

A parallel **5-axis layer** lives at [`taxonomy/axes.md`](taxonomy/axes.md) — every F-code is mapped to one of memory / reflection / planning / action / system (per AgentErrorTaxonomy, arxiv 2509.25370). Use flat codes for grep-able logs, axes for structural pressure analysis. The hybrid is intentional and documented in [`docs/adr/0002-taxonomy-expansion.md`](docs/adr/0002-taxonomy-expansion.md).

### Adoption guides, not just docs

[`recipes/`](recipes/) gives you the wiring for seven host platforms plus an eval-harness reference. No hand-waving — concrete file paths, concrete config, a verification step you can actually run.

| Recipe | What it covers |
|--------|----------------|
| [`claude-code.md`](recipes/claude-code.md) | `@`-imports, hook enforcement wiring, scope precedence |
| [`openai-agents.md`](recipes/openai-agents.md) | Python SDK integration, `Agent.clone()`, guardrail patterns |
| [`cursor.md`](recipes/cursor.md) | `.cursor/rules/` activation, scoped pull-ins |
| [`langchain.md`](recipes/langchain.md) | Middleware list enforcement, LangGraph interrupts, propagation |
| [`pydantic-ai.md`](recipes/pydantic-ai.md) | `Agent[Deps, Output]` generics, output validation, tool retries |
| [`baml.md`](recipes/baml.md) | Function-shaped LLM calls, Jinja prompt blocks, `BamlError` |
| [`system-prompt.md`](recipes/system-prompt.md) | Raw API / llama.cpp / Ollama wiring |
| [`eval-harnesses.md`](recipes/eval-harnesses.md) | Benchmark suite reference: τ²-bench, AgentDojo, AgentHarm, SYCON-Bench, etc. |
| [`stupid-agent-review.md`](recipes/stupid-agent-review.md) | Cheap-tier mechanical verifier auditing higher-tier output; the runtime behind A/B rule-efficacy testing |

---

## Before / after

A small but real example:

**Before** the conduct is loaded — agent context: *"fix the off-by-one in pagination":*

```diff
- function paginate(items, page, perPage) {
-   const start = page * perPage;
-   return items.slice(start, start + perPage);
- }
+ class Paginator {                          // unsolicited refactor (F04)
+   constructor(items) { this.items = items; }
+   /** Returns the requested page of items. */  // unsolicited docs (F04)
+   page(p, n) {
+     const start = (p - 1) * n;            // the actual fix
+     return this.items.slice(start, start + n);
+   }
+ }
```

**After** loading `conduct/discipline.md`:

```diff
  function paginate(items, page, perPage) {
-   const start = page * perPage;
+   const start = (page - 1) * perPage;
    return items.slice(start, start + perPage);
  }
```

Same task. Surgical change. No drift.

---

## Design principles

1. **Model-agnostic.** Examples may name a vendor; modules don't bind to one. Tier names are `top-tier / mid-tier / low-tier`, never Opus / Sonnet / Haiku in the body.
2. **Drop-in or à la carte.** Pick the modules you want; ignore the rest. No required entry point.
3. **Zero runtime dependencies.** Pure prose + math. Loadable into any system that accepts text instructions. Engines ship pseudocode, not Python packages.
4. **Honest numbers.** Engine docs include failure modes alongside the math. We tell you when the algorithm is the wrong tool. New modules acknowledge unverified assumptions explicitly (e.g., `agentproof.md` is marked `status: concept`).
5. **Layered, not bundled.** Conduct rules don't embed engine math; engines don't make decisions; taxonomy doesn't run code; recipes don't invent rules. The layering is the discipline.

See [`docs/architecture/README.md`](docs/architecture/README.md) for the structure and [`docs/adr/0001-four-layers.md`](docs/adr/0001-four-layers.md) for why.

---

## What this won't do

- **Force the agent to obey.** Memorized rules attenuate over long contexts. For load-bearing rules, pair with a runtime hook — the [`conduct/hooks.md`](conduct/hooks.md) starter patterns are a real path to enforcement, not a wish.
- **Replace evals.** Conduct shifts default behavior on average; per-task evals still own task quality. See [`recipes/eval-harnesses.md`](recipes/eval-harnesses.md) for benchmarks targeting agent conduct specifically.
- **Provide reference implementations.** Engines describe the math; runnable code lives in adopter projects.
- **Compete with prompt-engineering tools.** This is a *foundation* — it composes with your prompts, doesn't replace them.

---

## Resolved structural decisions

Two architectural questions that earlier versions of the framework deferred have now been resolved:

- **Taxonomy structure (resolved 2026-05-05).** Flat F-codes (current) AND 5-axis modular structure (AgentErrorTaxonomy, arxiv 2509.25370) — both layers ship. Hybrid path: F01–F21 stays as the operational identifier; [`taxonomy/axes.md`](taxonomy/axes.md) maps each code to one of memory / reflection / planning / action / system. Documented in [`docs/adr/0002-taxonomy-expansion.md`](docs/adr/0002-taxonomy-expansion.md).
- **F19/F20 placement (resolved 2026-05-05).** Awareness codes stay in main `taxonomy/` with explicit `(awareness)` flag at the index entry and at the top of each file. Adopters who don't need alignment-research codes can filter by tag rather than file path.

What remains genuinely external — and only adopters can close:

- **Self-test fixtures.** [`docs/self-test.md`](docs/self-test.md) ships the A/B fixture methodology; **19 of 19 modules** have shipped fixtures + **3 rounds of validation tests** as of 2026-05-06. On **Sonnet 4.6**: 5 of 19 show clear behavioral delta — **4 of those 5 replicate cleanly across 3+ runs** (`discipline` 3/3, `formatting` 4/4, `latency-budgeting` 3/3, `eval-driven-self-improvement` 3/3); the 5th (`context`) shows reliable module impact across 3 runs but variable operationalization (treatments apply different module-prescribed structural rules across runs). 12 show no Sonnet delta — confirmed as **training contamination by 2 OOD falsifiability tests** (synthetic modules with fabricated numerics + fabricated vocabulary; baselines did not reach for either). On **Haiku 4.5** (full 14 of 14 Sonnet-no-delta sample): **8 of 14 show measurable behavioral delta**. A previously-headlined "inverse delta" finding for `skill-authoring v2` was retracted after replication (3/3 reruns produced minimal tools — original was N=1 variance). The honest claim, now supported by 3 rounds of replication + 2 OOD controls + full-tier coverage: *modules act as documentation of behavior on Sonnet and as runtime guidance on Haiku.* See [`docs/self-test.md`](docs/self-test.md) § Validation rounds 1-3 for the full reading. [`recipes/stupid-agent-review.md`](recipes/stupid-agent-review.md) ships the runtime architecture; [`tests/runner.py`](tests/runner.py) ships a reference Python runner (syntax + fixture parsing validated; end-to-end API execution still adopter-side); [`.github/workflows/self-test.yml`](.github/workflows/self-test.yml) ships an example CI workflow.
- **Real-world adoption signal.** Until a downstream project reports on living with the conduct, every module is a hypothesis. The Sonnet/Haiku split data suggests adopters should weight module loading by their subject tier — full set load on Haiku, selective load on Sonnet.

---

## Contributing

Issues and PRs welcome. The contribution bar:

- **New conduct module:** justify why it doesn't fit an existing module. The framework is dependency-free; modules are prose, not packages.
- **New engine:** include reference, complexity, failure modes, and pseudocode. No language-specific runtime calls.
- **New failure code (F22+):** observed in 3+ independent contexts, testable counter, no overlap with existing codes. See [`taxonomy/README.md`](taxonomy/README.md) § How to extend.
- **New recipe:** concrete adoption steps + a verification check.

See [`CLAUDE.md`](CLAUDE.md) for repo-level editing rules. The framework is dogfooded — contributors are expected to follow the conduct while editing the conduct.

---

## License

MIT. See [LICENSE](LICENSE). Use freely, including commercially. No warranty.

---

## Acknowledgments

Built on the shoulders of well-studied algorithms — Aho & Corasick, Shannon, Tarjan, Wald, Hunt & Szymanski, Zhang & Shasha, Jaccard, Salton — and the operational lessons of every engineer who's debugged an LLM agent in production. Recent additions draw on published research from Anthropic, OpenAI, DeepMind, Berkeley/Stanford (MAST), and the practitioner community surveyed at scale.

If your team adopts agent-foundations and finds something missing, [open an issue](https://github.com/enchanter-ai/agent-foundations/issues). The framework grows by accumulation of named patterns, not by speculation.
