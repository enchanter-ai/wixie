# Recipes

Adoption guides for host platforms. Each recipe gives concrete file paths, concrete config, and verification steps for wiring agent-foundations into a specific host. Unlike the conduct modules (which say *what* to do) and the engines (which say *what to compute*), recipes say *where to put it* — per-host specifics that would be wrong to bake into the portable layers.

## Index

| Recipe | What it covers |
|--------|---------------|
| [claude-code.md](claude-code.md) | Wiring conduct modules and hooks into Claude Code via `CLAUDE.md` and `.claude/settings.json` |
| [openai-agents.md](openai-agents.md) | Integrating the framework with the OpenAI Agents SDK: tool descriptors, handoffs, and guardrails |
| [cursor.md](cursor.md) | Dropping conduct modules into Cursor via `.cursor/rules/` and `.mdc` frontmatter |
| [langchain.md](langchain.md) | Adopting the framework inside a LangChain agent pipeline: chain structure and callback hooks |
| [pydantic-ai.md](pydantic-ai.md) | Wiring conduct and engines into a Pydantic AI agent: validators, deps, and result types |
| [baml.md](baml.md) | Using BAML for structured output extraction in agent pipelines: schema authoring and BamlError handling |
| [system-prompt.md](system-prompt.md) | Loading conduct modules via a system prompt when no framework-native integration is available |
| [eval-harnesses.md](eval-harnesses.md) | Connecting agent-foundations to an eval harness: failure-code tagging, axis aggregation, and regression gates |

## How to read

1. **Match your host** — find the recipe for the platform or SDK you're adopting into.
2. **Read the recipe end-to-end** — each recipe is self-contained; it names the files to create, the config to set, and the check to run to confirm the integration is live.
3. **Follow cross-references** — recipes link into `conduct/`, `engines/`, and `taxonomy/` for the rules and math that back the wiring. Read those docs for the *why*; the recipe gives the *how*.
