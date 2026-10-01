#!/usr/bin/env python3
"""WIX-RUN-004: a corrupt derived catalog never destroys recoverability.

Acceptance criterion (findings.json): given a complete valid artifact stream and an unreadable
derived catalog, reconciliation deterministically restores a complete parseable catalog or
emits a controlled, documented recovery state without an unhandled exception.

Documented contract under test:
  reconcile  -> exit 0, the corrupt file is moved (bytes intact) to catalog.json.corrupt-*,
                the new catalog equals a clean rebuild and records last_recovery.
  status / query / render-briefing on a corrupt catalog -> exit 74, no traceback, no write.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap

try:
    from tests.inference_engine import _support as S
except ImportError:  # run as a script
    import _support as S

EXIT_CORRUPT_STATE = 74

RECORDS = [
    {"code": "A1", "tags": ["x"], "ts": "2026-09-01T00:00:00Z", "session_id": "s1"},
    {"code": "A1", "tags": ["x"], "ts": "2026-09-02T00:00:00Z", "session_id": "s2"},
    {"code": "A1", "tags": ["x"], "ts": "2026-09-03T00:00:00Z", "session_id": "s3"},
    {"code": "B1", "tags": ["y"], "ts": "2026-09-04T00:00:00Z", "session_id": "s1"},
]


class CatalogRecovery(S.StateTestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path
        cls._ref = Path(tempfile.mkdtemp(prefix="wixie-inference-ref-"))
        S.write_jsonl(cls._ref / "seed.jsonl", RECORDS)
        (cls._ref / "state").mkdir()
        S.write_jsonl(cls._ref / "state" / "artifacts.jsonl", RECORDS)
        proc = S.run_engine(cls._ref / "state", "reconcile")
        assert proc.returncode == 0, S.err(proc)
        cls.clean_catalog = S.catalog(cls._ref / "state")
        cls.clean_summary = S.summary(cls._ref / "state")
        cls.a1_pid = next(p for p, v in cls.clean_catalog["patterns"].items() if v["code"] == "A1")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._ref, ignore_errors=True)

    def _state_with_catalog(self, catalog_bytes: bytes):
        self.state.mkdir(parents=True, exist_ok=True)
        S.write_jsonl(self.state / "artifacts.jsonl", RECORDS)
        (self.state / "catalog.json").write_bytes(catalog_bytes)

    def _quarantined(self):
        return sorted(self.state.glob("catalog.json.corrupt-*"))

    def _assert_recovers(self, catalog_bytes: bytes):
        self._state_with_catalog(catalog_bytes)

        for args in (("status",), ("query", "A1"), ("render-briefing", "wixie")):
            proc = S.run_engine(self.state, *args)
            self.assertEqual(proc.returncode, EXIT_CORRUPT_STATE, f"{args}: {S.err(proc)}")
            self.assertNotIn("Traceback", S.err(proc))
            self.assertIn("reconcile", S.err(proc))
        self.assertFalse((self.state / "briefings" / "wixie.md").exists())

        self.ok(S.run_engine(self.state, "reconcile"))
        quarantined = self._quarantined()
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_bytes(), catalog_bytes)
        cat = S.catalog(self.state)
        self.assertEqual(S.summary(self.state), self.clean_summary)
        self.assertEqual(cat["last_recovery"]["quarantined_as"], quarantined[0].name)

        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(len(self._quarantined()), 1)
        self.assertNotIn("last_recovery", S.catalog(self.state))
        self.ok(S.run_engine(self.state, "status"))
        return cat

    def test_truncated_json(self):
        full = json.dumps(self.clean_catalog, indent=2).encode("utf-8")
        self._assert_recovers(full[: len(full) // 2])

    def test_invalid_json(self):
        self._assert_recovers(b"{broken")

    def test_empty_file(self):
        self._assert_recovers(b"")

    def test_invalid_utf8(self):
        self._assert_recovers(b'{"patterns": {"\xff\xfe": 1}}')

    def test_wrong_top_level_type(self):
        self._assert_recovers(b"[1, 2, 3]")
        (self.state / "catalog.json").write_bytes(b'"a string"')
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state), self.clean_summary)

    def test_patterns_not_an_object(self):
        self._assert_recovers(b'{"version": 1, "patterns": ["x"]}')

    def test_non_dict_pattern_entry_keeps_well_formed_stamps(self):
        # The elevated pattern's prior entry is not an object; another entry is well-formed and
        # carries a first-crossing stamp that must survive the rebuild.
        bad = json.loads(json.dumps(self.clean_catalog))
        b1 = next(p for p, v in bad["patterns"].items() if v["code"] == "B1")
        bad["patterns"][b1]["elevated_at"] = "2026-01-01T00:00:00Z"
        bad["patterns"][self.a1_pid] = 5
        cat = self._assert_recovers(json.dumps(bad).encode("utf-8"))
        self.assertEqual(cat["last_recovery"]["stamps_carried_from"], 1)

    def test_wrongly_typed_pattern_field(self):
        bad = json.loads(json.dumps(self.clean_catalog))
        bad["patterns"][self.a1_pid]["tags"] = 5
        self._assert_recovers(json.dumps(bad).encode("utf-8"))

    def test_catalog_path_is_a_directory(self):
        self.state.mkdir(parents=True)
        S.write_jsonl(self.state / "artifacts.jsonl", RECORDS)
        (self.state / "catalog.json").mkdir()
        proc = S.run_engine(self.state, "status")
        self.assertEqual(proc.returncode, EXIT_CORRUPT_STATE, S.err(proc))
        self.assertNotIn("Traceback", S.err(proc))
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertTrue(self._quarantined()[0].is_dir())
        self.assertEqual(S.summary(self.state), self.clean_summary)

    def test_first_crossing_stamp_survives_a_normal_reconcile(self):
        good = json.loads(json.dumps(self.clean_catalog))
        good["patterns"][self.a1_pid]["elevated_at"] = "2026-01-01T00:00:00Z"
        self._state_with_catalog(json.dumps(good).encode("utf-8"))
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.catalog(self.state)["patterns"][self.a1_pid]["elevated_at"],
                         "2026-01-01T00:00:00Z")
        self.assertEqual(self._quarantined(), [])

    def test_interrupted_recovery_then_reconcile(self):
        # A reconcile that quarantines a corrupt catalog and is then killed before it writes the
        # new one (os._exit at the fsync of the new catalog, so no cleanup runs) leaves the
        # state recoverable: the next reconcile rebuilds a complete catalog.
        self._state_with_catalog(b"{broken")
        killer = textwrap.dedent(f"""
            import os, runpy, sys
            os.fsync = lambda fd: os._exit(9)
            sys.argv = [{str(S.ENGINE)!r}, "reconcile"]
            runpy.run_path({str(S.ENGINE)!r}, run_name="__main__")
        """)
        proc = subprocess.run([sys.executable, "-c", killer], env=S.clean_env(self.state),
                              capture_output=True, timeout=120)
        self.assertEqual(proc.returncode, 9, S.err(proc))
        self.assertFalse((self.state / "catalog.json").exists())
        self.assertEqual(len(self._quarantined()), 1)
        self.ok(S.run_engine(self.state, "status"))
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state), self.clean_summary)

    def test_kill_during_catalog_write_keeps_previous_catalog(self):
        # Guard: an abrupt stop while a new catalog is being written never leaves a torn
        # catalog.json behind.
        self._state_with_catalog(json.dumps(self.clean_catalog).encode("utf-8"))
        before = (self.state / "catalog.json").read_bytes()
        killer = textwrap.dedent(f"""
            import os, runpy, sys
            os.replace = lambda *a, **k: os._exit(9)
            sys.argv = [{str(S.ENGINE)!r}, "reconcile"]
            runpy.run_path({str(S.ENGINE)!r}, run_name="__main__")
        """)
        proc = subprocess.run([sys.executable, "-c", killer], env=S.clean_env(self.state),
                              capture_output=True, timeout=120)
        self.assertEqual(proc.returncode, 9, S.err(proc))
        self.assertEqual((self.state / "catalog.json").read_bytes(), before)
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state), self.clean_summary)


if __name__ == "__main__":
    S.main()
