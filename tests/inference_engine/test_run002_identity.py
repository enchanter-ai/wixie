#!/usr/bin/env python3
"""WIX-RUN-002: event identity and replay correctness.

Acceptance criterion (findings.json): reapplying the same backfill after any success or
ambiguous interruption does not increase observations, sessions, LLR, or posterior counts
unless the input carries a distinct documented event identity.

Cases: exact replay; replay after a partial prior import; hard kill mid-backfill then replay;
identical content from two sessions (session_id, source_session, date, ts); two distinct
events in one session (emit, and repeated lines in one backfill source); re-importing a copy
of the engine-written log (as a backfill source and as a stray file in the state dir); the
host's CLAUDE_CODE_SESSION_ID and the documented session precedence; supplied event_id
retries.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest

try:
    from tests.inference_engine import _support as S
except ImportError:  # run as a script
    import _support as S

LLR_ONE = 1.7918  # ln(0.30/0.05), one observation


def precedent(code: str, **extra) -> dict:
    rec = {"code": code, "category": "process-discipline", "title": f"title {code}",
           "cause": "c", "counter": "k", "signal": "s", "tags": ["t", code.lower()]}
    rec.update(extra)
    return rec


class ReplayIdempotence(S.StateTestCase):
    def test_exact_replay_is_idempotent(self):
        seed = S.write_jsonl(self.tmp / "seed.jsonl", [
            {"code": "R1", "tags": ["repeat"], "ts": "2026-09-21T00:00:00Z", "session_id": "same"},
        ])
        for _ in range(3):
            self.ok(S.run_engine(self.state, "backfill", str(seed)))
        self.ok(S.run_engine(self.state, "reconcile"))
        pat = S.summary(self.state)["patterns"]["R1"]
        self.assertEqual(pat["observations"], 1)
        self.assertEqual(pat["sessions_seen"], ["same"])
        self.assertEqual(round(pat["llr"], 4), LLR_ONE)
        self.assertEqual(pat["verdict"], "noise")
        self.assertEqual(len(S.log_lines(self.state)), 1)

    def test_replay_after_success_matches_single_import(self):
        records = [precedent(f"P{i % 7}", date=f"2026-04-{10 + i % 5:02d}",
                             source_session=f"sess-{i % 3}", notes=f"n{i}") for i in range(40)]
        seed = S.write_jsonl(self.tmp / "seed.jsonl", records)
        clean = self.new_state("clean")
        self.ok(S.run_engine(clean, "backfill", str(seed)))
        self.ok(S.run_engine(clean, "reconcile"))

        for _ in range(2):
            self.ok(S.run_engine(self.state, "backfill", str(seed)))
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state), S.summary(clean))
        second = S.run_engine(self.state, "backfill", str(seed))
        self.ok(second)
        self.assertEqual(S.first_token(second), "backfilled")
        self.assertEqual(S.out(second).split()[1], "0")

    def test_replay_after_partial_import_adds_only_the_remainder(self):
        records = [precedent(f"Q{i}", date="2026-05-01", source_session="s") for i in range(30)]
        full = S.write_jsonl(self.tmp / "full.jsonl", records)
        half = S.write_jsonl(self.tmp / "half.jsonl", records[:13])
        clean = self.new_state("clean")
        self.ok(S.run_engine(clean, "backfill", str(full)))
        self.ok(S.run_engine(clean, "reconcile"))

        self.ok(S.run_engine(self.state, "backfill", str(half)))
        self.ok(S.run_engine(self.state, "backfill", str(full)))
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state), S.summary(clean))
        self.assertEqual(len(S.log_lines(self.state)), 30)

    def test_hard_kill_mid_backfill_then_replay(self):
        n = 3000
        records = [precedent(f"K{i % 50}", date=f"2026-03-{1 + i % 28:02d}",
                             source_session=f"ks-{i % 17}", notes=f"row {i}") for i in range(n)]
        seed = S.write_jsonl(self.tmp / "big.jsonl", records)
        clean = self.new_state("clean")
        self.ok(S.run_engine(clean, "backfill", str(seed), timeout=600))
        self.ok(S.run_engine(clean, "reconcile", timeout=600))

        log = self.state / "artifacts.jsonl"
        proc = subprocess.Popen([sys.executable, str(S.ENGINE), "backfill", str(seed)],
                                env=S.clean_env(self.state), stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            # Poll the size, not the content: a reader must not contend with the writer.
            if log.exists() and log.stat().st_size >= 200 * 200:
                break
            if proc.poll() is not None:
                break
            time.sleep(0.005)
        proc.kill()
        proc.wait()
        killed_at = len(S.log_lines(self.state))
        self.assertLess(killed_at, n, "backfill finished before it could be interrupted")
        self.assertGreater(killed_at, 0)

        self.ok(S.run_engine(self.state, "backfill", str(seed), timeout=600))
        again = self.ok(S.run_engine(self.state, "backfill", str(seed), timeout=600))
        self.assertEqual(S.out(again).split()[1], "0")
        # If the kill tore the line being written, that fragment stays its own rejected line
        # (reconcile then reports a partial outcome, exit 3) and the record it belonged to was
        # re-imported by the replay; every event is still counted exactly once.
        rec = S.run_engine(self.state, "reconcile", timeout=600)
        self.assertIn(rec.returncode, (0, 3), S.err(rec))
        self.assertNotIn("Traceback", S.err(rec))
        self.assertLessEqual(len(S.catalog(self.state).get("rejected", [])), 1)
        self.assertEqual(S.summary(self.state), S.summary(clean))


class DistinctEventsStayDistinct(S.StateTestCase):
    def test_same_content_from_two_source_sessions(self):
        seed = S.write_jsonl(self.tmp / "p.jsonl", [
            precedent("X1", date="2026-04-12", source_session="sessionA"),
            precedent("X1", date="2026-04-12", source_session="sessionB"),
        ])
        self.ok(S.run_engine(self.state, "backfill", str(seed)))
        self.ok(S.run_engine(self.state, "backfill", str(seed)))
        self.ok(S.run_engine(self.state, "reconcile"))
        pat = S.summary(self.state)["patterns"]["X1"]
        self.assertEqual(pat["observations"], 2)
        self.assertEqual(sorted(pat["sessions_seen"]), ["sessionA", "sessionB"])

    def test_same_content_distinct_date_or_ts(self):
        seed = S.write_jsonl(self.tmp / "p.jsonl", [
            precedent("D1", date="2026-04-12"),
            precedent("D1", date="2026-04-13"),
            precedent("T1", ts="2026-04-12T01:00:00Z"),
            precedent("T1", ts="2026-04-12T02:00:00Z"),
        ])
        self.ok(S.run_engine(self.state, "backfill", str(seed)))
        self.ok(S.run_engine(self.state, "backfill", str(seed)))
        self.ok(S.run_engine(self.state, "reconcile"))
        pats = S.summary(self.state)["patterns"]
        self.assertEqual(pats["D1"]["observations"], 2)
        self.assertEqual(pats["T1"]["observations"], 2)

    def test_two_emits_of_one_payload_in_one_session_are_two_events(self):
        rec = S.write_json(self.tmp / "r.json", precedent("E1"))
        for _ in range(2):
            self.ok(S.run_engine(self.state, "emit", str(rec), CLAUDE_CODE_SESSION_ID="sess-1"))
        self.ok(S.run_engine(self.state, "reconcile"))
        pat = S.summary(self.state)["patterns"]["E1"]
        self.assertEqual(pat["observations"], 2)
        self.assertEqual(pat["sessions_seen"], ["sess-1"])

    def test_repeated_lines_in_one_source_are_distinct_and_replay_safe(self):
        line = precedent("L1", date="2026-04-12", source_session="s")
        seed = S.write_jsonl(self.tmp / "p.jsonl", [line, line, precedent("L2"), line])
        self.ok(S.run_engine(self.state, "backfill", str(seed)))
        self.ok(S.run_engine(self.state, "backfill", str(seed)))
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state)["patterns"]["L1"]["observations"], 3)
        self.assertEqual(len(S.log_lines(self.state)), 4)


class LogCopyReimport(S.StateTestCase):
    def _populate(self):
        seed = S.write_jsonl(self.tmp / "p.jsonl", [
            precedent("C1", date="2026-04-12", source_session="a"),
            precedent("C1", date="2026-04-12", source_session="a"),   # repeat, ordinal 1
            precedent("C2"),                                          # no session, no time
            precedent("C3", date="2026-04-14"),
        ])
        self.ok(S.run_engine(self.state, "backfill", str(seed)))
        emitted = S.write_json(self.tmp / "e.json", precedent("C1"))
        self.ok(S.run_engine(self.state, "emit", str(emitted), CLAUDE_CODE_SESSION_ID="live"))
        self.ok(S.run_engine(self.state, "reconcile"))
        return S.summary(self.state), len(S.log_lines(self.state))

    def test_backfilling_a_copy_of_the_log_adds_nothing(self):
        before, lines = self._populate()
        copy = self.tmp / "artifacts-copy.jsonl"
        copy.write_bytes((self.state / "artifacts.jsonl").read_bytes())
        res = self.ok(S.run_engine(self.state, "backfill", str(copy)))
        self.assertEqual(S.out(res).split()[1], "0")
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state), before)
        self.assertEqual(len(S.log_lines(self.state)), lines)

    def test_a_log_copy_left_in_the_state_dir_is_not_double_counted(self):
        before, _ = self._populate()
        (self.state / "artifacts-backup.jsonl").write_bytes(
            (self.state / "artifacts.jsonl").read_bytes())
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state), before)

    def test_legacy_log_without_identity_keeps_its_counts(self):
        # A pre-identity log: engine-stamped lines with no _identity, including a line repeated
        # by the old non-idempotent backfill. Every line keeps counting as before, and
        # re-importing a copy of it adds nothing.
        rec = {"code": "G1", "tags": ["g"], "ts": "2026-04-12", "session_id": "a", "plugin": "p"}
        self.state.mkdir(parents=True)
        S.write_jsonl(self.state / "artifacts.jsonl", [rec, rec, dict(rec, code="G2")])
        self.ok(S.run_engine(self.state, "reconcile"))
        before = S.summary(self.state)
        self.assertEqual(before["patterns"]["G1"]["observations"], 2)
        copy = S.write_jsonl(self.tmp / "legacy-copy.jsonl", [rec, rec, dict(rec, code="G2")])
        self.ok(S.run_engine(self.state, "backfill", str(copy)))
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state), before)


class SessionIdentity(S.StateTestCase):
    def _emit(self, record, **env):
        path = S.write_json(self.tmp / "r.json", record)
        return self.ok(S.run_engine(self.state, "emit", str(path), **env))

    def _stored(self):
        return [json.loads(x) for x in S.log_lines(self.state)]

    def test_claude_code_session_id_is_captured(self):
        self._emit(precedent("S1"), CLAUDE_CODE_SESSION_ID="host-A")
        self._emit(precedent("S1"), CLAUDE_CODE_SESSION_ID="host-B")
        self.ok(S.run_engine(self.state, "reconcile"))
        pat = S.summary(self.state)["patterns"]["S1"]
        self.assertEqual(pat["observations"], 2)
        self.assertEqual(sorted(pat["sessions_seen"]), ["host-A", "host-B"])
        stored = self._stored()
        self.assertEqual([r["_session_source"] for r in stored],
                         ["env:CLAUDE_CODE_SESSION_ID", "env:CLAUDE_CODE_SESSION_ID"])

    def test_session_precedence(self):
        self._emit(precedent("S2"), CLAUDE_CODE_SESSION_ID="code", CLAUDE_SESSION_ID="legacy")
        self._emit(precedent("S2"), CLAUDE_SESSION_ID="legacy")
        self._emit(precedent("S2"))
        self._emit(precedent("S2", session_id="explicit"), CLAUDE_CODE_SESSION_ID="code")
        self._emit(precedent("S2", source_session="src"), CLAUDE_CODE_SESSION_ID="code")
        stored = self._stored()
        self.assertEqual([r["session_id"] for r in stored],
                         ["code", "legacy", "unknown", "explicit", "src"])
        self.assertEqual([r["_session_source"] for r in stored],
                         ["env:CLAUDE_CODE_SESSION_ID", "env:CLAUDE_SESSION_ID", "unknown",
                          "record:session_id", "record:source_session"])

    def test_backfill_never_takes_the_importing_session(self):
        seed = S.write_jsonl(self.tmp / "p.jsonl", [precedent("S3")])
        self.ok(S.run_engine(self.state, "backfill", str(seed), CLAUDE_CODE_SESSION_ID="importer"))
        stored = self._stored()
        self.assertEqual(stored[0]["session_id"], "unknown")
        self.assertEqual(stored[0]["_session_source"], "unknown")

    def test_supplied_event_id_makes_emit_retry_idempotent(self):
        rec = precedent("S4", event_id="hook-evt-1")
        first = self._emit(rec, CLAUDE_CODE_SESSION_ID="s")
        second = self._emit(rec, CLAUDE_CODE_SESSION_ID="s")
        self.assertEqual(S.first_token(first), "emitted")
        self.assertEqual(S.first_token(second), "duplicate")
        self._emit(precedent("S4", event_id="hook-evt-2"), CLAUDE_CODE_SESSION_ID="s")
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state)["patterns"]["S4"]["observations"], 2)
        self.assertEqual(len(S.log_lines(self.state)), 2)


if __name__ == "__main__":
    S.main()
