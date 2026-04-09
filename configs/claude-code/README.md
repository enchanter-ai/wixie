# Claude Code Configuration

Recommended settings for using Flux with Claude Code.

Place these in your project's `.claude/settings.json` or `~/.claude/settings.json`.

```json
{
  "permissions": {
    "allow": [
      "Bash(python scripts/*)"
    ]
  }
}
```

This allows the self-eval and token-count scripts to run without manual approval each time.
