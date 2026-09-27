"""WIX-SEC-REPORT-VERDICT-001 (CE-1): output-test.py's preflight never states DEPLOY by its own rule.

Before the fix, run_preflight labelled the prompt DEPLOY whenever overall >= 9.0 and no axis was
below 6, ignoring the 8 SAT assertions, sigma and the 7.0 axis floor. `output-test.py <folder>
--dry-run` (offline, free) then printed "Prompt quality: ... DEPLOY" and a final "Verdict: DEPLOY"
and wrote preflight.prompt_quality.verdict = "DEPLOY" for canonical-HOLD prompts. DEPLOY must now
come only from deploy_bar.py (the bar convergence.py and report-gen.py use); without it, never.

Real CLI, --dry-run, no API key, no model, no network. Usage: test_output_test_deploy_bar.py [repo]
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else HERE.parents[1]
sys.path.insert(0, str(HERE))
import _ot_harness as H  # noqa: E402

ROOT = H.setup(REPO)

DEPLOY_PROMPT = """<instructions>
You are a senior invoice-extraction specialist for Claude, extract vendor, date, and total from each invoice.
Return as JSON with keys vendor, date, total.
Use null for any field that is absent.
Do not invent values. Never guess a currency.
If the invoice is empty or invalid, return an error object instead.
Verify every total against the line items.
</instructions>
<context>
Invoices arrive as plain text from a scanner. Handle each edge case explicitly and default to null when unsure.
</context>
<example>
Input: ACME Corp, 2026-01-05, Total 120.00
Output: {"vendor": "ACME Corp", "date": "2026-01-05", "total": 120.00}
</example>
<output_format>
One JSON object per invoice.
</output_format>
"""
SAT7_PROMPT = DEPLOY_PROMPT.replace("You are a senior", "As a senior")       # 7/8 SAT, overall 9.6
AXIS6_PROMPT = """<role>
Act as an invoice-extraction specialist. Extract vendor, date, and total from each invoice as your job.
</role>
<rules>
Return JSON with these keys:
- vendor
- date
- total.
Use null for any absent field, such as a missing date.
Do not invent values.
Never guess a currency.
Return an error object if the invoice is empty or invalid.
Verify every total against the line items.
Handle each edge case explicitly and default to null when unsure.
</rules>
<examples>
Input: ACME Corp, 2026-01-05, Total 120
Output: {"vendor": "ACME Corp", "date": "2026-01-05", "total": 120}
</examples>
<output_format>
Output one JSON object per invoice.
Remember that the same rules apply on the OpenAI deployment and you must not add prose.
</output_format>
"""                                                                          # Model Fit 6.0, sigma 1.58, overall 9.2
META = {"target_model": "claude-opus-4-6", "task_domain": "data-extraction", "format": "xml",
        "status": "deploy", "config": {"temperature": 0, "max_tokens": 1024}}
TESTS = [{"name": f"t{i}", "input": "x", "expected_contains": ["vendor"], "tags": ["edge"]} for i in range(3)]


def tree(without=()):
    dest = H.scratch(ROOT, "ot-db-tree-")
    shutil.copytree(REPO / "shared", dest / "shared",
                    ignore=shutil.ignore_patterns("__pycache__", *without))
    return dest


def dry_run(t, text):
    folder = H.scratch(ROOT, "ot-db-p-")
    (folder / "prompt.xml").write_text(text, encoding="utf-8", newline="\n")
    (folder / "metadata.json").write_text(json.dumps(META), encoding="utf-8")
    (folder / "tests.json").write_text(json.dumps(TESTS), encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("ANTHROPIC_API_KEY", None)
    p = subprocess.run([sys.executable, "-B", str(t / "shared" / "scripts" / "output-test.py"), str(folder), "--dry-run"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=300)
    res = json.loads((folder / "output-test-results.json").read_text(encoding="utf-8"))
    return p, res


def canonical(text):
    spec = importlib.util.spec_from_file_location("deploy_bar_ot_test", REPO / "shared" / "scripts" / "deploy_bar.py")
    db = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db)
    return db.evaluate_text(text)


class TestPreflightDeploy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full = tree()

    def _deploy_lines(self, out):
        return [ln for ln in out.splitlines() if re.search(r"\bDEPLOY\b(?! bar)", ln)]  # a verdict, not "DEPLOY bar"

    def test_canonical_hold_is_never_preflight_deploy(self):
        for name, text in (("sat7", SAT7_PROMPT), ("axis6", AXIS6_PROMPT)):
            with self.subTest(case=name):
                c = canonical(text)
                self.assertEqual(c["verdict"], "HOLD")
                self.assertGreaterEqual(c["overall"], 9.0)     # the old rule would have said DEPLOY
                p, res = dry_run(self.full, text)
                self.assertNotIn("Traceback", p.stdout + p.stderr)
                pq = res["preflight"]["prompt_quality"]
                self.assertNotEqual(pq["verdict"], "DEPLOY")
                self.assertEqual(pq["verdict"], "PASS")          # preflight gate unchanged
                self.assertEqual(pq["deploy_bar"]["verdict"], "HOLD")
                self.assertFalse(pq["deploy_bar"]["deploy"])
                self.assertEqual(self._deploy_lines(p.stdout), [])
                self.assertIn("deploy bar: HOLD", p.stdout)
                self.assertEqual(res["final_verdict"], "DRY_RUN")

    def test_canonical_deploy_is_shown(self):
        self.assertEqual(canonical(DEPLOY_PROMPT)["verdict"], "DEPLOY")
        p, res = dry_run(self.full, DEPLOY_PROMPT)
        pq = res["preflight"]["prompt_quality"]
        self.assertEqual((pq["verdict"], pq["deploy_bar"]["verdict"]), ("DEPLOY", "DEPLOY"))
        self.assertRegex(p.stdout, r"Prompt quality:.*DEPLOY")

    def test_missing_canonical_bar_is_never_deploy(self):
        t = tree(without=("deploy_bar.py",))
        p, res = dry_run(t, DEPLOY_PROMPT)
        self.assertNotIn("Traceback", p.stdout + p.stderr)
        pq = res["preflight"]["prompt_quality"]
        self.assertEqual(pq["verdict"], "PASS")
        self.assertEqual(pq["deploy_bar"]["verdict"], "UNVERIFIED")
        self.assertEqual(self._deploy_lines(p.stdout), [])

    def test_needs_work_gate_unchanged(self):
        # (an <output_format> section keeps output-schema from exiting the run before the save)
        p, res = dry_run(self.full, "maybe do something.\n<output_format>\nmaybe json\n</output_format>\n")
        self.assertEqual(res["preflight"]["prompt_quality"]["verdict"], "NEEDS WORK")
        self.assertEqual(self._deploy_lines(p.stdout), [])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
