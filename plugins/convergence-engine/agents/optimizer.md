---
name: optimizer
description: >
  Background optimization agent. Runs convergence.py, updates artifacts,
  validates results. Fully autonomous — no user interaction.
model: sonnet
context: fork
allowed-tools: Bash(python *) Read Write Edit
---

# Optimizer Agent

Run convergence.py on the target prompt file. After completion, update metadata.json with final scores, generate report.pdf, and validate all files.

Report back: final scores, iteration count, verdict.
