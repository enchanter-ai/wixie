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

### Flux — Prompt Engineering Platform

6 plugins. 7 agents. 64 models. Create, optimize, test, harden, and translate prompts.

```
/plugin marketplace add enchanted-plugins/flux
```

[Repository](https://github.com/enchanted-plugins/flux) | [Science](https://github.com/enchanted-plugins/flux/blob/main/docs/science/README.md)

### Allay — Context Health Toolkit

3 plugins. 15 tests. Token management, drift detection, compaction survival.

```
/plugin marketplace add enchanted-plugins/allay
```

[Repository](https://github.com/enchanted-plugins/allay) | [Science](https://github.com/enchanted-plugins/flux/blob/main/docs/science/README.md#allay-context-health)

## Infrastructure

### Schematic — Repo Template

The canonical template from which every @enchanted-plugins sibling is cloned. Ships the invariant tree: 8-section CLAUDE.md, 10 universal `shared/conduct/*.md` behavioral modules, `docs/architecture/` auto-generation pipeline, example sub-plugin skeleton, and renderer toolchain. Never installed — cloned.

```
git clone https://github.com/enchanted-plugins/schematic.git <your-plugin-name>
```

[Repository](https://github.com/enchanted-plugins/schematic)

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
