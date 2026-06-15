#!/usr/bin/env python3
"""codex-mcp-server.py — dependency-free MCP stdio server that exposes a plugin's
bundled scripts as Codex tools.

This is the CLAUDE_PLUGIN_ROOT workaround: Claude Code injected ${CLAUDE_PLUGIN_ROOT}
at runtime so skills could shell out to shared/scripts/*.py. Codex has no such
injection, so codex-sync bundles this server + the scripts into the plugin at
`plugins/<n>/mcp/` and wires `.mcp.json` to launch it (cwd = plugin root):

    { "mcpServers": { "<name>": { "cwd": ".", "command": "python",
                                  "args": ["./mcp/server.py"] } } }

`codex plugin add` copies the whole plugin dir (including ./mcp) into its cache, so
this server and its ./lib scripts travel with the plugin and resolve relative to
__file__ — no absolute paths, no plugin-root variable needed.

Each `lib/*.py` becomes one tool named after the file stem. A tools/call runs
`python lib/<name>.py <args-split>` and returns stdout. Pure stdlib: implements the
JSON-RPC 2.0 / MCP stdio handshake (initialize, tools/list, tools/call) over
newline-delimited JSON.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parent / "lib"
PROTOCOL_FALLBACK = "2025-06-18"


def tools() -> list[dict]:
    out = []
    if LIB.is_dir():
        for p in sorted(LIB.glob("*.py")):
            out.append({
                "name": p.stem,
                "description": f"Run shared/scripts/{p.name} (bundled). Pass CLI args as a single string.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"args": {"type": "string", "description": "CLI arguments"}},
                },
            })
    return out


def call_tool(name: str, arguments: dict) -> dict:
    script = LIB / f"{name}.py"
    if not script.is_file():
        return {"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True}
    argstr = (arguments or {}).get("args", "") or ""
    try:
        cmd = [sys.executable, str(script), *shlex.split(argstr)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(LIB.parent.parent))
        text = proc.stdout if proc.returncode == 0 else f"[exit {proc.returncode}]\n{proc.stdout}\n{proc.stderr}"
        return {"content": [{"type": "text", "text": text or "(no output)"}], "isError": proc.returncode != 0}
    except Exception as e:  # noqa: BLE001 — surface any launch failure to the caller
        return {"content": [{"type": "text", "text": f"error running {name}: {e}"}], "isError": True}


def handle(msg: dict) -> dict | None:
    mid = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        ver = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_FALLBACK
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": ver,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "codex-scripts", "version": "1.0.0"},
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools()}}
    if method == "tools/call":
        params = msg.get("params") or {}
        return {"jsonrpc": "2.0", "id": mid, "result": call_tool(params.get("name", ""), params.get("arguments", {}))}
    if method is not None and method.startswith("notifications/"):
        return None  # notifications get no response
    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
