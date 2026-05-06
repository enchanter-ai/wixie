# Hooks — Advisory-Only Rules

Audience: any system wiring runtime hooks (PreToolUse, PostToolUse, UserPromptSubmit, Stop, etc.). How to wire hooks without breaking a skill-invoked lifecycle. Whether a hook is permitted is a project decision; this module defines the contract when they are.

## The rule

**Hooks inform, they don't decide.** Any hook in the system must pass this test:

> If the hook were removed, would the system still function correctly?
> If no — the hook is load-bearing, not advisory. Reconsider the design.

Load-bearing hooks are an anti-pattern in skill-invoked systems; hooks that gate behavior smuggle control flow into the runtime.

## Injection over denial

When a hook has something useful to say, inject context — don't block.

| Situation | Blocking hook (bad) | Injecting hook (good) |
|-----------|---------------------|----------------------|
| Post-edit TS errors | Reject the Write | PostToolUse emits: *"3 TS errors at lines 42/78/103"* |
| Missing test coverage | Reject the commit | Pre-submit emits: *"New function `foo` has no test — add one?"* |
| Registry mismatch | Reject the skill | UserPromptSubmit emits: *"Target not in registry — verify before proceeding"* |

The agent reads the injected context and decides. The hook does not short-circuit the decision.

## Matcher specificity

Always scope hooks to the smallest relevant event.

```jsonc
// Good — scoped to specific tools
{ "matcher": "Bash", "hooks": [...] }
{ "matcher": "Write|Edit", "hooks": [...] }

// Bad — fires on everything
{ "hooks": [...] }
```

Omitting the matcher runs the hook on every event — on a long session, that's thousands of invocations for one that matters.

## Single-entry dispatcher

One hook script that routes, not N scripts triggered in parallel.

```
.claude/hooks/dispatch.sh
├── if event == "PostToolUse:Write"  → lint.sh
├── if event == "PostToolUse:Bash"   → audit.sh
└── if event == "UserPromptSubmit"   → brief.sh
```

Why: one place to enable/disable, one log to grep, no hook-order confusion, no parallel-hook races.

## Subagent-loop guard

`UserPromptSubmit` can trigger when the parent *or* a subagent submits. Without a guard, you can loop:

1. Parent prompts → hook triggers → hook spawns a subagent → subagent's first prompt is a UserPromptSubmit → hook triggers again → …

Guard with an environment marker:

```bash
if [[ -n "$CLAUDE_SUBAGENT" ]]; then
  # inside a subagent, skip the hook
  exit 0
fi
```

Or check the nesting level in the hook payload if the runtime exposes one.

## Fail-open for advisory hooks

If an advisory hook errors, it must not block the underlying action.

```bash
#!/bin/bash
set -uo pipefail   # note: no -e

notify_save "$@" || true   # never propagate failure
exit 0
```

An advisory hook that sometimes blocks is worse than no hook — it introduces intermittent, hard-to-reproduce failures.

## Performance budget

Hooks run synchronously. They add latency to every matched event.

| Event | Budget |
|-------|--------|
| UserPromptSubmit | < 200ms |
| PostToolUse (high-frequency) | < 100ms |
| PreToolUse (on every tool call) | < 50ms |
| Stop | < 500ms (user already waiting) |

If the work doesn't fit the budget, move it async — spawn a background process, don't block the runtime.

## Logging from hooks

Hooks should log to a file, not stdout. stdout goes into the conversation and pollutes context.

```bash
echo "[$(date -Is)] prompt saved: $prompt_path" >> .claude/logs/hooks.log
```

Log format: timestamp, event, relevant id. Keep entries one-line so they're greppable.

## Legitimate hook jobs

- **Deterministic observation.** Save every prompt to disk, emit a Slack notification, update a dashboard.
- **Environment injection.** PreToolUse for Bash that adds env vars the command needs.
- **Post-hoc enrichment.** PostToolUse that appends lint output as a system message.

If the job is observe-or-inject, use a hook. If it's deny-or-gate, use a skill or a permission.

## Starter patterns

> **Note:** Verify these env-var names against the live Claude Code hook spec before relying on the skeletons in production.

Three copy-runnable shell skeletons. Each skeleton is self-contained and works as-is
under the single-entry dispatcher described in this module. Wire them via `.claude/settings.json`
under the appropriate lifecycle event.

### Pattern 1 — PreToolUse: destructive-op deny

Fires before every tool call. Returns non-zero to block the call; returns 0 to allow.
Use to enforce `conduct/verification.md` § Dry-run for destructive ops without relying
on the agent's own compliance.

Scope: target `Bash` and `Write` tool matchers. Do not set a global matcher — that fires
on every Read and Grep call, adding hundreds of no-op invocations per session.

```bash
#!/usr/bin/env bash
# hooks/preuse-destructive-guard.sh
# PreToolUse — blocks destructive shell patterns; injects a warning otherwise.
#
# Claude Code passes tool name and input via environment variables:
#   CLAUDE_TOOL_NAME   — e.g. "Bash", "Write", "Edit"
#   CLAUDE_TOOL_INPUT  — JSON blob of the tool call arguments
# Exit 1 to deny; exit 0 to allow.

set -uo pipefail

TOOL="${CLAUDE_TOOL_NAME:-}"
INPUT="${CLAUDE_TOOL_INPUT:-}"

# Only inspect Bash calls.
[[ "$TOOL" != "Bash" ]] && exit 0

# Patterns that require dry-run confirmation first.
DESTRUCTIVE_PATTERNS=(
  'rm\s+-rf'
  'git\s+reset\s+--hard'
  'git\s+push\s+--force'
  'git\s+push\s+-f\b'
  'DROP\s+TABLE'
  'TRUNCATE\s+'
)

for pattern in "${DESTRUCTIVE_PATTERNS[@]}"; do
  if echo "$INPUT" | grep -qiE "$pattern"; then
    echo "HOOK DENY: destructive pattern detected ('$pattern')." >&2
    echo "Run the dry-run plan first (conduct/verification.md § Dry-run), then re-issue." >&2
    exit 1
  fi
done

exit 0
```

**Register in `.claude/settings.json`:**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/preuse-destructive-guard.sh" }
        ]
      }
    ]
  }
}
```

---

### Pattern 2 — PostToolUse: lint-output inject

Fires after a Write or Edit completes. Appends lint results as a system message so the
agent sees errors without a separate tool call. This implements the "injection over denial"
principle from `conduct/hooks.md` § Injection over denial.

The hook exits 0 regardless of lint outcome — it informs, it does not block.

```bash
#!/usr/bin/env bash
# hooks/postuse-lint-inject.sh
# PostToolUse — runs a linter on the file just written; injects output as context.
#
# Claude Code passes:
#   CLAUDE_TOOL_NAME   — "Write" or "Edit"
#   CLAUDE_TOOL_OUTPUT — JSON blob including the affected file path
# Stdout is injected into the conversation as a system message.
# Always exit 0 — this hook is advisory, not blocking.

set -uo pipefail

TOOL="${CLAUDE_TOOL_NAME:-}"
OUTPUT="${CLAUDE_TOOL_OUTPUT:-}"

# Only inspect Write and Edit calls.
[[ "$TOOL" != "Write" && "$TOOL" != "Edit" ]] && exit 0

# Extract file path from the JSON output. Requires `jq`.
FILE_PATH=$(echo "$OUTPUT" | jq -r '.path // empty' 2>/dev/null)
[[ -z "$FILE_PATH" ]] && exit 0
[[ ! -f "$FILE_PATH" ]] && exit 0

# Run the appropriate linter based on extension.
EXT="${FILE_PATH##*.}"
LINT_OUTPUT=""

case "$EXT" in
  py)
    LINT_OUTPUT=$(python -m flake8 --max-line-length=100 "$FILE_PATH" 2>&1 || true) ;;
  js|ts|jsx|tsx)
    LINT_OUTPUT=$(npx eslint --no-eslintrc -c .eslintrc.json "$FILE_PATH" 2>&1 || true) ;;
  sh|bash)
    LINT_OUTPUT=$(shellcheck "$FILE_PATH" 2>&1 || true) ;;
  *)
    exit 0 ;;
esac

if [[ -n "$LINT_OUTPUT" ]]; then
  echo "HOOK: lint output for $FILE_PATH:"
  echo "$LINT_OUTPUT"
fi

exit 0
```

**Register in `.claude/settings.json`:**

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/postuse-lint-inject.sh" }
        ]
      }
    ]
  }
}
```

---

### Pattern 3 — Stop: prompt-save notification

Fires when the agent session ends normally. Writes the final prompt text to a timestamped
file in `state/prompts/` for the accumulation loop in `conduct/precedent.md` and
`conduct/inference-substrate.md`. This is pure observation — no blocking, no injection.

```bash
#!/usr/bin/env bash
# hooks/stop-prompt-save.sh
# Stop — saves the session prompt to state/prompts/ on normal exit.
#
# Claude Code passes:
#   CLAUDE_SESSION_ID    — unique session identifier
#   CLAUDE_PROMPT_TEXT   — the user-visible prompt text (may be empty for tool-only sessions)
# Always exit 0.

set -uo pipefail

SESSION="${CLAUDE_SESSION_ID:-unknown}"
PROMPT_TEXT="${CLAUDE_PROMPT_TEXT:-}"
SAVE_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/state/prompts"

mkdir -p "$SAVE_DIR"

TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
OUT="$SAVE_DIR/${TIMESTAMP}_${SESSION:0:8}.txt"

{
  echo "session: $SESSION"
  echo "timestamp: $TIMESTAMP"
  echo "---"
  echo "$PROMPT_TEXT"
} > "$OUT"

echo "[hook:stop-prompt-save] saved to $OUT" >> "${SAVE_DIR}/../hooks.log"
exit 0
```

**Register in `.claude/settings.json`:**

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/stop-prompt-save.sh" }
        ]
      }
    ]
  }
}
```

---

### Advisory vs. enforcing: a design choice

The three patterns above work in both modes. Pattern 1 is enforcing by default (exit 1 denies);
patterns 2 and 3 are advisory (exit 0 always). The framework's stance — hooks inform, they don't
decide — is a default, not a constraint. Teams that want hard gates replace the advisory exit
with a deny exit and document the choice as a project-level override.

The choice has consequences: an enforcing hook that fires incorrectly blocks the agent entirely,
whereas an advisory hook that fires incorrectly produces a noisy system message the agent can
ignore. Prefer advisory during development; promote to enforcing only after the pattern has been
validated in a non-blocking run.

## Anti-patterns

- **Blocking hook masquerading as advisory.** Exit non-zero to "warn" — in practice it rejects. Use exit 0 + injection.
- **Hook that writes to stdout.** Output shows up in the conversation; confusing and costly.
- **No matcher.** Fires on every event; unreadable logs, killed performance.
- **Multiple parallel hooks for the same event.** Order undefined, races possible.
- **Hook with side effects on the repo.** Auto-commits, auto-renames — the hook is now a collaborator, not a listener.
- **Subagent-triggered loops.** No guard, infinite recursion.
