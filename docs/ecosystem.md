# Enchanted Plugins Ecosystem Map

## The Five Questions

Every developer asks these during an AI-assisted session. Each question maps to a plugin.

```
┌──────────────────────────────────────────────────────────┐
│                   Developer Session                       │
│                                                          │
│   "What did I say?"        → Wixie     (prompts)          │
│   "What did I spend?"      → Emu    (tokens)           │
│   "What just happened?"    → Crow   (changes)          │
│   "Is it safe?"            → Hydra   (security)         │
│   "What did it cost?"      → Pech     (spend)            │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

## Three newer questions (Phase 2+)

```
┌──────────────────────────────────────────────────────────────────────┐
│   "Am I still working on what you asked?"   → Djinn   (intent)       │
│   "What does this codebase look like?"      → Gorgon  (structure)    │
│   "Make a new thing that looks like this."  → Naga    (replication)  │
└──────────────────────────────────────────────────────────────────────┘
```

## Plugin Ecosystem (modded Minecraft entities)

Shipped today: Wixie, Emu, Crow, Hydra, Sylph, Djinn. Planned: Pech, Gorgon, Naga, Athena, Crucible, Assembler, + 9 more in Phase 3–4.

```
                          ┌─────────────────┐
                          │  ENCHANTED MCP   │
                          │  (unified layer) │
                          └────────┬────────┘
                                   │
    ┌──────────┬──────────┬────────┼────────┬──────────┬──────────┐
    │          │          │        │        │          │          │
┌───▼────┐ ┌──▼───┐ ┌────▼────┐ ┌─▼────┐ ┌─▼──────┐ ┌─▼────┐ ┌───▼──────┐
│  Wixie  │ │Emu │ │ Crow  │ │Hydra│ │ Sylph │ │ Djinn │ │  + Phase │
│ prompt │ │token │ │ change  │ │sec-  │ │ git    │ │intent│ │   3-4    │
│ craft  │ │health│ │ trust   │ │urity │ │ flow   │ │anchor│ │ plugins  │
│  v4.0  │ │ v2.0 │ │  v1.0   │ │ v1.0 │ │ v0.0.1 │ │ v0.1 │ │          │
└────────┘ └──────┘ └─────────┘ └──────┘ └────────┘ └──────┘ └──────────┘
 Ars       Alex's    Alex's    Twilight   Ars         Ars     Ice and Fire,
 Nouveau   Mobs      Mobs      Forest     Nouveau     Nouveau  Twilight Forest,
                                                              Thaumcraft, ...
  Shipped     Shipped     Shipped    Shipped  Shipped   Shipped    Planned
```

**Phase 2 / Phase 3 — planned plugins**

```
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│   Pech   │ │  Gorgon  │ │   Naga   │ │  Athena  │ │ Crucible │ │ Assembler│
│   cost   │ │  repo    │ │ pattern  │ │  quality │ │  forge   │ │ pipeline │
│  track   │ │structure │ │  shift   │ │  judge   │ │ items    │ │  build   │
│   n/a    │ │   n/a    │ │   n/a    │ │   n/a    │ │   n/a    │ │   n/a    │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
 Thaumcraft  Ice & Fire   Twilight     Hades       Terraria      Factorio
                          Forest
  Planned     Planned     Planned     Planned      Planned       Planned
```

## Data Flow Between Plugins

```
Session Start
     │
     ▼
┌─────────┐    ┌─────────┐    ┌─────────┐
│ Hydra  │───▶│  Wixie   │───▶│  Emu  │
│ scans   │    │ crafts  │    │ tracks  │
│ configs │    │ prompt  │    │ tokens  │
└────┬────┘    └────┬────┘    └────┬────┘
     │              │              │
     │         ┌────▼────┐         │
     │         │ Crow  │         │
     │         │ watches │         │
     │         │ changes │         │
     │         └────┬────┘         │
     │              │              │
     │    ┌─────────▼─────────┐    │
     └───▶│     Pech          │◀───┘
           │  tallies costs   │
           └──────────────────┘
```

## Algorithm Distribution

```
Total: 47 named algorithms across 12 products (6 shipped + 6 planned)

Shipped:
  Wixie   (6):   Gauss ─── SAT ─── Game Theory ─── Adaptation ─── Verification ─── Accumulation
  Emu     (5):   Markov ─── Runway ─── Shannon ─── Atomic ─── Dedup
  Crow    (6):   Bayesian Trust ─── Semantic Diff ─── Info-Gain ─── Continuity ─── Adversarial ─── Learning
  Hydra   (8):   Aho-Corasick ─── Entropy ─── OWASP ─── Action ─── Config ─── Phantom ─── Overflow ─── Threat
  Sylph   (5):   Myers-Diff ─── Jaccard-Cosine ─── Workflow Classifier ─── Path-History ─── Gauss Learning (W5)
  Djinn   (5):   Hunt-Szymanski LCS ─── Baum-Welch HMM ─── Vitter Reservoir ─── PageRank Utterance-DAG ─── Gauss Accumulation (D5)

Planned:
  Pech      (2): Exponential Smoothing ─── Budget Boundary
  Gorgon    (5): Tarjan SCC ─── McCabe Cyclomatic ─── PageRank Symbol-Graph ─── Halstead Volume ─── Gauss Hotspot-Drift (G5)
  Naga      (5): Zhang-Shasha Tree-Edit ─── Spärck Jones TF-IDF ─── Levenshtein ─── Salton Cosine ─── Gauss Pattern-Fidelity (N5)
  Athena    (2): AST Diff ─── Decision Trees
  Crucible  (1): Genetic Mutation
  Assembler (1): Critical Path DAG
```

## Hook Lifecycle Coverage

```
SessionStart    ──▶  Hydra  (config-shield: scan for repo-level attacks)
                ──▶  Sylph  (capability-memory: provider registry, GitLab probe)
                ──▶  Djinn  (intent-anchor: capture first-turn intent → state/anchor.json)
                ──▶  Gorgon (gaze: snapshot AST + import graph + complexity map)  [planned]

UserPromptSubmit──▶  Djinn  (intent-anchor: refresh anchor on new user constraints)

PreToolUse      ──▶  Emu    (token-saver: compress output, block dupes)
                ──▶  Hydra  (action-guard: block dangerous commands)
                ──▶  Sylph  (sylph-gate: destructive-op decision gate)

PostToolUse     ──▶  Emu    (context-guard: drift detection, runway)
                ──▶  Crow   (change-tracker: semantic diff, trust scoring)
                ──▶  Hydra  (secret-scanner, vuln-detector, audit-trail)
                ──▶  Sylph  (boundary-segmenter: task-boundary clustering)
                ──▶  Djinn  (drift-aligner: per-turn LCS + HMM intent preservation)
                ──▶  Gorgon (watcher: incremental refresh of touched nodes)  [planned, Write|Edit only]

PreCompact      ──▶  Emu    (state-keeper: checkpoint before compaction)
                ──▶  Crow   (session-memory: save continuity graph)
                ──▶  Sylph  (sylph-learning: persist developer preferences)
                ──▶  Djinn  (compact-guard: inject intent anchor as compaction hint)
                ──▶  Djinn  (drift-learning: D5 Gauss accumulation of intent-type drift signature)
                ──▶  Gorgon (learning: G5 Gauss accumulation of hotspot-drift)  [planned]
                ──▶  Naga   (learning: N5 Gauss accumulation of pattern-fidelity)  [planned]
```

Naga is otherwise skill-invoked (not hook-driven) by design — it answers "make a new artifact like this one" via `/naga:match`, mirroring Wixie's skill-only lifecycle.

## Game Origin Reference

| Game | Plugin | Why this game fits |
|------|--------|-------------------|
| Ars Nouveau | Wixie | A cauldron-summoned familiar that iterates ingredients until the brew carries the right properties — enchanting prompts |
| Alex's Mobs | Emu | A flightless bird with long-range vision that spots threats on the horizon before they arrive — token horizon watching |
| Alex's Mobs | Crow | A sharp-eyed corvid that inspects every object it finds, remembers faces, and sorts friend from threat — change observation |
| Twilight Forest | Hydra | A multi-headed boss whose heads regenerate faster than they can be severed — suppress one surface and two more emerge — security scanning |
| Thaumcraft | Pech | Short hooded hoarders that pick up every dropped item and track every token in their packs — cost accounting |
| Ars Nouveau | Sylph | A wind elemental that threads air currents between distant points, carrying seeds across long distances to stitch the landscape — weaving branches, commits, and PRs into one history |
| Ars Nouveau | Djinn | A fey familiar bound to a Djinn Charm — a fixed anchor — that faithfully collects every drop back to that anchor without wandering, no matter how long the session runs — long-horizon intent preservation |
| Ice and Fire | Gorgon | A serpent-haired entity whose petrifying gaze freezes those it sees into immutable stone — a fixed structural snapshot of the codebase as it exists right now — repo-structure intelligence |
| Twilight Forest | Naga | A verdant serpent boss whose coiled body shifts to match the terrain of its lair, replicating the form it inhabits — pattern adaptation across artifacts |
| Hades | Athena | A game where gods judge your performance and reward excellence with boons — quality is earned |
| Terraria | Crucible | A game where you forge items in increasingly extreme conditions to prove their worth |
| Factorio | Assembler | A game that IS automation — every machine connects to the next in an optimized pipeline |

## Infrastructure

Beyond the plugins themselves, the ecosystem has one meta-artifact:

| Repo | Role |
|------|------|
| [`enchanter-ai/schematic`](https://github.com/enchanter-ai/schematic) | Canonical repo template. Every new sibling is cloned from here. Ships the invariant tree: `.claude-plugin/`, `CLAUDE.md` (8-section canonical shape), `shared/foundations/conduct/*.md` behavioral modules (vendored from agent-foundations), `docs/architecture/` auto-generation pipeline, `plugins/example-subplugin/` skeleton, renderer toolchain, tests scaffold. The template itself is never installed — it exists to be cloned. |

The architectural contract for the template is defined in [brand-guide.md § Plugin Structure Standard](brand-guide.md#plugin-structure-standard).
