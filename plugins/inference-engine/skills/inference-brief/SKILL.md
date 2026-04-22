---
name: inference-brief
description: >
  Render the top-of-context briefing for a target plugin. Reads the
  inference-engine catalog, filters elevated patterns tagged for the target
  plugin, writes state/briefings/<plugin>.md. Use before a session where
  the target plugin is about to do high-stakes work (e.g. /converge,
  /mantis-review). Safe and cheap — rendering is a pure function of the
  current catalog.
  Auto-triggers on: "/inference-brief", "render the flux briefing",
  "refresh briefings", "prep the ufopedia brief for <plugin>".
allowed-tools: Bash(python *) Read Agent
---

# Inference Brief

Emit `state/briefings/<plugin>.md` — a concise Markdown summary of elevated patterns that apply to the target plugin.

## Usage

The caller provides the plugin name. Defaults to `flux` at Phase 1. Pass `all` to include every elevated pattern regardless of tag.

## Pipeline

### Step 1: Spawn the briefer agent

Delegate to the Haiku-tier briefer for a shape-check pass:

```
Agent(subagent_type="general-purpose", model="haiku",
      prompt="Run the briefer agent defined at
              flux/plugins/inference-engine/agents/briefer.md
              with plugin='<target>'.")
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
- One briefing per file per plugin. `briefings/flux.md` is the only briefing a Flux skill reads.
