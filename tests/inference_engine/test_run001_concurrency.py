#!/usr/bin/env python3
"""WIX-RUN-001: concurrent reconcile and the emit-lock policy.

Acceptance criterion (findings.json): a bounded concurrent-reconcile test on supported
platforms completes every invocation with a documented success or controlled conflict outcome,
preserves a parseable catalog derived from the complete artifact stream, and emits no unhandled
filesystem exception.

Rate-independent design (OBS-03): contention is FORCED by an external process that holds
state/.lock through the engine's own state_lock(), so the busy outcome is exercised on every
run rather than hoped for. The concurrent run at the end checks the outcome set, not a
"0 failures in N runs" rate.

Documented contract under test:
  reconcile / backfill with the lock held -> exit 75 within WIXIE_INFERENCE_LOCK_TIMEOUT, no
                                             change to catalog or log.
  emit with the lock held                 -> waits at most WIXIE_INFERENCE_EMIT_WAIT, then writes
                                             state/pending/<identity>.json, exit 0, outcome
                                             token "queued"; folded into the log exactly once by
                                             the next lock holder.
  inference-emit.sh                       -> exit 0 only when the event is durably recorded
                                             (or the gate is off); 1 otherwise.
"""
from __future__ import annotations

import concurrent.futures
import json
import shutil
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

try:
    from tests.inference_engine import _support as S
except ImportError:  # run as a script
    import _support as S

EXIT_LOCK_BUSY = 75
SLACK = 20.0  # generous allowance for interpreter start-up on a loaded Windows host

HOLDER = textwrap.dedent("""
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("inference_engine", sys.argv[1])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with mod.state_lock(10, "test-holder"):
        print("held", flush=True)
        sys.stdin.readline()
""")

SEED = [{"code": f"C{i % 8}", "tags": ["c"], "ts": f"2026-09-{1 + i % 20:02d}T00:00:00Z",
         "session_id": f"s{i}"} for i in range(64)]


class LockHolder:
    """An external process holding state/.lock until released."""

    def __init__(self, state: Path) -> None:
        self.proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(S.ENGINE)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=S.clean_env(state))
        line = self.proc.stdout.readline().decode().strip()
        if line != "held":
            self.proc.kill()
            raise AssertionError("lock holder could not take state/.lock: "
                                 + self.proc.stderr.read().decode("utf-8", "replace"))

    def release(self) -> None:
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=30)
        for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            if not pipe.closed:
                pipe.close()


class ForcedContention(S.StateTestCase):
    def setUp(self):
        super().setUp()
        self.state.mkdir(parents=True)
        S.write_jsonl(self.state / "artifacts.jsonl", SEED)
        self.ok(S.run_engine(self.state, "reconcile"))
        self.catalog_before = (self.state / "catalog.json").read_bytes()
        self.log_before = (self.state / "artifacts.jsonl").read_bytes()
        self.holder = LockHolder(self.state)

    def tearDown(self):
        self.holder.release()
        super().tearDown()

    def test_reconcile_is_busy_within_the_bound_and_changes_nothing(self):
        t0 = time.monotonic()
        proc = S.run_engine(self.state, "reconcile", WIXIE_INFERENCE_LOCK_TIMEOUT="1")
        elapsed = time.monotonic() - t0
        self.ok(proc, EXIT_LOCK_BUSY)
        self.assertGreaterEqual(elapsed, 1.0)
        self.assertLess(elapsed, 1.0 + SLACK)
        self.assertEqual((self.state / "catalog.json").read_bytes(), self.catalog_before)
        self.holder.release()
        self.ok(S.run_engine(self.state, "reconcile"))

    def test_backfill_is_busy_and_imports_nothing(self):
        seed = S.write_jsonl(self.tmp / "p.jsonl", [{"code": "NEW", "tags": ["n"]}])
        proc = S.run_engine(self.state, "backfill", str(seed), WIXIE_INFERENCE_LOCK_TIMEOUT="1")
        self.ok(proc, EXIT_LOCK_BUSY)
        self.assertEqual((self.state / "artifacts.jsonl").read_bytes(), self.log_before)

    def test_emit_queues_after_a_bounded_wait_and_is_folded_exactly_once(self):
        # dup-1 is already in the log; dup-2 is queued twice (a retry); fresh is new.
        already = {"code": "Q1", "tags": ["q"], "event_id": "dup-1", "session_id": "sq"}
        self.holder.release()
        rec = S.write_json(self.tmp / "a.json", already)
        self.ok(S.run_engine(self.state, "emit", str(rec)))
        self.holder = LockHolder(self.state)
        log_before = (self.state / "artifacts.jsonl").read_bytes()

        records = [already,
                   {"code": "Q2", "tags": ["q"], "event_id": "dup-2", "session_id": "sq"},
                   {"code": "Q2", "tags": ["q"], "event_id": "dup-2", "session_id": "sq"},
                   {"code": "Q3", "tags": ["q"], "session_id": "sq"}]
        for i, r in enumerate(records):
            path = S.write_json(self.tmp / f"q{i}.json", r)
            t0 = time.monotonic()
            proc = S.run_engine(self.state, "emit", str(path), WIXIE_INFERENCE_EMIT_WAIT="0.5")
            self.assertLess(time.monotonic() - t0, 0.5 + SLACK)
            self.ok(proc)
            self.assertEqual(S.first_token(proc), "queued")
        self.assertEqual((self.state / "artifacts.jsonl").read_bytes(), log_before)
        self.assertEqual(len(list((self.state / "pending").glob("*.json"))), 3)

        self.holder.release()
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(list((self.state / "pending").glob("*")), [])
        pats = S.summary(self.state)["patterns"]
        self.assertEqual((pats["Q1"]["observations"], pats["Q2"]["observations"],
                          pats["Q3"]["observations"]), (1, 1, 1))
        first = S.summary(self.state)
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state), first)

    def test_broken_lock_file_is_a_controlled_outcome(self):
        self.holder.release()
        (self.state / ".lock").unlink()
        (self.state / ".lock").mkdir()
        proc = S.run_engine(self.state, "reconcile", WIXIE_INFERENCE_LOCK_TIMEOUT="1")
        self.ok(proc, EXIT_LOCK_BUSY)
        rec = S.write_json(self.tmp / "b.json", {"code": "B", "tags": ["b"]})
        proc = S.run_engine(self.state, "emit", str(rec), WIXIE_INFERENCE_EMIT_WAIT="0.2")
        self.ok(proc)
        self.assertEqual(S.first_token(proc), "queued")


class Folding(S.StateTestCase):
    def test_crash_between_append_and_pending_delete_counts_once(self):
        rec = S.write_json(self.tmp / "r.json", {"code": "F1", "tags": ["f"], "session_id": "s"})
        self.ok(S.run_engine(self.state, "emit", str(rec)))
        stored = json.loads(S.log_lines(self.state)[0])
        (self.state / "pending").mkdir()
        (self.state / "pending" / f"{stored['_identity']}.json").write_text(
            json.dumps(stored), encoding="utf-8")
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state)["patterns"]["F1"]["observations"], 1)
        self.assertEqual(list((self.state / "pending").glob("*")), [])

    def test_stale_catalog_temp_files_are_removed(self):
        S.write_jsonl(self.tmp / "p.jsonl", SEED[:3])
        self.ok(S.run_engine(self.state, "backfill", str(self.tmp / "p.jsonl")))
        (self.state / "catalog.json.tmp").write_text("{", encoding="utf-8")
        (self.state / "catalog.json.abc123.tmp").write_text("{", encoding="utf-8")
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(sorted(self.state.glob("catalog.json*.tmp")), [])


class ConcurrentLoad(S.StateTestCase):
    def test_concurrent_reconciles_and_emits(self):
        self.state.mkdir(parents=True)
        S.write_jsonl(self.state / "artifacts.jsonl", SEED)
        recs = [S.write_json(self.tmp / f"e{i}.json", {"code": f"E{i}", "tags": ["e"]})
                for i in range(16)]
        env = {"WIXIE_INFERENCE_LOCK_TIMEOUT": "240", "WIXIE_INFERENCE_EMIT_WAIT": "5"}
        jobs = [("reconcile",)] * 16 + [("emit", str(r)) for r in recs]
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda a: (a[0], S.run_engine(self.state, *a, timeout=600,
                                                                  **env)), jobs))
        for kind, proc in results:
            self.assertNotIn("Traceback", S.err(proc))
            if kind == "reconcile":
                self.assertIn(proc.returncode, (0, EXIT_LOCK_BUSY), S.err(proc))
            else:
                self.assertEqual(proc.returncode, 0, S.err(proc))
                self.assertIn(S.first_token(proc), ("emitted", "queued"))
        self.ok(S.run_engine(self.state, "reconcile"))
        cat = S.catalog(self.state)
        self.assertEqual(cat["outcome"], "clean")
        self.assertEqual(cat["total_artifacts"], 64 + 16)
        pats = S.summary(self.state)["patterns"]
        for i in range(16):
            self.assertEqual(pats[f"E{i}"]["observations"], 1)
        self.assertEqual(sorted(self.state.glob("catalog.json*.tmp")), [])


@unittest.skipUnless(shutil.which("bash"), "bash not available")
class EmitWrapper(S.StateTestCase):
    def _wrapper(self, *args, stdin=None, **env):
        env = {"WIXIE_INFERENCE_PYTHON": Path(sys.executable).as_posix(), **env}
        full = S.clean_env(self.state, **env)
        return subprocess.run([shutil.which("bash"), S.EMIT_SH.as_posix(), *args], input=stdin,
                              capture_output=True, env=full, timeout=180)

    def test_recorded_events_exit_zero(self):
        self.ok(self._wrapper("--code", "W1", "--title", "t — x", "--tags", "a,b"))
        self.ok(self._wrapper("-", stdin=b'{"code": "W2", "tags": ["x"]}'))
        self.assertEqual(len(S.log_lines(self.state)), 2)

    def test_unrecorded_events_never_exit_zero(self):
        self.ok(self._wrapper("-", stdin=b"{not json"), 1)
        self.ok(self._wrapper("--bogus"), 1)
        self.ok(self._wrapper("--code", "W3"), 1)
        self.ok(self._wrapper("--code", "W4", "--title", "t",
                              WIXIE_INFERENCE_PYTHON="no-such-python-binary"), 1)
        self.assertEqual(S.log_lines(self.state), [])

    def test_gate_off_is_a_silent_noop(self):
        proc = self.ok(self._wrapper("--code", "W5", "--title", "t", WIXIE_INFERENCE_ENABLED="0"))
        self.assertEqual(proc.stdout + proc.stderr, b"")
        self.assertFalse(self.state.exists())

    def test_busy_lock_queues_and_exits_zero(self):
        self.state.mkdir(parents=True)
        holder = LockHolder(self.state)
        try:
            proc = self._wrapper("--code", "W6", "--title", "t", "--event-id", "w6",
                                 WIXIE_INFERENCE_EMIT_WAIT="0.3")
            self.ok(proc)
            self.assertEqual(S.first_token(proc), "queued")
        finally:
            holder.release()
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state)["patterns"]["W6"]["observations"], 1)


if __name__ == "__main__":
    S.main()
