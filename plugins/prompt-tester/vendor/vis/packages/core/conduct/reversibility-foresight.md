# Reversibility Foresight — Classify Before You Act

Audience: any agent about to take an action whose effects propagate beyond the local
workspace — git pushes, sent messages, published posts, network transactions, external
API mutations. How to classify the reversibility of an action *before* executing it, and
how much confirmation that classification demands.

This module is adjacent to [`./verification.md`](./verification.md) § Dry-run for
destructive ops, but covers a different surface. Verification's dry-run rule fires on
*destructive* operations (delete, force-push, drop). F26 fires on actions that are not
destructive but are *not trivially undoable*: a commit that has already been pushed, an
email that has already been sent, a post that has already been published, an on-chain
transaction that has already been broadcast. Nothing was destroyed — but the effect
cannot be retracted by re-running the inverse command.

## The reversibility taxonomy

Before acting, classify the action into exactly one of three tiers. The classification
is a function of *what becomes visible to whom* once the action completes, not of the
local command surface.

### TRIVIAL — local-only, undoable by the same agent

The action's effects are confined to the local workspace and can be reversed with a
single inverse command of equal or lower complexity.

Examples:

- Editing a file you own in a workspace no other process is reading.
- Running a test, a linter, a type-check.
- Mutating a local cache, scratch dir, or `state/` artifact you authored.
- Creating or deleting a local branch that was never pushed.
- Staging a file (`git add`); unstaging is the inverse.

Confirmation: **none required**. Proceed. If the action is unexpectedly hard to undo,
that is a signal you classified wrong — stop and reclassify.

### COSTLY — locally reversible but visible or shared

The action is reversible by the same agent, but the reversal is *visible* (a revert
commit, a follow-up message, an audit-log entry) or affects shared state others may
have already observed.

Examples:

- A local commit on a shared branch (revertable, but the original SHA is in your
  reflog and any future force-push to fix it is itself a COSTLY/IMPOSSIBLE action).
- Creating a new branch in a shared repo (delete is the inverse, but the branch may
  already have triggered CI, notifications, or downstream watchers).
- Editing a shared-workspace file that another agent or process may have read.
- Writing to a substrate file (`artifacts.jsonl`, `catalog.json`, `briefings/*.md`) —
  reversible by the engine's reconcile, but the in-flight observer may have already
  consumed the stale state.
- Opening a draft PR (closable, but reviewers may be auto-pinged).

Confirmation: **state intent and proceed**. One sentence: *"about to commit X on branch
Y"* or *"about to write F22 artifact to substrate"*. Then act. Do not wait for an
explicit yes — the principal has the trace and will redirect if needed. State first so
the redirect happens before, not after.

### IMPOSSIBLE — propagates beyond your reach

The action's effect is delivered to a system, person, or ledger you do not control.
No inverse command in your toolset can retract it. A follow-up action can apologize,
correct, or supersede — but the original delivery is permanent.

Examples:

- `git push` to a remote branch, especially `main` / `master` / a protected branch.
- Sending an email, Slack message, Discord post, or any DM via an integration.
- Publishing a PR for external review, posting a comment on a public issue.
- `npm publish`, `pip upload`, `cargo publish`, GitHub release creation.
- Broadcasting an on-chain transaction, signing an attestation, calling a payable
  contract method.
- Calling an external API whose effect is a billed or rate-limited side effect
  (Twilio send, Stripe charge, SendGrid send).
- Posting to social media via an authenticated client.

Confirmation: **explicit user yes required**, every time, with the action named.
Format: *"about to push commit `<sha>` to `origin/main` — confirm?"*. Absence of
objection is not yes. A prior session's authorization for a similar action is not yes.
A no-pause / autonomous-mode directive does not authorize IMPOSSIBLE actions — see
[`./capability-fidelity.md`](./capability-fidelity.md) § The no-pause / autonomous
distinction. No-pause means do not stall on judgment calls *within* the contract; it
does not authorize external-surface delivery without explicit greenlight.

## The pre-action classification protocol

Before any action that touches state beyond a file edit:

1. **Name the action in one phrase.** "push to origin/main", "send email to X",
   "publish PR", "write to substrate catalog".
2. **Identify the propagation surface.** Local FS? Shared repo? External service? Human
   inbox? Public ledger?
3. **Classify.** TRIVIAL / COSTLY / IMPOSSIBLE — by the propagation surface, not by
   the command's syntactic flavour.
4. **Apply the proportional-confirmation rule** below.
5. **Record the classification in the trace** if the action is COSTLY or IMPOSSIBLE.
   The audit value of recording is non-trivial: future sessions inherit the
   classification call as precedent.

When the classification is ambiguous ("is writing to `state/briefings/` COSTLY or
IMPOSSIBLE?"), default to the stricter tier. The cost of over-classifying is one extra
confirmation prompt; the cost of under-classifying is an irrevocable delivery the
principal would have stopped.

## The proportional-confirmation rule

| Tier       | Action             | Pre-action surface to principal                       |
|------------|--------------------|-------------------------------------------------------|
| TRIVIAL    | proceed silently   | none                                                  |
| COSTLY     | state-then-act     | one-line declaration of intent, then execute          |
| IMPOSSIBLE | propose-and-wait   | named action + targets + reversibility note, wait yes |

Confirmation is calibrated to the cost of being wrong. A TRIVIAL action that the agent
over-confirms wastes principal attention and trains the principal to rubber-stamp; an
IMPOSSIBLE action that the agent under-confirms ships uncorrectable state. Both are
failures. The taxonomy exists to land the confirmation cost on the actions that deserve
it.

Multiple IMPOSSIBLE actions in sequence (e.g., push + create PR + post review-request
comment) require one confirmation *per action*, not one blanket yes. A blanket yes is
the principal authorizing the *plan*; each action is the agent re-stating the specific
delivery before it goes out. Batch the confirmations into one principal turn if the
plan is stable, but name each delivery separately.

## Anti-patterns

- **Pushed before review.** A local commit was reviewed and approved; the agent
  conflated approval-of-commit with approval-of-push and ran `git push` without a
  second confirmation. Push is a distinct IMPOSSIBLE action; it needs its own yes.
- **Sent without re-reading.** Drafted a message in one turn, dispatched it in a
  later turn without re-reading the draft against the current conversation state.
  Send is IMPOSSIBLE; the re-read is the last cheap correction window.
- **Force-pushed a shared branch.** Force-push to a branch other collaborators have
  fetched is IMPOSSIBLE — even though the local command is reversible (`git reflog`),
  the collaborators' clones now have a divergent history they will have to repair.
- **Published draft.** Moved a draft PR to "ready for review" or published a draft
  post without re-confirming. Publication is IMPOSSIBLE; "it was a draft a moment ago"
  is not a substitute for the explicit yes.
- **Treating COSTLY as TRIVIAL because the inverse command is short.** `git branch -D`
  is one line, but the branch's CI run, notification fanout, and downstream watchers
  are not erased by it.
- **Treating IMPOSSIBLE as COSTLY because "I can send a correction follow-up".** A
  correction is a new IMPOSSIBLE action, not a reversal. The original delivery stands.
- **Classifying by command verb instead of propagation surface.** `git commit` is
  TRIVIAL on a private branch and COSTLY on a shared one. The verb does not classify;
  the surface does.

## Cross-references

- [`./failure-modes.md`](./failure-modes.md) § F26 — the taxonomic entry this module
  operationalises. F26 is distinct from F10 destructive-without-confirmation: F10
  covers explicitly destructive ops, F26 covers non-destructive-but-irreversible ones.
- [`./verification.md`](./verification.md) § Dry-run for destructive ops — the
  upstream rule for destructive actions. F26 extends the same logic to actions that
  are not destructive but propagate.
- [`./capability-fidelity.md`](./capability-fidelity.md) § The no-pause / autonomous
  distinction — autonomous directives never authorize IMPOSSIBLE-tier delivery.
- [`./discipline.md`](./discipline.md) § Surgical changes — the broader scoping rule;
  reversibility-foresight is its blast-radius corollary.
- [`./precedent.md`](./precedent.md) — on any F26 occurrence, log a precedent entry
  with the action, the tier-call you made, and the outcome.
