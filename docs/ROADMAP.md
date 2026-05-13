# Enchanted Plugins Roadmap

**Vision:** Build the algorithm-driven operating system for AI-assisted development. 20 plugins connected through an MCP client, each backed by a named formal algorithm.

## Architecture Phases

```
Phase 1 (NOW)          Phase 2               Phase 3               Phase 4
5 plugins              MCP Client POC        10 plugins            Production MCP
Individual installs    Unified interface     Full coverage         Real-time dashboard
                                                                   Developer adoption
```

---

## Foundation Infrastructure

Before the first plugin ships, the ecosystem needs one shared piece: the repo template every sibling is cloned from.

| Repo | Role | Status |
|------|------|--------|
| [`enchanter-ai/schematic`](https://github.com/enchanter-ai/schematic) | Canonical repo template. Ships the 8-section CLAUDE.md, `shared/vis/conduct/*.md` modules (vendored from vis), `docs/architecture/` auto-generation pipeline, `plugins/example-subplugin/` skeleton, renderer toolchain. Never installed — cloned. | Shipped |

The template is the contract. When it drifts, all downstream siblings drift — so changes to `schematic` are treated as brand-standard changes, not per-plugin improvements.

---

## Phase 1: Core 5 Plugins (Foundation)

The first 5 plugins answer the 5 fundamental questions of AI-assisted development.

| # | Plugin | Question | Algorithms | Version | Status |
|---|--------|----------|------------|---------|--------|
| 1 | **Wixie** | What did I say? (prompt quality) | Gauss Convergence, Boolean SAT, Game Theory, Cross-Domain Adaptation | v3.0.0 | Shipped — 7 plugins |
| 2 | **Emu** | What did I spend? (token health) | Markov Drift, Shannon Compression, Linear Runway, Atomic Serialization | v2.0.0 | Shipped — 4 plugins |
| 3 | **Crow** | What just happened? (change comprehension) | Bayesian Trust, Semantic Diff, Information-Gain, Session Continuity | v1.0.0 | Shipped — 5 plugins |
| 4 | **Hydra** | Is it safe? (security) | Aho-Corasick, Shannon Entropy, Config Poisoning, Phantom Dependency, EMA Posture Decay | v1.0.0 | Shipped — 6 plugins |
| 5 | **Pech** | What did it cost? (spend tracking) | Exponential Smoothing, Budget Forecasting | — | Not started |

### Milestone: 5 plugins shipped
- Each plugin is a standalone Claude Code marketplace
- Each follows @enchanter-ai brand standard
- Each has named algorithms, managed agents, self-learning
- Users install individually: `/plugin marketplace add enchanter-ai/<name>`

---

## Phase 2: MCP Client POC (Unification)

Build `enchanted-mcp` — a Model Context Protocol client that connects all 5 plugins into a single orchestration layer.

### What the MCP Client Does

```
enchanted-mcp
├── Connects to all installed enchanter-ai via MCP
├── Unified dashboard: prompts + tokens + changes + security + costs
├── Cross-plugin intelligence:
│   ├── Wixie detects bad prompt → Emu shows token waste from it
│   ├── Crow flags risky change → Hydra scans it for vulnerabilities
│   ├── Pech shows cost spike → traces to which plugin/session caused it
│   └── All learnings shared across plugins (Gauss Accumulation network)
└── Single install: `npx enchanted-mcp` or Docker container
```

### Architecture

```
┌──────────────────────────────────────────────┐
│              enchanted-mcp (client)           │
│                                              │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │  Wixie   │ │  Emu  │ │  Crow  │  ...  │
│  │  (MCP)  │ │  (MCP)  │ │  (MCP)  │       │
│  └────┬────┘ └────┬────┘ └────┬────┘       │
│       │           │           │              │
│  ┌────▼───────────▼───────────▼────┐        │
│  │     Cross-Plugin Intelligence    │        │
│  │     Shared learnings.json        │        │
│  │     Unified event bus            │        │
│  └──────────────────────────────────┘        │
│                                              │
│  ┌──────────────────────────────────┐        │
│  │     Dashboard (localhost:3000)    │        │
│  │     Real-time session overview    │        │
│  └──────────────────────────────────┘        │
└──────────────────────────────────────────────┘
```

### Milestone: POC MCP client
- Connects to Wixie + Emu + Crow + Hydra + Pech
- Shared event bus for cross-plugin signals
- Basic web dashboard showing unified session view
- Cross-plugin learnings (Gauss Accumulation network)

---

## Phase 3: 10 Plugins (Full Coverage)

Add 5 more plugins covering code quality, testing, DevOps, documentation, and API design.

| # | Plugin | Question | Algorithm | Category |
|---|--------|----------|-----------|----------|
| 6 | **Lich** | Is this code good? | Cousot Interval + Falleri Structural Diff + Zheng Pairwise | Code review |
| 7 | **Crucible** | Do the tests catch bugs? | Genetic Mutation Testing | Testing/QA |
| 8 | **Assembler** | Can this deploy? | Critical Path DAG Optimization | DevOps/CI |
| 9 | **Scribe** | Is the docs up to date? | TF-IDF Extractive Summarization | Documentation |
| 10 | **Schema** | Is the API contract valid? | Semantic Version Diffing | API design |

> **Retired:** Athena (originally planned for slot #6) was retired before implementation. Lich replaces it with a more rigorous algorithm stack (Cousot Interval Analysis + Falleri Structural Diff + Zheng Pairwise Comparison) that provides static-analysis-grade code review rather than heuristic AST diff alone.

### Milestone: 10 plugins + enhanced MCP
- All 10 plugins connected to enchanted-mcp
- Dashboard shows full development lifecycle
- Cross-plugin intelligence covers: prompt → code → test → security → deploy → docs
- Plugin-to-plugin event triggers (Crow flags change → Lich auto-reviews → Crucible tests)

---

## Phase 4: Production MCP (Developer Adoption)

### 15 More Plugins

| # | Plugin | Algorithm | Category |
|---|--------|-----------|----------|
| 11 | **Beacon** | Isolation Forest Anomaly Detection | Observability |
| 12 | **Nexus** | Topological Sort + Dependency DAG | Multi-repo |
| 13 | **Comply** | SPDX License Graph Resolver | Compliance |
| 14 | **Prism** | WCAG Rule Engine + axe-core | Accessibility |
| 15 | **Tempo** | Statistical Flame Graph Sampling | Performance |
| 16 | **Rosetta** | Levenshtein Fuzzy Deduplication | i18n |
| 17 | **Onboard** | Spaced Repetition (SM-2) | Learning |
| 18 | **Synapse** | CRDT Knowledge Merging | Collaboration |
| 19 | **Vault** | Three-Way Merge Diffing | Database |
| 20 | **Relay** | Event Sourcing + Saga Pattern | Webhooks |
| 21 | **Sylph** ✓ | Jaccard-Cosine Boundary Segmentation + Myers-Diff Conventional Classifier | Git workflow (shipped early — v0.0.1, 9 plugins) |

### Production MCP Features

- Real-time web dashboard with WebSocket updates
- Team mode: shared learnings across developers
- Cost alerts and budget enforcement
- Plugin marketplace within the MCP (install/remove from dashboard)
- API for external integrations (Slack, Linear, Jira)
- Telemetry and analytics (opt-in)
- Plugin SDK for third-party developers

### Milestone: 21 plugins + production MCP
- Full developer operating system
- Every stage of AI-assisted development covered
- Algorithm-driven, agent-managed, self-learning at every layer
- Active developer community
- Third-party plugin ecosystem

---

## Timeline

| Phase | Milestone | Plugins | Target |
|-------|-----------|---------|--------|
| 1 | Foundation | 5 (Wixie, Emu, Crow, Hydra, Pech) — 4/5 shipped (Pech not started) | Q2 2026 |
| 2 | MCP POC | 5 + MCP client | Q3 2026 |
| 3 | Full Coverage | 10 + enhanced MCP | Q4 2026 |
| 4 | Production | 21 + production MCP — Sylph (#21) shipped early | Q1 2027 |

---

## Naming Convention

Every plugin is named after a game entity that metaphorically describes its function.

| Plugin | Entity | Game | Why |
|--------|--------|------|-----|
| **Wixie** | Enchantment Orbs | Minecraft | XP orbs that power the enchantment table — enchanting prompts |
| **Emu** | Emu Mob | Minecraft | Flying creature that collects items and brings them to you — collecting tokens |
| **Crow** | Crow | Hollow Knight | Ravenant protector who watches, tests, and judges from the shadows — watching changes |
| **Hydra** | Hydra Leviathan | Subnautica | You hear it before you see it. Hunts in the dark. Relentless. Nothing gets past it — security scanning |
| **Pech** | Tom Pech | Animal Crossing | Merchant-banker who tracks every bell you owe — cost accounting |
| **Athena** | Athena | Hades | Goddess of wisdom who judges your combat quality and grants boons for excellence — code review |
| **Crucible** | Crucible | Terraria | Endgame crafting station forged in hellfire — tests things to destruction — mutation testing |
| **Assembler** | Assembling Machine | Factorio | Takes parts in, produces artifacts out, chains into automated pipelines — CI/CD building |
| **Sylph** | Sylphs | Hollow Knight | Silk-spinners and Crow's ancestral kin who weave threads into coherent patterns — weaving branches, commits, and PRs into one history |

## Brand Standard (All Plugins)

Every @enchanter-ai product must:

1. Name every engine after a formal algorithm
2. Delegate background work to managed agents (Opus/Sonnet/Haiku)
3. Persist learning across sessions (Gauss Accumulation)
4. Report honest numbers — never inflate claims
5. Use atomic operations and handle race conditions
6. Maintain zero external dependencies (bash + jq for hooks, Python stdlib for scripts)
7. Include tests, dark-themed PDF reports, and comprehensive documentation
8. Follow the Emu-style plugin marketplace structure

---

## Algorithm Registry

Every named algorithm across the ecosystem:

| ID | Name | Product | Engine |
|----|------|---------|--------|
| F1 | Gauss Convergence | Wixie | Standard deviation minimization |
| F2 | Boolean SAT Overlay | Wixie | Hybrid SAT + continuous optimization |
| F3 | Cross-Domain Adaptation | Wixie | Constraint-preserving model translation |
| F4 | Game-Theoretic Security | Wixie | Zero-sum adversarial robustness |
| F5 | Static-Dynamic Verification | Wixie | Structure + behavior dual testing |
| F6 | Gauss Accumulation | Wixie | Cross-session knowledge persistence |
| A1 | Markov Drift Detection | Emu | Hidden state transition recognition |
| A2 | Linear Runway Forecasting | Emu | Token consumption prediction |
| A3 | Shannon Compression | Emu | Information-theoretic output reduction |
| A4 | Atomic State Serialization | Emu | Bounded checkpoint persistence |
| A5 | Content-Addressable Dedup | Emu | Hash-based read deduplication |
| H1 | Semantic Diff Compression | Crow | Multi-file change clustering |
| H2 | Bayesian Trust Scoring | Crow | Prior-posterior change risk assessment |
| H3 | Information-Gain Decision | Crow | Review prioritization by uncertainty reduction |
| H4 | Session Continuity Graph | Crow | Decision-causal relationship persistence |
| H5 | Adversarial Self-Review | Crow | Specific concern generation for risky changes |
| H6 | Gauss Learning (Crow) | Crow | Developer preference accumulation |
| R1 | Aho-Corasick Pattern | Hydra | Multi-pattern secret scanning |
| R2 | Shannon Entropy Analysis | Hydra | High-entropy string detection |
| R3 | OWASP Vulnerability Graph | Hydra | Vulnerability pattern detection |
| R4 | Markov Action Classification | Hydra | Dangerous command classification |
| R5 | Config Poisoning Detection | Hydra | Malicious config interception at SessionStart |
| R6 | Phantom Dependency Detection | Hydra | Slopsquatting / dependency confusion detection |
| R7 | Subcommand Overflow | Hydra | Subcommand injection and overflow detection |
| R8 | EMA Posture Decay | Hydra | Cross-hook EMA threat-rate decay (α=0.3; Roberts 1959) |
| L1 | Exponential Smoothing | Pech | Cost forecasting |
| L2 | Budget Boundary Detection | Pech | Spend threshold alerting |
| W1 | Myers-Diff Conventional Classifier | Sylph | Diff-to-Conventional-Commits classification |
| W2 | Jaccard-Cosine Boundary Segmentation | Sylph | Task-boundary clustering from edit-event stream (defining engine) |
| W3 | Workflow-Pattern Classifier | Sylph | Repo-signal → branching-model inference |
| W4 | Path-History Reviewer Routing | Sylph | Blame-graph reviewer suggestion |
| W5 | Gauss Learning (Sylph) | Sylph | Developer workflow-preference accumulation |

*This is a living document. Update as plugins ship and algorithms evolve. Sylph W1–W5 are seed names from `prompts/sylph-architecture/` — final names emerge from the architecture prompt's output.*
