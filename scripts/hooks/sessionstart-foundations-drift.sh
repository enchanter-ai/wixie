#!/usr/bin/env bash
# sessionstart-foundations-drift.sh — Claude Code SessionStart hook.
#
# Per s2.0 recommendation Layer 2: at session start, compare .foundations-versions
# (manifest intent) and .foundations-lock (resolved state) against the actual
# ../foundations checkout. Fail loud on mismatch with a one-line
# remediation — never auto-heal.
#
# Hook is advisory per conduct/hooks.md § Injection over denial: stdout is
# surfaced as injected context; exit code is informational. We exit 0 on
# drift too (advisory mode) so the hook never blocks; the message in stdout
# is the signal.
#
# Register in .claude/settings.json under SessionStart:
#   { "hooks": { "SessionStart": [ { "matcher": "",
#       "hooks": [ { "type": "command",
#         "command": "./scripts/hooks/sessionstart-foundations-drift.sh" } ] } ] } }

set -uo pipefail

# Skip inside a subagent — drift only matters at the top-level session start.
if [[ -n "${CLAUDE_SUBAGENT:-}" ]]; then
  exit 0
fi

PLUGIN_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
FOUNDATIONS_DIR="$(cd "$PLUGIN_DIR/.." && pwd)/foundations"
LOCK_FILE="$PLUGIN_DIR/.foundations-lock"

# Use the bootstrap script's --verify mode as the single source of truth.
# It already emits the canonical one-line remediation messages.
if [[ ! -x "$PLUGIN_DIR/scripts/bootstrap.sh" ]]; then
  echo "foundations drift hook: scripts/bootstrap.sh missing or not executable"
  exit 0
fi

# Run verify silently on success, surface output on failure.
output="$("$PLUGIN_DIR/scripts/bootstrap.sh" --verify 2>&1)"
rc=$?

if [[ $rc -ne 0 ]]; then
  echo "HOOK foundations-drift:"
  echo "$output"
fi

# Advisory: always exit 0 so the hook never blocks.
exit 0
