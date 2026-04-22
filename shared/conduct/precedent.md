# Precedent — Don't Repeat Known Failures

Audience: Claude. How plugins avoid re-running commands, patterns, or approaches that have already failed. The twin of `failure-modes.md` — that one tags domain-level failures in the scoring loop; this one tracks *operational* failures in shell, file, and tool commands across sessions.

> **Relationship to the inference-engine (Ufopedia, 2026-04).** `flux/state/precedent.jsonl` is now the **archival seed** — the human-written, git-committed ancestry of self-caught failures. New entries flow into the inference-engine's append-only stream at `flux/plugins/inference-engine/state/artifacts-YYYY-MM.jsonl` via `/inference-emit` (or the `inference-engine.py emit` CLI). The engine runs Wald SPRT + Beta-Binomial over those artifacts and promotes the load-bearing ones into per-plugin briefings consumed at session start. Read `shared/conduct/inference-substrate.md` for the emission contract. The archival precedent.jsonl rows stay visible in git history; they're not deleted or migrated — they *seeded* the substrate via backfill.

## The problem

Claude forgets between sessions. A command that failed yesterday (wrong quoting, missing dep, Windows path issue, obsolete flag) will be attempted again tomorrow unless the failure is recorded *and consulted*. Every session re-discovering the same gotcha is silent waste.

## Distinction from other logs

| Log | Scope | Populated by | Consulted when |
|-----|-------|--------------|----------------|
| Auto-memory `feedback` | Cross-project, user-taught | User correction | Any session where guidance applies |
| Per-workflow `learnings.md` | One workflow's iteration log | Convergence / accumulation loop | Starting a new iteration round |
| `state/precedent-log.md` | This plugin/project | Self-observed failures | Before running a class of operation |

Precedent is for failures *Claude itself* discovered, in *this* project. No user correction needed to log — the failure is evidence enough.

## What to log

Log when:

1. A command fails *unexpectedly* (you had reason to believe it would work).
2. A pattern (tool sequence, prompt structure, build step) succeeds initially then breaks on second run.
3. An approach was tried, reverted, and replaced with a working alternative — log the dead-end *and* the replacement.
4. An environmental quirk trips you up (Windows path, PowerShell vs. bash, proxy, perm issue).

Don't log:

- First-try failures on unfamiliar commands — that's discovery, not precedent.
- Transient failures (network blip, rate limit) — only log if repeatable.
- User-introduced errors — those belong in feedback memory, not precedent.

## Entry format

Append to `state/precedent-log.md`. Each entry is a self-contained block:

```markdown
## 2026-04-17 — Windows path quoting in Bash tool

**Command that failed:**
`python c:/git/flux/shared/scripts/score.py`

**Why it failed:**
Windows path with no quotes; shell split on the colon in `c:/`.

**What worked:**
`python "c:/git/flux/shared/scripts/score.py"` — always quote Windows paths.

**Signal:** next time you see `c:/` or a space in a path, reach for quotes.

**Tags:** bash, windows, quoting
```

Required fields: date, title, *command that failed*, *why*, *what worked*, *signal*, *tags*.

Tags are lowercase single words, comma-separated. Pick from an evolving vocabulary — no new tag without checking the existing set first.

## When to read the log

Consult `state/precedent-log.md` before:

1. **Running a non-trivial Bash command** — grep for the command verb (`find`, `python`, `git reset`) and any literal flags.
2. **Composing a multi-step tool sequence** — grep for the sequence shape ("write-then-read", "rename-then-import").
3. **Starting a new plugin skill that touches the same subsystem as a logged failure** — grep by tag.

This is a 2-4 second grep, not a full read. If `Grep` returns a hit, read it. If not, proceed.

## Consult-then-act protocol

```
Before a risky or Bash-heavy step:
  1. Grep state/precedent-log.md for relevant terms.
  2. If hit → read the entry, apply the signal.
  3. If no hit → proceed.
Step executes.
  4a. Succeeds → no log needed.
  4b. Fails unexpectedly → after fixing, append a new entry.
```

## Log hygiene

Precedent compounds only if entries stay high-signal. Enforce:

- **One failure per entry.** If two happen together, split them.
- **Actionable signal line.** *"Always quote Windows paths"* is actionable. *"Be careful with paths"* is not.
- **Cite the exact command.** Not a paraphrase. The grep-ability of the log depends on literal matching.
- **Prune resolved environmental issues.** If a quirk was fixed at the infra level (e.g., Windows shell replaced with WSL), mark the entry `RESOLVED 2026-XX-XX` and keep it as history, but deprioritize in reads.

## Cross-session durability

`state/precedent-log.md` is *not* in `.gitignore` if the plugin is shared. Precedent is a team asset — the failure one developer hit is a failure the next would repeat. Commit the log.

For single-developer or local experiments, keep `state/precedent-log.md` local. Mark the plugin's README accordingly.

## Relationship to auto-memory

Auto-memory (at `~/.claude/projects/.../memory/`) captures user-taught guidance across projects. Precedent captures self-observed failures within a project. They complement each other:

- User says *"always use `uv` instead of `pip` in this project"* → auto-memory `feedback`.
- Claude runs `pip install`, hits a resolver conflict, fixes it with `uv pip install`, logs the fix → `state/precedent-log.md`.

If the same failure recurs across multiple projects, promote a precedent entry to an auto-memory feedback. Precedent → memory is a manual, deliberate graduation.

## Anti-patterns

- **Logging every first-try failure.** The log becomes noise. Only log *unexpected* or *repeated* failures.
- **Never consulting the log.** Precedent without recall is a diary, not a tool.
- **Paraphrasing the failing command.** Breaks grep-ability; defeats the whole system.
- **Vague signal lines.** *"Don't do that"* teaches nothing. Name the trigger and the counter.
- **Letting the log grow unbounded.** Quarterly: prune resolved entries, consolidate near-duplicates, confirm signals still apply.
- **Skipping the consult step "because I remember."** Across sessions, you don't. Grep is cheap.
