# Troubleshooting

If something is broken, scan this page before filing a bug. Most first-time issues are one of these.

## First pass

1. `/version` — is Claude Code on a current stable release?
2. `/plugin list` — is the plugin actually installed?
3. `/doctor` — does Claude Code flag any environment issues?
4. Did you restart Claude Code after install? Hooks register at session start.

Most "it doesn't work" reports resolve on this list alone.

## Common issues

### Hooks don't fire

**Symptom:** You edited a file, ran a command, or started a session, and the plugin's hook output never appears.

**Usual causes:**

- The hook event doesn't match what you're doing. Check the hook's `matcher` in `plugins/*/hooks/*.json`. A hook matched to `Write` does not fire on `Bash`.
- Hook permissions: the hook script isn't executable (`chmod +x path/to/hook.sh`).
- jq not installed. Hooks that parse JSON silently fail if `jq` is missing. Run `which jq`.
- The hook timed out. Hooks have per-event budgets; see [../enchanter-foundations/packages/core/conduct/hooks.md](../../enchanter-foundations/packages/core/conduct/hooks.md) § Performance budget.

**Fix:** re-run with a more specific matcher, install `jq`, or restart Claude Code to re-register hooks.

### Permission prompts on every command

**Symptom:** Claude Code prompts for permission each time a plugin runs a tool.

**Cause:** Your `settings.json` doesn't have the plugin's tools in `permissions.allow`.

**Fix:** Add the specific tools (not a wildcard) to the `permissions.allow` list. Prefer per-tool entries over broad grants.

### "Plugin not found" after marketplace install

**Symptom:** `/plugin install full@wixie` succeeds but `/plugin list` doesn't show the sub-plugins.

**Cause:** Stale marketplace cache or a partial clone.

**Fix:**

```
/plugin marketplace remove enchanter-ai/wixie
/plugin marketplace add enchanter-ai/wixie
/plugin install full@wixie
```

### Renderer toolchain fails

**Symptom:** `npm install` in `docs/assets/` errors out, or `node render-math.js` / Puppeteer fails.

**Usual causes:**

- Node version mismatch. The toolchain targets Node 18+. Check `node --version`.
- Puppeteer couldn't download Chromium. Network policies or sandbox restrictions can block it. Set `PUPPETEER_SKIP_DOWNLOAD=true` and point `PUPPETEER_EXECUTABLE_PATH` at a local Chrome/Chromium.

**Fix:** upgrade Node, adjust Puppeteer env vars, or skip regeneration and commit pre-rendered artifacts from another machine.

### Python script fails with `ModuleNotFoundError`

**Symptom:** A helper script in `shared/scripts/` complains about a missing import.

**Cause:** You're on Python <3.8, or a shared-conduct rule was violated and someone added a pip dependency.

**Fix:** upgrade Python. If a new dep snuck in, file it as a bug — the ecosystem contract is **Python stdlib only** for scripts (see [CONTRIBUTING.md](../CONTRIBUTING.md)).

### Windows-specific gotchas

- **Path quoting.** Windows paths with drive letters (`c:/…`) and paths containing spaces **must** be quoted. Bash on Windows splits on the colon otherwise.
- **CRLF in shell scripts.** Git on Windows may have converted `.sh` files. `git config core.autocrlf input` before cloning, or re-save with LF.
- **`jq` not in PATH.** Install via `winget install jqlang.jq` or scoop, then restart the terminal.

### Tests fail on a fresh clone

**Symptom:** `bash tests/run-all.sh` reports failures immediately.

**Usual causes, in order of likelihood:**

1. Didn't run `install.sh` first — hooks aren't registered.
2. Running from the wrong working directory — `run-all.sh` expects repo root.
3. Dirty env: a previous session left state in `state/` directories. Reset per the test README.

### Ambiguous error messages

**Symptom:** A hook or script output is "Failed" with no detail.

**Cause:** Someone's error payload is unhelpful — see [../enchanter-foundations/packages/core/conduct/tool-use.md](../../enchanter-foundations/packages/core/conduct/tool-use.md) § Error payloads are contracts.

**Fix:** file a bug with the exact command and the observed output. Ambiguous errors are themselves bugs.

## When to file a bug vs. ask in Discussions

- **Bug:** reproducible, unexpected behavior. File in [Issues](https://github.com/enchanter-ai/wixie/issues) with the bug template.
- **Question or "is this expected?":** open a thread in [Discussions](https://github.com/enchanter-ai/wixie/discussions).
- **Security issue:** never file publicly. See [SECURITY.md](../SECURITY.md).

## Still stuck?

Gather these before asking:

- Exact command you ran.
- Exact error output (verbatim — don't paraphrase).
- `claude --version`, `/plugin list`, OS, and shell.
- Any non-default `settings.json` hook or permission entries relevant to the failure.

Then: [Discussions Q&A](https://github.com/enchanter-ai/wixie/discussions/categories/q-a).
