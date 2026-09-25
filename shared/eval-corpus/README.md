# Eval Corpus — the measured DEPLOY bar

This directory holds **fixed eval corpora** consumed by `shared/scripts/efficacy-replay.py corpus`.
They turn the DEPLOY-relevant signal for `/converge` and `/test-prompt` from a *heuristic linter*
(stdlib regex over the prompt TEXT, zero model calls) into a *measurement* (real `claude -p` calls
against a live model, scored with a Wilson 95% confidence interval).

## Why

Historically wixie's 5-axis scores, σ, and the 8 SAT assertions came from
`output-eval.py` / `convergence.py` — self-satisfiable heuristics that never call a model.
`efficacy-replay.py` is the one script that genuinely exercises a model. Corpus mode reuses that
engine so the accept/reject decision rests on measured behavior, not on linting the prompt string.

The heuristic linter still runs as a **fast pre-check** — it is cheap and catches gross problems
before spending tokens — but it is no longer the DEPLOY-relevant signal.

## Schema (`<corpus>/corpus.json`)

```json
{
  "name": "deploy-bar",
  "description": "...",
  "control_system": "baseline system prompt for the --with-control arm",
  "accept": { "rate_floor": 0.75 },
  "cases": [
    {
      "id": "unique-case-id",
      "input": "the user turn fed to the model",
      "expect_patterns": ["regex that MUST appear in the assistant text -> PASS"],
      "reject_patterns": ["regex whose presence forces FAIL"]
    }
  ]
}
```

Classification per trial (`classify_corpus`) — only for trials whose TRANSPORT succeeded (see
"Transport vs. task" below; a trial whose transport failed never reaches this classifier):

- **PASS** — every `expect_patterns` regex matches the assistant text AND no `reject_patterns` matches.
- **FAIL** — any `reject_patterns` matches, or a required `expect_patterns` is missing.

There is no NEITHER arm: for prompt correctness, "expected behavior absent" is a real failure, so
every MEASURED trial scores. Pass rate = passes / measured, where `measured = (cases × n) −
transport_failures` — **not** `cases × n` (`attempted` in the verdict carries the raw `cases × n`
count; `total` is the measured denominator actually used for the rate and the Wilson CI).

## Running

```bash
# ACCEPT (exit 0) / REJECT (exit 1) / NO_MEASUREMENT (exit 3), decided on the Wilson CI lower bound.
python shared/scripts/efficacy-replay.py corpus deploy-bar --prompt path/to/prompt.xml -n 5

# add a baseline arm and additionally require MEASURED LIFT over it:
python shared/scripts/efficacy-replay.py corpus deploy-bar --prompt path/to/prompt.xml -n 5 --with-control
```

## Transport vs. task (WIX-EFF-001)

Every trial's TRANSPORT outcome (did `claude -p` reach the provider and return a parseable
envelope) is recorded separately from its TASK outcome (did the output pass/fail the corpus
case). A trial whose transport failed — auth failure, empty output, an invalid/garbled envelope,
a hung trial past `WIXIE_EFFICACY_TIMEOUT`, a rate-limit or provider error — is **never** handed
to `classify_corpus` and **never** counted as a PASS or a FAIL: it is excluded from the Wilson
denominator entirely, not scored as zero-valued evidence. Each arm's `transport_failures` list and
`measurement_valid` flag are persisted in `verdict.json` with cause, attempt (case/seed), exit
code and a redacted, length-capped stderr excerpt (see "Secrets" below).

When an arm ends up with **zero valid measurements** (every trial in it failed transport, or, with
`--with-control`, either arm does), the DEPLOY bar was never applied: `decision.verdict` reads
`"NO_MEASUREMENT"` — never `"REJECT"` or `"ACCEPT"` — in both stdout and `verdict.json`, and the
process exits **3**. A **mixed** run (some trials transport-fail, others measure) is NOT
NO_MEASUREMENT as long as at least one trial per arm produced a real measurement; ACCEPT/REJECT is
then computed only over the trials that did.

## Accept / reject predicate

`accept_predicate` (the measured DEPLOY bar) only runs once both arms have at least one valid
measurement (otherwise the run short-circuits to NO_MEASUREMENT, above):

- **ACCEPT** (exit 0) — treatment CI lower bound ≥ `rate_floor`
  AND (no control arm, OR treatment CI low > control CI high  ← measured lift over baseline).
- **REJECT** (exit 1) — the bar was applied and not met.
- **NO_MEASUREMENT** (exit 3) — the bar was never applied (see "Transport vs. task" above).

Reporting the CI **lower bound** rather than the point rate is the honest-numbers move: a high rate
on few trials with a wide CI does not clear the bar. `n` scales the CI width — raise it to tighten.

Full run artifact: `<corpus>/verdict.json`; per-trial traces under `<corpus>/runs/`.

## Secrets

Any credential-shaped substring (`sk-ant-*`, other `sk-*` keys, `Bearer <token>`, an
`x-api-key`/`api-key` value, or `ANTHROPIC_API_KEY=...`) is redacted to `[REDACTED]` wherever a
trial's raw CLI output or a transport failure's `detail` excerpt is persisted — in `verdict.json`,
in the printed stdout summary, and in the per-trial `<corpus>/runs/*.json` traces. Redaction runs
only at those persistence/print boundaries, never on the text used for transport-reason detection
or task classification, so it cannot mask or change a verdict.

## Cost & CI safety

`corpus` mode makes real `claude -p` calls (tokens + CLI + network). Automated tests MUST NOT.
Every trial resolves its binary through `resolve_claude_bin()`, which honors
`WIXIE_EFFICACY_CLAUDE_BIN` — point it at a fake CLI that emits canned stream-json to exercise the
full parse → classify → Wilson-CI → accept path offline. See `tests/convergence-engine/`.

## The `deploy-bar` corpus

A small, prompt-agnostic seed: the cases stress a prompt-under-test on open-ended, decisive,
edge-case, and concise-output demands, and the expect/reject regexes encode the same behaviors the
old linter checked (`has_structure`, `no_hedges`, `no_filler`, `has_edge_cases`) — now measured on
real output. Add domain-specific corpora next to it when a prompt family needs representative inputs.
