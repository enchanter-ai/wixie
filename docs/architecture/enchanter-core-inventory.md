# Enchanter Core Inventory

Cross-repo survey: what to port, what to defer, what to leave behind when building the Enchanter agent runtime.

## TL;DR — five must-port assets

| Asset | Location | Why load-bearing |
|---|---|---|
| `inference-engine.py` | `wixie/shared/scripts/` | The only production statistics layer. SPRT, Beta-Binomial, EMA, atomic JSONL, SHA-1 fingerprinting. No deps. |
| `catalog.json` + 128 elevated patterns | `wixie/plugins/inference-engine/state/` | Irreplaceable cross-session accumulated knowledge. |
| `models-registry.json` | `wixie/shared/` | 255 models, capability profiles. Every tier-routing decision starts here. |
| `convergence.py` + `self-eval.py` | `wixie/shared/scripts/` | 5-axis scoring + 8 SAT assertions + auto-revert. The DEPLOY-bar engine. |
| `vis` conduct (10 modules) | `vis/packages/core/conduct/` | Canonical behavioral rules. |

## Repo-by-repo (one-line each)

- **vis** — Spec-only. 21 conduct modules, 12 algorithm engines, F-code taxonomy, ABI test fixtures
- **wixie** — Prompt engineering runtime. The most complete plugin. Inference engine + 7-stage skill pipeline + 255-model registry
- **hydra** — Security/red-team. 12 plugins, the richest hook example (pre-tool-use deny, secret scan, vuln detect, egress monitor). Aho-Corasick pattern engine
- **lich** — Code quality review. Cousot interval propagation + Falleri structural diff (GumTree) + 5 language adapters
- **sylph** — PR lifecycle. 6 git-host adapters + 7 CI adapters. Atomic state pattern. The cleanest test suite
- **djinn** — Intent preservation via hooks. 5 pure-math engines (LCS, HMM, reservoir, pagerank, EMA). Stdlib, fail-open
- **naga** — Code fingerprinting. TF-IDF + Levenshtein. Lightweight
- **crow** — Trust scoring. Bayesian Beta-Bernoulli per file/author (distinct from wixie's pattern SPRT)
- **emu** — Context budget. Drift-awareness + token instrumentation + state recovery
- **pech** — Cost tracking. Per-session ledger + EMA learning + rate cards + budget watcher
- **gorgon** — Complexity + deps + churn-weighted hotspots. Thin wrappers; value as Lich feed

## Critical architectural questions the inventory surfaced

These were not in the architecture doc. They block Phase 0.

### 1. `vis` vs `vis` — two canonical sources

Both exist. `vis` has a superset (engine specs, recipe files, F15-F21 taxonomy). `CONDUCT_SOURCE.md` in wixie points at `vis`. **Which is the real canonical?** Must resolve before the runtime writes its conduct loader.

### 2. Conduct enforcement gap

Every conduct module is Markdown advisory text. The ABI tests only check Markdown hasn't drifted — not that any runtime *enforces* it. The architecture doc says "runtime-enforced conduct" but doesn't specify the mechanism. How does Python SDK code translate "doubt-engine fires before agreement" into a call interception? This is the core architectural challenge.

### 3. Inference-engine opt-in vs always-on

`WIXIE_INFERENCE_ENABLED=1` is the current rollout switch. The new runtime presumably makes it always-on. The catalog's 128 patterns were accumulated under opt-in mode. Need a reconcile + re-render pass before the first always-on run, or the briefing will be stale.

### 4. Cross-plugin state contracts are informal

Lich reads Hydra's `audit.jsonl`. Crow feeds Lich. Pech exports `learnings.json` for cross-plugin reads. **No JSON Schemas anywhere on these handoff surfaces.** The new runtime must formalize them or the pipeline breaks silently on shape changes.

### 5. Hook dual-mode (sh + py)

Djinn, Hydra, Sylph all ship `.sh` AND `.py` variants of the same hooks. Python is clearly the intended direction. The new runtime should deprecate `.sh` hooks explicitly.

### 6. Model registry drift

255 models, dated 2026-04-24. With current model release cadence the registry drifts within weeks. Need an automated update contract — manual `last_updated` bumps don't scale.

## Tiered porting catalog

### Tier 1 — Must port (no Enchanter without it)

1. `inference-engine.py` — the statistical layer
2. `catalog.json` + `artifacts.jsonl` + briefings — accumulated knowledge
3. `models-registry.json` — tier-routing input
4. `convergence.py` + `self-eval.py` — DEPLOY-bar engine
5. `vis/packages/core/conduct/*.md` (10 modules) — rule corpus
6. `deep-research` SKILL + artifact schema — first engine to port

### Tier 2 — Real value (Phase 2+)

- Hydra `action-guard` + `pattern-engine.py` (Aho-Corasick) — first machine-enforced conduct rule
- `atomic_json.py` / `atomic_state.py` (sylph) — shared state-write primitive
- Djinn engines (LCS, HMM, reservoir, pagerank, EMA) — algorithmic primitives
- `vis/packages/orchestration/engines/*.md` — algorithm derivations
- Lich `mantis-core` language adapters — Python/TS/Go/C++/Java static analysis
- `output-schema.py` — output correctness gate

### Tier 3 — Optional

- Pech `nook-learning` (EMA cost learning, slow-α variant)
- Sylph multi-host PR adapter stack
- Naga TF-IDF + Levenshtein fingerprinting
- Crow Beta-Bernoulli trust scoring
- `report-gen.py` + `html-to-pdf.py` (PDF audit reports)

### Tier 4 — Do NOT port

- One-off simulation scripts in `wixie/state/` (`sim_iter2.py`, `apply_fixes.py`, etc.)
- `inference-stress.py` (dev load-test)
- `rebrand.py` (already run; obsolete)
- `docs/assets/node_modules/**` (vendored MathJax)
- Pre-lifecycle `prompts/*/learnings.json` scratch (superseded by catalog.json)
- Gorgon standalone plugins (value is as Lich feed only)

## Migration order (5 steps)

1. **Port `inference-engine.py`** — verify existing `artifacts.jsonl` replays cleanly. Validates the statistical foundation before anything else is wired.
2. **Resolve `vis` vs `vis`** — pick canonical, run `conduct-sync.sh`, then write the enforcement layer against that single source.
3. **Port `convergence.py` + `self-eval.py` + `models-registry.json`** — the scoring layer. Already tested. Produces DEPLOY/HOLD/FAIL.
4. **Port `atomic_json.py` / `atomic_state.py`** — canonical state-write primitive. Prevents the race conditions `catalog.json` already saw.
5. **Wire Hydra `action-guard` + `pattern-engine.py`** — first machine-enforced conduct rule (destructive-op confirmation, dangerous-command blocking).
