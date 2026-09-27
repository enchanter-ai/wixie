#!/usr/bin/env python3
"""WIX-SEC-OT-STALE-RESULT-001: a failed current evaluation can never leave a previous
successful result indistinguishable from the current run.

Each output-test.py run has a run_id, atomically publishes an IN_PROGRESS record before any
model call, and ends as exactly one CURRENT COMPLETE or CURRENT ERROR record (with error
provenance). Evaluator JSON is schema-validated before use; malformed evaluator replies end
the run as ERROR with the payload preserved; malformed fixer replies are a failed fix; malformed
provider usage is UNKNOWN (never zero, never a crash). No AttributeError / KeyError / TypeError
escapes. The CLI exits 3 for ERROR, 1 for an honest non-PASS, 0 for PASS.

Offline only: stub / fake SDK clients, no model, no network, no key. Usage:
    python test_output_test_stale_result.py <REPO_ROOT>        (exit 0 = all pass)
"""
import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

REPO = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith("-") \
    else Path(__file__).resolve().parents[2]
if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
    del sys.argv[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ot_harness as H  # noqa: E402

ROOT = H.setup(REPO)
F = H.fence

EVALUATOR_VARIANTS = {
    "top_list": "[1, 2, 3]",
    "top_string": '"PASS"',
    "top_number": "42",
    "top_null": "null",
    "top_true": "true",
    "top_false": "false",
    "criteria_string": F({"criteria": "PASS", "overall": "FAIL"}),
    "criteria_int": F({"criteria": 5, "overall": "FAIL"}),
    "criteria_object": F({"criteria": {"id": 1, "verdict": "FAIL"}, "overall": "FAIL"}),
    "criteria_null": F({"criteria": None, "overall": "FAIL"}),
    "criterion_nonobject": F({"criteria": [1], "overall": "FAIL"}),
    "criterion_list": F({"criteria": [["id", 1]], "overall": "FAIL"}),
    "criterion_missing_id": F({"criteria": [{"verdict": "FAIL", "reason": "r"}], "overall": "FAIL"}),
    "criterion_missing_id_pass": F({"criteria": [{"verdict": "PASS"}], "overall": "FAIL"}),
    "criterion_bool_id": F({"criteria": [{"id": True, "verdict": "FAIL"}], "overall": "FAIL"}),
    "criterion_bad_verdict": F({"criteria": [{"id": 1, "verdict": "DEPLOY"}], "overall": "FAIL"}),
    "criterion_reason_int": F({"criteria": [{"id": 1, "verdict": "FAIL", "reason": 7}], "overall": "FAIL"}),
    "criterion_fix_list": F({"criteria": [{"id": 1, "verdict": "FAIL", "fix": ["x"]}], "overall": "FAIL"}),
    "missing_all_fields": F({}),
    "missing_overall": F({"criteria": []}),
    "missing_criteria": F({"overall": "FAIL"}),
    "overall_deploy": F({"criteria": [], "overall": "DEPLOY"}),
    "overall_lowercase_pass": F({"criteria": [], "overall": "pass"}),
    "overall_list": F({"criteria": [], "overall": ["PASS"]}),
    "overall_pass_with_fail_criterion": F({"criteria": [{"id": 1, "verdict": "FAIL"}], "overall": "PASS"}),
    "top_fix_object": F({"criteria": [], "overall": "FAIL", "top_fix": {"a": 1}}),
    "quality_string": F({"criteria": [], "overall": "FAIL", "output_quality_score": "9"}),
    "quality_out_of_range": F({"criteria": [], "overall": "FAIL", "output_quality_score": 99}),
    "unparseable_text": "I think it passes.",
    "fenced_broken_json": "```json\n{\"criteria\": [\n```",
}

FIXER_VARIANTS = {
    "top_list": "[1]",
    "top_string": '"x"',
    "top_number": "3",
    "top_null": "null",
    "missing_target": F({"replacement": "q", "reason": "r"}),
    "target_int": F({"target": 5, "replacement": "q"}),
    "replacement_null": F({"target": "a", "replacement": None}),
    "reason_int": F({"target": "a", "replacement": "b", "reason": 7}),
    "not_json": "Just change the task line.",
}

COMPLETE_2_0_KEYS = {"engine", "version", "last_run", "prompt_folder", "model", "model_identity",
                     "model_resolution_errors", "fallback_events", "iterations", "final_verdict",
                     "final_score", "total_cost_usd", "known_cost_usd", "cost_unknown_calls",
                     "cost_status", "total_duration_sec", "cost_breakdown", "provider_failures",
                     "preflight", "iterations_detail", "available_engines"}
RUN_KEYS = {"run_id", "run_status", "started_at", "finished_at", "error", "inputs", "output_reference"}


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tree = H.script_tree(REPO, ROOT, minimal=True)
        self.ot = H.load_ot(self.tree)

    def pass_first(self, name):
        """A folder whose last result is a genuine PASS (run 1)."""
        folder = H.make_folder(ROOT, name)
        res, exc, log = H.run_in_process(self.ot, folder, H.StubClient(target=[H.GOOD_OUTPUT]),
                                         max_iterations=1)
        self.assertIsNone(exc, log)
        r1 = H.results(folder)
        self.assertEqual((r1["final_verdict"], r1["run_status"]), ("PASS", "COMPLETE"))
        return folder, r1

    def assert_current(self, r, r1, outcome):
        """The record on disk is this run's, never run 1's PASS."""
        self.assertNotEqual(r["run_id"], r1["run_id"])
        self.assertEqual(r["run_id"], outcome.run_id)
        self.assertNotEqual(r["final_verdict"], "PASS")
        self.assertIsNotNone(r["finished_at"])


class TestMalformedEvaluator(Base):
    def test_every_variant_ends_as_current_error_with_evidence(self):
        for name, reply in EVALUATOR_VARIANTS.items():
            for verbose in (False, True):
                with self.subTest(variant=name, verbose=verbose):
                    folder, r1 = self.pass_first("ev")
                    client = H.StubClient(target=[H.MARGINAL_OUTPUT] * 3, evaluator=[reply] * 3,
                                          fixer=[H.FIX_OK] * 3)
                    outcome, exc, log = H.run_in_process(self.ot, folder, client, max_iterations=3,
                                                         verbose=verbose)
                    self.assertIsNone(exc, f"{exc!r}\n{log}")
                    r = H.results(folder)
                    self.assert_current(r, r1, outcome)
                    self.assertEqual((r["run_status"], r["final_verdict"], r["final_score"]),
                                     ("ERROR", "EVALUATION_ERROR", None))
                    self.assertEqual((outcome.run_status, self.ot.exit_code_for(outcome)), ("ERROR", 3))
                    self.assertEqual(r["error"]["kind"], "malformed_evaluator_reply")
                    self.assertEqual(r["error"]["phase"], "evaluate")
                    self.assertEqual(r["error"]["evidence"], "iterations_detail[0].fix.error")
                    ev = r["iterations_detail"][0]["fix"]["error"]
                    self.assertEqual(ev["raw_sha256"], sha(reply))
                    self.assertEqual(ev["raw_response"], reply)
                    self.assertTrue(ev["errors"])
                    self.assertNotIn("fixer", client.log)          # no fix from a bad evaluation
                    self.assertEqual(client.log, ["target", "evaluator"])   # loop stopped
                    ref = r["output_reference"]                    # links to THIS run's output
                    self.assertEqual((ref["run_id"], ref["sha256"]), (r["run_id"], sha(H.MARGINAL_OUTPUT)))
                    self.assertEqual(ref["sha256"], hashlib.sha256(
                        (folder / "output-reference.md").read_bytes()).hexdigest())

    def test_valid_fail_is_an_honest_complete_result(self):
        folder, r1 = self.pass_first("ev-ok")
        client = H.StubClient(target=[H.MARGINAL_OUTPUT] * 2, evaluator=[H.EVAL_FAIL] * 2,
                              fixer=[H.FIX_OK] * 2)
        outcome, exc, log = H.run_in_process(self.ot, folder, client, max_iterations=2)
        self.assertIsNone(exc, log)
        r = H.results(folder)
        self.assert_current(r, r1, outcome)
        self.assertEqual((r["run_status"], r["final_verdict"], r["error"]), ("COMPLETE", "MARGINAL", None))
        self.assertEqual(self.ot.exit_code_for(outcome), 1)

    def test_injected_evaluator_result_is_validated_too(self):
        errs = self.ot.validate_evaluator_reply
        self.assertEqual(errs({"criteria": [], "overall": "FAIL"}), [])
        self.assertEqual(errs({"criteria": [{"id": "c1", "verdict": "PASS", "reason": "ok", "fix": None}],
                               "overall": "PASS", "output_quality_score": 9.5}), [])
        for bad in ([], "x", 1, None, {"criteria": [{}], "overall": "FAIL"}):
            self.assertTrue(errs(bad), bad)


class TestMalformedFixer(Base):
    def test_fixer_variants_are_failed_fixes_not_crashes(self):
        for name, reply in FIXER_VARIANTS.items():
            with self.subTest(variant=name):
                folder, r1 = self.pass_first("fx")
                client = H.StubClient(target=[H.MARGINAL_OUTPUT] * 2, evaluator=[H.EVAL_FAIL] * 2,
                                      fixer=[reply] * 2)
                outcome, exc, log = H.run_in_process(self.ot, folder, client, max_iterations=2)
                self.assertIsNone(exc, f"{exc!r}\n{log}")
                r = H.results(folder)
                self.assert_current(r, r1, outcome)
                self.assertEqual((r["run_status"], r["final_verdict"]), ("COMPLETE", "MARGINAL"))
                fx = r["iterations_detail"][0]["fix"]
                self.assertTrue(fx["fix_failed"])
                self.assertFalse(fx["applied"])
                self.assertEqual(fx["error"]["kind"], "malformed_fixer_reply")
                self.assertEqual(fx["error"]["raw_sha256"], sha(reply))
                self.assertEqual(self.ot.exit_code_for(outcome), 1)


class TestUsage(Base):
    def test_malformed_usage_is_unknown_not_zero_not_a_crash(self):
        for usage in (("10", 20), (1.5, 2), (True, 3), (-1, 5), ([1], 2), (None, 5)):
            with self.subTest(usage=usage):
                folder, r1 = self.pass_first("use")
                client = H.StubClient(target=[(H.GOOD_OUTPUT, usage)])
                outcome, exc, log = H.run_in_process(self.ot, folder, client, max_iterations=1)
                self.assertIsNone(exc, f"{exc!r}\n{log}")
                r = H.results(folder)
                self.assertNotEqual(r["run_id"], r1["run_id"])
                self.assertEqual(r["run_status"], "COMPLETE")
                call = r["iterations_detail"][0]["calls"][0]
                self.assertIsNone(call["cost_usd"])
                self.assertTrue(call["cost_provenance"].startswith("UNKNOWN"))
                self.assertIsNone(r["total_cost_usd"])
                self.assertNotEqual(call["usage"], {"input_tokens": 0, "output_tokens": 0})
                if usage[0] is not None:
                    self.assertIsNone(call["usage"])
                    self.assertIn("malformed", call["usage_error"])


class TestRunIdentity(Base):
    def test_in_progress_is_published_before_any_model_call(self):
        folder, r1 = self.pass_first("inprog")
        seen = []

        class Peek(H.StubClient):
            def create(self, **kw):
                seen.append(H.results(folder))
                return super().create(**kw)
        outcome, exc, log = H.run_in_process(self.ot, folder, Peek(target=[H.GOOD_OUTPUT]),
                                             max_iterations=1)
        self.assertIsNone(exc, log)
        first = seen[0]
        self.assertEqual((first["run_status"], first["final_verdict"], first["final_score"]),
                         ("IN_PROGRESS", "IN_PROGRESS", None))
        self.assertNotEqual(first["run_id"], r1["run_id"])
        self.assertIsNone(first["finished_at"])
        r = H.results(folder)
        self.assertEqual((r["run_id"], r["run_status"], r["final_verdict"]),
                         (first["run_id"], "COMPLETE", "PASS"))

    def test_internal_exception_is_a_current_error(self):
        folder, r1 = self.pass_first("exc")

        def boom(*a, **k):
            raise KeyError("synthetic")
        self.ot.run_contains_tests = boom
        outcome, exc, log = H.run_in_process(self.ot, folder, H.StubClient(target=[H.GOOD_OUTPUT]),
                                             max_iterations=1)
        self.assertIsNone(exc, log)
        r = H.results(folder)
        self.assert_current(r, r1, outcome)
        self.assertEqual((r["run_status"], r["final_verdict"]), ("ERROR", "EVALUATION_ERROR"))
        self.assertEqual((r["error"]["kind"], r["error"]["exception_type"], r["error"]["phase"]),
                         ("internal_exception", "KeyError", "evaluate"))
        self.assertEqual(r["output_reference"]["sha256"], sha(H.GOOD_OUTPUT))
        self.assertEqual(self.ot.exit_code_for(outcome), 3)

    def test_malformed_inputs_are_a_current_error(self):
        for fname, content in (("tests.json", '["just a string"]'), ("tests.json", '{"a": 1}'),
                               ("metadata.json", "{not json"), ("metadata.json", "[1]")):
            with self.subTest(file=fname, content=content):
                folder, r1 = self.pass_first("inp")
                (folder / fname).write_text(content, encoding="utf-8")
                client = H.StubClient(target=[H.GOOD_OUTPUT])
                outcome, exc, log = H.run_in_process(self.ot, folder, client, max_iterations=1)
                self.assertIsNone(exc, log)
                r = H.results(folder)
                self.assert_current(r, r1, outcome)
                self.assertEqual((r["run_status"], r["error"]["phase"]), ("ERROR", "load"))
                self.assertEqual(client.log, [])

    def test_interrupt_and_missing_key_are_recorded(self):
        folder, r1 = self.pass_first("intr")
        outcome, exc, log = H.run_in_process(self.ot, folder, H.StubClient(target=[KeyboardInterrupt()]),
                                             max_iterations=1)
        self.assertIsInstance(exc, KeyboardInterrupt)
        r = H.results(folder)
        self.assertNotEqual(r["run_id"], r1["run_id"])
        self.assertEqual((r["run_status"], r["error"]["kind"]), ("ERROR", "interrupted"))
        # client=None and no ANTHROPIC_API_KEY: get_client exits; that is recorded, exit 3
        os.environ.pop("ANTHROPIC_API_KEY", None)
        outcome, exc, log = H.run_in_process(self.ot, folder, None, max_iterations=1)
        self.assertIsInstance(exc, SystemExit)
        self.assertEqual(exc.code, 3)
        r2 = H.results(folder)
        self.assertNotEqual(r2["run_id"], r["run_id"])
        self.assertEqual((r2["run_status"], r2["error"]["kind"], r2["error"]["phase"]),
                         ("ERROR", "setup_exit", "client"))

    def test_schema_backwards_readable_and_no_stray_files(self):
        folder, r1 = self.pass_first("schema")
        self.assertTrue(COMPLETE_2_0_KEYS <= set(r1), COMPLETE_2_0_KEYS - set(r1))
        self.assertTrue(RUN_KEYS <= set(r1))
        self.assertEqual(r1["version"], "2.1")
        self.assertEqual(r1["inputs"]["prompt_file"], "prompt.xml")
        self.assertEqual(r1["inputs"]["tests_sha256"],
                         hashlib.sha256((folder / "tests.json").read_bytes()).hexdigest())
        client = H.StubClient(target=[H.MARGINAL_OUTPUT], evaluator=["[1]"])
        H.run_in_process(self.ot, folder, client, max_iterations=2)
        r = H.results(folder)
        self.assertTrue(COMPLETE_2_0_KEYS <= set(r))
        # evidence stays inside the results record; nothing else (no temp files) is left behind
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["metadata.json", "output-reference.md", "output-test-results.json",
                          "prompt.xml", "tests.json"])


class TestCli(Base):
    def test_exit_codes_distinguish_error_from_honest_fail(self):
        folder = H.make_folder(ROOT, "cli")
        code, out, _ = H.run_cli(ROOT, self.tree, folder, {"target": [H.GOOD_OUTPUT]}, ["--max", "1"])
        self.assertEqual(code, 0, out)
        r1 = H.results(folder)
        code, out, roles = H.run_cli(ROOT, self.tree, folder,
                                     {"target": [H.MARGINAL_OUTPUT] * 2,
                                      "evaluator": [F({"criteria": "PASS", "overall": "FAIL"})] * 2},
                                     ["--max", "2"])
        self.assertEqual(code, 3, out)
        self.assertNotIn("Traceback", out)
        r2 = H.results(folder)
        self.assertNotEqual(r2["run_id"], r1["run_id"])
        self.assertEqual((r2["run_status"], r2["final_verdict"]), ("ERROR", "EVALUATION_ERROR"))
        code, out, roles = H.run_cli(ROOT, self.tree, folder,
                                     {"target": [H.MARGINAL_OUTPUT] * 2, "evaluator": [H.EVAL_FAIL],
                                      "fixer": [H.FIX_OK]}, ["--max", "2"])
        self.assertEqual(code, 1, out)
        r3 = H.results(folder)
        self.assertEqual((r3["run_status"], r3["final_verdict"]), ("COMPLETE", "MARGINAL"))

    def test_usage_non_numeric_via_cli(self):
        folder = H.make_folder(ROOT, "cli-use")
        code, out, _ = H.run_cli(ROOT, self.tree, folder,
                                 {"target": [H.GOOD_OUTPUT], "usage": ["many", 3]}, ["--max", "1"])
        self.assertEqual(code, 0, out)
        r = H.results(folder)
        self.assertIsNone(r["iterations_detail"][0]["calls"][0]["usage"])
        self.assertIsNone(r["total_cost_usd"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
