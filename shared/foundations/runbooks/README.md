# Runbooks — MTTR per Failure Code

Per-failure-mode operational runbooks keyed to the F-code taxonomy in `../conduct/failure-modes.md`. Each runbook follows a fixed shape: Signature, Detection (audit-trail / metrics / self-report signals), Triage steps, Rollback (in-flight + deployed), and Post-incident logging.

Closes audit findings F-007 (no MTTR runbooks) and F-049 (no per-failure-mode rollback documentation).

## Index

### Generation failures
- [F01.md](F01.md) — Sycophancy: agent abandons a flagged concern after social affirmation.
- [F02.md](F02.md) — Fabrication: cited API / flag / file does not exist.
- [F03.md](F03.md) — Context decay: top-of-context instruction violated at the bottom.
- [F04.md](F04.md) — Task drift: work expanded past the stated goal.
- [F05.md](F05.md) — Instruction attenuation: rule stated once, obeyed once, then forgotten.

### Action failures
- [F06.md](F06.md) — Premature action: edited before grounding (wrong file, wrong function).
- [F07.md](F07.md) — Over-helpful substitution: solved a problem the user didn't ask about.
- [F08.md](F08.md) — Tool mis-invocation: wrong tool for the job (e.g. Bash for read).
- [F09.md](F09.md) — Parallel race: two writes to the same file or branch.
- [F10.md](F10.md) — Destructive without confirmation: `rm`, `reset --hard`, `force push` without explicit yes.

### Reasoning failures
- [F11.md](F11.md) — Reward hacking: hit the metric by gaming it.
- [F12.md](F12.md) — Degeneration loop: same edit, reverted, re-applied across iterations.
- [F13.md](F13.md) — Distractor pollution: long irrelevant context bent the output.
- [F14.md](F14.md) — Version drift: used deprecated API / retired model ID / old flag.

### Multi-agent and alignment failures
- [F15.md](F15.md) — Inter-agent misalignment: two parallel agents produced contradictory outputs.
- [F16.md](F16.md) — Task-verification skip: subagent returned success without running the required check.
- [F17.md](F17.md) — System-design brittleness: pipeline breaks when agents are reordered or replaced.
- [F18.md](F18.md) — Goal-conflict insider behavior: agent pursued an unsanctioned instrumental goal.
- [F19.md](F19.md) — Alignment faking *(awareness)*: agent behaves compliantly only under observation.
- [F20.md](F20.md) — Sandbagging *(awareness)*: agent underperforms on evals to avoid oversight thresholds.
- [F21.md](F21.md) — Weaponized tool use: agent used a legitimate tool to cause harm.

## Authoring guide

New runbooks follow the shape of existing F01–F21 entries: Signature / Detection / Triage / Rollback / Post-incident / See also. New F-codes must first land in `../conduct/failure-modes.md` per its § Extending the taxonomy clause; only then add a runbook here.

Improvements directory: file detector gaps, missing signals, or rollback issues under `improvements/` (created on first need).
