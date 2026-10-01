"""WIX-SEC-REPORT-VERDICT-001: one authoritative DEPLOY verdict across Wixie surfaces.

report-gen.py used to print DEPLOY whenever overall >= 9 and its own audit found no warning,
ignoring the 8 SAT assertions, the sigma floor and the 7.0 axis floor, and its header badge came
from metadata.json's `status`. These tests pin the fix:
  - shared/scripts/deploy_bar.py is the single bar; convergence.py's deploy_verdict routes
    through it and keeps its old behaviour (grid check against the pre-fix formula);
  - the report shows DEPLOY only when the canonical bar says DEPLOY; 7/8 SAT, a failed sigma,
    an axis in [5,7), metadata claiming deploy, or missing evidence never show DEPLOY;
  - the verdict label, header badge, data-verdict attributes, the embedded
    <meta name="wixie-report-verdict"> JSON and the REPORT_VERDICT_JSON stdout line all agree;
  - the vendored copies (convergence-engine, prompt-crafter, prompt-refiner) behave identically.
Offline: no model, no network, no browser (report-gen runs from a copy without html-to-pdf.py,
which is its documented HTML fallback).
"""
from __future__ import annotations

import html
import importlib.util
import itertools
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_root_spec = importlib.util.spec_from_file_location(
    "wixie_test_root", Path(__file__).resolve().parents[1] / "_test_root.py")
_root_mod = importlib.util.module_from_spec(_root_spec)
_root_spec.loader.exec_module(_root_mod)
_root_mod.ensure_test_root()
os.environ["WIXIE_EFFICACY_CLAUDE_BIN"] = os.path.join(os.sep, "nonexistent", "claude")

REPO = Path(__file__).resolve().parents[2]
SHARED = REPO / "shared"
VENDORED = ["convergence-engine", "prompt-crafter", "prompt-refiner"]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Prompt fixtures (scored by the real scorers; preconditions are asserted in the tests).
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
# 7/8 SAT (no role phrase), otherwise the same high scores.
SAT7_PROMPT = DEPLOY_PROMPT.replace("You are a senior", "As a senior")
# Model Fit in [5,7): overall still >= 9, 8/8 SAT.
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
"""
META_KEYS = {"Clarity": "clarity", "Completeness": "completeness", "Efficiency": "efficiency",
             "Model Fit": "model_fit", "Failure Resilience": "failure_resilience"}


def refine_metadata(scores):
    meta = metadata_for(scores, mode="refine")
    meta["scores"] = {"before": {"overall": 8.0}, "after": meta["scores"]}
    return meta


def metadata_for(scores, **over):
    meta = {
        "created": "2026-09-27T00:00:00Z", "task": "Extract invoice fields as JSON",
        "target_model": "claude-opus-4-6", "task_domain": "data-extraction", "format": "xml",
        "techniques": ["Few-Shot", "Structured Output"], "techniques_avoided": ["Chain-of-Thought"],
        "tokens": {"estimated": 143, "context_window": 1000000, "usage_percent": 0.0},
        "scores": {META_KEYS[a]: v for a, v in scores.items() if a in META_KEYS},
        "status": "pass", "version": 1,
        "config": {"temperature": 0, "max_tokens": 1024, "stop_sequences": [], "system_prompt": True},
    }
    meta["scores"]["overall"] = scores["overall"]
    meta.update(over)
    return meta


TESTS_JSON = [{"name": f"t{i}", "input": "x", "expected_contains": [], "tags": ["edge"]} for i in range(3)]


def parse_report(report_html, stdout):
    """Every verdict carrier in one run: visible label, badge, data attributes, meta JSON, stdout."""
    label = re.search(r'class="v-label"[^>]*>([^<]+)<', report_html).group(1)
    badge = re.search(r'<span class="badge [^"]+" data-verdict="([^"]+)">([^<]+)<', report_html)
    attrs = re.findall(r'data-(?:wixie-)?verdict="([^"]+)"', report_html)
    meta = json.loads(html.unescape(
        re.search(r'<meta name="wixie-report-verdict" content="([^"]*)">', report_html).group(1)))
    lines = [ln for ln in stdout.splitlines() if ln.startswith("REPORT_VERDICT_JSON ")]
    assert len(lines) == 1, stdout
    out = json.loads(lines[0][len("REPORT_VERDICT_JSON "):])
    return {"label": label, "badge": badge.group(2), "badge_attr": badge.group(1), "attrs": attrs,
            "meta": meta, "stdout": out}


class ReportRunner:
    """Runs a report-gen.py copy (whole shared/ tree minus html-to-pdf.py) on a prompt folder."""

    def __init__(self, shared_src, work):
        self.shared = Path(work) / "shared"
        shutil.copytree(shared_src, self.shared,
                        ignore=shutil.ignore_patterns("html-to-pdf.py", "__pycache__"))
        self.work = Path(work)

    def run(self, name, prompt_text, meta, prompt_name="prompt.xml"):
        d = self.work / "prompts" / name
        d.mkdir(parents=True)
        if prompt_text is not None:
            (d / prompt_name).write_text(prompt_text, encoding="utf-8", newline="\n")
        (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        (d / "tests.json").write_text(json.dumps(TESTS_JSON), encoding="utf-8")
        p = subprocess.run([sys.executable, str(self.shared / "scripts" / "report-gen.py"), str(d)],
                           capture_output=True, text=True, timeout=120)
        self_check = p.returncode == 1 and "Traceback" not in p.stderr
        assert self_check, (p.returncode, p.stderr)
        return parse_report((d / "report.html").read_text(encoding="utf-8"), p.stdout)


def cases(db):
    """(name, prompt text, metadata, expected verdict) for every criterion."""
    s_ok = db.score(DEPLOY_PROMPT)
    s_7 = db.score(SAT7_PROMPT)
    s_ax = db.score(AXIS6_PROMPT)
    return [
        ("deploy", DEPLOY_PROMPT, metadata_for(s_ok), "DEPLOY"),
        ("sat7", SAT7_PROMPT, metadata_for(s_7), "HOLD"),
        ("axis6", AXIS6_PROMPT, metadata_for(s_ax), "HOLD"),
        ("axis6_needs_improvement", AXIS6_PROMPT, metadata_for(s_ax, status="needs_improvement"), "HOLD"),
        ("axis6_refine", AXIS6_PROMPT, refine_metadata(s_ax), "HOLD"),
        # metadata claims DEPLOY with perfect scores: canonical HOLD still wins
        ("meta_claims_deploy", SAT7_PROMPT,
         metadata_for({**{a: 10.0 for a in META_KEYS}, "overall": 10.0}, status="deploy"), "HOLD"),
        # no prompt file at all: no evidence
        ("no_prompt", None, metadata_for(s_ok, status="deploy"), "UNVERIFIED"),
        # empty prompt file
        ("empty_prompt", "", metadata_for(s_ok, status="deploy"), "UNVERIFIED"),
    ]


class TestDeployBar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = _load("deploy_bar_under_test", SHARED / "scripts" / "deploy_bar.py")

    def test_fixture_preconditions(self):
        db = self.db
        ok, s7, ax = (db.evaluate_text(t) for t in (DEPLOY_PROMPT, SAT7_PROMPT, AXIS6_PROMPT))
        self.assertEqual(ok["verdict"], "DEPLOY", ok)
        self.assertEqual((s7["assertions_passed"], s7["verdict"]), (7, "HOLD"))
        self.assertGreaterEqual(s7["overall"], 9.0)
        self.assertTrue(s7["sigma_pass"])
        self.assertTrue(all(v >= 7.0 for v in s7["axes"].values()))
        self.assertEqual(ax["assertions_passed"], 8)
        self.assertGreaterEqual(ax["overall"], 9.0)
        self.assertTrue(any(5.0 <= v < 7.0 for v in ax["axes"].values()), ax["axes"])

    def _scores(self, vals):
        s = dict(zip(self.db.AXES, vals))
        s["overall"] = round(sum(vals) / 5, 1)
        return s

    def test_bar_rules(self):
        db = self.db
        ok8 = [(n, True, n) for n in db.ASSERTION_NAMES]
        seven = [(n, n != "has_role", n) for n in db.ASSERTION_NAMES]
        self.assertEqual(db.evaluate(self._scores([9.4] * 5), ok8, 0.45)["verdict"], "DEPLOY")
        # 7/8 SAT with overall > 9
        self.assertEqual(db.evaluate(self._scores([9.8] * 5), seven, 0.45)["verdict"], "HOLD")
        # sigma above the floor, every axis >= 7, overall >= 9, 8/8
        r = db.evaluate(self._scores([10, 10, 10, 10, 7.0]), ok8, 0.45)
        self.assertEqual((r["verdict"], r["sigma_pass"]), ("HOLD", False))
        # an axis in [5,7)
        self.assertEqual(db.evaluate(self._scores([10, 10, 10, 10, 6.5]), ok8, 5.0)["verdict"], "HOLD")
        # missing evidence
        for scores, asserts, floor in [(self._scores([9.5] * 5), [], 0.45),
                                       (self._scores([9.5] * 5), ok8[:7], 0.45),
                                       (self._scores([9.5] * 5), ok8, None),
                                       ({"overall": 9.5}, ok8, 0.45),
                                       ({**self._scores([9.5] * 5), "Clarity": "9.5"}, ok8, 0.45),
                                       ({**self._scores([9.5] * 5), "overall": True}, ok8, 0.45),
                                       (None, None, None)]:
            r = db.evaluate(scores, asserts, floor)
            self.assertEqual((r["verdict"], r["deploy"]), ("UNVERIFIED", False), r)
        self.assertEqual(db.evaluate_text("")["verdict"], "UNVERIFIED")

    def test_convergence_routes_through_the_shared_bar_unchanged(self):
        conv = _load("convergence_under_test", SHARED / "scripts" / "convergence.py")
        self.assertEqual(Path(conv.DB.__file__).resolve(), (SHARED / "scripts" / "deploy_bar.py").resolve())
        self.assertIs(conv.run_assertions, conv.DB.run_assertions)
        self.assertIs(conv.score_prompt, conv.DB.score)

        def old_verdict(scores, assertions, floor):  # the pre-fix convergence formula
            sigma = statistics.pstdev([scores[a] for a in conv.AXES])
            gate = scores["overall"] >= 9.0 and all(scores[a] >= 7.0 for a in conv.AXES)
            return gate and sigma <= floor and all(a[1] for a in assertions), sigma

        names = self.db.ASSERTION_NAMES
        texts = {"short": "word " * 10, "mid": "word " * 1500, "long": "word " * 2500}
        for vals in itertools.product([6.9, 7.0, 8.6, 9.5, 10.0], repeat=3):
            scores = self._scores([vals[0], vals[1], vals[2], 10.0, 9.6])
            for fail in (None, "has_role"):
                asserts = [(n, n != fail, n) for n in names]
                for text in texts.values():
                    deploy, sigma, floor = conv.deploy_verdict(scores, asserts, text)
                    self.assertEqual((deploy, sigma), old_verdict(scores, asserts, floor))
                    self.assertEqual(floor, conv._eval.dynamic_sigma_floor(text))

    def test_convergence_and_report_agree_on_fixtures(self):
        conv = _load("convergence_agree", SHARED / "scripts" / "convergence.py")
        for text in (DEPLOY_PROMPT, SAT7_PROMPT, AXIS6_PROMPT):
            deploy, sigma, floor = conv.deploy_verdict(conv.score_prompt(text), conv.run_assertions(text), text)
            r = self.db.evaluate_text(text)
            self.assertEqual((r["deploy"], r["sigma"], r["sigma_floor"]), (deploy, sigma, floor))


class TestReportVerdict(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = _load("deploy_bar_cases", SHARED / "scripts" / "deploy_bar.py")
        cls.cases = cases(cls.db)
        cls.tmp = tempfile.mkdtemp(prefix="report-verdict-")
        cls.results = {}
        for label, shared in [("source", SHARED)] + [
                (p, REPO / "plugins" / p / "vendor" / "wixie" / "shared") for p in VENDORED]:
            runner = ReportRunner(shared, os.path.join(cls.tmp, label))
            cls.results[label] = {name: runner.run(name, text, meta) for name, text, meta, _ in cls.cases}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _check(self, r, expected, where):
        self.assertEqual(r["label"], expected, where)
        self.assertEqual(r["badge"], expected, where)
        self.assertEqual(r["badge_attr"], expected, where)
        self.assertEqual(set(r["attrs"]), {expected}, where)
        self.assertEqual(r["meta"], r["stdout"], where)
        self.assertEqual(r["stdout"]["verdict"], expected, where)
        self.assertEqual(r["stdout"]["deploy"], expected == "DEPLOY", where)
        if expected != "DEPLOY":
            self.assertNotEqual(r["stdout"]["canonical"].get("deploy"), True, where)

    def test_verdicts_and_machine_status_agree(self):
        for name, _, _, expected in self.cases:
            with self.subTest(case=name):
                self._check(self.results["source"][name], expected, name)

    def test_hold_reasons_are_the_canonical_ones(self):
        res = self.results["source"]
        self.assertIn("SAT 7/8", " ".join(res["sat7"]["stdout"]["canonical"]["failed"]))
        self.assertTrue(any("< 7.0" in f for f in res["axis6"]["stdout"]["canonical"]["failed"]))
        self.assertIn("SAT 7/8", " ".join(res["meta_claims_deploy"]["stdout"]["canonical"]["failed"]))

    def test_vendored_copies_behave_identically(self):
        for p in VENDORED:
            vend = REPO / "plugins" / p / "vendor" / "wixie" / "shared" / "scripts"
            for f in ("deploy_bar.py", "report-gen.py", "convergence.py"):
                self.assertEqual((vend / f).read_bytes(), (SHARED / "scripts" / f).read_bytes(), f"{p}/{f}")
            for name, _, _, expected in self.cases:
                with self.subTest(plugin=p, case=name):
                    self._check(self.results[p][name], expected, f"{p}/{name}")
                    self.assertEqual(self.results[p][name]["stdout"], self.results["source"][name]["stdout"])

    def test_sigma_failure_alone_is_not_deploy(self):
        """A sigma-only failure (8/8 SAT, every axis >= 7, overall >= 9) through the report path."""
        rg = _load("report_gen_sigma", SHARED / "scripts" / "report-gen.py")
        db = sys.modules["deploy_bar"] = _load("deploy_bar", SHARED / "scripts" / "deploy_bar.py")
        fixed = dict(zip(db.AXES, [10.0, 10.0, 10.0, 10.0, 7.0]))
        fixed["overall"] = 9.4
        real = db.score
        db.score = lambda text: dict(fixed)
        try:
            d = Path(self.tmp) / "sigma"
            d.mkdir()
            (d / "prompt.xml").write_text(DEPLOY_PROMPT, encoding="utf-8")
            (d / "tests.json").write_text(json.dumps(TESTS_JSON), encoding="utf-8")
            page, payload = rg.build_report(metadata_for(fixed, status="deploy"), str(d))
        finally:
            db.score = real
            sys.modules.pop("deploy_bar", None)
        c = payload["canonical"]
        self.assertEqual((c["assertions_passed"], c["sigma_pass"], c["overall"]), (8, False, 9.4))
        self.assertEqual(payload["verdict"], "HOLD")
        self.assertIn('class="badge b-no" data-verdict="HOLD">HOLD<', page)

    def test_missing_canonical_helper_is_unverified(self):
        """report-gen.py copied alone (no deploy_bar.py): never DEPLOY, no crash."""
        d = Path(self.tmp) / "alone"
        (d / "bin").mkdir(parents=True)
        shutil.copy(SHARED / "scripts" / "report-gen.py", d / "bin" / "report-gen.py")
        (d / "p").mkdir()
        (d / "p" / "prompt.xml").write_text(DEPLOY_PROMPT, encoding="utf-8")
        (d / "p" / "metadata.json").write_text(json.dumps(metadata_for(self.db.score(DEPLOY_PROMPT), status="deploy")),
                                               encoding="utf-8")
        p = subprocess.run([sys.executable, str(d / "bin" / "report-gen.py"), str(d / "p")],
                           capture_output=True, text=True, timeout=120)
        self.assertNotIn("Traceback", p.stderr)
        self._check(parse_report((d / "p" / "report.html").read_text(encoding="utf-8"), p.stdout),
                    "UNVERIFIED", "alone")


if __name__ == "__main__":
    unittest.main()
