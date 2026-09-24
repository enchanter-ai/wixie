#!/usr/bin/env python3
"""WIX-SEC-BRIEF-001: render-briefing must not write outside the briefings directory.

Acceptance criterion (control/NEW_FINDINGS.json): render-briefing refuses any plugin name that
is not a documented slug and never writes outside the resolved briefings directory, verified by
a post-resolution containment check; legitimate slugs still render; refusal is a documented
non-zero exit (2).
"""
from __future__ import annotations

import os
import unittest

try:
    from tests.inference_engine import _support as S
except ImportError:  # run as a script
    import _support as S

EXIT_USAGE = 2

RECORDS = [{"code": "P1", "tags": ["wixie"], "ts": "2026-09-01T00:00:00Z", "session_id": f"s{i}"}
           for i in range(3)]


class BriefingPath(S.StateTestCase):
    def setUp(self):
        super().setUp()
        self.state.mkdir(parents=True)
        S.write_jsonl(self.state / "artifacts.jsonl", RECORDS)
        self.ok(S.run_engine(self.state, "reconcile"))

    def _files(self):
        return sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*") if p.is_file())

    def test_traversal_and_non_slug_names_are_refused(self):
        before = self._files()
        bad = ["../../escaped", "../escaped", "..", ".", "a/b", "a\\b", "/abs", "C:x", "x:y",
               "a b", ".hidden", "-dash", "", "x" * 65, "CON", "nul", "com1.txt", "LPT9",
               "conin$", "café"]
        for name in bad:
            proc = S.run_engine(self.state, "render-briefing", name)
            self.ok(proc, EXIT_USAGE)
        self.assertEqual(self._files(), before)
        self.assertFalse((self.tmp / "escaped.md").exists())

    def test_legitimate_slugs_render_inside_the_briefings_dir(self):
        for name in ("wixie", "all", "hydra", "wixie.v2", "my_plugin-2", "X" * 64):
            proc = S.run_engine(self.state, "render-briefing", name)
            self.ok(proc)
            target = self.state / "briefings" / f"{name}.md"
            self.assertTrue(target.is_file(), name)
        text = (self.state / "briefings" / "wixie.md").read_text(encoding="utf-8")
        self.assertIn("### P1", text)

    def test_symlinked_target_is_refused(self):
        outside = self.tmp / "outside.md"
        outside.write_text("untouched", encoding="utf-8")
        (self.state / "briefings").mkdir(exist_ok=True)
        try:
            os.symlink(outside, self.state / "briefings" / "evil.md")
        except (OSError, NotImplementedError) as exc:
            raise unittest.SkipTest(f"cannot create symlinks here: {exc}")
        proc = S.run_engine(self.state, "render-briefing", "evil")
        self.ok(proc, EXIT_USAGE)
        self.assertEqual(outside.read_text(encoding="utf-8"), "untouched")


if __name__ == "__main__":
    S.main()
