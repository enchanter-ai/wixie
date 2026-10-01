# Direction Lock (grill-me)

Audience: Claude, inside `/create`, `/refine`, `/converge`. The gate that confirms the prompt's **direction** is the one the developer actually wants — *before* spending tokens generating, refining, or converging. It exists to stop Wixie from autonomously deciding the load-bearing choices and discovering three phases later that the direction was wrong.

**Default: ON.** Every `/create`, `/refine`, and `/converge` runs the Direction Lock unless the developer explicitly skips it (a trivial one-off inline prompt) or collapses it ("proceed with all recommendations"). Do not skip it silently on a non-trivial prompt to save turns — that is the exact failure this gate prevents.

## Protocol

1. **Reflect the understood direction in one line** before asking anything: intent + target model + scope + output format. e.g. *"Direction so far: a production-grade invoice-field extractor for Claude Opus, strict JSON out. Confirming a few choices before I build."*

2. **Grill one decision at a time, and go deep.** Use the interactive question tool, **one question per call** — never batch (batching defeats the gate). The point is not a cookie-cutter *scope / model / format* trio — those are the shallow end and, on their own, waste the developer's attention. Grill the **specific, load-bearing forks this particular prompt must resolve**: the real ambiguities, edge cases, and failure modes of *this* task in *this* domain, the ones the prompt would otherwise get quietly wrong.

   **Two tiers:**
   - **Coarse direction (resolve fast, don't over-ask).** Intent, scope, target model (post model-fit), output format, technique family. Where you can infer these from the task + `CLAUDE.md`, **state the inference in one line and invite a correction** rather than spending a full question on it. Only ask when a choice is genuinely open or high-stakes.
   - **Deep grill (the real work — 3–6 questions).** Derive these from the domain's actual decision points and failure modes. Each question resolves one concrete fork where a reasonable agent could pick wrong. Every assumption Wixie is about to bake in gets surfaced here as a question, not buried.

   **Generic vs. deep** — for a "extract action items from a transcript" prompt:
   - *Too generic (avoid):* "What scope — minimal / standard / comprehensive?"
   - *Deep (prefer):* "'I'll ship the deck **if** Marketing sends assets by Tuesday' — conditional item (emit with the condition), firm item, or skip?" · "Two people assigned the same task — one row with two owners or two rows?" · "'Follow up next week' with no meeting date in the transcript — `null`, or a relative-date placeholder?" · "A task someone *did* during the meeting (past tense) — action item or not?" · "Verbatim task text or a normalized paraphrase?"

   Depth is task-specific by construction: read the domain, enumerate where it breaks, and ask about those. If your questions would fit any prompt, they are too shallow — throw them out and find the ones that only fit this one.

3. **Attach one decisive recommendation to each question.** A single line, produced by the **orchestrator model — Opus-5 by default** (overridable: if the developer names another recommender, use it; the fallback is always Opus-5). Format the first option as the recommendation and mark it, e.g. `Rec (Opus-5): strict JSON — the downstream parser can't accept prose`. The developer picks it, overrides it, or edits. The recommendation is a lever for a fast decision, never an excuse to auto-pick.

4. **Block until the direction is confirmed.** Do not advance to generation / refinement / the convergence loop until every direction decision is settled. When the developer overrides a choice, update the working direction and carry it forward into the rest of the lifecycle (technique selection, formatting, metadata).

5. **Escape hatches.**
   - *"Proceed with all recommendations"* — accept the outstanding Opus-5 recs and continue. Offer this for the **coarse-direction tier**, not as a blanket collapse *before* the deep task-specific forks are asked — those forks are the reason the gate exists, so don't let the escape hatch skip them. Once the deep forks are settled, an aligned developer can wave the rest through.
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
