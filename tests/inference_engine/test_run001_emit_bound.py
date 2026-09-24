#!/usr/bin/env python3
"""WIX-RUN-001 follow-up (verifier finding V-RUN001-2, notes V-RUN001-1/-3).

- Claude Code discards a hook that outlives its timeout, and this plugin's own hooks use 3-5 s.
  The default emit wait therefore keeps a contended emit (engine alone, and through
  inference-emit.sh) well under 3 s: it returns "queued" with exit 0 in that bound.
- A queued event's rename is made durable (the pending directory is fsynced on POSIX).
- A pending/*.tmp left by a killed queue write is removed once it is stale; a fresh one (a
  write possibly in flight) and every completed pending/*.json are kept until folded.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

try:
    from tests.inference_engine import _support as S
    from tests.inference_engine.test_run001_concurrency import LockHolder
except ImportError:  # run as a script
    import _support as S
    from test_run001_concurrency import LockHolder

SMALLEST_HOOK_TIMEOUT = 3.0  # plugins/inference-engine/hooks/hooks.json


class EmitBound(S.StateTestCase):
    def setUp(self):
        super().setUp()
        self.state.mkdir(parents=True)
        self.holder = LockHolder(self.state)

    def tearDown(self):
        self.holder.release()
        super().tearDown()

    def test_engine_emit_default_wait_fits_the_hook_timeout(self):
        rec = S.write_json(self.tmp / "r.json", {"code": "B1", "tags": ["b"]})
        t0 = time.monotonic()
        proc = S.run_engine(self.state, "emit", str(rec))
        elapsed = time.monotonic() - t0
        self.ok(proc)
        self.assertEqual(S.first_token(proc), "queued")
        self.assertLess(elapsed, SMALLEST_HOOK_TIMEOUT)

    @unittest.skipUnless(shutil.which("bash"), "bash not available")
    def test_wrapper_default_wait_fits_the_hook_timeout(self):
        env = S.clean_env(self.state, WIXIE_INFERENCE_PYTHON=Path(sys.executable).as_posix())
        t0 = time.monotonic()
        proc = subprocess.run([shutil.which("bash"), S.EMIT_SH.as_posix(), "--code", "B2",
                               "--title", "t"], capture_output=True, env=env, timeout=60)
        elapsed = time.monotonic() - t0
        self.ok(proc)
        self.assertEqual(S.first_token(proc), "queued")
        self.assertLess(elapsed, SMALLEST_HOOK_TIMEOUT)

    @unittest.skipIf(sys.platform == "win32", "directory fsync is POSIX-only")
    def test_queued_event_fsyncs_the_pending_directory(self):
        rec = S.write_json(self.tmp / "r.json", {"code": "B3", "tags": ["b"]})
        probe = textwrap.dedent(f"""
            import os, runpy, stat, sys
            real = os.fsync
            def spy(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    sys.stderr.write("DIRFSYNC\\n")
                return real(fd)
            os.fsync = spy
            sys.argv = [{str(S.ENGINE)!r}, "emit", {str(rec)!r}]
            runpy.run_path({str(S.ENGINE)!r}, run_name="__main__")
        """)
        proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, timeout=60,
                              env=S.clean_env(self.state, WIXIE_INFERENCE_EMIT_WAIT="0.2"))
        self.assertEqual(S.first_token(proc), "queued", S.err(proc))
        self.assertIn("DIRFSYNC", S.err(proc).splitlines())


class StalePendingTemp(S.StateTestCase):
    def test_only_stale_temp_files_are_removed(self):
        pending = self.state / "pending"
        pending.mkdir(parents=True)
        old = time.time() - 3600
        stale = pending / "abc.json.x1y2.tmp"
        stale.write_text("{", encoding="utf-8")
        os.utime(stale, (old, old))
        fresh = pending / "def.json.z9.tmp"
        fresh.write_text("{", encoding="utf-8")
        event = {"code": "P1", "tags": ["p"], "session_id": "s", "event_id": "e1",
                 "ts": "2026-09-01T00:00:00Z"}
        done = pending / "0123.json"
        done.write_text(json.dumps(event), encoding="utf-8")
        os.utime(done, (old, old))

        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())
        self.assertFalse(done.exists())
        self.assertEqual(S.summary(self.state)["patterns"]["P1"]["observations"], 1)


if __name__ == "__main__":
    S.main()
