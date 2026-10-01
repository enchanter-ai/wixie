#!/usr/bin/env python3
"""WIX-RUN-003 follow-up (verifier finding V-RUN003-1): a NEW rejected line is never hidden
behind older ones.

Contract: catalog accounting carries new_rejected_lines (rejections not listed by the previous
catalog); each catalog "rejected" entry carries new: true/false; stderr lists the new lines
first and in full (up to 200), then only a count of previously reported ones; stdout ends in
"[partial: N rejected line(s), M new]".
"""
from __future__ import annotations

import json

try:
    from tests.inference_engine import _support as S
except ImportError:  # run as a script
    import _support as S

EXIT_PARTIAL = 3
GOOD = {"code": "OK", "tags": ["x"], "ts": "2026-09-21T00:00:00Z", "session_id": "s1"}


def line(rec) -> bytes:
    return (json.dumps(rec) + "\n").encode("utf-8")


def located(proc) -> list[str]:
    return [ln.strip().split(": ", 1)[0] for ln in S.err(proc).splitlines()
            if ln.startswith("  artifacts.jsonl:")]


class NewRejections(S.StateTestCase):
    def setUp(self):
        super().setUp()
        self.state.mkdir(parents=True)
        # 25 old rejections: more than any stderr cap used before.
        (self.state / "artifacts.jsonl").write_bytes(
            line(GOOD) + b"".join(b"{bad %d\n" % i for i in range(25)))
        first = self.ok(S.run_engine(self.state, "reconcile"), EXIT_PARTIAL)
        self.assertEqual(S.catalog(self.state)["accounting"]["new_rejected_lines"], 25)
        self.assertEqual(len(located(first)), 25)

    def test_unchanged_log_reports_no_new_rejections(self):
        proc = self.ok(S.run_engine(self.state, "reconcile"), EXIT_PARTIAL)
        cat = S.catalog(self.state)
        self.assertEqual(cat["accounting"]["new_rejected_lines"], 0)
        self.assertEqual(cat["accounting"]["rejected_lines"], 25)
        self.assertEqual([r["new"] for r in cat["rejected"]], [False] * 25)
        self.assertEqual(located(proc), [])
        self.assertTrue(S.out(proc).strip().endswith("[partial: 25 rejected line(s), 0 new]"))

    def test_a_new_rejection_is_listed_first_and_counted(self):
        with (self.state / "artifacts.jsonl").open("ab") as f:
            f.write(line(dict(GOOD, code="OK2")) + b'{"code": 5}\n')
        proc = self.ok(S.run_engine(self.state, "reconcile"), EXIT_PARTIAL)
        cat = S.catalog(self.state)
        self.assertEqual(cat["accounting"]["new_rejected_lines"], 1)
        self.assertEqual(cat["accounting"]["rejected_lines"], 26)
        new = [r for r in cat["rejected"] if r["new"] is True]
        self.assertEqual([(r["file"], r["line"]) for r in new], [("artifacts.jsonl", 28)])
        self.assertEqual(located(proc), ["artifacts.jsonl:28"])
        self.assertTrue(S.out(proc).strip().endswith("[partial: 26 rejected line(s), 1 new]"))
        status = json.loads(S.out(self.ok(S.run_engine(self.state, "status"))))
        self.assertEqual(status["new_rejected_lines"], 1)

    def test_after_recovery_every_rejection_is_new_again(self):
        (self.state / "catalog.json").write_bytes(b"{broken")
        self.ok(S.run_engine(self.state, "reconcile"), EXIT_PARTIAL)
        self.assertEqual(S.catalog(self.state)["accounting"]["new_rejected_lines"], 25)


if __name__ == "__main__":
    S.main()
