# Verification — Independent Checks

Audience: any agent producing artifacts (code, configs, scores, outputs). How an artifact earns a shipping verdict. Product-specific shipping bars live in your project; this module defines the *process* to meet them.

## First law

**Self-certification is not verification.** The agent that produced the artifact does not get to declare it correct. A different model, a different context, or a deterministic check must confirm.

## The three verification modes

| Mode | Who runs it | When it applies |
|------|-------------|-----------------|
| Tier split | Validator tier reviews Executor tier output (e.g., a smaller/cheaper model checks a larger one's work) | Every generation, audit, or translation round |
| Deterministic check | Test, lint, hash compare, schema validator | Any artifact with a machine-checkable property |
| Diff read-back | Fresh agent reads the unified diff cold | Code or config edits beyond a trivial one-liner |

A run picks the strongest mode available. If two apply, use both.

## Baseline snapshot

Capture the pre-change state before you edit. Only *new* regressions count.

1. **Before the edit:** test output, lint output, file hash, relevant metric (score, size, latency).
2. **After the edit:** same four, recorded.
3. **Diff the two.** If a test failed before and still fails, it's pre-existing — flag but don't block. If it passed before and fails now, that's the regression you own.

Without a baseline, every failure looks like your fault and real regressions hide in the noise.

## Dry-run for destructive ops

Any action that is hard to reverse emits a plan first and waits for confirmation. No exceptions.

| Operation | Dry-run form |
|-----------|--------------|
| `rm -rf <path>` | List the files that would be deleted. Confirm. |
| `git reset --hard`, `git push --force`, branch delete | State the refs lost. Confirm. |
| Schema migration, `DROP`, `TRUNCATE` | Print the migration plan + rollback. Confirm. |
| Mass rename / mass edit across >5 files | Show 2-3 sample diffs. Confirm. |
| Publishing (npm, PyPI, release) | State the version and target registry. Confirm. |

Confirmation is *explicit user yes*, not absence of objection.

## Assertion over observation

Prints show output; assertions protect behavior. Only the second survives the next regression.

1. **After every fix, add or update the assertion that would have caught it.** Otherwise the bug comes back.
2. **Regression-test fixtures are assertions, not samples.** Expected output is part of the fixture; fuzzy matching is a last resort.
3. **Prints are debug aids, not verification.** Remove them before handing back.

## Post-change diff read-back

Before declaring done on any code change:

1. Run the equivalent of `git diff` on the change.
2. Read it line by line.
3. Confirm: *every line in the diff is either (a) the change requested, (b) required by (a), or (c) pre-existing drift you will flag.* Any line that doesn't fit one of the three is an unsolicited edit — revert it.

This is the single cheapest scope-creep filter. See also [`./discipline.md`](./discipline.md) § Surgical changes.

## Verification is not optional for shipping claims

A shipping verdict comes from the *current* run's scores and assertions, not from stored metadata of a prior session. If you're unsure whether the numbers are fresh, re-run the self-eval. Stale verdicts are the single most common late-stage failure.

## Anti-patterns

- **"Tests passed locally"** without showing the output. Show it or it didn't happen.
- **Reading the code you just wrote to decide if it's correct.** That's self-certification. Run the test.
- **Skipping the baseline because "it was probably fine before."** Now you can't distinguish your regression from a pre-existing one.
- **Treating a hook's advisory message as a blocker you work around.** Fix the underlying issue; don't dodge the signal.
- **`--no-verify` / `--no-gpg-sign` / bypass flags.** Never, unless the user explicitly asks. The failing check is the signal.

## Done means verified

"Done" is a claim that all five hold: deterministic check passed, diff is scoped, tier-split or read-back cleared it, baseline captured, no unconfirmed destructive op. Any miss → HOLD with the reason, not DONE.
