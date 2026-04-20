# Installation

`flux` is an @enchanted-plugins product. It installs as a Claude Code plugin.

## Prerequisites

- **Claude Code** — latest stable. Check with `/version`.
- **bash + jq** — for hooks. Pre-installed on macOS and most Linux; on Windows use git-bash (bundled with Git for Windows) and install `jq` manually.
- **Python 3.8+** — for helper scripts in `shared/scripts/`. Standard library only; no pip installs.
- **Node 18+** — *only* if you will regenerate diagrams or render math SVGs. Ignore if you only consume pre-rendered artifacts.

## Recommended: Claude Code marketplace

```
/plugin marketplace add enchanted-plugins/flux
/plugin install full@flux
```

Claude Code resolves the meta-plugin's dependency list and installs every sub-plugin in one pass. Verify with:

```
/plugin list
```

You should see each sub-plugin listed with its version. If a sub-plugin is missing, check `/plugin marketplace list` and confirm the `enchanted-plugins/flux` entry is present.

## Cherry-pick a single sub-plugin

Some sub-plugins are useful on their own. To install only one:

```
/plugin install <sub-plugin-name>@flux
```

See [README.md](../README.md) § Plugins for the list of sub-plugin names.

## Via shell

The shell installer clones the repo, validates the environment, and copies plugins into `~/.claude/plugins/`. Use this path when you need the local `shared/scripts/*.py` available outside Claude Code.

```bash
bash <(curl -s https://raw.githubusercontent.com/enchanted-plugins/flux/main/install.sh)
```

The installer is idempotent — re-running it upgrades in place.

## From source (for contributors)

```bash
git clone https://github.com/enchanted-plugins/flux.git
cd flux
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
/plugin uninstall full@flux
/plugin marketplace remove enchanted-plugins/flux
```

To remove the shell-installed copies as well: `rm -rf ~/.claude/plugins/flux-*`.

## Upgrades

`/plugin upgrade full@flux` for the marketplace install. Re-run the shell installer for the curl-based install. Before upgrading across a major version, skim [CHANGELOG.md](../CHANGELOG.md) for breaking changes.
