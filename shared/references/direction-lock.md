# Direction Lock (grill-me)

Audience: Claude, inside `/create`, `/refine`, `/converge`. The gate that confirms the prompt's **direction** is the one the developer actually wants — *before* spending tokens generating, refining, or converging. It exists to stop Wixie from autonomously deciding the load-bearing choices and discovering three phases later that the direction was wrong.

**Default: ON.** Every `/create`, `/refine`, and `/converge` runs the Direction Lock unless the developer explicitly skips it (a trivial one-off inline prompt) or collapses it ("proceed with all recommendations"). Do not skip it silently on a non-trivial prompt to save turns — that is the exact failure this gate prevents.

## Protocol

1. **Reflect the understood direction in one line** before asking anything: intent + target model + scope + output format. e.g. *"Direction so far: a production-grade invoice-field extractor for Claude Opus, strict JSON out. Confirming a few choices before I build."*

2. **Grill one decision at a time.** Use the interactive question tool, **one question per call** — never batch the direction decisions into a single call (batching defeats the gate). Ask only about the choices Wixie would otherwise pick autonomously and that change the *direction*:
   - **Intent / goal** — reflect back what the prompt is meant to *do*; confirm or correct.
   - **Scope** — minimal / standard / production-grade.
   - **Target model** — post model-fit check: confirm the model, or switch.
   - **Output format / structure** — the shape the caller depends on.
   - **Technique approach** — the *family* (reasoning-heavy CoT / few-shot / structured extraction / role+constraints / …), not the full 16-technique selection.
   - **Load-bearing assumptions** — every assumption Wixie is about to bake in gets surfaced as a question, not buried. If you are assuming it, ask it.

3. **Attach one decisive recommendation to each question.** A single line, produced by the **orchestrator model — Opus-5 by default** (overridable: if the developer names another recommender, use it; the fallback is always Opus-5). Format the first option as the recommendation and mark it, e.g. `Rec (Opus-5): strict JSON — the downstream parser can't accept prose`. The developer picks it, overrides it, or edits. The recommendation is a lever for a fast decision, never an excuse to auto-pick.

4. **Block until the direction is confirmed.** Do not advance to generation / refinement / the convergence loop until every direction decision is settled. When the developer overrides a choice, update the working direction and carry it forward into the rest of the lifecycle (technique selection, formatting, metadata).

5. **Escape hatches.**
   - *"Proceed with all recommendations"* — collapse the remaining questions by accepting every Opus-5 rec, and continue. Offer this after the first one or two questions so an aligned developer isn't over-grilled.
   - *Trivial inline prompt* — a single-model, single-session throwaway may skip the gate entirely (same bar as "`/create` is overkill — write it inline").

## Per-stage placement

- **`/create`** — Phase 2.8, after context / model-fit / research are gathered, immediately before Phase 3 Generation. Confirms the whole direction, then generation proceeds on a locked direction.
- **`/refine`** — Phase 1.5, after Diagnosis, before Refinement. Confirms *which* weaknesses to fix and which axes to move — a refine can change a prompt's direction as much as a create.
- **`/converge`** — Step 1.5, once at the start of the run (the convergence loop itself stays autonomous per the no-permission-asks contract). Confirms the target axes, the goal, and the stopping criteria before the loop begins; it does **not** grill per-hypothesis.

## Anti-patterns

- **Batching the direction questions** into one call — that is profiling, not grilling. One decision, one call.
- **Auto-picking** technique / format / scope / model and only revealing it in the finished artifact.
- **Burying an assumption** in the prompt instead of asking about it.
- **Skipping the gate** on a non-trivial prompt to save turns.
- **Hardcoding the recommender** to a non-default model — Opus-5 is the fallback; only switch when the developer asks.
