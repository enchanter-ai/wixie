# Glossary

Audience: anyone reading this repo for the first time. The terminology used across [`conduct/`](conduct/) and [`engines/`](engines/), defined once.

## Agent / Subagent

**Agent** — an LLM instance running with a defined role, tool set, and prompt. The unit of execution.

**Subagent** — an agent spawned by another agent (the *parent*). Subagents have their own context window, isolated from the parent. The parent receives only the subagent's structured return.

## Agent-card

A structured document — file, manifest, or frontmatter block — that declares an agent's
or skill's identity, capabilities, and invocation conditions to a host system. The framework's
SKILL.md is an agent-card. External equivalents include MCP Tool/Prompt/Resource objects,
OpenAI tool descriptors, and Cursor `.mdc` frontmatter.

See [`./conduct/skill-authoring.md`](./conduct/skill-authoring.md) § Cross-vendor schema alignment.

---

## Tier (Top / Mid / Low)

A model-capability tier. Concrete examples:

| Tier | Anthropic | OpenAI | Google |
|------|-----------|--------|--------|
| Top | Opus | GPT-5 | Gemini 2.5 Pro |
| Mid | Sonnet | GPT-4o | Gemini 2.5 Flash |
| Low | Haiku | GPT-4o-mini | Gemini 2.5 Flash-Lite |

Used to calibrate prompt verbosity ([`./conduct/tier-sizing.md`](./conduct/tier-sizing.md)) and delegate by cost.

## Conduct

A behavioral rule for agents. Lives in [`conduct/`](conduct/). Conduct *governs* — it says what to do or avoid. It does not compute.

## Engine

A math-grounded primitive an agent system leans on. Lives in [`engines/`](engines/). Engines *compute* — they return numbers or verdicts. They don't decide downstream actions; conduct does.

## Skill

A named workflow with a manifest (frontmatter) declaring its name, description, target model, and tool whitelist. The selector matches a user's request against the description; the body is read after selection. See [`./conduct/skill-authoring.md`](./conduct/skill-authoring.md).

## Hook

A runtime callback fired on a specific event (PreToolUse, PostToolUse, UserPromptSubmit, Stop). Hooks here are **advisory** — they inject context, never gate behavior. See [`./conduct/hooks.md`](./conduct/hooks.md).

## Validator (cheaper-tier check)

A subagent on a lower tier that reviews a higher-tier agent's output. Catches shape errors and obvious mistakes before they propagate. The pattern's load-bearing form is documented at [`./recipes/stupid-agent-review.md`](./recipes/stupid-agent-review.md): a *cheap-tier* LLM running structural boolean tests against a higher-tier subject's artifact. The cost asymmetry is intentional — the verifier's literal mechanical reading is a feature, not a fallback.

## A/B fixture

A paired-run test that measures whether loading a conduct module changes agent behavior on a defined axis. Two identical runs — one without the module (baseline), one with (treatment) — scored against a binary or bounded pass criterion. Without the baseline run, you have not measured the module; you have measured the model. See [`./docs/self-test.md`](./docs/self-test.md) for methodology, [`./tests/`](./tests/) for shipped fixtures.

## Orchestrator

The top-tier agent in a chain. Spawns subagents, consumes their structured returns, makes high-level decisions. Never spawned itself.

## Executor

A mid-tier agent that runs a long loop or substantive subtask (convergence, adversarial audit, format translation). Returns a structured artifact.

## Fetcher

A low-tier subagent whose job is to fetch and extract from web pages. Owns `WebFetch`. See [`./conduct/web-fetch.md`](./conduct/web-fetch.md).

## Failure log / Precedent log

Two kinds of logs:

- **Failure log** (e.g., `learnings.md`) — domain-level failures in the iteration / scoring loop. Tagged by [F-codes](./conduct/failure-modes.md).
- **Precedent log** (e.g., `state/precedent-log.md`) — operational failures in shell, file, and tool commands. Self-observed, project-local. See [`./conduct/precedent.md`](./conduct/precedent.md).

## Doubt pass

A four-step adversarial self-check (state proposal → steelman opposite → name evidence against → surface or proceed) run before any agreement, alignment, or scope acceptance — including silent acceptance of one's own prior framing. The active counter to F01 sycophancy. See [`./conduct/doubt-engine.md`](./conduct/doubt-engine.md).

## Checkpoint

A summary block emitted at ~50% context budget that becomes the new source of truth. Drops prior turns from active context. Format defined in [`./conduct/context.md`](./conduct/context.md).

## DEPLOY / HOLD / FAIL

Common shipping verdicts:

- **DEPLOY** — all gates passed; ship.
- **HOLD** — at least one quality gate didn't pass; iterate.
- **FAIL** — structural issue (registry mismatch, contract violation); fix the flagged issue first.

Verdicts come from the *current* run's measurements — never from cached metadata of a prior session ([`./conduct/verification.md`](./conduct/verification.md)).

## Conjugate prior

A prior distribution that, combined with a likelihood, yields a posterior in the same family. The Beta distribution is conjugate to the Bernoulli likelihood ([`./engines/trust-scoring.md`](./engines/trust-scoring.md)). Updates are `O(1)` — no integration required.

## EMA (Exponential Moving Average)

```
EMA_t = α · x_t + (1 - α) · EMA_{t-1}
```

Smooths a noisy signal with `O(1)` state. Higher `α` reacts faster; lower `α` smooths more. Half-life ≈ `ln(2) / α`.

## SPRT (Sequential Probability Ratio Test)

A statistical test that achieves the minimum expected sample size to decide between two hypotheses for fixed error rates ([`./engines/sprt.md`](./engines/sprt.md)). Use when you want to elevate a pattern only after enough evidence.

## LLR (Log-Likelihood Ratio)

The accumulated `log(P(data | H₁) / P(data | H₀))`. The decision variable in SPRT.

## MCP manifest

A JSON-RPC message conforming to the MCP Specification (Model Context Protocol) that exposes
a server's Tools, Resources, and Prompts to an MCP client. The canonical schema reference for
cross-vendor skill interoperability. Specification: `https://spec.modelcontextprotocol.io/`.

---

## Posterior mean / Posterior variance

For a Beta distribution `Beta(α, β)`:

- Mean: `α / (α + β)`
- Variance: `α · β / [(α + β)² · (α + β + 1)]`

Mean is the score; variance is how much to trust it.

## SCC (Strongly-Connected Component)

A maximal mutually-reachable subset of a directed graph. Found in `O(V + E)` by Tarjan's algorithm ([`./engines/scc.md`](./engines/scc.md)).

## LCS (Longest Common Subsequence)

The longest sequence appearing in both inputs while preserving order. Used to measure how much of an anchor sequence survives in a current state ([`./engines/lcs-alignment.md`](./engines/lcs-alignment.md)).

## Tool-descriptor

A structured object, typically JSON or YAML, that describes one tool's name, purpose, input
schema, and behavioral annotations (readOnly, destructive, idempotent, openWorld). OpenAI's
Agents SDK formalizes tool-descriptors with those four annotations. The framework captures
tool identity and purpose in SKILL.md frontmatter; it does not yet capture behavioral annotations.

See [`./conduct/skill-authoring.md`](./conduct/skill-authoring.md) § Cross-vendor schema alignment.

---

## Tree edit distance

Minimum number of insert / delete / relabel operations to transform one tree into another ([`./engines/tree-edit.md`](./engines/tree-edit.md)). Quantifies structural change.

## Aho-Corasick automaton

A finite-state machine built from a fixed set of patterns; scans text in `O(|T| + z)` where `z` is the match count ([`./engines/pattern-detection.md`](./engines/pattern-detection.md)).

## Shannon entropy

```
H(s) = - Σ p(c) · log₂ p(c)
```

A measure of how "random" a string looks. Used to detect generated tokens (secrets, hashes) without a pattern list ([`./engines/entropy-analysis.md`](./engines/entropy-analysis.md)).

---

## All-Add

Anti-pattern memory strategy: appending every observation to working memory without pruning, leading to self-degradation as irrelevant or stale entries crowd out load-bearing ones. The correct alternative is selective, expiry-aware logging. See [`./conduct/memory-hygiene.md`](./conduct/memory-hygiene.md).

## Awareness code

Taxonomy classification for alignment-research failure modes (F19, F20) that are included for completeness but are not expected in routine operational workflows. Awareness codes carry an explicit notice at the top of their per-code doc; their Counter sections reflect red-team and evaluation-protocol responses rather than runtime detection patterns. See [`./taxonomy/README.md`](./taxonomy/README.md) § Per-doc shape.

## Axes (5-axis taxonomy mapping)

An orthogonal layer mapping every F-code to one of five structural axes: memory, reflection, planning, action, or system. Adopted from AgentErrorTaxonomy (arxiv 2509.25370). The flat F01–F21 numbering remains the operational logging identifier; axes are the structural review layer. See [`./taxonomy/axes.md`](./taxonomy/axes.md).

## BamlError

Base exception class in BAML's parser; subclasses indicate specific parse failure modes. See [`./recipes/baml.md`](./recipes/baml.md).

## DFA (Deterministic Finite Automaton)

A finite state machine used to evaluate temporal safety policies in [`./engines/agentproof.md`](./engines/agentproof.md). Given a sequence of agent actions, the DFA advances through states and flags sequences that violate a declared policy.

## Number of Flip

SYCON-Bench metric: how often a model shifts stance under sustained user pressure across a session. Complements Turn of Flip (which measures how quickly the first flip occurs). See [`./conduct/multi-turn-negotiation.md`](./conduct/multi-turn-negotiation.md) and [`./engines/calibration.md`](./engines/calibration.md).

## Turn of Flip

SYCON-Bench metric: how quickly a model conforms to user pressure — specifically, at which turn (counted from the first pushback) the model first abandons a well-founded position. Lower Turn of Flip indicates higher sycophancy risk. See [`./conduct/multi-turn-negotiation.md`](./conduct/multi-turn-negotiation.md) and [`./engines/calibration.md`](./engines/calibration.md).
