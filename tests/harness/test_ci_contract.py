"""Static CI contract for the shell suite (WIX-CI-001). Offline; reads files only.

Fails if .github/workflows/ci.yml regains an executable-bit guard or skip branch around
tests/run-all.sh, stops invoking it explicitly through bash, stops asserting the execution
evidence (the WIXIE_SUITE_SUMMARY line with total > 0), or stops setting the private test root;
or if tests/run-all.sh stops emitting that evidence. Every workflow is checked for exec-bit
dependent ways of starting the suite.

Repo under test: WIXIE_STATIC_REPO if set (used to show the check fails on an older tree),
else this checkout.
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

REPO = Path(os.environ.get("WIXIE_STATIC_REPO") or Path(__file__).resolve().parents[2])
WORKFLOWS = REPO / ".github" / "workflows"


def tests_job(ci: str) -> str:
    """Text of the `tests:` job in ci.yml (up to the next two-space-indented key)."""
    m = re.search(r"^  tests:\n(.*?)(?=^  \S|\Z)", ci, re.M | re.S)
    return m.group(1) if m else ""


class CIContract(unittest.TestCase):
    def setUp(self):
        self.ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        self.job = tests_job(self.ci)

    def test_tests_job_exists(self):
        self.assertTrue(self.job, "ci.yml has no `tests:` job")

    def test_no_exec_bit_guard_or_skip_branch(self):
        for wf in sorted(WORKFLOWS.glob("*.y*ml")):
            text = wf.read_text(encoding="utf-8")
            for n, line in enumerate(text.splitlines(), 1):
                if "run-all" not in line:
                    continue
                self.assertNotRegex(line, r"(\[\s*-x|\btest\s+-x)", f"{wf.name}:{n}: -x guard on run-all.sh")
                self.assertNotRegex(line, r"^\s*if\b", f"{wf.name}:{n}: run-all.sh behind an if")
                self.assertNotRegex(line, r"(^|[\s;&|])\./tests/run-all\.sh",
                                    f"{wf.name}:{n}: exec-bit dependent ./tests/run-all.sh")
                self.assertNotIn("skipping", line.lower(), f"{wf.name}:{n}: skip branch for run-all.sh")
        self.assertNotRegex(self.job, r"\[\s*-x|\btest\s+-x", "tests job has an -x guard")
        self.assertNotRegex(self.job, r"(?i)skipping", "tests job has a skip branch")
        self.assertNotRegex(self.job, r"(?m)^\s*(if|else|fi)\b", "tests job has a conditional around the suite")

    def test_invokes_run_all_via_bash_and_fails_closed(self):
        self.assertRegex(self.job, r"(?m)^\s*bash tests/run-all\.sh\b", "suite not invoked as `bash tests/run-all.sh`")
        self.assertIn("set -euo pipefail", self.job, "suite step must fail on a non-zero exit (set -euo pipefail)")
        self.assertRegex(self.job, r"test -f tests/run-all\.sh \|\|", "suite step must fail when run-all.sh is missing")

    def test_asserts_execution_evidence(self):
        self.assertIn("WIXIE_SUITE_SUMMARY total=", self.job, "CI does not check the WIXIE_SUITE_SUMMARY line")
        self.assertRegex(self.job, r'\[\s*"\$total"\s+-gt\s+0\s*\]', "CI does not require total > 0")
        self.assertRegex(self.job, r'\[\s*"\$failed"\s+-eq\s+0\s*\]', "CI does not require failed == 0")

    def test_sets_private_test_root(self):
        self.assertRegex(self.job, r"WIXIE_TEST_ROOT:\s*\$\{\{\s*runner\.temp\s*\}\}/", "CI does not set WIXIE_TEST_ROOT")

    def test_run_all_emits_evidence(self):
        run_all = (REPO / "tests" / "run-all.sh").read_text(encoding="utf-8")
        self.assertIn('SUMMARY="WIXIE_SUITE_SUMMARY total=$TOTAL passed=$PASS failed=$FAIL"', run_all)
        self.assertRegex(run_all, r"\$TOTAL -eq 0 \]\];?\s*then[\s\S]{0,80}exit 1",
                         "run-all.sh must fail when no test ran")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
