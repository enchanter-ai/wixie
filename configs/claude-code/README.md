# Claude Code Configuration

Recommended settings for zero-friction Flux usage. The 6-plugin multi-agent pipeline runs autonomously — these permissions prevent pausing for approval.

Place in your project's `.claude/settings.json` or `~/.claude/settings.json`.

```json
{
  "permissions": {
    "allow": [
      "Bash(python shared/scripts/*)",
      "Bash(mkdir -p prompts/*)",
      "Agent"
    ]
  }
}
```

This allows:
- **Convergence engine** to run self-eval, token-count, convergence, and report-gen
- **Prompt folder creation** without approval
- **Agent spawning** for optimizer, reviewer, executor, red-team, and adapter agents
- **Prompt tester** to execute test suites
- **Prompt harden** to run adversarial attack patterns
- **Prompt translate** to convert between model formats

Without these permissions, every tool call in the pipeline pauses for approval — defeating autonomous convergence.

## Plugin Commands

| Command | Plugin | What it does |
|---------|--------|-------------|
| `/enchant` | prompt-crafter | Create a new prompt |
| `/refine` | prompt-refiner | Improve an existing prompt |
| `/converge` | convergence-engine | Optimize any prompt (100 iterations) |
| `/test-prompt` | prompt-tester | Run tests.json assertions |
| `/harden` | prompt-harden | Security audit (12 attack patterns) |
| `/translate-prompt` | prompt-translate | Convert between models |
