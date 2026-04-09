# prompt-crafter

**The prompt enchantment engine.**

Reads your intent, picks the right techniques, formats for the target model, scores the result.

## Skills

| Skill | Triggers on |
|-------|-------------|
| prompt-prompt-crafter | "I need a prompt for...", "make this prompt better", `/enchant` |

## 4-Phase Workflow

| Phase | What happens |
|---|---|
| **1. Context Scan** | Silently reads CLAUDE.md, .cursorrules, detects domain and model |
| **2. Interactive Profiling** | 3-8 targeted questions via GUI |
| **3. Enchanting** | Selects techniques, adapts format, generates prompt |
| **4. Self-Evaluation** | 5-axis scorer, flags weaknesses, offers fixes |

## Scripts

Both stdlib-only Python (zero pip installs):

- **self-eval.py** — Heuristic 5-axis prompt scorer
- **token-count.py** — Token estimator with context window fit

## Performance

Technique selection is O(1) — lookup table, not search.
Token estimation is word-count heuristic. No API calls.
