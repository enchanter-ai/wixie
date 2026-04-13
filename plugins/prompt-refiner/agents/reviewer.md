---
name: reviewer
description: >
  Background agent that validates a refined prompt folder. Same checks
  as the crafter's reviewer. Runs after convergence completes.
model: haiku
context: fork
allowed-tools: Bash(python *) Read
---

# Reviewer Agent (Refiner)

Same validation checks as the crafter's reviewer agent. See plugins/prompt-crafter/agents/reviewer.md for full specification.

Additional check for refine mode: verify metadata contains `before` and `after` score objects, and that `after.overall > before.overall` (refinement should improve the score).
