# Inference Engine

<p>
  <a href="../../LICENSE.txt"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-3fb950?style=for-the-badge"></a>
  <img alt="5 engines (U1-U6)" src="https://img.shields.io/badge/Engines-U1%E2%80%93U6-bc8cff?style=for-the-badge">
  <img alt="4 skills + 2 agents" src="https://img.shields.io/badge/Surfaces-4%20skills%20%2B%202%20agents-58a6ff?style=for-the-badge">
  <img alt="Zero runtime deps (bash plus jq plus stdlib)" src="https://img.shields.io/badge/Deps-0-f85149?style=for-the-badge">
  <img alt="Honest numbers contract" src="https://img.shields.io/badge/Honest-Numbers-f0883e?style=for-the-badge">
  <a href="https://www.repostatus.org/#wip"><img alt="Project Status: WIP" src="https://www.repostatus.org/badges/latest/wip.svg"></a>
</p>

> **An @enchanted-plugins product — algorithm-driven, agent-managed, self-learning.**

The cross-session evidence substrate for AI-assisted development. Turns every self-caught failure into a compounding asset the whole ecosystem reads at session start.

**5 formal engines. 4 skills. 2 agents. 95% credible intervals on every elevated pattern. Zero runtime deps.**

> On 2026-04-21 the agent shipped a Flux prompt after one draft and reacted to five user pushbacks instead of running the full lifecycle. The correction was logged as F07.
>
> On 2026-04-22 the inference engine ingested that one artifact, accumulated 5 SPRT observations from the evidence field, crossed the elevation threshold at `LLR = 8.95`, posted `F07` to `state/briefings/flux.md` with posterior mean 0.83 and 95% credible interval 0.55–0.98.
>
> On the next `/converge` invocation, the skill's top-of-context reads *"run all four lifecycle stages in one pass"* before iteration 1. The correction is armed before the next mistake.
>
> Time to elevation: one reconcile. Manual intervention: zero. Honest numbers: every count came from the engine's summary, not the narrator.

---

## Origin

Inference Engine is internally codenamed **Ufopedia** after the research archive in *X-COM: UFO Defense* (MicroProse / Mythos, 1994) — every autopsied alien, recovered craft, and interrogated officer contributed to a growing knowledge base that shaped the next mission. Miss a lesson and the squad dies on a repeat encounter. Read the Ufopedia before dropoff and the outcome is different.

The plugin's *file-system* name is **`inference-engine`** because inside any @enchanted-plugins repo the naming convention is clear-names for commands, hooks, state, and scripts — game names live only at the product/repo level (like `reaper`, `flux`, `weaver`). So the codename and the filesystem name diverge deliberately.

The question this plugin answers: *When the same mistake happens in a fourth independent session, how does every enchanted-plugin see it before the fifth attempt?*

## Who this is for

- Developers who've noticed their AI agent making the same mistake across weeks of sessions and want a principled way to make the correction stick without hard-coding it into every prompt.
- Teams running multi-plugin workflows (Flux + Hornet + Reaper + Mantis) who want cross-plugin failure patterns visible at session start, not buried in 9 separate per-plugin `learnings.json` files.
- Engineers who believe *honest numbers over blind compliance* — elevated patterns ship with posterior means, 95% credible intervals, and EMA-decayed weights, so a consumer can distinguish `LLR=2.9, 1 session` from `LLR=9.8, 6 sessions, weight 0.94`.

Not for:

- Teams satisfied with greppable prose notes in a wiki — the inference engine's value is statistical, not documentary.
- Single-prompt quick jobs — the substrate's value grows with session count. Under three sessions, a shared doc is cheaper.
- Replacing a per-plugin engine — Mantis's M6 Beta-Binomial-per-(developer, rule) stays local. The inference engine adds a cross-session layer on top.

## Contents

- [The Problem](#the-problem)
- [How It Works](#how-it-works)
- [What Makes Inference Engine Different](#what-makes-inference-engine-different)
- [The Full Lifecycle](#the-full-lifecycle)
- [Install](#install)
- [Quickstart](#quickstart)
- [4 Skills, 2 Agents, 5 Engines](#4-skills-2-agents-5-engines)
- [What You Get Per Session](#what-you-get-per-session)
- [The Math Behind Inference Engine](#the-math-behind-inference-engine)
- [Architecture](#architecture)
- [Opt-in + Graceful Degradation](#opt-in--graceful-degradation)
- [Relationship to Per-Plugin Learning Engines](#relationship-to-per-plugin-learning-engines)
- [vs Everything Else](#vs-everything-else)
- [Agent Conduct Modules](#agent-conduct-modules)
- [Testing](#testing)
- [Versioning & release cadence](#versioning--release-cadence)
- [Acknowledgments](#acknowledgments)
- [License](#license)

## The Problem

AI-assisted development sessions catch the same mistakes again and again. The plugin ecosystem already has *local* learning engines per plugin (F6 in Flux, H6 in Hornet, M6 in Mantis, L5 in Nook, W5 in Weaver, R8 in Reaper, A7 in Allay) — but they **never talk to each other**. A failure Flux catches during `/converge` never reaches Mantis. A preference Weaver learns never informs Hornet. Seven isolated learning loops.

The literature on AI-era failure modes — Anthropic's Claude Code retrospectives, Shinn et al.'s Reflexion, Park et al.'s Generative Agents, MemGPT, Voyager — converges on one insight: **agents that remember** compound, **agents that rediscover** don't. Reflexion's mechanism (verbal reinforcement from failed trajectories) and Voyager's skill library (new skills build on old) both rely on a single shared memory surface.

The enchanted-plugins ecosystem had six per-plugin *memories* and no *substrate*. Every session started from the same level of naïveté. That is the problem.

## How It Works

The inference engine is a four-stage pipeline over an append-only event stream. One line per artifact; one stream per month; one atomic catalog.

```
  emit                    reconcile                       render-briefing           consume
  ─────                   ─────────                       ────────────────          ───────
  plugin catches          U1 fingerprint                  filter elevated           target plugin
  a failure or            U2 Wald SPRT                    sort by weight            reads at
  precedent  ───►         U3 Beta-Binomial  ───►          write markdown   ───►     session start
  emits JSONL             U5 EMA decay                    to state/briefings        via U-curve top
  to artifacts-*.jsonl    U6 Reservoir                    /<plugin>.md              slot
                          atomic catalog.json
```

**U1 — Pattern fingerprint** is a SHA-1 over `(code, sorted(tags))`. Identical patterns across weeks collapse to one record; paraphrased titles don't split the evidence.

**U2 — Wald SPRT** (Sequential Probability Ratio Test, Wald 1945) accumulates log-likelihood ratios per observation. Under the null *"this is noise"* with `p₀ = 0.05`, versus alternative *"this is real recurrence"* with `p₁ = 0.30`, each positive observation adds `log(p₁/p₀) ≈ 1.79` to the running LLR. Elevate when `LLR ≥ log((1−β)/α) ≈ 2.89`; retire when `LLR ≤ log(β/(1−α)) ≈ −2.25`.

**U3 — Beta-Binomial posterior** (Thompson 1933) maintains `(α, β)` per pattern, starting at `Beta(1, 1)` (uniform prior). Each recurrence adds one to `α`; each session-without-recurrence adds one to `β`. Posterior mean `α / (α + β)` is a calibrated estimate of recurrence probability; the 95% credible interval is computed via bisection over the regularized incomplete beta function — stdlib only, no scipy.

**U5 — EMA decay** (Roberts 1959) applies `weight ← weight · exp(−λ · Δt)` with half-life `λ = ln(2) / 30 days`. A pattern unseen for 30 days weighs half what it did when last observed. Patterns that were true once but no longer recur retire naturally.

**U6 — Reservoir sampling** (Vitter 1985, Algorithm R) retains up to `K = 50` raw artifact references per pattern under bounded memory. Even if a pattern recurs hundreds of times, the substrate keeps a uniform random sample — the briefing stays readable and the state file stays small.

U4 (Bayesian Online Change-point, Adams & MacKay 2007) is deferred to Phase 1b — it matters only once a pattern's distribution shifts after elevation. Shipping without it keeps the MVP focused.

## What Makes Inference Engine Different

### Honest numbers, not a dashboard

Every elevated pattern ships with three numbers that mean something:

- **Posterior mean** — calibrated recurrence probability from the Beta-Binomial update.
- **95% credible interval** — the actual uncertainty. `F07` is `posterior 0.83, CI 0.55–0.98` — wide because we have only one session of evidence; the interval narrows as sessions accumulate.
- **EMA-decayed weight** — time-weighted relevance. A pattern elevated six months ago with no recurrences weighs roughly `0.01`; the briefing renderer drops it below the fold.

No vanity counters. No "99.4% sure". The engine's verdict is honest: `elevated`, `noise`, or `retired`, with the evidence visible.

### Stdlib only

Wald SPRT, Beta-Binomial posteriors, beta-quantile via regularized incomplete beta, EMA decay, reservoir sampling — all in `math`, `hashlib`, `json`, `random`, `pathlib`. No scipy. No numpy. No pandas. No npm. The `bash + jq + Python stdlib` brand contract held at every step.

### Append-only + atomic

Artifacts are append-only (the stream is a log, not a table). Catalog writes are atomic via `tmp-file + rename` — the catalog either reflects the old reconcile or the new one, never a half-written state. Honest even under a concurrent reconcile + briefing render.

### Complements, never replaces

The seven per-plugin engines stay exactly where they are. Mantis's M6 still computes Beta-Binomial-per-(developer, rule). Flux's F6 still writes per-prompt `learnings.json`. Reaper's R8 still applies EMA over threat-rate observations. The inference engine reads the same kinds of events and *adds* a cross-plugin layer.

### Game metaphor that actually fits

Ufopedia wasn't a passive log in X-COM — it was the loop that made the next mission winnable. Autopsies fed weapons research; interrogations fed base defence. Every elevated pattern in the engine's catalog is an X-COM research entry: unlock it and the next run is different.

## The Full Lifecycle

Five stages from failure to countermeasure:

1. **Observation.** A plugin catches a failure (Flux notices reactive iteration, Hornet flags a silent revert, Reaper classifies a new attack pattern). The plugin composes a JSON artifact with `code`, `category`, `title`, `cause`, `counter`, `signal`, `tags`, and `evidence`.

2. **Emission.** The plugin calls `inference-engine.py emit` (or the `inference-emit.sh` bash wrapper). The engine stamps `ts`, `session_id`, `plugin`, appends to `state/artifacts-YYYY-MM.jsonl`. Opt-in gate `FLUX_INFERENCE_ENABLED=1` required; otherwise silent no-op.

3. **Reconciliation.** Triggered manually, on schedule, or after an artifact write. The engine loads every artifact, fingerprints, runs SPRT + Beta-Binomial + EMA + Reservoir, writes `catalog.json` atomically. Idempotent on identical streams.

4. **Briefing.** The briefer agent renders `state/briefings/<plugin>.md` — filtered to that plugin's tags, sorted by weight, formatted for human + machine reading.

5. **Consumption.** At session start the target plugin's primary skill (Phase 1: `/converge` in Flux) reads the briefing at top-of-context. The U-curve top-200-tokens slot (`shared/conduct/context.md`) means the learned patterns are the first thing Claude sees.

## Install

Part of the Flux bundle. The simplest install is the `full` meta-plugin:

```
/plugin marketplace add enchanted-plugins/flux
/plugin install full@flux
```

Standalone:

```
/plugin install inference-engine@flux
```

## Quickstart

```bash
# Enable during rollout
export FLUX_INFERENCE_ENABLED=1

# Backfill from precedent.jsonl (the human-written archive — 6 rows)
python flux/shared/scripts/inference-engine.py backfill flux/state/precedent.jsonl

# Run the first reconcile
python flux/shared/scripts/inference-engine.py reconcile

# Render the Flux briefing
python flux/shared/scripts/inference-engine.py render-briefing flux

# Verify
cat flux/plugins/inference-engine/state/briefings/flux.md
```

Or via skills:

```
/inference-emit          # append one artifact from structured input
/inference-reconcile     # re-run the catalog
/inference-brief flux    # render the briefing
/inference-query F07     # search the catalog
```

## 4 Skills, 2 Agents, 5 Engines

| Sub-plugin / Skill           | Owns                                       | Trigger          | Agent tier |
|------------------------------|--------------------------------------------|------------------|------------|
| `skills/inference-emit/`     | Artifact emission to the append-only stream| skill-invoked    | —          |
| `skills/inference-reconcile/`| Full reconcile: U1 + U2 + U3 + U5 + U6     | skill-invoked    | Sonnet     |
| `skills/inference-brief/`    | Per-plugin briefing render                 | skill-invoked    | Haiku      |
| `skills/inference-query/`    | Catalog search by code / tag / pattern_id  | skill-invoked    | —          |

| Agent         | Tier   | Role                                                                     |
|---------------|--------|--------------------------------------------------------------------------|
| `reconciler`  | Sonnet | Long-running statistics; reads all artifacts; atomic catalog write       |
| `briefer`     | Haiku  | Shape-check + formatting; filter + sort + render markdown                |

| Engine | Algorithm                                   | Paper / source                                       |
|--------|---------------------------------------------|------------------------------------------------------|
| U1     | SHA-1 pattern fingerprint                   | FIPS 180-4 (used as content-addressable id)          |
| U2     | Wald Sequential Probability Ratio Test      | Wald 1945 — *Sequential Tests of Statistical Hypotheses* |
| U3     | Beta-Binomial conjugate posterior           | Thompson 1933; Russo & Van Roy 2018                  |
| U5     | Exponential Moving Average decay            | Roberts 1959 — *Technometrics*                       |
| U6     | Reservoir sampling (Algorithm R)            | Vitter 1985 — *ACM TOMS*                             |

| Command                  | Agent             |
|--------------------------|-------------------|
| `/inference-emit`        | none — direct call|
| `/inference-reconcile`   | Sonnet            |
| `/inference-brief <p>`   | Haiku             |
| `/inference-query <t>`   | none — direct call|

## What You Get Per Session

One machine-readable catalog. One per-plugin briefing. Honest numbers on every entry.

```
state/catalog.json                             → full catalog, posteriors + CIs + verdicts
state/briefings/flux.md                        → top-of-context briefing for /converge
state/artifacts-YYYY-MM.jsonl                  → append-only stream (one per month)
```

An elevated pattern entry in a briefing looks like:

```markdown
### F07 — Ran seven reactive iterations instead of one-pass Flux lifecycle

- Weight: 0.942   Posterior: 0.833 (95% CI 0.554–0.982)   LLR: 8.95
- Observations: 5 across 1 session(s)   Last seen: 2026-04-21 (1d ago)
- Tags: `flux, lifecycle, convergence, prompt-engineering, process-discipline`

**Signal:** When generating any prompt artifact for Flux, walk the four lifecycle stages in order before the user sees the result.

**Counter:** Run /create → /converge → /test-prompt → /harden in one pass.
```

## The Math Behind Inference Engine

### U1. Pattern Fingerprint

A deterministic, collision-resistant id per semantic pattern:

> fingerprint(code, tags) = first_16_hex(SHA-1(code ‖ '|' ‖ sort(tags).join('|')))

FIPS 180-4 SHA-1 produces 160 bits; truncating to the first 16 hex characters (64 bits) gives a birthday-collision probability of ~2^-32 at a million patterns — adequate headroom for the lifetime of the substrate. The same `code` with reordered tags collapses to the same id; a paraphrased title does not split the evidence.

### U2. Wald Sequential Probability Ratio Test

For each pattern, maintain a running log-likelihood ratio over observations `x₁, x₂, …, xₙ` where each `xᵢ ∈ {0, 1}` indicates recurrence:

> LLR_n = ∑ᵢ xᵢ · log(p₁/p₀) + (1−xᵢ) · log((1−p₁)/(1−p₀))

With `p₀ = 0.05` (noise floor) and `p₁ = 0.30` (real recurrence), each positive observation adds `log(0.30/0.05) ≈ 1.7918`. Wald's optimal stopping rule with false-positive rate `α = 0.05` and false-negative rate `β = 0.10` gives:

> elevate when LLR ≥ log((1−β)/α) = log(0.90/0.05) ≈ 2.890
> retire when LLR ≤ log(β/(1−α)) = log(0.10/0.95) ≈ −2.251
> else: noise

Wald 1945 proves this decision rule minimizes expected observation count at the specified error rates. In practice: three independent positive observations elevate a pattern; ~two sessions of silence after elevation retire it. For single-session artifacts with explicit recurrence counts (e.g. `evidence.iterations = 7`), the engine credits `N` observations from the one artifact — same evidence, same math, faster to first elevation.

### U3. Beta-Binomial Conjugate Posterior

Maintain `(αₙ, βₙ)` per pattern. Starting at `Beta(1, 1)` (uniform prior — no prejudice):

> αₙ₊₁ = αₙ + xₙ (success count)
> βₙ₊₁ = βₙ + (1 − xₙ) (failure count)

Posterior distribution after `n` observations:

> p ~ Beta(αₙ, βₙ)
> posterior mean = αₙ / (αₙ + βₙ)
> 95% credible interval = [I⁻¹(0.025; α, β), I⁻¹(0.975; α, β)]

where `I⁻¹` is the inverse of the regularized incomplete beta function:

> I_x(a, b) = ∫₀ˣ t^(a−1) (1−t)^(b−1) dt / B(a, b)
> B(a, b) = Γ(a) Γ(b) / Γ(a + b)

The engine computes `Γ` via `math.lgamma` (stdlib), Simpson-integrates the incomplete beta integrand over 256 steps, and bisects to 60 iterations for the inverse — adequate for 3-decimal CI reporting and the honest-numbers contract. No scipy required.

### U5. Exponential Moving Average Decay

Pattern weight decays exponentially with time since last observation:

> weight(t) = weight₀ · exp(−λ · (t − t_last))
> λ = ln(2) / 30 days

The 30-day half-life is calibrated to agent development cycles: a pattern unobserved for 30 days is half as relevant; unobserved for 60 days is a quarter. Roberts 1959 proves EMA is the minimum-mean-square-error predictor under geometric-decay loss; the inference engine uses it to decide which elevated patterns a briefing still surfaces.

### U6. Reservoir Sampling (Vitter's Algorithm R)

For each pattern, keep up to `K = 50` raw artifact references under bounded memory. For the n-th observation:

> if len(reservoir) < K: append
> else: j ~ Uniform(0, n); if j < K: reservoir[j] ← new

Vitter 1985 proves this yields a uniform random sample of all observations seen — each artifact has probability `K/n` of being in the reservoir after `n` observations, independent of arrival order. The catalog stays bounded even when a pattern recurs thousands of times.

### Why these five

Each engine answers a different question:

| Engine | Question                                    |
|--------|---------------------------------------------|
| U1     | *Is this the same pattern we've seen before?* |
| U2     | *Is this pattern real or noise?*            |
| U3     | *What's the calibrated probability of recurrence, with honest uncertainty?* |
| U5     | *How much do past observations still matter?* |
| U6     | *Which raw artifacts illustrate this pattern when the catalog is full?* |

Together they turn a JSONL of raw observations into a catalog a plugin can act on — with no black box, no hyperparameters to tune beyond the two Wald thresholds (`α = 0.05, β = 0.10`) and the one EMA half-life (`30 days`).

## Architecture

```
flux/plugins/inference-engine/
├── .claude-plugin/plugin.json           marketplace manifest
├── README.md                            this file
├── agents/
│   ├── reconciler.md                    Sonnet · runs U1/U2/U3/U5/U6
│   └── briefer.md                       Haiku  · renders per-plugin briefings
├── skills/
│   ├── inference-emit/SKILL.md          /inference-emit
│   ├── inference-reconcile/SKILL.md     /inference-reconcile
│   ├── inference-brief/SKILL.md         /inference-brief <plugin>
│   └── inference-query/SKILL.md         /inference-query <term>
├── hooks/hooks.json                     advisory PostToolUse notifier
└── state/
    ├── artifacts-YYYY-MM.jsonl          append-only event stream
    ├── catalog.json                     pattern catalog (atomic writes)
    └── briefings/
        └── flux.md                      top-of-context briefing for /converge

flux/shared/scripts/
├── inference-engine.py                  ≈ 350 LOC stdlib Python, 6 subcommands
└── inference-emit.sh                    ≈ 50 LOC bash wrapper for hook callers

flux/shared/conduct/
└── inference-substrate.md               brand-standard module — how to write/read honestly
```

## Opt-in + Graceful Degradation

The substrate is **off by default**. `emit` is a no-op unless `FLUX_INFERENCE_ENABLED=1`. `reconcile` and `render-briefing` run regardless but are safe on empty state (reconcile over zero artifacts yields an empty catalog; render-briefing writes a placeholder *"no elevated patterns yet"*).

When enabled and later unreachable — filesystem error, missing script, permission problem:

- `emit` from a hook logs to stderr and exits 0 (fail-open; brand contract `hooks.md`).
- `reconcile` aborts with a non-zero exit; the caller reports honestly and does not proceed with stale briefings.
- `render-briefing` on a missing catalog writes the placeholder.
- Any consuming plugin that reads `briefings/flux.md` tolerates a missing or stale file — the briefing is advisory, never load-bearing.

## Relationship to Per-Plugin Learning Engines

Every existing per-plugin learning engine stays local. The substrate publishes *upward* from them; it does not replace any.

| Plugin   | Existing engine                                  | What stays local                               | What flows into substrate |
|----------|--------------------------------------------------|------------------------------------------------|---------------------------|
| Flux     | F6 — learnings.json hypothesis log               | Per-prompt axis progressions, hypothesis log   | Cross-prompt F-codes (F01–F14) |
| Allay    | A7 — Bayesian cross-session accumulation         | Per-strategy compression-success rates         | Drift patterns (A-codes)  |
| Hornet   | H6 — developer-preference accumulation           | Per-file Beta-Bernoulli posteriors             | Cross-session H-codes     |
| Reaper   | R8 — EMA Posture Decay                           | Per-threat EMA rates                           | Novel attack patterns (S-codes) |
| Weaver   | W5 — workflow-preference accumulation            | Per-developer commit/branch preferences        | Cross-session W-codes     |
| Mantis   | M6 — Beta-Binomial per-(developer, rule)         | Per-(developer, rule) posteriors               | Novel rule families (M-codes) |
| Nook     | L5 — cost-pattern accumulation                   | Per-session cost traces                        | Cross-session cost patterns |

This is the branding-drift fix the Casting-Doubt panel caught: only Mantis M6 was genuinely Bayesian; five others were EMA-class. The taxonomy is now honest — engines keep their real mechanisms, the substrate adds the Bayesian layer on top.

## vs Everything Else

| System                       | What it gives you                        | Why it's not this               |
|------------------------------|------------------------------------------|---------------------------------|
| Sentry / Rollbar             | Error clustering + fingerprint           | Cloud-hosted; runtime errors; not cross-session agent patterns |
| LangSmith / LangFuse         | LLM trace annotation + feedback          | Cloud-hosted; per-call focus; no SPRT elevation                |
| Reflexion (Shinn 2023)       | Verbal reinforcement from failed traces  | Per-agent, not cross-plugin; no formal elevation threshold      |
| Voyager (Wang 2023)          | Skill library with hierarchical recall   | Skill granularity ≠ failure granularity; no calibrated posteriors |
| MemGPT (Packer 2023)         | Hierarchical context-window management   | Orthogonal concern; could coexist                               |
| Grep on a wiki               | Free-text recall                         | No elevation logic; no bounded memory; no honest-numbers        |
| Per-plugin `learnings.json`  | Local accumulation                       | What we already have — this plugin is the cross-plugin layer    |

The closest production analog is **Sentry's fingerprint-and-elevate** model, but Sentry elevates by raw occurrence count. The inference engine elevates by *calibrated probability of future recurrence* (SPRT + Beta-Binomial) — the difference matters when a pattern has many occurrences in one session but has never recurred cross-session, or vice versa.

## Agent Conduct Modules

Inherits all 10 `shared/conduct/*.md` modules:

1. `discipline.md` — think-first, simplicity, surgical edits.
2. `context.md` — U-curve placement; the briefing *is* the top-of-context slot.
3. `verification.md` — catalog writes atomic; briefings re-rendered before high-stakes reads.
4. `delegation.md` — reconciler is Sonnet; briefer is Haiku.
5. `failure-modes.md` — F07 was the first elevated code in the substrate.
6. `tool-use.md` — Python stdlib only; no `find`/`grep`/`cat`.
7. `formatting.md` — briefings follow Claude XML-free markdown structure for fast top-of-context parsing.
8. `skill-authoring.md` — each skill names *what* + *when*; auto-trigger phrases present.
9. `hooks.md` — the PostToolUse hook is advisory; never auto-triggers reconcile.
10. `precedent.md` — the ancestry contract for how precedent.jsonl feeds the substrate.

Plus one new module shipped with this plugin:

- `shared/conduct/inference-substrate.md` — emission contract, mutation discipline, recursion bound.

## Testing

```bash
# Unit round-trip: emit → reconcile → brief, on a scratch state dir
export FLUX_INFERENCE_STATE=/tmp/inference-test-$$
mkdir -p "$FLUX_INFERENCE_STATE"
FLUX_INFERENCE_ENABLED=1 python flux/shared/scripts/inference-engine.py backfill \
  flux/state/precedent.jsonl
python flux/shared/scripts/inference-engine.py reconcile
python flux/shared/scripts/inference-engine.py render-briefing flux
cat "$FLUX_INFERENCE_STATE/briefings/flux.md"
rm -rf "$FLUX_INFERENCE_STATE"
```

The Phase 1 acceptance test is the 30-day success criterion: after 30 days of Flux use on a real machine, `state/briefings/flux.md` carries at least one elevated pattern (F07 is the obvious candidate; its evidence count of 5 user pushbacks in one session is enough to cross SPRT on the first reconcile) and `/converge` reads it before iteration 1.

## Versioning & release cadence

- Semantic versioning. `0.1.0` (current) = Phase 1 MVP, Flux-only wiring.
- `0.2.0` = U4 Bayesian Online Change-point. Automatic pattern retirement when distributions shift.
- `0.3.0` = Phase 2 MCP integration. `inference.pattern.elevated` / `.retired` / `.drifted` events over the `enchanted-mcp` bus; file-based fallback preserved.
- `1.0.0` = All seven plugins wired. 90-day cross-plugin recurrence data. Production DEPLOY bar on the substrate's own outputs.

Breaking changes flagged in `CHANGELOG.md`. Pattern-id hashes stable across versions (SHA-1 of `code + sorted(tags)` — changing either is a breaking change for catalog continuity).

## Acknowledgments

- Abraham Wald for SPRT (1945) — still the optimal sequential test 80 years later.
- William Thompson (1933) and the Russo / Van Roy tutorial (Stanford 2018) for making Beta-Binomial posteriors accessible.
- S.W. Roberts (1959) for EMA's minimum-MSE-under-geometric-loss result.
- Jeffrey Vitter (1985) for Algorithm R — a lifetime of bounded-memory streams made possible.
- Shinn et al. (Reflexion, NeurIPS 2023), Wang et al. (Voyager, NeurIPS 2023), Packer et al. (MemGPT, 2023) for the modern agent-memory canon this substrate stands on.
- Allspaw, Dekker, Reason, Leveson — the blameless-postmortem and systems-safety tradition that informs the category names and the honest-numbers contract.
- The X-COM: UFO Defense design team (Mythos / MicroProse, 1994) for a research-archive loop that taught a generation of engineers what *compounding evidence* looks like in a game mechanic.

## License

MIT. See repo root.
