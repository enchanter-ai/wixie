#!/usr/bin/env python3
"""WIX-IE-EMIT-WRAPPER-001 (D25): the hook wrapper the inference-emit skill names must ship
inside the installed inference-engine plugin.

A marketplace install copies only plugins/inference-engine/. A hook told to run the repo-root
`shared/scripts/inference-emit.sh` finds nothing there, so the event is silently lost.

  a  static: the path in the SKILL.md hook sentence ("Hooks should call `...`") is a
     ${CLAUDE_PLUGIN_ROOT} path that resolves to a file inside the plugin, and no skill, agent,
     hook or README text under plugins/ tells a caller to run a repo-root `shared/scripts/...`
     path (bare, not vendor/wixie/- or wixie/-prefixed) or names inference-emit.sh by any path
     other than the vendored one.
  b  live: ONLY plugins/inference-engine is copied to a scratch dir outside the checkout; the
     hook invocation extracted from the copied SKILL.md runs in bash with cwd outside the repo,
     no WIXIE_*/CLAUDE_* repo variables, WIXIE_INFERENCE_ENABLED=1 and a private
     CLAUDE_PLUGIN_DATA, in pipe-in and flag mode: exit 0, recorded exactly once; a duplicate
     event_id exits 0 and adds nothing; gate off exits 0 and records nothing. Every byte of the
     copied plugin is unchanged afterwards and no __pycache__ appears in it.

Offline: no model, no network. All scratch lives under WIXIE_TEST_ROOT.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
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
PLUGINS = REPO / "plugins"
PLUGIN = PLUGINS / "inference-engine"
SKILL_REL = Path("skills") / "inference-emit" / "SKILL.md"
GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")
BASH = str(GIT_BASH) if os.name == "nt" and GIT_BASH.is_file() else "bash"
HOOK_SENTENCE = re.compile(r"Hooks should call\s+`([^`]+)`")
ROOT_PATH = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s\"'`]+)")
FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.S | re.M)
BARE = r"(?<![\w/.-])(?:\./)?shared/scripts/[\w.-]+"
RUN_BARE = re.compile(r"\b(?:call|run|invoke|execute|bash|sh|python3?(?:\s+-\w+)*)\s+[`\"']?" + BARE)
EMIT_SH_PATH = re.compile(r"[\w.${}/-]*/inference-emit\.sh")
INSTALLED_SUFFIX = "vendor/wixie/shared/scripts/inference-emit.sh"


def hook_invocation(skill_text: str) -> str:
    m = HOOK_SENTENCE.search(skill_text)
    if not m:
        raise AssertionError("SKILL.md has no 'Hooks should call `...`' instruction")
    return m.group(1)


def shipped_text_files() -> list[Path]:
    out = []
    for p in sorted(PLUGINS.rglob("*")):
        rel = p.relative_to(PLUGINS).parts
        if not p.is_file() or len(rel) < 2 or rel[1] in ("vendor", "state"):
            continue
        if (p.suffix == ".md" and ({"skills", "agents"} & set(rel) or p.name == "README.md")) \
                or (rel[1] == "hooks" and p.suffix == ".json"):
            out.append(p)
    return out


def tree_digest(root: Path) -> dict:
    return {f.relative_to(root).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(root.rglob("*")) if f.is_file()}


def inside(child: Path, parent: Path) -> bool:
    c, p = os.path.normcase(os.path.abspath(child)), os.path.normcase(os.path.abspath(parent))
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


class EmitWrapperInstalled(unittest.TestCase):
    def test_a_hook_path_is_plugin_local(self):
        inv = hook_invocation((PLUGIN / SKILL_REL).read_text(encoding="utf-8"))
        m = ROOT_PATH.search(inv)
        self.assertIsNotNone(m, f"hook invocation {inv!r} does not name a ${{CLAUDE_PLUGIN_ROOT}} path")
        target = (PLUGIN / m.group(1)).resolve()
        self.assertTrue(inside(target, PLUGIN.resolve()), f"{inv!r} escapes the plugin dir")
        self.assertTrue(target.is_file(), f"{inv!r} -> {target} is not shipped in the plugin")

        bad = []
        for p in shipped_text_files():
            text = p.read_text(encoding="utf-8")
            where = p.relative_to(REPO).as_posix()
            for n, line in enumerate(text.splitlines(), 1):
                if RUN_BARE.search(line):
                    bad.append(f"{where}:{n}: runs a repo-root shared/scripts path: {line.strip()}")
                for tok in EMIT_SH_PATH.findall(line):
                    # The installed path, or the explicitly repo-labelled source tree (wixie/shared/...).
                    if not tok.endswith(INSTALLED_SUFFIX) and not tok.startswith("wixie/shared/scripts/"):
                        bad.append(f"{where}:{n}: inference-emit.sh by a non-installed path: {tok}")
            for block in FENCE.findall(text):
                for line in block.splitlines():
                    if re.search(BARE, line):
                        bad.append(f"{where}: fenced command uses a repo-root shared/scripts path: {line.strip()}")
        self.assertEqual(bad, [])

    def test_b_plugin_only_copy_runs_the_hook(self):
        tmp = Path(tempfile.mkdtemp(prefix="wixie-emit-wrapper-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        # Outside the checkout (or only in its gitignored .test-root scratch when WIXIE_TEST_ROOT is unset).
        self.assertTrue(not inside(tmp, REPO) or inside(tmp, REPO / ".test-root"), tmp)
        root = tmp / "cache" / "inference-engine"
        shutil.copytree(PLUGIN, root, ignore=shutil.ignore_patterns("__pycache__"))
        data = tmp / "data"
        work = tmp / "cwd"
        work.mkdir()
        before = tree_digest(root)

        inv = hook_invocation((root / SKILL_REL).read_text(encoding="utf-8"))
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("WIXIE_", "CLAUDE_")) and k not in S.SCRUBBED_ENV
               and k not in ("PYTHONDONTWRITEBYTECODE", "PYTHONPATH", "PYTHONHOME")}
        env.update(CLAUDE_PLUGIN_ROOT=root.as_posix(), CLAUDE_PLUGIN_DATA=data.as_posix(),
                   CLAUDE_CODE_SESSION_ID="emit-wrapper-probe",
                   WIXIE_INFERENCE_PYTHON=Path(sys.executable).as_posix())

        def hook(args: str, stdin: bytes | None = None, enabled: bool = True):
            e = dict(env)
            if enabled:
                e["WIXIE_INFERENCE_ENABLED"] = "1"
            p = subprocess.run([BASH, "-c", f"{inv} {args}"], cwd=work, env=e, input=stdin,
                               capture_output=True, timeout=120)
            return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")

        def hits(event_id: str) -> int:
            log = data / "state" / "artifacts.jsonl"
            if not log.is_file():
                return 0
            return sum(1 for ln in log.read_bytes().splitlines()
                       if ln.strip() and json.loads(ln).get("event_id") == event_id)

        rec = {"code": "F97", "category": "test", "title": "emit wrapper pipe probe", "cause": "test",
               "counter": "test", "signal": "test", "tags": ["wixie", "emit-wrapper-probe"],
               "scope": "wixie", "event_id": "wix-ie-emit-wrapper-pipe"}
        for _ in range(2):  # second run: duplicate event_id, exit 0, nothing added
            rc, out, err = hook("-", json.dumps(rec).encode("utf-8"))
            self.assertEqual(rc, 0, f"pipe-in: stdout {out!r} stderr {err}")
            self.assertEqual(hits("wix-ie-emit-wrapper-pipe"), 1, f"stdout {out!r} stderr {err}")

        flags = " ".join(shlex.quote(a) for a in (
            "--code", "F96", "--category", "test", "--title", "emit wrapper flag probe",
            "--cause", "test", "--counter", "test", "--signal", "test",
            "--tags", "wixie,emit-wrapper-probe", "--scope", "wixie", "--event-id", "wix-ie-emit-wrapper-flag"))
        for _ in range(2):
            rc, out, err = hook(flags)
            self.assertEqual(rc, 0, f"flag: stdout {out!r} stderr {err}")
            self.assertEqual(hits("wix-ie-emit-wrapper-flag"), 1, f"stdout {out!r} stderr {err}")

        off = dict(rec, event_id="wix-ie-emit-wrapper-off")
        rc, out, err = hook("-", json.dumps(off).encode("utf-8"), enabled=False)
        self.assertEqual((rc, out), (0, ""), err)
        self.assertEqual(hits("wix-ie-emit-wrapper-off"), 0)

        pending = data / "state" / "pending"
        self.assertEqual(sorted(pending.glob("*.json")) if pending.is_dir() else [], [])
        self.assertEqual(list(root.rglob("__pycache__")), [])
        self.assertEqual(tree_digest(root), before, "the installed plugin dir was modified")


if __name__ == "__main__":
    S.main()
