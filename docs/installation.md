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

Claude Code installs a plugin by copying only its own `plugins/<name>/` directory. Nothing from the repository root (`CLAUDE.md`, `.vis-lock`, `.vis-cache/`, `scripts/`, `shared/`) is part of an install, so every shared-conduct module a plugin's own files reference is shipped **inside the plugin**:

- Location: `plugins/<name>/vendor/vis/packages/<pkg>/conduct/<module>.md` for vis conduct, and `plugins/<name>/vendor/wixie/shared/conduct/<module>.md` for Wixie's own shared conduct.
- References: plugin files point at them as `${CLAUDE_PLUGIN_ROOT}/vendor/...`. Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}` with the installed plugin root in plugin skill content and plugin agent bodies, so the path resolves wherever the plugin is installed. No sibling vis checkout, no `../vis`, and no post-install bootstrap is involved.
- Provenance: each plugin's `vendor/VENDORED.json` lists every vendored file with its source path, vis package, version, tag, tag commit, sha256 and sha1. The content is copied from the pinned vis commit recorded in `.vis-lock` (currently `enchanter-<pkg>--v0.7.0` at `904873d`), never hand-edited.

| Plugin | Vendored shared conduct |
|---|---|
| deep-research | vis `core`: capability-fidelity, precedent, tier-sizing; vis `web`: citation-verification, mcp-research-discipline, research-pipeline, source-discipline, web-fetch |
| inference-engine | vis `core`: context; Wixie `shared/conduct/inference-substrate.md` |
| prompt-tester | vis `core`: tier-sizing; vis `skills`: formatting |
| convergence-engine, prompt-crafter, prompt-refiner, prompt-harden, prompt-translate, full | none (their files reference no shared-conduct module) |

The repo-level `CLAUDE.md` contract (its imported conduct modules, DEPLOY bar and behavioral contracts) is loaded by Claude Code only when you work inside a full checkout of this repository, where `./scripts/bootstrap.sh` materializes the pinned vis modules into `.vis-cache/vis/`. It is not delivered by a plugin install.

### Maintainers: regenerating vendored conduct

The vendored files are generated; vis stays the source of truth. After changing a pin (`.vis-versions`) or adding/removing a `${CLAUDE_PLUGIN_ROOT}/vendor/...` reference in a plugin:

```bash
./scripts/bootstrap.sh                   # re-resolve the pin, rewrite .vis-lock
python scripts/vendor-conduct.py         # regenerate plugins/*/vendor/ from the pinned commit
python scripts/vendor-conduct.py --check # byte-identity against the pin (needs the ../vis sibling)
```

Commit `.vis-lock` and `plugins/*/vendor/` together (a marketplace install clones the repository, so the vendored files must be committed). `--check` fails on a missing, extra or non-identical vendored file, a manifest mismatch, a moved tag, or a plugin reference that still points outside the plugin (for example `.vis-cache/` or `../vis/`). CI runs it in `vis-verify.yml`; `tests/distribution/` runs the offline form (`--check --offline`, anchored to the `.vis-lock` hashes) plus drift cases against a synthetic vis release.

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
