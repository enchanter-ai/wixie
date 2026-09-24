#!/usr/bin/env python3
"""WIX-RUN-003: a non-empty input record never disappears silently.

Acceptance criterion (findings.json): every non-empty artifact line is either represented in
the catalog or reported as a rejected record with source location, and callers can
distinguish clean success from partial reconciliation.

Documented contract under test:
  reconcile: exit 0 + outcome "clean" when every line was counted; exit 3 + outcome "partial"
             when any line was rejected. catalog.json lists every rejected line (file, line,
             reason) and accounting satisfies nonempty_lines == events + duplicate_lines +
             rejected_lines.
  backfill:  imports the usable lines, lists each rejected source line as "  <file>:<line>: ..."
             on stderr, exits 3.
  emit:      an unusable record is refused with exit 2 and nothing is written.
  append:    a torn final line gets a newline before the next record, so it cannot swallow it.
"""
from __future__ import annotations

import json

try:
    from tests.inference_engine import _support as S
except ImportError:  # run as a script
    import _support as S

EXIT_USAGE = 2
EXIT_PARTIAL = 3

GOOD = {"code": "OK", "tags": ["x"], "ts": "2026-09-21T00:00:00Z", "session_id": "s1"}


def line(rec) -> bytes:
    return (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")


class MalformedLog(S.StateTestCase):
    def _log(self, data: bytes):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "artifacts.jsonl").write_bytes(data)

    def _reconcile(self, expected: int):
        proc = S.run_engine(self.state, "reconcile")
        self.ok(proc, expected)
        return S.catalog(self.state)

    def _assert_accounting(self, cat, events, rejected_lines, duplicates=0):
        acc = cat["accounting"]
        self.assertEqual(acc["events"], events)
        self.assertEqual(acc["rejected_lines"], rejected_lines)
        self.assertEqual(acc["duplicate_lines"], duplicates)
        self.assertEqual(acc["nonempty_lines"], events + rejected_lines + duplicates)
        self.assertEqual(cat["total_artifacts"], events)
        self.assertEqual(cat["outcome"], "partial" if rejected_lines else "clean")
        self.assertEqual(len(cat["rejected"]), rejected_lines)

    def test_clean_log_is_clean(self):
        self._log(line(GOOD) + line(dict(GOOD, code="OK2")))
        cat = self._reconcile(0)
        self._assert_accounting(cat, events=2, rejected_lines=0)

    def test_malformed_line_is_reported_with_location(self):
        self._log(line(GOOD) + b"{malformed-json}\n")
        cat = self._reconcile(EXIT_PARTIAL)
        self._assert_accounting(cat, events=1, rejected_lines=1)
        self.assertEqual((cat["rejected"][0]["file"], cat["rejected"][0]["line"]),
                         ("artifacts.jsonl", 2))
        status = S.run_engine(self.state, "status")
        self.ok(status)
        info = json.loads(S.out(status))
        self.assertEqual(info["last_outcome"], "partial")
        self.assertEqual(info["rejected_lines"], 1)

    def test_truncated_and_non_object_lines(self):
        full = json.dumps(dict(GOOD, code="T"))
        self._log(line(GOOD) + full[:20].encode() + b"\n" + b"[1, 2]\n42\n\"s\"\nnull\n"
                  + line(dict(GOOD, code="OK3")))
        cat = self._reconcile(EXIT_PARTIAL)
        self._assert_accounting(cat, events=2, rejected_lines=5)
        self.assertEqual([r["line"] for r in cat["rejected"]], [2, 3, 4, 5, 6])

    def test_wrongly_typed_fields_are_rejected_not_fatal(self):
        bad = [
            dict(GOOD, tags=5),
            dict(GOOD, ts=5),
            dict(GOOD, code=5),
            dict(GOOD, session_id=["a"]),
            dict(GOOD, tags=[1, 2]),
            dict(GOOD, evidence="many"),
            dict(GOOD, title=None),
            dict(GOOD, evidence={"iterations": 10 ** 400}),
        ]
        self._log(line(GOOD) + b"".join(line(b) for b in bad) + line(dict(GOOD, code="LAST")))
        cat = self._reconcile(EXIT_PARTIAL)
        self._assert_accounting(cat, events=2, rejected_lines=len(bad))
        self.assertEqual([r["line"] for r in cat["rejected"]], list(range(2, 2 + len(bad))))
        self.assertEqual(sorted(p["code"] for p in cat["patterns"].values()), ["LAST", "OK"])

    def test_deeply_nested_line_is_rejected(self):
        self._log(line(GOOD) + b"[" * 200000 + b"\n")
        cat = self._reconcile(EXIT_PARTIAL)
        self._assert_accounting(cat, events=1, rejected_lines=1)

    def test_invalid_utf8_line_does_not_hide_its_neighbours(self):
        self._log(line(GOOD) + b'{"code": "\xff\xfe"}\n' + line(dict(GOOD, code="AFTER")))
        cat = self._reconcile(EXIT_PARTIAL)
        self._assert_accounting(cat, events=2, rejected_lines=1)
        self.assertEqual(cat["rejected"][0]["line"], 2)

    def test_write_torn_inside_a_multibyte_character(self):
        # The real log contains em-dashes. A write torn after the first byte of one leaves an
        # undecodable, newline-less tail; the next emit must still land intact on its own line.
        torn = line(dict(GOOD, code="TORN", title="a — b"))
        cut = torn.index("—".encode("utf-8")) + 1
        self._log(line(GOOD) + torn[:cut])
        rec = S.write_json(self.tmp / "r.json", {"code": "NEXT", "tags": ["x"]})
        self.ok(S.run_engine(self.state, "emit", str(rec), CLAUDE_CODE_SESSION_ID="s9"))
        cat = self._reconcile(EXIT_PARTIAL)
        self._assert_accounting(cat, events=2, rejected_lines=1)
        self.assertEqual(cat["rejected"][0]["line"], 2)
        self.assertEqual(sorted(p["code"] for p in cat["patterns"].values()), ["NEXT", "OK"])

    def test_torn_last_line_does_not_swallow_the_next_append(self):
        self._log(line(GOOD) + b'{"code": "HALF", "ta')
        seed = S.write_jsonl(self.tmp / "p.jsonl", [dict(GOOD, code="B1"), dict(GOOD, code="B2")])
        self.ok(S.run_engine(self.state, "backfill", str(seed)))
        cat = self._reconcile(EXIT_PARTIAL)
        self._assert_accounting(cat, events=3, rejected_lines=1)
        self.assertEqual(sorted(p["code"] for p in cat["patterns"].values()), ["B1", "B2", "OK"])

    def test_torn_final_line_is_reported_as_torn(self):
        self._log(line(GOOD) + b'{"code": "HALF"')
        cat = self._reconcile(EXIT_PARTIAL)
        self.assertTrue(cat["rejected"][0]["reason"].startswith("incomplete final line"))

    def test_whitespace_only_log_is_the_documented_noop(self):
        self._log(b"\n   \n\n")
        self.ok(S.run_engine(self.state, "reconcile"))
        self.assertFalse((self.state / "catalog.json").exists())


class MalformedInput(S.StateTestCase):
    def test_backfill_reports_rejected_source_lines(self):
        src = self.tmp / "src.jsonl"
        src.write_bytes(line(GOOD) + b"{bad\n" + line(dict(GOOD, tags=5)) + b"\xff\xfe\n"
                        + line(dict(GOOD, code="OK2")) + b"[" * 200000 + b"\n")
        proc = S.run_engine(self.state, "backfill", str(src))
        self.ok(proc, EXIT_PARTIAL)
        located = [ln.strip().split(": ", 1)[0] for ln in S.err(proc).splitlines()
                   if ln.startswith("  src.jsonl:")]
        self.assertEqual(located, ["src.jsonl:2", "src.jsonl:3", "src.jsonl:4", "src.jsonl:6"])
        self.assertEqual(len(S.log_lines(self.state)), 2)
        self.ok(S.run_engine(self.state, "reconcile"))

    def test_emit_refuses_unusable_records(self):
        cases = {
            "badjson.json": b"{not json",
            "list.json": b"[1, 2]",
            "tags.json": json.dumps({"code": "X", "tags": 5}).encode(),
            "ts.json": json.dumps({"code": "X", "ts": 5}).encode(),
            "utf8.json": b'{"code": "\xff"}',
        }
        for name, data in cases.items():
            path = self.tmp / name
            path.write_bytes(data)
            proc = S.run_engine(self.state, "emit", str(path))
            self.ok(proc, EXIT_USAGE)
            proc = S.run_engine(self.state, "emit", "-", stdin=data)
            self.ok(proc, EXIT_USAGE)
        self.assertEqual(S.log_lines(self.state), [])

    def test_emit_reads_utf8_stdin(self):
        rec = {"code": "U1", "tags": ["x"], "title": "em — dash"}
        proc = S.run_engine(self.state, "emit", "-", stdin=json.dumps(rec, ensure_ascii=False).encode("utf-8"))
        self.ok(proc)
        stored = json.loads(S.log_lines(self.state)[0])
        self.assertEqual(stored["title"], "em — dash")


if __name__ == "__main__":
    S.main()
