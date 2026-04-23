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

## Plugin Ecosystem (modded Minecraft entities)

Shipped today: Wixie, Emu, Crow, Hydra, Sylph. Planned: Pech, Athena, Crucible, Assembler, + 11 more in Phase 3–4.

```
                          ┌─────────────────┐
                          │  ENCHANTED MCP   │
                          │  (unified layer) │
                          └────────┬────────┘
                                   │
    ┌──────────┬──────────┬────────┼────────┬──────────┬──────────┐
    │          │          │        │        │          │          │
┌───▼────┐ ┌──▼───┐ ┌────▼────┐ ┌─▼────┐ ┌─▼──────┐ ┌─▼────┐ ┌───▼──────┐
│  Wixie  │ │Emu │ │ Crow  │ │Hydra│ │ Sylph │ │ Pech │ │  + Phase │
│ prompt │ │token │ │ change  │ │sec-  │ │ git    │ │ cost │ │   3-4    │
│ craft  │ │health│ │ trust   │ │urity │ │ flow   │ │track │ │ plugins  │
│  v3.0  │ │ v2.0 │ │  v1.0   │ │ v1.0 │ │ v0.0.1 │ │ n/a  │ │          │
└────────┘ └──────┘ └─────────┘ └──────┘ └────────┘ └──────┘ └──────────┘
 Alex's   Ars        Alex's  Twilight   Ars      Thaumcraft  Hades, Terraria,
 Mobs     Nouveau    Mobs      Forest     Nouveau              Factorio, ...

  Shipped     Shipped     Shipped    Shipped  Shipped   Planned    Planned
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
Total: 32 named algorithms across 9 products (5 shipped + 4 planned)

Shipped:
  Wixie   (6):   Gauss ─── SAT ─── Game Theory ─── Adaptation ─── Verification ─── Accumulation
  Emu  (5):   Markov ─── Runway ─── Shannon ─── Atomic ─── Dedup
  Crow (6):   Bayesian Trust ─── Semantic Diff ─── Info-Gain ─── Continuity ─── Adversarial ─── Learning
  Hydra (8):   Aho-Corasick ─── Entropy ─── OWASP ─── Action ─── Config ─── Phantom ─── Overflow ─── Threat
  Sylph (5):   Myers-Diff ─── Jaccard-Cosine ─── Workflow Classifier ─── Path-History ─── Gauss Learning (W5)

Planned:
  Pech      (2): Exponential Smoothing ─── Budget Boundary
  Athena    (2): AST Diff ─── Decision Trees
  Crucible  (1): Genetic Mutation
  Assembler (1): Critical Path DAG
```

## Hook Lifecycle Coverage

```
SessionStart  ──▶  Hydra (config-shield: scan for repo-level attacks)
              ──▶  Sylph (capability-memory: provider registry, GitLab probe)

PreToolUse    ──▶  Emu  (token-saver: compress output, block dupes)
              ──▶  Hydra (action-guard: block dangerous commands)
              ──▶  Sylph (sylph-gate: destructive-op decision gate)

PostToolUse   ──▶  Emu  (context-guard: drift detection, runway)
              ──▶  Crow (change-tracker: semantic diff, trust scoring)
              ──▶  Hydra (secret-scanner, vuln-detector, audit-trail)
              ──▶  Sylph (boundary-segmenter: task-boundary clustering)

PreCompact    ──▶  Emu  (state-keeper: checkpoint before compaction)
              ──▶  Crow (session-memory: save continuity graph)
              ──▶  Sylph (sylph-learning: persist developer preferences)
```

## Game Origin Reference

| Game | Plugin | Why this game fits |
|------|--------|-------------------|
| Ars Nouveau | Wixie | A cauldron-summoned familiar that iterates ingredients until the brew carries the right properties — enchanting prompts |
| Alex's Mobs | Emu | A flightless bird with long-range vision that spots threats on the horizon before they arrive — token horizon watching |
| Alex's Mobs | Crow | A sharp-eyed corvid that inspects every object it finds, remembers faces, and sorts friend from threat — change observation |
| Twilight Forest | Hydra | A multi-headed boss whose heads regenerate faster than they can be severed — suppress one surface and two more emerge — security scanning |
| Thaumcraft | Pech | Short hooded hoarders that pick up every dropped item and track every token in their packs — cost accounting |
| Hades | Athena | A game where gods judge your performance and reward excellence with boons — quality is earned |
| Terraria | Crucible | A game where you forge items in increasingly extreme conditions to prove their worth |
| Factorio | Assembler | A game that IS automation — every machine connects to the next in an optimized pipeline |
| Ars Nouveau | Sylph | A wind elemental that threads air currents between distant points, carrying seeds across long distances to stitch the landscape — weaving branches, commits, and PRs into one history |

## Infrastructure

Beyond the plugins themselves, the ecosystem has one meta-artifact:

| Repo | Role |
|------|------|
| [`enchanted-plugins/schematic`](https://github.com/enchanted-plugins/schematic) | Canonical repo template. Every new sibling is cloned from here. Ships the invariant tree: `.claude-plugin/`, `CLAUDE.md` (8-section canonical shape), 10 `shared/conduct/*.md` behavioral modules, `docs/architecture/` auto-generation pipeline, `plugins/example-subplugin/` skeleton, renderer toolchain, tests scaffold. The template itself is never installed — it exists to be cloned. |

The architectural contract for the template is defined in [brand-guide.md § Plugin Structure Standard](brand-guide.md#plugin-structure-standard).
