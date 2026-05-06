# Engines — Algorithmic Primitives for Agent Systems

Audience: anyone designing or auditing the moving parts of an agent system. This folder catalogs the small set of well-studied algorithms that, in practice, do the heavy lifting in production agent stacks.

## What an "engine" is here

An engine is a **named, math-grounded primitive** that a workflow leans on. Not a heuristic. Not a vibe-coded scoring function. Each engine ships with:

1. **Problem** — the question the engine answers.
2. **Formula** — the math, in one or two equations.
3. **Decision rule** — the boundary that turns the math into a verdict.
4. **Complexity** — Big-O for both time and space.
5. **Reference implementation pattern** — language-neutral pseudocode + dependencies.
6. **Failure modes** — when this engine breaks or is the wrong tool.

If you can't fill in those six sections, what you have is a heuristic, not an engine.

## When to add an engine

Add an engine when the same algorithmic question shows up across **two or more** of your workflows and either:

- the cost of getting it wrong is high (security scans, trust scoring, destructive ops), or
- the workflow is in a tight loop where a 10× speedup matters (real-time hooks, per-tool-call validation).

Don't add an engine for:

- one-off computations a single workflow does once,
- LLM judgment calls (those belong in a prompt, not a formula),
- anything you'd be embarrassed to publish a derivation for.

## Naming and labels

Within a project, engines often carry a project-letter prefix (e.g., H1–H5 for project Hydra, W1–W5 for project Sylph). That's a local convenience. In this catalog, engines are named by **what they compute**, not where they live:

- `agentproof.md` — Pre-execution static verification: six structural graph checks + temporal safety policy DFA evaluation (status: concept)
- `boundary-segmentation.md` — Jaccard-Cosine multi-signal clustering
- `calibration.md` — Sycophancy-rate calibration via progressive/regressive ratios — turns doubt-engine prose into a measurable axis
- `drift-detection.md` — Markov drift + EMA learning
- `entropy-analysis.md` — Shannon entropy
- `lcs-alignment.md` — Hunt-Szymanski longest common subsequence
- `llm-bandit.md` — Contextual multi-armed bandit for model-tier routing by cost-adjusted quality reward
- `pattern-detection.md` — Aho-Corasick multi-pattern matching
- `scc.md` — Tarjan strongly-connected components
- `sprt.md` — Wald sequential probability ratio test
- `tree-edit.md` — Zhang-Shasha tree edit distance
- `trust-scoring.md` — Beta-Bernoulli conjugate prior

When projects adopt one of these, they typically wrap it with a project-specific signature and label, but the underlying math is the same.

## How engines compose with conduct

Engines compute; [`../conduct/`](../conduct/) modules govern. An engine reports a number; the conduct says what to do with it (escalate, log, abstain, ship). Don't bake decisions into engines — keep the math pure and let the conduct rule on its output.

Example: `trust-scoring.md` produces a posterior mean ∈ [0, 1]. [`../conduct/verification.md`](../conduct/verification.md) decides what threshold gates a destructive op, and [`../conduct/failure-modes.md`](../conduct/failure-modes.md) names what kind of failure each band represents.

## Reference list

| Engine | Algorithm | Best for |
|--------|-----------|----------|
| Pattern detection | Aho-Corasick | Scan text against a fixed set of patterns in linear time |
| Entropy analysis | Shannon | Detect high-entropy tokens (secrets, random IDs) without a pattern list |
| Trust scoring | Beta-Bernoulli | Online posterior estimate of a probability with conjugate updates |
| Drift detection | Markov + EMA | Catch repeated unproductive patterns in a stream of events |
| LCS alignment | Hunt-Szymanski | Measure how much of an anchor sequence survives in current state |
| Tree edit | Zhang-Shasha (or Wagner-Fischer reduction) | Quantify structural change between two trees (ASTs, configs) |
| Strongly-connected components | Tarjan | Find dependency cycles in O(V+E) over directed graphs |
| Sequential probability ratio | Wald SPRT | Decide between two hypotheses with the minimum sample count |
| Boundary segmentation | Jaccard + cosine + time-decay | Cluster a stream of events into discrete tasks |
| LLM Bandit | Contextual ε-greedy / UCB bandit | Route each invocation to the optimal model tier by cost-adjusted quality reward; warm-starts from a cross-session state file |
| Agentproof | Six structural graph checks + DFA temporal policy evaluation | Verify an agent workflow statically before execution; returns PASS or FAIL with a witness trace (status: concept) |
| Calibration | Progressive/regressive sycophancy ratios | Quantify the F01 sycophancy rate over a session and produce a CALIBRATED / SYCOPHANTIC / OVERCORRECTED verdict |
