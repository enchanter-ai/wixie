---
name: inference-brief
description: >
  Render the top-of-context briefing for a target plugin. Reads the
  inference-engine catalog, filters elevated patterns tagged for the target
  plugin, writes state/briefings/<plugin>.md. Use before a session where
  the target plugin is about to do high-stakes work (e.g. /converge,
  /lich-review). Safe and cheap — rendering is a pure function of the
  current catalog.
  Auto-triggers on: "/inference-brief", "render the wixie briefing",
  "refresh briefings", "prep the ufopedia brief for <plugin>".
allowed-tools: Bash(python *) Read Agent
---

# Inference Brief

**State location (WIX-SEC-WS-001).** The installed plugin tree is read-only. The engine keeps its state in `${CLAUDE_PLUGIN_DATA}/state/` (passed as `--plugin-data`), seeded once from the shipped `state/` on first write; `WIXIE_INFERENCE_STATE` overrides it, and in a repo checkout without plugin data it uses `plugins/inference-engine/state/`. `state/...` paths below are relative to that resolved directory (`status` prints it as `state_dir`).

Emit `state/briefings/<plugin>.md` — a concise Markdown summary of elevated patterns that apply to the target plugin.

## Usage

The caller provides the plugin name. Defaults to `wixie` at Phase 1. Pass `all` to include every elevated pattern regardless of tag.

The name must be a plugin slug: 1-64 characters from `[A-Za-z0-9._-]`, starting with a letter
or digit, and not a Windows device name (`CON`, `PRN`, `AUX`, `NUL`, `CONIN$`, `CONOUT$`,
`COM1`-`COM9`, `LPT1`-`LPT9`, with or without an extension). Anything else is refused with exit
`2` and nothing is written; the engine never rewrites a name into a different one. The output
path is checked after resolution to sit directly in the resolved `state/briefings/` directory,
and the file is written by atomic rename. Exit `74` means `catalog.json` is corrupt: run
`/inference-reconcile` first.

## Pipeline

### Step 1: Spawn the briefer agent

Delegate to the Haiku-tier briefer for a shape-check pass:

```
Agent(subagent_type="general-purpose", model="haiku",
      prompt="Run the briefer agent defined at
              ${CLAUDE_PLUGIN_ROOT}/agents/briefer.md
              with plugin='<target>' plugin_data='${CLAUDE_PLUGIN_DATA}'.")
```

### Step 2: Parse the agent's report

The agent returns one line:

```
rendered state/briefings/<plugin>.md (<N> elevated pattern(s), <M> bytes)
```

### Step 3: Report to caller

```
Briefing rendered: state/briefings/<plugin>.md
Elevated patterns: <N>
Last reconciled: <timestamp from catalog>
```

If `N == 0`, the briefing file contains a placeholder explaining that no cross-session patterns have elevated yet — the caller should not block on this. The briefing is advisory.

## Rules

- Do NOT render a briefing from a stale catalog. If the caller is about to do high-stakes work, run `/inference-reconcile` first. If unclear, ask.
- Do NOT fabricate elevated patterns. If the catalog is empty, the briefing says so.
- Do NOT filter or sort differently from the renderer. Consistency across plugins is load-bearing.
- One briefing per file per plugin. `briefings/wixie.md` is the only briefing a Wixie skill reads.
