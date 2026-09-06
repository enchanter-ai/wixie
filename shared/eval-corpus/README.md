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

Classification per trial (`classify_corpus`):

- **PASS** — every `expect_patterns` regex matches the assistant text AND no `reject_patterns` matches.
- **FAIL** — any `reject_patterns` matches, or a required `expect_patterns` is missing.

There is no NEITHER arm: for prompt correctness, "expected behavior absent" is a real failure, so
every trial scores. Pass rate = passes / (cases × n).

## Running

```bash
# ACCEPT (exit 0) / REJECT (exit 1), decided on the Wilson CI lower bound.
python shared/scripts/efficacy-replay.py corpus deploy-bar --prompt path/to/prompt.xml -n 5

# add a baseline arm and additionally require MEASURED LIFT over it:
python shared/scripts/efficacy-replay.py corpus deploy-bar --prompt path/to/prompt.xml -n 5 --with-control
```

## Accept / reject predicate

`accept_predicate` (the measured DEPLOY bar):

- **ACCEPT** — treatment CI lower bound ≥ `rate_floor`
  AND (no control arm, OR treatment CI low > control CI high  ← measured lift over baseline).
- **REJECT** — otherwise.

Reporting the CI **lower bound** rather than the point rate is the honest-numbers move: a high rate
on few trials with a wide CI does not clear the bar. `n` scales the CI width — raise it to tighten.

Full run artifact: `<corpus>/verdict.json`; per-trial traces under `<corpus>/runs/`.

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
