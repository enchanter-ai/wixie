# Enchanter Agent — Architecture

## Vision

The Enchanter agent is a purpose-built agent runtime that enforces the Enchanter ecosystem's contracts — tier routing, conduct injection, DEPLOY-bar verification, lifecycle auto-fire, cost accounting, and cross-session learning — at the process level rather than relying on LLM self-compliance. Claude Code is the current substrate, and it works well for developers who have internalized the full conduct stack; but a developer who has never read `discipline.md` or `tier-sizing.md` gets no guardrail from the system. The Enchanter agent flips that: contracts live in Python, not prose, so a naïve developer invoking `/create` gets the same tier routing, conduct injection, DEPLOY-bar check, and precedent pre-screen as an expert. It is not a replacement for Claude Code's general capabilities; it is a thin, opinionated wrapper that "eats" Enchanter's own enhancements rather than referencing them.

---

## What gets runtime-enforced

| Contract | How the runtime enforces it |
|---|---|
| **Tier routing** | `tier_router.py` maps the active skill to its declared `model` field from `SKILL.md` frontmatter; rejects calls that route a Haiku-declared validator task to Opus. Returns an error payload before any API call fires. |
| **Conduct injection (system prompt, U-curve)** | `conduct_injector.py` builds the system prompt for every agent call: top-200-token slot gets role + task + hard constraints; conduct modules relevant to the subagent's tool whitelist are injected via Pattern B (whitelist inject) per `delegation.md` § Whitelist inject; bottom-200-token slot repeats the DEPLOY-bar and no-regression constraint. |
| **Lifecycle auto-fire** | `loop.py` reads the skill's declared `lifecycle_position` and auto-fires adjacent skills when artifacts are stale: if `/create` is invoked and `claims.json` freshness ≥ 30 days, E0 is auto-dispatched first; if `/converge` exits HOLD three times on the same axis, the loop stops and escalates. |
| **DEPLOY-bar verification** | `verifier.py` runs the 8 SAT assertion checks and computes σ across the 5 axes deterministically after every `/converge` round; the loop gate blocks DEPLOY verdict unless σ < 0.45, overall ≥ 9.0, all axes ≥ 7.0, and 8/8 assertions pass. Self-certification by the model is not accepted — the runtime check is the gate. |
| **Cost ledger** | `cost_ledger.py` tracks token spend per tier per session and per-skill; enforces the tier cost contract (F-code logged on Haiku task routed to Opus); writes a session summary to `state/cost-log.jsonl` on exit. |
| **Precedent log pre-check** | `precedent_check.py` greps `state/precedent-log.md` for the current command verb and relevant tags before every non-trivial Bash dispatch; surfaces hits as a system message per `precedent.md` § Consult-then-act protocol. |
| **Doubt-engine middleware** | `doubt_engine.py` wraps the reply gate: before any DEPLOY / DONE / SHIP verdict is emitted, it runs the four-step pass defined in `doubt-engine.md` as a deterministic schema check (verdict present → steelman field present → evidence field non-empty → surfaced-or-skipped boolean). Verdicts that skip the pass are blocked. |
| **Failure-mode auto-tagging** | `tool_middleware.py` intercepts tool-call errors and reply-gate failures and appends a tagged entry to `state/failure-log.md` using the 21-code taxonomy from `failure-modes.md`. Tags are derived from the error shape (self-certification attempt → F16, parallel writes to same path → F09, stale verdict → F12). |
| **Briefing read on session start** | `briefing_loader.py` reads `plugins/inference-engine/state/briefings/<plugin>.md` at session boot and places it in the top-200-token slot of the orchestrator's system prompt, per `inference-substrate.md` § Reading a briefing. Skips silently if `WIXIE_INFERENCE_ENABLED` is unset. |

---

## What stays prompt-conveyed

These rules are judgment-dependent; the runtime guarantees they are injected but cannot guarantee follow-through.

| Contract | Why it can't be code-enforced | Runtime guarantee |
|---|---|---|
| **Think-first** (surface assumptions, name the tradeoff) | Requires the model to reason about what it doesn't know | `conduct_injector.py` injects `discipline.md` § Think before coding into every orchestrator system prompt |
| **Simplicity-first** (three lines beats premature abstraction) | Requires judgment about what counts as speculative | Injected via Pattern B for any subagent with Write/Edit in its tool whitelist |
| **Surgical changes** (touch only flagged lines) | Diff read-back is a signal, not a blocker | `verifier.py` runs post-change diff read-back and emits a structured warning; the developer decides |
| **Doubt-engine four-step pass** (steelman + concrete evidence) | Evidence quality is a model judgment | `doubt_engine.py` enforces the structural schema (all four fields present); it cannot verify that the steelman is genuine |
| **Ask, don't guess** (unknown metadata fields) | Depends on model recognizing its own ignorance | Injected as a hard constraint in the top-200-token slot; enforced via the reply gate blocking fabricated scores (SAT assertion `no_fabricated_scores` added to the 8-assertion set) |
| **Format follows model** (XML for Claude, sandwich for GPT) | Translation quality is a model judgment | `tier_router.py` reads `target_model` from `metadata.json` and injects the correct format convention; it does not verify the model followed it |
| **Image escalation** (wait for developer rating) | Loop termination depends on developer input | `loop.py` detects `target_model` in the image-model set and injects the escalation constraint; it cannot force the model to wait |

---

## Substrate decision

**Claude Agent SDK (Python).** Three reasons: `inference-engine.py` already exists as a Python script with atomic writes, SHA-1 fingerprinting, and Wald SPRT logic; the SDK's `Agent` constructor exposes `system_prompt`, `model`, and `tools` as first-class parameters, which maps cleanly to the conduct injector and tier router; and the existing `SKILL.md` frontmatter (`model`, `tools`, `allowed-tools`) can be parsed directly without a new schema.

**LiteLLM** is the multi-model shim: any skill targeting a non-Anthropic model (GPT, Gemini, o-series) routes through `litellm.completion()` rather than the Anthropic SDK directly. This keeps `tier_router.py` model-agnostic and avoids per-provider SDK dependencies in the core loop. LiteLLM is optional at Phase 0; it becomes mandatory in Phase 4 when `/translate-prompt` runs end-to-end through the runtime.

---

## Core loop

```python
# runtime/loop.py — Enchanter agent core loop (pseudocode, ~30 lines)

async def run_session(skill_path: str, args: dict) -> SessionResult:
    skill = parse_skill_frontmatter(skill_path)          # name, model, tools, lifecycle_position
    plugin = detect_plugin(skill_path)

    # Session boot
    briefing = briefing_loader.load(plugin)              # inference-substrate.md § Reading a briefing
    precedent_hits = precedent_check.query(skill.name, args)  # precedent.md § Consult-then-act

    # Build system prompt (U-curve: top + middle + bottom)
    system_prompt = conduct_injector.build(
        skill=skill,
        briefing=briefing,
        precedent_hits=precedent_hits,
    )                                                    # delegation.md § Whitelist inject

    # Tier gate: reject mis-routed calls before any API spend
    tier_router.validate(skill.model, task_class=skill.name)  # tier-sizing.md § The principle

    agent = sdk.Agent(model=skill.model, system_prompt=system_prompt,
                      tools=tool_middleware.wrap(skill.tools))

    cost_ledger.begin_session(skill.name, skill.model)

    # Main reply loop
    async for turn in agent.run(user_message=args["input"]):
        tool_middleware.intercept(turn)                  # auto-tag F-codes on errors
        reply = turn.final_message

        # Lifecycle auto-fire: stale research, HOLD escalation
        lifecycle_result = lifecycle_check(skill, reply, state_dir=plugin.state_dir)
        if lifecycle_result.requires_upstream:
            await run_session(lifecycle_result.upstream_skill, lifecycle_result.args)

        # Reply gate: doubt pass + DEPLOY-bar
        if is_verdict(reply):
            doubt_engine.check(reply)                    # doubt-engine.md § The four-step pass
            verifier.check_deploy_bar(reply, plugin)     # verification.md § Verification is not optional

        cost_ledger.record_turn(turn)

        if turn.is_final:
            break

    cost_ledger.end_session()
    return SessionResult(reply=reply, artifacts=plugin.artifacts())
```

---

## Module map

| Module | Responsibility |
|---|---|
| `runtime/loop.py` | Session boot, main agent-turn loop, lifecycle auto-fire, session teardown |
| `runtime/tier_router.py` | Reads `SKILL.md` `model` field; validates tier-to-task assignment; rejects mis-routes before API call; maps tier names to LiteLLM model IDs |
| `runtime/conduct_injector.py` | Builds the system prompt: top-200-token slot (briefing + constraints), middle (conduct modules selected by tool whitelist per Pattern B), bottom-200-token slot (DEPLOY bar + no-regression reminder) |
| `runtime/tool_middleware.py` | Wraps each tool call: pre-call precedent grep for Bash, post-call error intercept with F-code tagging, parallel-write race detection |
| `runtime/verifier.py` | Runs 8 SAT assertions and σ check after every `/converge` round; runs post-change diff read-back for code edits; blocks DEPLOY until all criteria clear |
| `runtime/cost_ledger.py` | Tracks token spend by tier, skill, and session; enforces tier cost contract; writes `state/cost-log.jsonl`; reads `cost-accounting.md` ceiling |
| `runtime/doubt_engine.py` | Wraps the reply gate: on any DEPLOY/DONE/SHIP verdict, asserts four-step pass schema (proposal → steelman → evidence → surfaced); blocks verdicts that omit evidence |
| `runtime/precedent_check.py` | Greps `state/precedent-log.md` for the command verb and tags before Bash dispatch; returns hits as structured advisory injected into system prompt |
| `runtime/briefing_loader.py` | Reads `plugins/inference-engine/state/briefings/<plugin>.md` at session boot; respects `WIXIE_INFERENCE_ENABLED` gate; places briefing in top-200-token slot |

---

## Phase plan

**Phase 0 — Skeleton** (2–3 weeks)
Wire `loop.py`, `conduct_injector.py`, `tier_router.py`, and `cost_ledger.py`. No engine logic; the loop accepts a skill path and calls the SDK with the correctly-built system prompt. Validates that conduct injection, tier routing, and cost tracking work end-to-end on a trivial task before any engine complexity is added.
*Acceptance criterion:* `/create` invoked on a static topic routes to Opus, injects the correct conduct modules for an Opus orchestrator + Write tool, records token spend, and returns a reply. No DEPLOY-bar check yet.

**Phase 1 — Port `/deep-research` as standalone engine** (2–3 weeks)
Implement `tool_middleware.py` and `precedent_check.py`. Port the deep-research SKILL.md multi-phase loop (Decompose → Cast → Triangulate → Gap-fill → Synthesize → Verify) into the runtime: Phase 2 parallel Haiku dispatches become parallel `Agent` calls managed by `loop.py`; Phase 6 Haiku verification becomes a `verifier.py` call.
*Acceptance criterion:* `enchanter deep-research "prompt engineering 2026"` produces `claims.json` + `sources.jsonl` + `trace.json` with `verify_passed: true`, costs recorded, precedent pre-check fired before every Bash mkdir.

**Phase 2 — Verifier sidecar + DEPLOY bar runtime** (1–2 weeks)
Implement `verifier.py` fully: 8 SAT assertions, σ computation, diff read-back, baseline snapshot. Implement `doubt_engine.py`. Wire both into the reply gate so no DEPLOY verdict exits the loop without clearing the bar.
*Acceptance criterion:* A prompt with 7/8 SAT assertions passing is blocked at the reply gate with verdict HOLD; the session summary shows which assertion failed.

**Phase 3 — Lifecycle automation** (2–3 weeks)
Implement the lifecycle auto-fire logic in `loop.py`: stale-brief detection triggers E0 before `/create`; three consecutive HOLD exits on the same axis escalate to developer; `briefing_loader.py` triggers auto-reconcile before high-stakes briefing reads (`/converge`, `/harden`).
*Acceptance criterion:* `/create` invoked with `claims.json` freshness > 30 days auto-fires `/deep-research` first, without developer prompting, and records the auto-fire in the session trace.

**Phase 4 — Port `/converge` as runtime loop** (2–3 weeks)
Port the convergence engine (E1 Gauss, E2 SAT overlay, E6 accumulation) into the runtime. The convergence loop runs inside `loop.py` as a bounded iteration (max N rounds, no-regression contract enforced by `verifier.py`). LiteLLM integration goes in here to support multi-model convergence targets.
*Acceptance criterion:* `/converge` on a prompt that starts at overall 7.5 reaches DEPLOY bar or logs a `F12 degeneration-loop` entry to `learnings.md` when saturated, without human intervention.

**Phase 5 — Packaging** (1 week)
`pip install enchanter` with CLI entry point (`enchanter <skill> [args]`) and optional daemon mode (long-running process that watches `.enchanter/` for skill invocations). Publish to PyPI. Runtime config via `.enchanter/config.toml` in the project root; daemon config via `pyproject.toml` optional section.
*Acceptance criterion:* `pip install enchanter && enchanter deep-research "test topic"` works on a clean machine with no prior Enchanter tooling installed.

---

## Open questions

- **Format for injected conduct.** The conduct modules are currently Markdown. The format tournament has not concluded. If the winner is XML, `conduct_injector.py` needs a Markdown-to-XML converter or a parallel XML-native module set. Deferred until the tournament resolves.

- **Single-model loop vs. multi-model orchestration.** Phase 0–2 assume a single SDK call per turn; the full tier map (Opus orchestrator + Sonnet executor + Haiku validator) requires the loop to dispatch multiple SDK calls per logical turn. The switch from single to multi is a non-trivial refactor. Decision point: after Phase 1 validates the single-model path.

- **File-state vs. SQLite for catalog, briefings, and precedent log.** Current state surfaces are flat files (`artifacts.jsonl`, `catalog.json`, `precedent-log.md`). SQLite would give atomic multi-table updates and indexed queries; flat files keep `inference-engine.py` dependency-free. The choice affects `cost_ledger.py` and `precedent_check.py` as well. Decision deferred to Phase 3.

- **Sync vs. async loop.** The SDK supports both; async is required for parallel Haiku dispatch (Phase 2 of deep-research). The pseudocode above is async throughout, but sync would be simpler for Phase 0. Decision: start sync in Phase 0, migrate to async in Phase 1 when parallel dispatch is required.

- **Developer skill hook-in mechanism.** How does a developer add a new engine to the runtime without forking `loop.py`? Candidates: Python entry-point discovery (`enchanter.skills` group in `pyproject.toml`), a `.enchanter/skills/` directory scanned at boot, or explicit registration in `.enchanter/config.toml`. The entry-point approach is most Pythonic and aligns with how LiteLLM and pytest handle plugins. No decision yet; needed before Phase 5.

---

## Risks

1. **SDK API churn.** The Claude Agent SDK is not yet stable. `loop.py`'s `Agent` constructor interface, the `system_prompt` parameter name, and the `tools` whitelist format may change between now and Phase 5. Mitigation: wrap SDK calls in a thin `sdk_adapter.py` shim so changes are one-file fixes.

2. **Conduct-injection token cost dominates small tasks.** Injecting 5 conduct modules at ~600 tokens each adds 3,000+ tokens to every session. For a one-line rename task, the conduct overhead exceeds the task tokens. Mitigation: Pattern B (whitelist inject) cuts this by 50–70% for bounded tool whitelists; Phase 0 must profile injection cost against a representative task distribution before committing to full-inject as default.

3. **Runtime-enforced rules conflict with developer intent.** A developer who explicitly overrides a contract (per `discipline.md` § When to violate) will find the runtime blocking them. The override mechanism must be explicit and logged, not silently bypassed. Mitigation: every enforcement gate accepts an `--override <reason>` flag that logs the override to `state/precedent-log.md` with tag `runtime-override` and proceeds.

4. **Verifier false positives block legitimate prompts.** The 8 SAT assertion set was designed for LLM self-evaluation, not deterministic regex. A regex-based `verifier.py` will have false-positive rates on edge-case prompt structures. Mitigation: Phase 2 ships the verifier with a `--strict` flag defaulting to off; enable strict only after calibrating against the existing prompt corpus.

5. **Parallel agent dispatch without a race guard breaks the cost ledger and artifact state.** Phase 1's parallel Haiku fetchers all write to `sources.jsonl`. Without atomic append logic inherited from `inference-engine.py`, writes race. Mitigation: `tool_middleware.py` enforces the serial-write-to-same-path rule from `tool-use.md` § Parallel vs. serial and channels all `sources.jsonl` writes through a single append queue.

---

## Migration path from Claude Code

The eleven existing plugins (`deep-research`, `prompt-crafter`, `prompt-refiner`, `convergence-engine`, `prompt-tester`, `prompt-harden`, `prompt-translate`, `inference-engine`, and the `full` meta-plugin) remain on Claude Code during the build. The runtime is developed in parallel; no plugin is migrated until its Phase acceptance criterion is met.

Migration order follows the phase plan: Phase 1 ports `deep-research` first because it has the cleanest artifact contract and the most deterministic verification (Phase 6 verifier already exists as `agents/verifier.md`). Each subsequent phase ports one engine. The Claude Code version of each skill is kept live as the fallback during dual-run: both the CC plugin and the runtime engine are callable, and output artifacts are diff-checked for parity before the CC plugin is deprecated.

The `full` meta-plugin (which composes all skills into a single plugin.json) is deprecated last. It serves as the integration test surface during dual-run: if `full` passes its regression suite under the new runtime, CC plugins are retired.

Developer-facing change is minimal during migration: skill invocations (`/create`, `/converge`, etc.) keep their names; the runtime intercepts them via the `.enchanter/` discovery mechanism rather than Claude Code's plugin system. The `state/` and `prompts/` directory layouts are unchanged; the runtime reads and writes the same artifact shapes.
