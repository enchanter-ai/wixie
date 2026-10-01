# Installation

`wixie` is an @enchanter-ai product. It installs as a Claude Code plugin.

## Prerequisites

- **Claude Code** — latest stable. Check with `/version`.
- **bash + jq** — for hooks. Pre-installed on macOS and most Linux; on Windows use git-bash (bundled with Git for Windows) and install `jq` manually.
- **Python 3.8+** — for helper scripts in `shared/scripts/`. Standard library only; no pip installs.
- **Node 18+** — *only* if you will regenerate diagrams or render math SVGs. Ignore if you only consume pre-rendered artifacts.

## Recommended: Claude Code marketplace

```
/plugin marketplace add enchanter-ai/wixie
/plugin install full@wixie
```

Claude Code resolves the meta-plugin's dependency list and installs every sub-plugin in one pass. Verify with:

```
/plugin list
```

You should see each sub-plugin listed with its version. If a sub-plugin is missing, check `/plugin marketplace list` and confirm the `enchanter-ai/wixie` entry is present.

## What an installed plugin carries

Claude Code installs a plugin by copying only its own `plugins/<name>/` directory. Nothing from the repository root (`CLAUDE.md`, `.vis-lock`, `.vis-cache/`, `scripts/`, `shared/`) is part of an install, so each plugin ships the **transitive runtime dependency closure** of its skills, agents, hooks and scripts **inside the plugin**, under `vendor/`:

- Scripts, the model registry, reference docs and eval corpora: `plugins/<name>/vendor/wixie/shared/...`, mirroring the repo layout, so each script's own lookups (for example `token-count.py` reading `../models-registry.json`, `convergence.py` loading `self-eval.py`, `report-gen.py` running `html-to-pdf.py`) resolve inside the plugin.
- Shared conduct: `plugins/<name>/vendor/vis/packages/<pkg>/conduct/<module>.md` (pinned vis release) and `plugins/<name>/vendor/wixie/shared/conduct/<module>.md` (Wixie's own).
- The parts of the repo-level contract a plugin relies on: exact `## ` sections of `CLAUDE.md` as `plugins/<name>/vendor/wixie/claude-md.<section>.md` (for example `claude-md.deploy-bar.md`, `claude-md.behavioral-contracts.md`), never the whole file.
- References: skills and agents point at these as `${CLAUDE_PLUGIN_ROOT}/vendor/...`. Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}` with the installed plugin root in plugin skill content and agent bodies. Prompt folders are user workspace and go to `${CLAUDE_PROJECT_DIR}/prompts/` (your project), not into the plugin; plugin state (inference-engine catalog and briefings, deep-research briefs) lives in the plugin's own `state/`.
- Provenance: each plugin's `vendor/VENDORED.json` lists every vendored file with its destination, source, source path, source revision (vis tag commit, or the git blob id of the Wixie source), sha256, sha1 and consumers (the plugin files or vendored files that need it), plus any relative link inside a pinned upstream file that has no target in its source (recorded, not dropped).

| Plugin | Files | Vendored runtime closure |
|---|---|---|
| convergence-engine | 14 | CLAUDE.md sections: agent-tiers, anti-patterns, artifacts-per-prompt, behavioral-contracts, deploy-bar; data: eval-corpus/deploy-bar/corpus.json, models-registry.json; references: direction-lock; scripts: convergence.py, efficacy-replay.py, html-to-pdf.py, report-gen.py, self-eval.py, token-count.py |
| deep-research | 23 | scripts: dossier-cite-validator.py, fetcher-normalize.py; vis conduct: capability-fidelity, context, delegation, discipline, doubt-engine, failure-modes, precedent-freshness, precedent, prior-art-discovery, reversibility-foresight, substrate-consumption, sunk-cost-iteration, tier-sizing, tool-use, verdict-calibration, verification, citation-verification, mcp-research-discipline, research-pipeline, source-discipline, web-fetch |
| inference-engine | 19 | data: conduct/inference-substrate.md, models-registry.json; scripts: inference-engine.py; vis conduct: capability-fidelity, context, delegation, discipline, doubt-engine, failure-modes, precedent-freshness, precedent, prior-art-discovery, reversibility-foresight, substrate-consumption, sunk-cost-iteration, tier-sizing, tool-use, verdict-calibration, verification |
| prompt-crafter | 16 | CLAUDE.md sections: agent-tiers, anti-patterns, artifacts-per-prompt, behavioral-contracts, deploy-bar; data: models-registry.json; references: direction-lock, model-profiles, output-formats, prompt-anatomy, technique-engine; scripts: convergence.py, html-to-pdf.py, report-gen.py, self-eval.py, token-count.py |
| prompt-harden | 4 | CLAUDE.md sections: artifacts-per-prompt, behavioral-contracts, deploy-bar; references: direction-lock |
| prompt-refiner | 16 | CLAUDE.md sections: agent-tiers, anti-patterns, artifacts-per-prompt, behavioral-contracts, deploy-bar; data: models-registry.json; references: direction-lock, model-profiles, output-formats, prompt-anatomy, technique-engine; scripts: convergence.py, html-to-pdf.py, report-gen.py, self-eval.py, token-count.py |
| prompt-tester | 23 | CLAUDE.md sections: artifacts-per-prompt, behavioral-contracts, deploy-bar; data: eval-corpus/deploy-bar/corpus.json; references: direction-lock; scripts: efficacy-replay.py; vis conduct: capability-fidelity, context, delegation, discipline, doubt-engine, failure-modes, precedent-freshness, precedent, prior-art-discovery, reversibility-foresight, substrate-consumption, sunk-cost-iteration, tier-sizing, tool-use, verdict-calibration, verification, formatting |
| prompt-translate | 8 | CLAUDE.md sections: anti-patterns, behavioral-contracts, deploy-bar; data: models-registry.json; references: direction-lock, model-profiles, technique-engine; scripts: self-eval.py |
| full | 0 | none (meta-plugin) |

Not delivered by an install, by design or by limitation:

- The rest of the repo-level `CLAUDE.md` (its section on shared behavioral modules that "apply to every skill", the lifecycle and engine overviews) is loaded by Claude Code only when you work inside a full checkout, where `./scripts/bootstrap.sh` materializes the pinned vis modules into `.vis-cache/vis/`. Claude Code (2.1.280) has no plugin-level always-loaded context file; a plugin can only reach the model through the skills and agents it ships, so an install carries the sections its skills and agents cite, not the whole file.
- Two cross-plugin optional reads cannot resolve in an install because they are another plugin's mutable state: `/converge` step 0 (inference-engine's `state/briefings/wixie.md`) and `/create`'s reuse of a deep-research brief. Both skills treat a missing file as a normal branch (proceed without the briefing; run `/deep-research`).

### Maintainers: regenerating vendored files

The vendored files are generated; vis and this repository stay the source of truth. After changing a pin (`.vis-versions`), a vendored source (anything under `shared/` that a plugin uses, or a cited `CLAUDE.md` section), or a `${CLAUDE_PLUGIN_ROOT}/vendor/...` reference in a plugin:

```bash
./scripts/bootstrap.sh                   # re-resolve the pin, rewrite .vis-lock (pin changes only)
python scripts/vendor-conduct.py         # regenerate plugins/*/vendor/ (one command)
python scripts/vendor-conduct.py --check # byte-identity against the pin and this repo (needs the ../vis sibling)
```

Commit `.vis-lock`, the changed sources and `plugins/*/vendor/` together (a marketplace install clones the repository, so the vendored files must be committed). `--check` fails on a missing dependency, an unexpected file in `vendor/`, hash drift against the pin, this repo or `VENDORED.json` (including a source edited without regenerating), an external unresolved path (a skill, agent, hook or plugin script reference that leaves the plugin: `${CLAUDE_PLUGIN_ROOT}/..`, a cwd-relative `wixie/...` path, `.vis-cache/`, `../vis/`), and a duplicate conflicting destination. CI runs it in `vis-verify.yml`; `tests/distribution/` runs the offline form (`--check --offline`, anchored to the `.vis-lock` hashes and this repo), install-layout runtime checks, and drift cases against a synthetic vis release.

## Cherry-pick a single sub-plugin

Some sub-plugins are useful on their own. To install only one:

```
/plugin install <sub-plugin-name>@wixie
```

See [README.md](../README.md) § Plugins for the list of sub-plugin names.

## Via shell

The shell installer clones the repo, validates the environment, and copies plugins into `~/.claude/plugins/`. Use this path when you need the local `shared/scripts/*.py` available outside Claude Code.

```bash
bash <(curl -s https://raw.githubusercontent.com/enchanter-ai/wixie/main/install.sh)
```

The installer is idempotent — re-running it upgrades in place.

## From source (for contributors)

```bash
git clone https://github.com/enchanter-ai/wixie.git
cd wixie
bash install.sh
cd docs/assets && npm install     # only if you will touch diagrams / math SVGs
```

## Verifying the install

1. **Plugin list.** `/plugin list` shows each sub-plugin.
2. **First command.** Run the smoke test in [getting-started.md](getting-started.md).
3. **Tests.** For a contributor clone: `bash tests/run-all.sh`.

If any step fails, see [troubleshooting.md](troubleshooting.md).

## Uninstall

```
/plugin uninstall full@wixie
/plugin marketplace remove enchanter-ai/wixie
```

To remove the shell-installed copies as well: `rm -rf ~/.claude/plugins/wixie-*`.

## Upgrades

`/plugin upgrade full@wixie` for the marketplace install. Re-run the shell installer for the curl-based install. Before upgrading across a major version, skim [CHANGELOG.md](../CHANGELOG.md) for breaking changes.
