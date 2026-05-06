# F10 — Destructive Without Confirmation

## Signature

Agent runs a hard-to-reverse operation without explicit user approval. The action might have been correct; the failure is the absence of a confirmation gate.

Common shapes:

- `rm -rf <path>` without listing what would be deleted first.
- `git reset --hard`, `git push --force`, branch delete without naming the refs that would be lost.
- `DROP`, `TRUNCATE`, schema migration without showing the plan.
- Mass rename across many files without a sample-diff preview.
- Publishing (npm, PyPI, release) without naming the version + target registry.

## Counter

See [`../conduct/verification.md`](../conduct/verification.md) § Dry-run for destructive ops.

Concrete:

| Operation | Dry-run form |
|-----------|--------------|
| `rm -rf` | List the files that would be deleted; ask. |
| `git reset --hard`, force-push, branch delete | State the refs lost; ask. |
| Schema migration | Print plan + rollback; ask. |
| Mass rename | Show 2–3 sample diffs; ask. |
| Publish | State version + target registry; ask. |

Confirmation is **explicit user yes**, not absence of objection. "Sure" or silence is not approval — only a clear yes counts.

## Examples

1. Agent decides to "clean up" stale branches. Runs `git branch -D feature-x feature-y feature-z` without listing them first. Two were active branches with unmerged work. **Counter:** List branches; ask for confirmation per branch or for the batch.

2. Agent finds a directory that "looks like leftover" and `rm -rf`s it. The directory was the user's draft folder. **Counter:** Print contents; ask before any `rm -rf`.

3. Agent updates a database schema with `ALTER TABLE users DROP COLUMN legacy_id;` to "clean up" the table. Backfill plan unclear, downstream consumers not checked. **Counter:** Print the migration; ask whether downstream systems are ready.

## Adjacent codes

- **F07 over-helpful substitution** — substitution does an *unrequested* thing; destructive-without-confirmation does an *unconfirmed* thing. They overlap when the unrequested thing is also destructive.
- **F02 fabrication** — fabrication invents content; destructive-without-confirmation acts on real content too quickly.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Recover what's recoverable; log; reissue with the dry-run form |
| 3+ in one workflow | Pause the workflow — the contract is broken. Add a hard gate (hook or permission) before any destructive op |
