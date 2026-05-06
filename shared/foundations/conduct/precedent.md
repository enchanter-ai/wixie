# Precedent — Don't Repeat Known Failures

Audience: any agent that runs across multiple sessions. How to avoid re-running commands, patterns, or approaches that have already failed. The twin of [`./failure-modes.md`](./failure-modes.md) — that one tags domain-level failures in the scoring/quality loop; this one tracks *operational* failures in shell, file, and tool commands across sessions.

## The problem

LLM agents forget between sessions. A command that failed yesterday (wrong quoting, missing dep, Windows path issue, obsolete flag) will be attempted again tomorrow unless the failure is recorded *and consulted*. Every session re-discovering the same gotcha is silent waste.

## Distinction from other logs

| Log | Scope | Populated by | Consulted when |
|-----|-------|--------------|----------------|
| Cross-session memory (e.g., user preferences) | Cross-project, user-taught | User correction | Any session where guidance applies |
| Per-workflow learnings log | One workflow's iteration log | Convergence / accumulation loop | Starting a new iteration round |
| Project precedent log | This project | Self-observed failures | Before running a class of operation |

Precedent is for failures *the agent itself* discovered, in *this* project. No user correction needed to log — the failure is evidence enough.

## What to log

Log when:

1. A command fails *unexpectedly* (you had reason to believe it would work).
2. A pattern (tool sequence, prompt structure, build step) succeeds initially then breaks on second run.
3. An approach was tried, reverted, and replaced with a working alternative — log the dead-end *and* the replacement.
4. An environmental quirk trips you up (Windows path, PowerShell vs. bash, proxy, perm issue).

Don't log:

- First-try failures on unfamiliar commands — that's discovery, not precedent.
- Transient failures (network blip, rate limit) — only log if repeatable.
- User-introduced errors — those belong in cross-session feedback memory, not precedent.

## Entry format

Append to your project's precedent log (recommended path: `state/precedent-log.md` or similar). Each entry is a self-contained block:

```markdown
## 2026-04-17 — Windows path quoting in Bash tool

**Command that failed:**
`python C:/path/to/repo/shared/scripts/score.py`

**Why it failed:**
Windows path with no quotes; shell split on the colon in `C:/`.

**What worked:**
`python "C:/path/to/repo/shared/scripts/score.py"` — always quote Windows paths.

**Signal:** next time you see `C:/` or a space in a path, reach for quotes.

**Tags:** bash, windows, quoting
```

Required fields: date, title, *command that failed*, *why*, *what worked*, *signal*, *tags*.

Tags are lowercase single words, comma-separated. Pick from an evolving vocabulary — no new tag without checking the existing set first.

## When to read the log

Consult the precedent log before:

1. **Running a non-trivial Bash command** — grep for the command verb (`find`, `python`, `git reset`) and any literal flags.
2. **Composing a multi-step tool sequence** — grep for the sequence shape ("write-then-read", "rename-then-import").
3. **Starting a new workflow that touches the same subsystem as a logged failure** — grep by tag.

This is a 2-4 second grep, not a full read. If the grep returns a hit, read it. If not, proceed.

## Consult-then-act protocol

```
Before a risky or Bash-heavy step:
  1. Grep the precedent log for relevant terms.
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

The precedent log is *not* in `.gitignore` if the project is shared. Precedent is a team asset — the failure one developer hit is a failure the next would repeat. Commit the log.

For single-developer or local experiments, keep the precedent log local. Mark the project's README accordingly.

## Relationship to cross-session memory

Cross-session memory captures user-taught guidance across projects. Precedent captures self-observed failures within a project. They complement each other:

- User says *"always use `uv` instead of `pip` in this project"* → cross-session memory.
- Agent runs `pip install`, hits a resolver conflict, fixes it with `uv pip install`, logs the fix → project precedent log.

If the same failure recurs across multiple projects, promote a precedent entry to cross-session memory. Precedent → memory is a manual, deliberate graduation.

## Anti-patterns

- **Logging every first-try failure.** The log becomes noise. Only log *unexpected* or *repeated* failures.
- **Never consulting the log.** Precedent without recall is a diary, not a tool.
- **Paraphrasing the failing command.** Breaks grep-ability; defeats the whole system.
- **Vague signal lines.** *"Don't do that"* teaches nothing. Name the trigger and the counter.
- **Letting the log grow unbounded.** Quarterly: prune resolved entries, consolidate near-duplicates, confirm signals still apply.
- **Skipping the consult step "because I remember."** Across sessions, you don't. Grep is cheap.
