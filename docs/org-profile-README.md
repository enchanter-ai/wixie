# Enchanted Plugins

**Algorithm-driven tools for Claude Code. Managed agents. Mathematical engines. Production-grade.**

We build Claude Code plugins powered by formal mathematical models — not heuristics, not rules of thumb. Every engine is backed by a named algorithm with a proof of concept.

## Two Pillars

### Pillar 1: Managed Agent Networks

Multi-tier agent orchestration where each agent uses the optimal model for its role:

| Tier | Model | Role | Cost |
|------|-------|------|------|
| Orchestrator | Opus | Judgment calls, intent understanding, technique selection | Highest quality |
| Optimizer | Sonnet | Background execution, convergence, adaptation | Balanced |
| Reviewer | Haiku | Validation, pass/fail checks, file integrity | Fastest |

Agents run autonomously in the background. Zero permission prompts. The orchestrator delegates, the optimizer executes, the reviewer validates. If the reviewer finds issues, the optimizer re-runs. Fully autonomous loops.

### Pillar 2: Mathematical & Algorithm-Based Engines

Every engine implements a named mathematical model:

| Engine | Algorithm | What it does |
|--------|-----------|-------------|
| **Gauss Convergence** | Standard deviation minimization | Iterates up to 100 times, each cycle reduces deviation from perfection |
| **Boolean Satisfiability** | Hybrid SAT + continuous optimization | 8 binary assertions overlaid on 5-axis scoring |
| **Game-Theoretic Security** | Zero-sum adversarial testing | 12 attack patterns with quality-preserving defense injection |
| **Constraint-Preserving Transformation** | Semantic-invariant model translation | Convert prompts across 64 models without losing intent |
| **Hidden Markov Detection** | State transition pattern recognition | Detect unproductive loops (read loops, edit reverts, test failures) |
| **Information-Theoretic Compression** | Entropy-bounded output reduction | Compress tool output while preserving semantic content above fidelity threshold |
| **Gauss Accumulation** | Cross-session knowledge persistence | Strategy success rates, pattern detection, unreliable strategy avoidance |

The math isn't documentation. It runs as code.

## Products

### Wixie — Prompt Engineering Platform

7 agents. 64 models. Create, optimize, test, harden, and translate prompts.

```
/plugin marketplace add enchanter-ai/wixie
```

[Repository](https://github.com/enchanter-ai/wixie) · v3.0.0 · 7 plugins · [Science](https://github.com/enchanter-ai/wixie/blob/main/docs/science/README.md)

### Emu — Context Health Toolkit

Token management, drift detection, compaction survival.

```
/plugin marketplace add enchanter-ai/emu
```

[Repository](https://github.com/enchanter-ai/emu) · v2.0.0 · 4 plugins

### Crow — Change Comprehension

Bayesian trust scoring, semantic-diff clustering, and information-gain decision support for Claude Code.

```
/plugin marketplace add enchanter-ai/crow
```

[Repository](https://github.com/enchanter-ai/crow) · v1.0.0 · 5 plugins

### Hydra — Security Guardrails

Secret scanning, vulnerability detection, action guarding, config shielding, and audit logging.

```
/plugin marketplace add enchanter-ai/hydra
```

[Repository](https://github.com/enchanter-ai/hydra) · v1.0.0 · 6 plugins

### Sylph — Git Workflow Layer

Auto-orchestrates branch / commit / PR per task boundary; reads CI status across 9 hosts and 8 CI systems.

```
/plugin marketplace add enchanter-ai/sylph
```

[Repository](https://github.com/enchanter-ai/sylph) · v0.0.1 · 9 plugins

## Infrastructure

### Schematic — Repo Template

The canonical template from which every @enchanter-ai sibling is cloned. Ships the invariant tree: 8-section CLAUDE.md, universal `shared/vis/conduct/*.md` behavioral modules (vendored from vis), `docs/architecture/` auto-generation pipeline, example sub-plugin skeleton, and renderer toolchain. Never installed — cloned.

```
git clone https://github.com/enchanter-ai/schematic.git <your-plugin-name>
```

[Repository](https://github.com/enchanter-ai/schematic)

## The Standard

We believe AI tooling should be:

- **Algorithm-based** — every feature backed by a formal model, not ad-hoc rules
- **Agent-managed** — autonomous multi-tier orchestration, not single-thread execution
- **Self-learning** — engines that accumulate knowledge across sessions and improve over time
- **Honest** — report real numbers, auto-revert on regression, never inflate claims
- **Free** — MIT licensed, Python stdlib, zero dependencies

## Contributing

Both repositories welcome contributions. See each repo's `CONTRIBUTING.md` for guidelines.

## License

MIT
