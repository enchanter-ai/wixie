# Recipe — Generic System Prompt

How to adopt agent-foundations when your runtime gives you only a system prompt — no skill registry, no hook framework, no submodule magic. Works for the OpenAI Chat Completions API, the Anthropic Messages API, llama.cpp, Ollama, or any place you control a single string.

## What you get

A system prompt assembled from selected conduct modules, optionally with a per-task suffix. The agent loads the rules at the top of every turn — no runtime support required.

## The core pattern

```python
from pathlib import Path
import requests

ROOT = Path("vendor/agent-foundations")  # or wherever you cloned it

def assemble_system_prompt(role: str, modules: list[str], task_specific: str = "") -> str:
    sections = [f"# Role\n\n{role.strip()}"]
    for name in modules:
        body = (ROOT / "conduct" / f"{name}.md").read_text()
        sections.append(body)
    if task_specific:
        sections.append(f"# Task-specific\n\n{task_specific.strip()}")
    return "\n\n---\n\n".join(sections)

system = assemble_system_prompt(
    role="You are a senior backend engineer working on a Python codebase.",
    modules=["discipline", "verification", "tool-use", "failure-modes"],
)
```

Send `system` as the system prompt of your API call.

## Picking modules

For runtimes that don't have skills/hooks/registries, the framework collapses to a curated subset:

| If your agent does… | Load these |
|---------------------|-----------|
| Single-shot Q&A, no tools | `discipline.md` (~ 60 tokens overhead is fine) |
| Tool calls (file ops, web fetch) | + `tool-use.md`, `verification.md` |
| Long iterative loops | + `context.md`, `failure-modes.md` |
| Spawns parallel sub-calls | + `delegation.md` |
| Outputs structured JSON / XML | + `formatting.md` |

For minimal footprint, **just load `discipline.md`**. The four stances (think-first, simplicity, surgical, goal-driven) catch most behavior failures alone.

## Token cost

Approximate token costs for each conduct module (English, GPT-4 tokenizer):

| Module | Tokens |
|--------|--------|
| `discipline.md` | ~700 |
| `context.md` | ~900 |
| `verification.md` | ~900 |
| `delegation.md` | ~1100 |
| `tool-use.md` | ~1200 |
| `formatting.md` | ~1300 |
| `skill-authoring.md` | ~1300 |
| `hooks.md` | ~1200 |
| `precedent.md` | ~1400 |
| `tier-sizing.md` | ~1300 |
| `web-fetch.md` | ~1100 |
| `failure-modes.md` | ~1200 |

A 5-module starter pack is ~4500 tokens — meaningful but not ruinous on long contexts.

## Top-200 / bottom-200 anchoring

System prompt placement matters (see [`../conduct/context.md`](../conduct/context.md) § U-curve placement). Concrete:

```python
TOP = "# Critical rules\n\n- Never run `rm -rf` without confirmation.\n- Always verify file paths via Glob before Edit."
BOTTOM = "# Reminder\n\n- Critical rules above are non-negotiable. Re-read before any destructive action."

system = "\n\n".join([
    TOP,
    assemble_system_prompt(role, modules),
    BOTTOM,
])
```

Anything in the middle of a long system prompt is in the recall valley. Move load-bearing rules to top or bottom.

## Failure logging without a runtime

Without hooks or runtime support, log failures yourself after each interaction:

```python
def review_turn(transcript: str) -> dict | None:
    """
    Heuristic post-hoc review. Look for known failure signatures.
    Return a {code, evidence, counter} dict, or None.
    """
    if "rm -rf" in transcript and "confirm" not in transcript.lower():
        return {"code": "F10", "evidence": "destructive op without confirm", "counter": "..."}
    if any(x in transcript for x in ["I think it might", "should work", "probably"]):
        return {"code": "F02", "evidence": "unverified claim", "counter": "..."}
    return None
```

Pipe results to a JSONL log; reference [`../taxonomy/`](../taxonomy/) for the full code list.

## Verifying the adoption

A simple ablation:

1. Run your eval suite *without* the conduct loaded.
2. Run it *with* the 5-module starter pack loaded.
3. Compare: did refusals on destructive ops increase? Did unverified claims decrease? Did task-drift incidents go down?

If the deltas are zero, the modules aren't being loaded — check your assembly path.

## What this won't do

- Provide runtime enforcement. A system prompt is advisory; the model can choose to ignore it under certain conditions (jailbreaks, conflicting user instructions, attenuation over long context).
- Compete with structured-output APIs. If you need exact JSON, pair with the API's response schema mode.
- Replace evals. The conduct shifts default behavior; per-task prompts and evals still own task quality.
