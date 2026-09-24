#!/usr/bin/env python3
"""WIX-RUN-004 follow-up (verifier notes V-RUN004-1, V-RUN004-2).

- A catalog whose top-level fields have the wrong type (accounting as a list, ...) is corrupt:
  status / query / render-briefing exit 74 with no traceback, and reconcile quarantines and
  rebuilds it.
- A corrupt catalog next to an empty or missing artifact log is still repaired by reconcile
  (quarantined; the empty state has no catalog), so status stops pointing at reconcile.
"""
from __future__ import annotations

import json

try:
    from tests.inference_engine import _support as S
except ImportError:  # run as a script
    import _support as S

EXIT_CORRUPT_STATE = 74
RECORDS = [{"code": "A1", "tags": ["x"], "ts": "2026-09-01T00:00:00Z", "session_id": f"s{i}"}
           for i in range(3)]


class TopLevelFields(S.StateTestCase):
    def _check(self, mutate):
        self.state.mkdir(parents=True)
        S.write_jsonl(self.state / "artifacts.jsonl", RECORDS)
        self.ok(S.run_engine(self.state, "reconcile"))
        clean = S.summary(self.state)
        cat = S.catalog(self.state)
        mutate(cat)
        bad = json.dumps(cat).encode("utf-8")
        (self.state / "catalog.json").write_bytes(bad)
        for args in (("status",), ("query", "A1"), ("render-briefing", "wixie")):
            self.ok(S.run_engine(self.state, *args), EXIT_CORRUPT_STATE)
        self.ok(S.run_engine(self.state, "reconcile"))
        quarantined = sorted(self.state.glob("catalog.json.corrupt-*"))
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_bytes(), bad)
        self.assertEqual(S.summary(self.state), clean)
        self.ok(S.run_engine(self.state, "status"))

    def test_accounting_is_a_list(self):
        self._check(lambda c: c.__setitem__("accounting", [1, 2]))

    def test_accounting_is_a_string(self):
        self._check(lambda c: c.__setitem__("accounting", "x"))

    def test_accounting_value_not_an_int(self):
        self._check(lambda c: c["accounting"].__setitem__("rejected_lines", "many"))

    def test_rejected_is_not_a_list_of_objects(self):
        self._check(lambda c: c.__setitem__("rejected", [5]))

    def test_outcome_and_totals_wrong_type(self):
        self._check(lambda c: c.update(outcome=5, total_artifacts="3"))


class CorruptCatalogEmptyLog(S.StateTestCase):
    def _check(self, log_bytes):
        self.state.mkdir(parents=True)
        if log_bytes is not None:
            (self.state / "artifacts.jsonl").write_bytes(log_bytes)
        (self.state / "catalog.json").write_bytes(b"{broken")
        self.ok(S.run_engine(self.state, "status"), EXIT_CORRUPT_STATE)
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(len(list(self.state.glob("catalog.json.corrupt-*"))), 1)
        self.assertFalse((self.state / "catalog.json").exists())
        self.ok(S.run_engine(self.state, "status"))
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertEqual(len(list(self.state.glob("catalog.json.corrupt-*"))), 1)

    def test_missing_log(self):
        self._check(None)

    def test_empty_log(self):
        self._check(b"")

    def test_whitespace_only_log(self):
        self._check(b"\n  \n")


if __name__ == "__main__":
    S.main()
