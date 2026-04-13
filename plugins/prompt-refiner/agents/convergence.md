---
name: convergence
description: >
  Background agent that runs the Convergence Engine on a refined prompt.
  Iterates up to 100 times to reach DEPLOY verdict. Spawned by
  prompt-improver after refinement.
model: sonnet
context: fork
allowed-tools: Bash(python *) Read Write Edit
---

# Convergence Agent (Refiner)

Identical to the crafter's convergence agent. Run convergence.py on the refined prompt, update metadata with before/after scores, generate report.pdf.

See the crafter's convergence agent for full instructions. The only difference: metadata should include `"mode": "refine"` and before/after score comparison.
