#!/usr/bin/env python3
"""WIX-IE-EMIT-WIN-001: the inference-emit skill's Step 2 command must work under Git Bash +
native Windows Python (the documented Windows path).

Bash process substitution `<(...)` hands the child a /proc/<pid>/fd/N path that a native
Windows python.exe cannot open, so the engine exits 2 and records nothing. The record is fed on
stdin (`emit -`) instead.

  a  static: no skill/agent markdown under plugins/ feeds a python script through `<(`.
  b  live: the Step 2 block, extracted verbatim from SKILL.md with a valid record substituted,
     runs in bash against a private copy of the plugin and a private CLAUDE_PLUGIN_DATA; it
     exits 0, prints `emitted`, and the event is recorded exactly once.

Offline: no model, no network. All scratch lives under WIXIE_TEST_ROOT.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from tests.inference_engine import _support as S
except ImportError:  # run as a script
    import _support as S

REPO = S.REPO
PLUGIN = REPO / "plugins" / "inference-engine"
SKILL = PLUGIN / "skills" / "inference-emit" / "SKILL.md"
GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")
BASH = str(GIT_BASH) if os.name == "nt" and GIT_BASH.is_file() else "bash"
SCRUB = S.SCRUBBED_ENV + ("WIXIE_INFERENCE_SEED", "CLAUDE_PLUGIN_DATA", "CLAUDE_PLUGIN_ROOT")
FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.S | re.M)
PYTHON = re.compile(r"\bpython[0-9.]*\b")
EVENT_ID = "wix-ie-emit-win-001-probe"


def md_files() -> list[Path]:
    return [p for p in sorted((REPO / "plugins").rglob("*.md"))
            if {"skills", "agents"} & set(p.relative_to(REPO / "plugins").parts)]


def step2_block(text: str) -> str:
    section = text.split("### Step 2: Emit", 1)[1].split("\n### ", 1)[0]
    m = FENCE.search(section)
    if not m:
        raise AssertionError("no fenced command block under '### Step 2: Emit'")
    return m.group(1)


class EmitSkillStdin(unittest.TestCase):
    def test_a_no_process_substitution_into_python(self):
        bad = []
        for p in md_files():
            text = p.read_text(encoding="utf-8")
            chunks = FENCE.findall(text) + text.splitlines()
            if any("<(" in c and PYTHON.search(c) for c in chunks):
                bad.append(p.relative_to(REPO).as_posix())
        self.assertEqual(bad, [], "python fed through `<(` process substitution (breaks native "
                                  "Windows python under Git Bash; use `emit -` on stdin)")

    def test_b_step2_command_records_once(self):
        tmp = Path(tempfile.mkdtemp(prefix="wixie-emit-skill-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        root = tmp / "cache" / "inference-engine"
        shutil.copytree(PLUGIN, root, ignore=shutil.ignore_patterns("__pycache__"))
        data = tmp / "data"
        record = {"code": "F99", "category": "test", "title": "emit skill stdin probe",
                  "cause": "test", "counter": "test", "signal": "test",
                  "tags": ["wixie", "emit-skill-probe"], "scope": "wixie",
                  "event_id": EVENT_ID, "session_id": "emit-skill-probe"}
        block = step2_block(SKILL.read_text(encoding="utf-8"))
        self.assertIn("<your JSON record>", block)
        script = block.replace("<your JSON record>", json.dumps(record))
        # Run the block verbatim; `python` resolves to the interpreter running this test.
        shim = 'python() { "$WIXIE_TEST_PY" "$@"; }\n'
        env = {k: v for k, v in os.environ.items() if k not in SCRUB}
        env.update(CLAUDE_PLUGIN_ROOT=root.as_posix(), CLAUDE_PLUGIN_DATA=data.as_posix(),
                   WIXIE_TEST_PY=Path(sys.executable).as_posix())
        proc = subprocess.run([BASH, "-c", shim + script], cwd=tmp, env=env,
                              capture_output=True, timeout=120)
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0, f"stdout: {out}\nstderr: {err}")
        self.assertTrue(out.startswith("emitted"), f"stdout: {out!r}\nstderr: {err}")
        state = data / "state"
        hits = sum(1 for ln in (state / "artifacts.jsonl").read_bytes().splitlines()
                   if ln.strip() and json.loads(ln).get("event_id") == EVENT_ID)
        self.assertEqual(hits, 1)
        pending = state / "pending"
        self.assertEqual(sorted(pending.glob("*.json")) if pending.is_dir() else [], [])


if __name__ == "__main__":
    S.main()
