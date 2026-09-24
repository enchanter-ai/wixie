#!/usr/bin/env python3
"""WIX-RUN-002 (verifier finding V-RUN002-1): any copy of an engine-written event log adds
nothing.

A line the engine wrote carries a stored _identity. When it recomputes exactly from the line,
it is that event: a plain copy, the log concatenated with itself, or the master log duplicated
in place must not change any count. Lines whose _identity does not verify (edited or forged)
fall back to content identity, and genuinely distinct events still count.
"""
from __future__ import annotations

import json

try:
    from tests.inference_engine import _support as S
except ImportError:  # run as a script
    import _support as S


def rec(code, **extra):
    r = {"code": code, "tags": ["t"], "title": f"title {code}"}
    r.update(extra)
    return r


class EngineLogCopies(S.StateTestCase):
    def setUp(self):
        super().setUp()
        # An engine-written log mixing every stamp kind: repeated source lines (source_ordinal),
        # a record with no time (clock-stamped ts), dated precedent lines, and live emits.
        seed = S.write_jsonl(self.tmp / "p.jsonl", [
            rec("A", date="2026-04-12", source_session="s1"),
            rec("A", date="2026-04-12", source_session="s1"),
            rec("B"),
            rec("C", date="2026-04-13"),
        ])
        self.ok(S.run_engine(self.state, "backfill", str(seed)))
        for sess in ("live-1", "live-2"):
            e = S.write_json(self.tmp / "e.json", rec("A"))
            self.ok(S.run_engine(self.state, "emit", str(e), CLAUDE_CODE_SESSION_ID=sess))
        self.ok(S.run_engine(self.state, "reconcile"))
        self.before = S.summary(self.state)
        self.log = (self.state / "artifacts.jsonl").read_bytes()
        self.assertEqual(self.before["total_artifacts"], 6)

    def _imported(self, proc):
        return int(S.out(proc).split()[1])

    def test_plain_copy_adds_nothing(self):
        copy = self.tmp / "copy.jsonl"
        copy.write_bytes(self.log)
        res = self.ok(S.run_engine(self.state, "backfill", str(copy)))
        self.assertEqual(self._imported(res), 0)
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state), self.before)

    def test_log_concatenated_with_itself_adds_nothing(self):
        copy = self.tmp / "double.jsonl"
        copy.write_bytes(self.log + self.log + self.log)
        res = self.ok(S.run_engine(self.state, "backfill", str(copy)))
        self.assertEqual(self._imported(res), 0)
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(S.summary(self.state), self.before)
        self.assertEqual((self.state / "artifacts.jsonl").read_bytes(), self.log)

    def test_master_log_duplicated_in_place_counts_once(self):
        (self.state / "artifacts.jsonl").write_bytes(self.log + self.log)
        self.ok(S.run_engine(self.state, "reconcile"))
        cat = S.catalog(self.state)
        self.assertEqual(S.summary(self.state), self.before)
        self.assertEqual(cat["accounting"]["duplicate_lines"], 6)

    def test_concatenated_copy_into_a_fresh_store_equals_the_original(self):
        fresh = self.new_state("fresh")
        copy = self.tmp / "double.jsonl"
        copy.write_bytes(self.log + self.log)
        res = self.ok(S.run_engine(fresh, "backfill", str(copy)))
        self.assertEqual(self._imported(res), 6)
        self.ok(S.run_engine(fresh, "reconcile"))
        self.assertEqual(S.summary(fresh), self.before)

    def test_distinct_events_still_count_and_bad_identity_is_not_trusted(self):
        lines = [json.loads(x) for x in S.log_lines(self.state)]
        # A forged _identity copied from another line does not verify: the line is identified by
        # its content and counts as its own event.
        forged = dict(rec("D", date="2026-05-01"), _identity=lines[0]["_identity"])
        src = S.write_jsonl(self.tmp / "new.jsonl", [forged, rec("E", date="2026-05-02")])
        res = self.ok(S.run_engine(self.state, "backfill", str(src)))
        self.assertEqual(self._imported(res), 2)
        self.ok(S.run_engine(self.state, "reconcile"))
        pats = S.summary(self.state)["patterns"]
        self.assertEqual((pats["D"]["observations"], pats["E"]["observations"]), (1, 1))
        self.assertEqual(S.summary(self.state)["total_artifacts"], 8)


if __name__ == "__main__":
    S.main()
