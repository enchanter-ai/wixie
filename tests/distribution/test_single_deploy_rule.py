"""WIX-SEC-REPORT-VERDICT-001: exactly one authoritative DEPLOY rule in the product.

Static and offline. shared/scripts/deploy_bar.py is the only script that may DECIDE a DEPLOY
verdict. Every other product Python file (git-tracked, outside tests/ and vendor/ copies) that
produces a "DEPLOY..." string literal must
  - load deploy_bar.py (reference the file name), and
  - never guard that literal with a numeric threshold comparison (<, <=, >, >= against a number):
    it may only present a verdict the canonical bar already computed (e.g. `"DEPLOY" if deploy`),
    and may only downgrade on non-threshold conditions.
The pre-fix rules this catches: report-gen `if overall >= 9 and ...: return "DEPLOY"` and
output-test `"DEPLOY" if overall >= 9.0 and not low_axes`.

Agent/skill instructions that ask for a written DEPLOY verdict must point at the canonical bar
(the translate adapter's score-delta.json verdict is deploy_bar.py's output, copied).
"""
from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CANONICAL = "shared/scripts/deploy_bar.py"
ORDERING = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def product_python_files():
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "*.py"], capture_output=True, text=True, check=True)
    for rel in out.stdout.split():
        if rel.startswith("tests/") or "/vendor/" in rel:
            continue
        yield rel


def _numeric_const(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def threshold_compares(test):
    """Ordering comparisons against a numeric literal inside a condition."""
    found = []
    for n in ast.walk(test):
        if isinstance(n, ast.Compare):
            operands = [n.left] + list(n.comparators)
            if any(isinstance(op, ORDERING) for op in n.ops) and any(_numeric_const(o) for o in operands):
                found.append(ast.unparse(n))
    return found


def deploy_producers(tree):
    """(line, [threshold compares guarding it]) for every produced "DEPLOY..." literal. A literal
    that is itself an operand of a comparison (`x == "DEPLOY"`) is a consumer, not a producer."""
    parents = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p):
            parents[c] = p
    out = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("DEPLOY")):
            continue
        if isinstance(parents.get(n), ast.Compare):
            continue
        guards, child, cur = [], n, parents.get(n)
        while cur is not None:
            if isinstance(cur, (ast.If, ast.IfExp, ast.While)) and child is not cur.test:
                guards += threshold_compares(cur.test)
            if isinstance(cur, ast.BoolOp):       # `a >= 9 and "DEPLOY"` style
                for v in cur.values:
                    if v is not child:
                        guards += threshold_compares(v)
            child, cur = cur, parents.get(cur)
        out.append((n.lineno, guards))
    return out


class TestSingleDeployRule(unittest.TestCase):
    def test_no_script_other_than_deploy_bar_decides_deploy(self):
        seen = 0
        for rel in product_python_files():
            src = (REPO / rel).read_text(encoding="utf-8")
            producers = deploy_producers(ast.parse(src))
            if rel == CANONICAL or not producers:
                continue
            seen += 1
            with self.subTest(file=rel):
                self.assertIn("deploy_bar.py", src, "states DEPLOY without loading the canonical bar")
                for line, guards in producers:
                    self.assertEqual(guards, [], f"{rel}:{line} DEPLOY guarded by its own threshold")
        self.assertGreaterEqual(seen, 3)   # convergence.py, report-gen.py, output-test.py present it

    def test_detector_catches_the_pre_fix_rules(self):
        for bad in ('def v(overall, w):\n    if overall >= 9 and w == 0:\n        return "DEPLOY"\n',
                    'v = "DEPLOY" if overall >= 9.0 and not low else "PASS"\n',
                    'v = overall > 8.9 and "DEPLOY (heuristic)"\n'):
            self.assertTrue(any(g for _, g in deploy_producers(ast.parse(bad))), bad)
        ok = 'v = "DEPLOY" if canon["verdict"] == "DEPLOY" and n == 0 else "HOLD"\n'
        self.assertFalse(any(g for _, g in deploy_producers(ast.parse(ok))))

    def test_canonical_bar_holds_the_thresholds(self):
        src = (REPO / CANONICAL).read_text(encoding="utf-8")
        self.assertIn("OVERALL_MIN = 9.0", src)
        self.assertIn("AXIS_MIN = 7.0", src)

    def test_translate_verdict_is_the_canonical_bar(self):
        adapter = (REPO / "plugins/prompt-translate/agents/adapter.md").read_text(encoding="utf-8")
        skill = (REPO / "plugins/prompt-translate/skills/translate/SKILL.md").read_text(encoding="utf-8")
        ref = "${CLAUDE_PLUGIN_ROOT}/vendor/wixie/shared/scripts/deploy_bar.py"
        self.assertIn(ref, adapter)
        self.assertIn(ref, skill)
        self.assertNotIn('"verdict": "DEPLOY | HOLD | FAIL"', adapter)
        self.assertTrue((REPO / "plugins/prompt-translate/vendor/wixie/shared/scripts/deploy_bar.py").is_file())


if __name__ == "__main__":
    unittest.main()
