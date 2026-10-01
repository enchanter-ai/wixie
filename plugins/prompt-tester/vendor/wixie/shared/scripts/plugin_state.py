"""Where Wixie scripts keep mutable runtime state (WIX-SEC-WS-001, decision D17).

An installed plugin tree (CLAUDE_PLUGIN_ROOT, the Claude Code plugin cache) is immutable
product content: no script writes into it. Every script that persists state resolves the
location with this one precedence:

  1. explicit: a per-feature override (an env var such as WIXIE_INFERENCE_STATE, or an option
     such as efficacy-replay.py --out).
  2. plugin data: the plugin's persistent data directory. Claude Code exports
     CLAUDE_PLUGIN_DATA to plugin hooks and substitutes ${CLAUDE_PLUGIN_DATA} into skill and
     agent text, which hands it to the script as --plugin-data. Installed mode is detected by
     this value only, never by the shape of the script's path.
  3. checkout: full-checkout development mode, a documented location inside the Wixie
     repository checkout that contains the running script (unchanged behaviour). A checkout
     is recognised positively: a directory above the script holding both
     .claude-plugin/marketplace.json and shared/scripts/plugin_state.py.

When none applies (for example a vendored copy run by hand from an installed plugin without
CLAUDE_PLUGIN_DATA) there is no writable location: the caller refuses to write.

Stdlib only. Importing this module has no side effects.
"""
from __future__ import annotations

import os
from pathlib import Path

HELPER_NAME = "plugin_state.py"
MARKETPLACE = Path(".claude-plugin") / "marketplace.json"
_MAX_WALK = 8


def plugin_data_dir(value: str | None = None) -> Path | None:
    """The plugin data directory: `value` (from --plugin-data) if non-empty, else $CLAUDE_PLUGIN_DATA."""
    for v in (value, os.environ.get("CLAUDE_PLUGIN_DATA")):
        if v and v.strip():
            return Path(v.strip())
    return None


def checkout_root(script: str | os.PathLike) -> Path | None:
    """The Wixie repository checkout that contains `script` (canonical or vendored copy), or None."""
    here = Path(script).resolve()
    for d in list(here.parents)[:_MAX_WALK]:
        if (d / MARKETPLACE).is_file() and (d / "shared" / "scripts" / HELPER_NAME).is_file():
            return d
    return None


def resolve(script: str | os.PathLike, *, explicit: str | os.PathLike | None, data_sub: str,
            checkout_rel: str, plugin_data: str | None = None) -> tuple[Path | None, str]:
    """Return (location, source) with source in explicit | plugin-data | checkout | unresolved."""
    if explicit is not None and str(explicit).strip():
        return Path(str(explicit).strip()), "explicit"
    data = plugin_data_dir(plugin_data)
    if data is not None:
        return data / data_sub, "plugin-data"
    root = checkout_root(script)
    if root is not None:
        return root / checkout_rel, "checkout"
    return None, "unresolved"


UNRESOLVED_HINT = ("no writable state location: this copy runs outside a Wixie checkout and neither "
                   "CLAUDE_PLUGIN_DATA (--plugin-data) nor an explicit location is set; the installed "
                   "plugin tree is read-only (WIX-SEC-WS-001)")
