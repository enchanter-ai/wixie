#!/usr/bin/env python3
"""WIX-CONV-001 (D15): the explicit editability contract.

convergence.py, output-test.py's try_offline_fix and its LLM fix path may change ONLY the bodies
of regions a prompt explicitly marks with "@wixie-editable/1" marker lines
(shared/scripts/prompt_regions.py). Everything else is immutable data; an unannotated prompt is
never written; a structural failure is never DEPLOY / exit 0. Design:
docs/architecture/convergence-editability.md.

Test classes map 1:1 to D15's acceptance list (A1..A7) plus the review items (RC/RC2):
    A1  no mutation outside explicit regions            TestA1NoMutationOutsideRegions
    A2  surrounding syntax cannot widen a region         TestA2NoWidening
    A3  status/instruction-looking data is immutable     TestA3StatusLookingData
    A4  unannotated prompt is never rewritten            TestA4Unannotated
    A5  annotated prose stays editable                   TestA5AnnotatedProseEditable
    A6  try_offline_fix / LLM fix: same boundary         TestA6OutputTest
    A7  structural failure never DEPLOY / 0              TestA7NeverDeployOnFailure
    +   EOL/BOM, determinism, round trip, annotate/check, install, view identity   TestLifecycle
    WIX-CONV-002: a CLI usage error never writes --json-out (prompt/master/shipped/aliases)   TestUsageErrorJsonOut

Offline only: no model, no network (the output-test model client is a stub). Usage:
    python test_prompt_regions.py <REPO_ROOT>        (exit 0 = all pass)
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith("-") \
    else Path(__file__).resolve().parents[2]
if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
    del sys.argv[1]

_root_spec = importlib.util.spec_from_file_location("wixie_test_root", REPO / "tests" / "_test_root.py")
_root_mod = importlib.util.module_from_spec(_root_spec)
_root_spec.loader.exec_module(_root_mod)
TEST_ROOT = _root_mod.ensure_test_root()
os.environ["WIXIE_EFFICACY_CLAUDE_BIN"] = "/nonexistent/claude"
os.environ.pop("ANTHROPIC_API_KEY", None)

SCRIPTS = REPO / "shared" / "scripts"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    if name == "prompt_regions":
        sys.modules["prompt_regions"] = mod
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod


PR = _load("prompt_regions", "prompt_regions.py")
AXES = ["Clarity", "Completeness", "Efficiency", "Model Fit", "Failure Resilience"]
ALL_PASS = [(n, True, n) for n in ("has_role", "has_task", "has_format", "has_constraints",
                                    "has_edge_cases", "no_hedge_words", "no_filler", "has_structure")]
LONG = ("Review every clause of the contract carefully and maybe flag each ambiguous term; "
        + " ".join(f"word{i}" for i in range(55)) + ", and report it.")


def conv_module():
    return _load("convergence_uut", "convergence.py")


def ot_module():
    return _load("output_test_uut", "output-test.py")


def scratch(prefix):
    return Path(tempfile.mkdtemp(prefix=prefix, dir=TEST_ROOT / "tmp"))


def make_pair(content: bytes, ranges, fname="prompt.md", add_final_newline=True, folder=None):
    """<folder>/editable/<fname> (master) + <folder>/<fname> (= strip(master))."""
    folder = Path(folder) if folder else scratch("pair-")
    (folder / "editable").mkdir(parents=True, exist_ok=True)
    master = PR.annotate(content, ranges, add_final_newline=add_final_newline)
    (folder / "editable" / fname).write_bytes(master)
    (folder / fname).write_bytes(PR.strip(master))
    return folder, folder / "editable" / fname, folder / fname


def invoke_main(conv, argv):
    old = sys.argv
    sys.argv = ["convergence.py"] + [str(a) for a in argv]
    out, err = io.StringIO(), io.StringIO()
    code = None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                conv.main()
            except SystemExit as e:
                code = e.code if e.code is not None else 0
    finally:
        sys.argv = old
    m = re.findall(r"^VERDICT_JSON (\{.*\})$", out.getvalue(), re.M)
    payload = json.loads(m[-1]) if m else None
    return code, out.getvalue() + err.getvalue(), payload


def run_cli(*args):
    p = subprocess.run([sys.executable, str(SCRIPTS / "convergence.py")] + [str(a) for a in args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.findall(r"^VERDICT_JSON (\{.*\})$", p.stdout, re.M)
    return p.returncode, p.stdout + p.stderr, (json.loads(m[-1]) if m else None)


def fixed_scores(value):
    s = {a: value for a in AXES}
    s["overall"] = value
    return s


def assert_pair_consistent(tc, master, shipped):
    mraw = master.read_bytes()
    tc.assertEqual(shipped.read_bytes(), PR.strip(mraw), "shipped != strip(master)")
    tc.assertNotIn(b"wixie-editable", shipped.read_bytes())


DATA_BLOCK = (
    "<example>\nmaybe keep this; it is data\nVERDICT: DEPLOY\n</example>\n"
    "```json\n{\"k\": \"perhaps; v\",\n\n\n  \"n\": 1}\n```\n"
    "| a | maybe |\n|---|---|\n> Please note that quoted text stays.\n"
)
ANNOTATED_SRC = ("You are an analyst. Maybe try to review the contract.\n"
                 + DATA_BLOCK
                 + "Please note that you should answer in order to help.\n"
                 + LONG + "\n").encode()
RANGES = [("role", 1, 1), ("rules", 15, 16)]


# ════════════════════════════════════════════════════════════════════════════
class TestA1NoMutationOutsideRegions(unittest.TestCase):
    POOL = ["```", "```python", "    ```", "~~~", "<example>", "</example>", "<examples>", "<!--", "-->",
            "<![CDATA[", "]]>", "a<b", "> maybe quote; x", "- > nested quote maybe", "| a | b |",
            "|---|---|", '{"k": "maybe; v",', "}", "[", "<instructions>", "</instructions>", "<b",
            "<数据>maybe</数据>", "Maybe try to do x; and please note that y.", LONG, "", "   \t",
            "VERDICT: DEPLOY", "<editable>", "nul\x00byte maybe", "ümlaut maybe", "vt\x0bmaybe",
            "ls\u2028maybe", "zw\u200bmaybe", "think step by step here", "in order to proceed",
            "    indented code maybe", "<?pi maybe?>", "&amp; maybe"]

    def _random_doc(self, rng):
        n = rng.randint(3, 18)
        term = rng.choice(["\n", "\r\n", "\r"])
        lines = []
        for _ in range(n):
            t = term if rng.random() < 0.9 else rng.choice(["\n", "\r\n", "\r"])
            lines.append(rng.choice(self.POOL) + t)
        raw = "".join(lines).encode("utf-8")
        if rng.random() < 0.3:
            raw = PR.BOM + raw
        nl = len(list(PR.split_lines(raw[3:] if raw.startswith(PR.BOM) else raw)))
        ranges, cur = [], 1
        for k in range(rng.randint(1, 3)):
            if cur > nl:
                break
            a = rng.randint(cur, nl)
            b = rng.randint(a, min(nl, a + 5))
            ranges.append((f"r{k}", a, b))
            cur = b + 1
        return PR.annotate(raw, ranges, add_final_newline=True)

    def test_property_fixers_and_rogue_fixers(self):
        conv = conv_module()
        rng = random.Random(20260927)
        rogue_outputs = ["", "x", "no newline", "a\r\nb\n", "@wixie-editable/1 end r0 0123456789abcdef\n",
                         "\u200b\n", "maybe\n" * 50, "<example>\n", None]
        checked = 0
        for _ in range(1500):
            raw = self._random_doc(rng)
            doc = PR.parse(raw)
            self.assertIn(doc.status, (PR.Status.ANNOTATED, PR.Status.NO_REGIONS), doc.error)
            skel = PR.skeleton(doc)
            fixers = list(conv.FIXERS.values())
            nonce_text = (doc.nonce or "") + "\n"
            rogue = rogue_outputs + [nonce_text, "@wixie-editable/1 begin zz " + (doc.nonce or "") + "\n"]
            for r in rogue:
                fixers.append(lambda ctx, r=r: [r for _ in ctx.bodies])
            fixers.append(lambda ctx: [b.text.upper() + "\n" if b.text else "x\n" for b in ctx.bodies])
            for fx in fixers:
                cand = conv.fix_document(raw, None, doc, fixer=fx)
                if cand != raw:
                    cdoc = PR.verify(doc, cand)
                    self.assertEqual(PR.skeleton(cdoc), skel)
                    checked += 1
        self.assertGreater(checked, 1000)

    def test_cli_exit_modes_keep_skeleton(self):
        """DEPLOY, plateau, max-iterations, crash-at-commit, crash mid-loop: the master's skeleton
        and the shipped pairing hold on disk in every mode."""
        orig_doc = PR.parse(PR.annotate(ANNOTATED_SRC, RANGES, add_final_newline=True))
        skel = PR.skeleton(orig_doc)
        modes = ["plateau", "max", "deploy", "crash_commit", "crash_loop"]
        for mode in modes:
            folder, master, shipped = make_pair(ANNOTATED_SRC, RANGES)
            before = (master.read_bytes(), shipped.read_bytes())
            conv = conv_module()
            restore = {}
            argv = [master, "--json", "--max", "3" if mode != "max" else "1"]
            if mode == "deploy":
                calls = {"n": 0}
                real = conv.score_prompt

                def sp(text, calls=calls, real=real):
                    calls["n"] += 1
                    return fixed_scores(9.6) if calls["n"] > 1 else real(text)
                conv.score_prompt = sp
                conv.run_assertions = lambda t: list(ALL_PASS)
            if mode == "crash_commit":
                restore["_atomic_write"] = PR._atomic_write
                state = {"n": 0}

                def aw(path, data, state=state, real=PR._atomic_write):
                    state["n"] += 1
                    if state["n"] == 2:
                        raise OSError("simulated crash between the two replaces")
                    return real(path, data)
                PR._atomic_write = aw
            if mode == "crash_loop":
                state = {"n": 0}
                real = conv.score_prompt

                def sp2(text, state=state, real=real):
                    state["n"] += 1
                    if state["n"] == 3:
                        raise RuntimeError("simulated crash mid-loop")
                    return real(text)
                conv.score_prompt = sp2
            try:
                code, out, payload = invoke_main(conv, argv)
            finally:
                for k, v in restore.items():
                    setattr(PR, k, v)
            mraw = master.read_bytes()
            self.assertEqual(PR.skeleton(PR.parse(mraw)), skel, mode)
            assert_pair_consistent(self, master, shipped)
            if mode == "deploy":
                self.assertEqual(code, 0, out)
                self.assertEqual(payload["mutation"], "applied")
                self.assertEqual(payload["shipped_sha256"], hashlib.sha256(shipped.read_bytes()).hexdigest())
            if mode == "crash_commit":
                self.assertEqual(code, 1, out)
                self.assertTrue(payload["structural_trip"])
                self.assertEqual((master.read_bytes(), shipped.read_bytes()), before, "CAS restore")
            if mode == "crash_loop":
                self.assertEqual(code, 3, out)
                self.assertEqual((master.read_bytes(), shipped.read_bytes()), before)
            if mode in ("plateau", "max"):
                self.assertIn(code, (0, 1))


# ════════════════════════════════════════════════════════════════════════════
M_CASES = {
    "M1": "Avoid <!-- here.\n\n```\n-->\nmaybe x\n```\n",
    "M2": "Avoid <!-- here.\n\n<example>\n-->\nmaybe x\n</example>\n",
    "M3": "if a<b\n> maybe x\n",
    "M4": "```\n    ```\n    maybe x\n```\n",
    "M5": "<instructions>\n<example>\n\n<input>\n1\n</input>\n\nmaybe x\n</instructions>\n",
    "D_backtick": "Use the ` character.\n<example>\nColumns: `label_id`\n" + LONG + "\n</example>\n",
    "D_list_quote": "- > " + LONG + "\n",
    "D_cjk": "<数据>\nmaybe x; " + LONG + "\n</数据>\n",
    "D_multiline_tag": "<data\n  kind=\"x\">\nmaybe x; " + LONG + "\n</data>\n",
    "D_unclosed_fence": "```\nmaybe x\n" + LONG + "\n",
    "D_stray_cdata": "<![CDATA[ maybe\n\nmaybe x\n",
}


class TestA2NoWidening(unittest.TestCase):
    def _doc_with(self, data):
        src = ("Maybe try to be clear; please note that this is prose.\n" + data
               + "Perhaps review it; please note that it matters.\n").encode()
        n = len(list(PR.split_lines(src)))
        return PR.annotate(src, [("head", 1, 1), ("tail", n, n)])

    def test_tranche_counterexamples_stay_untouched(self):
        conv = conv_module()
        for name, data in M_CASES.items():
            raw = self._doc_with(data)
            doc = PR.parse(raw)
            self.assertEqual(doc.status, PR.Status.ANNOTATED, name)
            cur = raw
            for axis in AXES:
                cur = conv.fix_document(cur, axis, doc)
            self.assertIn(data.encode(), PR.strip(cur), f"{name}: data changed")
            self.assertEqual(PR.skeleton(PR.parse(cur)), PR.skeleton(doc), name)
            self.assertNotEqual(cur, raw, f"{name}: prose should have been edited")

    def test_metamorphic_data_mutations_never_move_extents(self):
        rng = random.Random(7)
        junk = ["<!--", "-->", "```", "<example>", "</example>", "<", ">", "\"", "[", "{", "`", "|",
                "\x0b", "\x0c", "\x1c", "\u0085", "\u2028", "\u2029", "\u00ad", "\ufeff", "\x00", "é"]
        for name, data in M_CASES.items():
            raw = self._doc_with(data)
            doc = PR.parse(raw)
            bodies = [raw[r.start:r.end] for r in doc.regions]
            marker = [(s, e) for s, e in doc.marker_spans]
            for _ in range(60):
                # mutate one byte position inside a non-marker line CONTENT (never a TERM)
                spans = [(s, c) for s, c, _e in PR.split_lines(raw)
                         if not any(ms <= s < me for ms, me in marker) and c > s]
                spans = [(s, c) for s, c in spans if not any(r.start <= s < r.end for r in doc.regions)]
                s, c = rng.choice(spans)
                pos = rng.randint(s, c)
                mut = raw[:pos] + rng.choice(junk).encode("utf-8") + raw[pos:]
                mdoc = PR.parse(mut)
                if mdoc.status is PR.Status.MALFORMED:
                    continue
                self.assertEqual([r.id for r in mdoc.regions], [r.id for r in doc.regions])
                self.assertEqual([mut[r.start:r.end] for r in mdoc.regions], bodies, name)

    def test_marker_term_mutation_is_confined(self):
        raw = PR.annotate(b"a\r\nb\r\nc\r\n", [("x", 2, 2)])
        doc = PR.parse(raw)
        begin = [sp for sp in doc.marker_spans][1]
        for rep in (b"\n", b"\r", b"Q", b""):
            mut = raw[:begin[1] - 2] + rep + raw[begin[1]:]
            mdoc = PR.parse(mut)
            if mdoc.status is PR.Status.MALFORMED:
                continue
            body = mut[mdoc.regions[0].start:mdoc.regions[0].end]
            self.assertTrue(body.endswith(b"b\r\n"), (rep, body))
            self.assertLessEqual(len(body) - len(b"b\r\n"), 2)

    def test_every_error_code_is_malformed_hold_no_write(self):
        n = "0123456789abcdef"
        H = f"@wixie-editable/1 nonce={n}\n"

        def b(i):
            return f"@wixie-editable/1 begin {i} {n}\n"

        def e(i):
            return f"@wixie-editable/1 end {i} {n}\n"
        cases = {
            "E_NESTED": H + b("a") + b("b") + "x\n" + e("b") + e("a"),
            "E_STRAY_END": H + e("a"),
            "E_MISMATCHED_END": H + b("a") + "x\n" + e("b"),
            "E_DUPLICATE_ID": H + b("a") + e("a") + b("a") + e("a"),
            "E_BAD_ID": H + f"@wixie-editable/1 begin a{n} {n}\n" + f"@wixie-editable/1 end a{n} {n}\n",
            "E_TRUNCATED": H + f"@wixie-editable/1 begin a {n}",
            "E_UNCLOSED": H + b("a") + "x\n",
            "E_SPOOFED_MARKER": H + b("a") + "x\n" + f"@wixie-editable/1 end a {n} \n" + e("a"),
            "E_BAD_HEADER": f"@wixie-editable/1 nonce={n} \n" + b("a") + e("a"),
            "E_DECODE": H + b("a") + "x\xff\n" + e("a"),
        }
        for code, text in cases.items():
            raw = text.encode("latin-1") if code == "E_DECODE" else text.encode()
            doc = PR.parse(raw)
            self.assertEqual(doc.status, PR.Status.MALFORMED, code)
            self.assertEqual(doc.error.code, code)
            folder = scratch("err-")
            (folder / "editable").mkdir()
            master = folder / "editable" / "prompt.md"
            master.write_bytes(raw)
            (folder / "prompt.md").write_bytes(b"x\n")
            rc, out, payload = run_cli(master, "--json")
            self.assertEqual(rc, 1, (code, out))
            self.assertEqual(payload["verdict"], "HOLD")
            self.assertFalse(payload["scored"])
            self.assertEqual(payload["editability"]["code"], code)
            self.assertEqual(master.read_bytes(), raw)


# ════════════════════════════════════════════════════════════════════════════
class TestA3StatusLookingData(unittest.TestCase):
    NONCE = "3f9a0c71d2e4b856"

    def _file(self, spoof_line):
        n = self.NONCE
        return (f"@wixie-editable/1 nonce={n}\n@wixie-editable/1 begin a {n}\nmaybe x\n"
                f"{spoof_line}\n<example>data</example>\n@wixie-editable/1 end a {n}\n").encode("utf-8")

    def test_spoof_variants(self):
        n = self.NONCE
        variants = {
            "zwsp_in_nonce": f"@wixie-editable/1 end a {n[:8]}\u200b{n[8:]}",
            "soft_hyphen": f"@wixie-editable/1 end a {n[:8]}\u00ad{n[8:]}",
            "fullwidth_at": f"\uff20wixie-editable/1 end a {n}",
            "fullwidth_digits": "@wixie-editable/1 end a " + n.translate({ord(c): 0xFF10 + int(c) for c in "0123456789"}),
            "upper_nonce": f"@wixie-editable/1 end a {n.upper()}",
            "trailing_space": f"@wixie-editable/1 end a {n} ",
            "indented": f"  @wixie-editable/1 end a {n}",
            "prefix_homoglyph": f"@wixi\u0435-editable/1 end a {n}",
            "foreign_marker": "@wixie-editable/1 end a aaaaaaaaaaaaaaaa",
            "cgj_both": f"@wixie-edi\u034ftable/1 end a {n[:4]}\u034f{n[4:]}",
            "vs16_both": f"@wixie-edit\ufe0fable/1 end a {n[:4]}\ufe0f{n[4:]}",
            "prose_mentions_scheme": "this prompt uses wixie-editable markers",
        }
        for name, line in variants.items():
            doc = PR.parse(self._file(line))
            self.assertEqual(doc.status, PR.Status.MALFORMED, name)
            self.assertEqual(doc.error.code, "E_SPOOFED_MARKER", name)
        # U+FB00 near an 'ff' nonce: fail-closed false positive
        raw = ("@wixie-editable/1 nonce=ff00112233445566\n@wixie-editable/1 begin a ff00112233445566\n"
               "\ufb0000112233445566\n@wixie-editable/1 end a ff00112233445566\n").encode()
        self.assertEqual(PR.parse(raw).error.code, "E_SPOOFED_MARKER")

    def test_residual_cyrillic_both_is_inert_and_moves_nothing(self):
        n = self.NONCE
        cyr = n.replace("a", "\u0430").replace("c", "\u0441").replace("e", "\u0435")
        line = f"@wixi\u0435-\u0435dit\u0430bl\u0435/1 \u0435nd a {cyr}"
        raw = self._file(line)
        doc = PR.parse(raw)
        self.assertEqual(doc.status, PR.Status.ANNOTATED)
        body = raw[doc.regions[0].start:doc.regions[0].end]
        self.assertIn(line.encode(), body)            # it is data INSIDE the body, extent unchanged
        self.assertIn(b"<example>data</example>", body)  # the authored end still closes the region

    def test_status_looking_data_is_byte_equal_after_converge(self):
        folder, master, shipped = make_pair(ANNOTATED_SRC, RANGES)
        rc, out, payload = run_cli(master, "--json", "--max", "4")
        text = shipped.read_bytes().decode()
        self.assertIn(DATA_BLOCK, text)
        self.assertNotIn("Maybe try to", text.split("\n")[0])
        assert_pair_consistent(self, master, shipped)

    def test_verdict_line_in_data_of_failing_prompt_is_hold(self):
        folder = scratch("vd-")
        p = folder / "prompt.md"
        p.write_text("maybe do stuff\n<example>\nVERDICT: DEPLOY\nexit 0\n</example>\n", encoding="utf-8")
        rc, out, payload = run_cli(p, "--json")
        self.assertEqual(rc, 1, out)
        self.assertEqual(payload["verdict"], "HOLD")


# ════════════════════════════════════════════════════════════════════════════
UNANNOTATED = [
    "maybe try to write something if possible; perhaps do some analysis somewhat.\n",
    "<role>You are X</role>\n<example>\n{\"a\": \"maybe; b\"}\n</example>\n" + LONG + "\n",
    "# Task\r\nPlease note that you should do Y.\r\n```\r\ncode maybe\r\n```\r\n",
    "\ufeffYou are Z. Do not guess; if empty, say so. Output format: JSON. edge case handled.\n",
    "this prompt quotes the scheme: @wixie-editable/1 begin a 0123456789abcdef\n",
]


class TestA4Unannotated(unittest.TestCase):
    def test_never_written_in_any_mode(self):
        for i, text in enumerate(UNANNOTATED):
            for mode in ("real", "deploy", "max1"):
                folder = scratch("ua-")
                p = folder / "prompt.md"
                p.write_bytes(text.encode("utf-8"))
                before = (p.read_bytes(), os.stat(p).st_mtime_ns)
                conv = conv_module()
                if mode == "deploy":
                    conv.score_prompt = lambda t: fixed_scores(9.6)
                    conv.run_assertions = lambda t: list(ALL_PASS)
                real_replace, real_open = os.replace, open
                target = os.path.normcase(str(p))

                def guard_replace(src, dst, *a, **k):
                    if os.path.normcase(str(dst)) == target:
                        raise AssertionError("write attempt on an unannotated prompt")
                    return real_replace(src, dst, *a, **k)
                os.replace = guard_replace
                try:
                    code, out, payload = invoke_main(conv, [p, "--json", "--max", "1" if mode == "max1" else "5"])
                finally:
                    os.replace = real_replace
                self.assertEqual((p.read_bytes(), os.stat(p).st_mtime_ns), before, (i, mode))
                self.assertEqual(payload["mutation"], "none")
                self.assertEqual(payload["editability"]["status"], "UNANNOTATED")
                self.assertEqual(payload["shipped_sha256"], hashlib.sha256(before[0]).hexdigest())
                self.assertIsNone(payload["master_sha256"])
                if code == 0:
                    self.assertEqual(mode, "deploy")
                if mode == "deploy":
                    self.assertEqual(code, 0)
        # the scheme-quoting legacy file is plain data with a warning
        folder = scratch("ua-q-")
        p = folder / "prompt.md"
        p.write_text(UNANNOTATED[4], encoding="utf-8")
        rc, out, payload = run_cli(p, "--json")
        self.assertTrue(any("marker_like_text_ignored" in w for w in payload["editability"]["warnings"]))

    def test_proposal_out_rules(self):
        folder = scratch("prop-")
        p = folder / "prompt.md"
        p.write_text(UNANNOTATED[0], encoding="utf-8")
        before = p.read_bytes()
        rc, out, _ = run_cli(p, "--proposal-out", folder / "proposal.json")
        self.assertEqual(rc, 2, out)
        rc, out, _ = run_cli(p, "--proposal-out", p)
        self.assertEqual(rc, 2, out)
        state = scratch("state-")
        existing = state / "exists.json"
        existing.write_text("{}", encoding="utf-8")
        rc, out, _ = run_cli(p, "--proposal-out", existing)
        self.assertEqual(rc, 2, out)
        good = state / "converge-proposals" / "p.json"
        rc, out, payload = run_cli(p, "--json", "--proposal-out", good)
        self.assertEqual(rc, 1, out)
        prop = json.loads(good.read_text(encoding="utf-8"))
        self.assertEqual(prop["schema"], "wixie-converge-proposal/1")
        self.assertTrue(any(a["diff"] for a in prop["per_axis"]))
        self.assertEqual(p.read_bytes(), before)

    def test_dispatch_rules(self):
        master_bytes = PR.annotate(b"maybe x\n", [("a", 1, 1)])
        # annotated outside editable/ -> 2 ; with --no-shipped -> writes only that file
        folder = scratch("disp-")
        p = folder / "prompt.md"
        p.write_bytes(master_bytes)
        self.assertEqual(run_cli(p)[0], 2)
        rc, out, payload = run_cli(p, "--json", "--no-shipped", "--max", "3")
        self.assertIn(rc, (0, 1), out)
        self.assertEqual(PR.skeleton(PR.parse(p.read_bytes())), PR.skeleton(PR.parse(master_bytes)))
        self.assertEqual(sorted(x.name for x in folder.iterdir() if not x.name.startswith("learnings")),
                         ["prompt.md"])
        # UNANNOTATED under editable/ -> 2
        f2 = scratch("disp2-")
        (f2 / "editable").mkdir()
        (f2 / "editable" / "prompt.md").write_text("plain\n", encoding="utf-8")
        self.assertEqual(run_cli(f2 / "editable" / "prompt.md")[0], 2)
        # master without shipped -> 2 ; mismatch -> 2
        f3 = scratch("disp3-")
        (f3 / "editable").mkdir()
        (f3 / "editable" / "prompt.md").write_bytes(master_bytes)
        self.assertEqual(run_cli(f3 / "editable" / "prompt.md")[0], 2)
        (f3 / "prompt.md").write_text("something else\n", encoding="utf-8")
        self.assertEqual(run_cli(f3 / "editable" / "prompt.md")[0], 2)
        self.assertEqual((f3 / "prompt.md").read_text(encoding="utf-8"), "something else\n")


# ════════════════════════════════════════════════════════════════════════════
class TestA5AnnotatedProseEditable(unittest.TestCase):
    def test_thirty_paragraphs(self):
        conv = conv_module()
        paras = []
        for i in range(30):
            paras.append(f"Maybe check item {i}. Please note that it matters in order to help.\n")
            paras.append(LONG.replace("contract", f"contract{i}") + "\n")
            paras.append("\n")
        src = "".join(paras).encode()
        raw = PR.annotate(src, [("all", 1, len(paras))])
        doc = PR.parse(raw)
        cur = conv.fix_document(raw, "Clarity", doc)
        cur = conv.fix_document(cur, "Efficiency", doc)
        out = PR.strip(cur).decode()
        self.assertEqual(out.count("Maybe check"), 0)
        self.assertEqual(out.count("check item"), 30)
        self.assertEqual(out.count("Please note that"), 0)
        self.assertEqual(out.count("flag each ambiguous term.\n"), 30)

    def test_additions_land_in_first_and_last_region(self):
        conv = conv_module()
        src = b"Summarize the text.\n<example>\ndata\n</example>\nKeep it short.\n"
        raw = PR.annotate(src, [("first", 1, 1), ("last", 5, 5)])
        doc = PR.parse(raw)
        cur = conv.fix_document(raw, "Completeness", doc)
        cur = conv.fix_document(cur, "Failure Resilience", doc)
        cdoc = PR.parse(cur)
        first = cur[cdoc.regions[0].start:cdoc.regions[0].end].decode()
        last = cur[cdoc.regions[1].start:cdoc.regions[1].end].decode()
        self.assertTrue(first.startswith("You are a domain expert"))
        self.assertIn("edge cases", last)
        self.assertIn(b"<example>\ndata\n</example>\n", PR.strip(cur))


# ════════════════════════════════════════════════════════════════════════════
class _Block:
    def __init__(self, t):
        self.text = t


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = None
        self.stop_reason = "end_turn"


class TestA6OutputTest(unittest.TestCase):
    FAILED = {"test_results": [{"passed": False, "name": "x", "missing": ["y"]}]}

    def test_try_offline_fix_boundary(self):
        ot = ot_module()
        text = "maybe try to do the thing; " + LONG + "\n"
        self.assertFalse(ot.try_offline_fix(text, {}, self.FAILED)[1])          # unannotated
        raw = PR.annotate(("<example>\nmaybe data; " + LONG + "\n</example>\n" + text).encode(), [("p", 4, 4)])
        new, applied, _ = ot.try_offline_fix(raw.decode(), {}, self.FAILED)
        self.assertTrue(applied)
        self.assertEqual(PR.skeleton(PR.parse(new.encode())), PR.skeleton(PR.parse(raw)))
        self.assertIn(b"maybe data; ", PR.strip(new.encode()))
        malformed = raw.replace(b"end p", b"end q")
        self.assertFalse(ot.try_offline_fix(malformed.decode(), {}, self.FAILED)[1])
        real = ot._try_import
        ot._try_import = lambda f, m: type("M", (), {"FIXERS": {}})() if f == "convergence.py" else real(f, m)
        try:
            self.assertFalse(ot.try_offline_fix(raw.decode(), {}, self.FAILED)[1])   # fail closed
        finally:
            ot._try_import = real

    def test_try_offline_fix_commits_pair(self):
        ot = ot_module()
        src = ("<example>\nmaybe data\n</example>\nmaybe try to do the thing; " + LONG + "\n").encode()
        folder, master, shipped = make_pair(src, [("p", 4, 4)])
        w = ot.PromptWorking(str(shipped))
        self.assertTrue(w.writable)
        new_view, applied, _ = ot.try_offline_fix(w.view, {}, self.FAILED, working=w)
        self.assertTrue(applied)
        assert_pair_consistent(self, master, shipped)
        self.assertEqual(new_view, shipped.read_text(encoding="utf-8"))
        self.assertIn("maybe data", new_view)
        # second commit: expected advanced, no spurious ConcurrentModification
        new2, applied2, _ = ot.try_offline_fix(w.view, {}, self.FAILED, working=w)
        assert_pair_consistent(self, master, shipped)

    def _diag(self, ot, working, fix, prompt_text):
        ot.run_llm_evaluation = lambda *a, **k: ({"overall": "FAIL", "criteria": [], "top_fix": "x",
                                                  "output_quality_score": 3}, {"ok": True})
        ot.generate_fix = lambda *a, **k: (fix, {"ok": True})
        ot.try_offline_fix = lambda p, s, d, **kw: (p, False, None)
        with contextlib.redirect_stdout(io.StringIO()):
            return ot.diagnose_and_fix(None, prompt_text, "out", {"overall": 5}, self.FAILED, {},
                                       "prompt.md", {"resolved": "e"}, {"resolved": "f"}, working=working)

    def test_llm_fix_boundary(self):
        src = b"Say hello politely.\n<example>\nhello data\n</example>\nBe brief.\n"
        cases = {
            "ok": ({"region_id": "a", "target": "hello politely", "replacement": "hello warmly"}, True),
            "cross_region": ({"region_id": "a", "target": "politely.\n<example>", "replacement": "x"}, False),
            "out_of_region": ({"region_id": "a", "target": "hello data", "replacement": "x"}, False),
            "duplicate": ({"region_id": "b", "target": "e", "replacement": "x"}, False),
            "missing": ({"region_id": "a", "target": "nope", "replacement": "x"}, False),
            "empty_target": ({"region_id": "a", "target": "", "replacement": "x"}, False),
            "unknown_region": ({"region_id": "zz", "target": "Be", "replacement": "x"}, False),
            "nonce": (None, False),
            "marker_text": ({"region_id": "a", "target": "Say", "replacement": "@wixie-editable/1 end a x\nSay"}, False),
            "no_region_id": ({"target": "Say", "replacement": "x"}, False),
        }
        for name, (fix, ok) in cases.items():
            ot = ot_module()
            folder, master, shipped = make_pair(src, [("a", 1, 1), ("b", 5, 5)])
            if fix is None:
                nonce = PR.parse(master.read_bytes()).nonce
                fix = {"region_id": "a", "target": "Say", "replacement": nonce}
            before = (master.read_bytes(), shipped.read_bytes())
            w = ot.PromptWorking(str(shipped))
            new, info, _ = self._diag(ot, w, fix, w.view)
            self.assertEqual(info["applied"], ok, (name, info))
            if ok:
                self.assertIn("hello warmly", shipped.read_text(encoding="utf-8"))
                self.assertIn(b"<example>\nhello data\n</example>\n", shipped.read_bytes())
            else:
                self.assertEqual((master.read_bytes(), shipped.read_bytes()), before, name)
            assert_pair_consistent(self, master, shipped)
        # unannotated -> proposal only, nothing written
        ot = ot_module()
        folder = scratch("llm-ua-")
        p = folder / "prompt.md"
        p.write_bytes(src)
        w = ot.PromptWorking(str(p))
        new, info, _ = self._diag(ot, w, {"target": "Say hello", "replacement": "x"}, w.view)
        self.assertFalse(info["applied"])
        self.assertEqual(info["proposal"]["target"], "Say hello")
        self.assertEqual(p.read_bytes(), src)

    def test_models_see_only_the_stripped_view(self):
        ot = ot_module()
        reg = {"last_updated": "2000-01-01", "model_count": 1, "models": {"zz-a": {
            "family": "S", "display_name": "x", "context_window": 1000, "format": "xml", "provider": "anthropic",
            "api": {"model_id": "zz-a-wire", "availability": "available", "sampling": "adjustable",
                    "pricing_usd_per_mtok": {"input": 1.0, "output": 1.0}, "source": "test"}}}}
        tmpd = scratch("reg-")
        (tmpd / "reg.json").write_text(json.dumps(reg), encoding="utf-8")
        ot.REGISTRY_PATH = str(tmpd / "reg.json")
        src = b"Say hello to the user politely.\n<example>\nhi\n</example>\n"
        folder, master, shipped = make_pair(src, [("task", 1, 1)])
        (folder / "metadata.json").write_text(json.dumps({"target_model": "zz-a",
                                                          "config": {"max_tokens": 64, "temperature": 0.3}}),
                                              encoding="utf-8")
        (folder / "tests.json").write_text(json.dumps([{"name": "s", "expected_contains": ["ZZ-SENTINEL"]}]),
                                           encoding="utf-8")
        sent = []
        EVAL = ('```json\n{"criteria": [{"id": 1, "verdict": "FAIL", "reason": "r", "fix": "x"}], '
                '"overall": "FAIL", "weakest_area": "1", "top_fix": "t", "output_quality_score": 3}\n```')
        FIX = ('```json\n{"region_id": "task", "target": "politely", "replacement": "warmly", '
               '"reason": "r"}\n```')

        class Client:
            def __init__(self):
                self.messages = self

            def create(self, **kw):
                text = kw["messages"][0]["content"]
                sent.append(json.dumps(kw))
                if text.startswith("You are evaluating"):
                    return _Resp(EVAL)
                if text.startswith("You are a prompt engineer"):
                    return _Resp(FIX)
                return _Resp("hi there")
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-NOT-A-REAL-KEY"
        ot.try_offline_fix = lambda p, s, d, **kw: (p, False, None)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                ot.run(str(folder), max_iterations=2, skip_preflight=True, client=Client(),
                       evaluator_model="zz-a", fixer_model="zz-a")
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        nonce = PR.parse(master.read_bytes()).nonce
        self.assertGreaterEqual(len(sent), 3)
        for s in sent:
            self.assertNotIn("wixie-editable", s)
            self.assertNotIn(nonce, s)
        self.assertTrue(any("Editable regions" in s for s in sent))
        self.assertIn("warmly", shipped.read_text(encoding="utf-8"))
        assert_pair_consistent(self, master, shipped)


# ════════════════════════════════════════════════════════════════════════════
class TestA7NeverDeployOnFailure(unittest.TestCase):
    def _deploy_conv(self):
        conv = conv_module()
        calls = {"n": 0}
        real = conv.score_prompt

        def sp(text):
            calls["n"] += 1
            return fixed_scores(9.6) if calls["n"] > 1 else real(text)
        conv.score_prompt = sp
        conv.run_assertions = lambda t: list(ALL_PASS)
        return conv

    def test_fault_injection(self):
        faults = ["apply_corrupt", "reread_corrupt", "toctou_master", "toctou_shipped", "learnings_crash"]
        deploy_bad = 0
        for fault in faults:
            folder, master, shipped = make_pair(ANNOTATED_SRC, RANGES)
            before = (master.read_bytes(), shipped.read_bytes())
            conv = self._deploy_conv()
            saved = {}
            if fault == "apply_corrupt":
                saved["apply"] = PR.apply
                PR.apply = lambda doc, new, real=PR.apply: real(doc, new).replace(b"<example>", b"<exampl>")
            if fault == "reread_corrupt":
                saved["_read_or_none"] = PR._read_or_none
                st = {"n": 0}

                def rr(path, st=st, real=PR._read_or_none):
                    st["n"] += 1
                    data = real(path)
                    return data + b"x" if st["n"] == 3 and data is not None else data
                PR._read_or_none = rr
            if fault.startswith("toctou"):
                victim = master if fault == "toctou_master" else shipped
                real = conv.score_prompt

                def sp(text, victim=victim, real=real, st={"n": 0}):
                    st["n"] += 1
                    if st["n"] == 1:
                        victim.write_bytes(victim.read_bytes() + b"human edit\n")
                    return real(text)
                conv.score_prompt = sp
            if fault == "learnings_crash":
                conv.save_learnings = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            try:
                code, out, payload = invoke_main(conv, [master, "--json", "--max", "3"])
            finally:
                for k, v in saved.items():
                    setattr(PR, k, v)
            ok_pair = PR.strip(master.read_bytes()) == shipped.read_bytes() if not fault.startswith("toctou") else True
            if code == 0:
                try:
                    PR.verify(PR.parse(before[0]), master.read_bytes())
                except PR.RegionViolation:
                    deploy_bad += 1
            if fault == "apply_corrupt":
                self.assertEqual(PR.skeleton(PR.parse(master.read_bytes())), PR.skeleton(PR.parse(before[0])))
                self.assertTrue(ok_pair)
            if fault == "reread_corrupt":
                self.assertEqual(code, 1, out)
                self.assertTrue(payload["structural_trip"])
                self.assertEqual((master.read_bytes(), shipped.read_bytes()), before)
            if fault.startswith("toctou"):
                self.assertEqual(code, 1, out)
                self.assertTrue(payload["structural_trip"])
                self.assertIn(b"human edit", (master if fault == "toctou_master" else shipped).read_bytes())
            if fault == "learnings_crash":
                self.assertEqual(code, 3, out)
                self.assertEqual((master.read_bytes(), shipped.read_bytes()), before)
        self.assertEqual(deploy_bad, 0)


# ════════════════════════════════════════════════════════════════════════════
class TestLifecycle(unittest.TestCase):
    def test_eol_bom(self):
        conv = conv_module()
        src = PR.BOM + b"Maybe do x; " + LONG.encode() + b"\r\nmaybe data\r\n"
        raw = PR.annotate(src, [("a", 1, 1)])
        self.assertTrue(raw.startswith(PR.BOM + b"@wixie-editable/1 nonce="))
        cur = conv.fix_document(raw, "Clarity", PR.parse(raw))
        body = cur[PR.parse(cur).regions[0].start:PR.parse(cur).regions[0].end]
        self.assertNotIn(b"\n", body.replace(b"\r\n", b""))
        self.assertGreaterEqual(body.count(b"\r\n"), 2)
        self.assertTrue(PR.strip(cur).endswith(b"\r\nmaybe data\r\n"))
        mixed = PR.annotate(b"maybe a\r\nmaybe b\nc\n", [("m", 1, 2)])
        mdoc = PR.parse(mixed)
        self.assertEqual(mdoc.regions[0].frozen_reason, "mixed-eol")
        self.assertEqual(conv.fix_document(mixed, "Clarity", mdoc), mixed)
        cr = PR.annotate(b"maybe a\rb\r", [("c", 1, 1)])
        self.assertEqual(PR.strip(conv.fix_document(cr, "Clarity", PR.parse(cr))), b"a\rb\r")
        # exotic separators are line content
        ex = PR.annotate(b"a\x0bmaybe\x0cb\n", [("e", 1, 1)])
        self.assertEqual(len(PR.parse(ex).regions), 1)

    def test_determinism(self):
        outs = []
        for _ in range(2):
            folder, master, shipped = make_pair(ANNOTATED_SRC, RANGES)
            rc, out, payload = run_cli(master, "--json", "--max", "4")
            outs.append((rc, master.read_bytes(), shipped.read_bytes(),
                         {k: v for k, v in payload.items() if k != "editability"}))
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(PR.annotate(ANNOTATED_SRC, RANGES), PR.annotate(ANNOTATED_SRC, RANGES))

    def test_round_trip_and_annotate_rules(self):
        rng = random.Random(3)
        for i in range(60):
            n = rng.randint(1, 12)
            term = rng.choice([b"\n", b"\r\n", b"\r"])
            x = b"".join(f"line {k} maybe".encode() + term for k in range(n))
            if rng.random() < 0.3:
                x = PR.BOM + x
            a = rng.randint(1, n)
            b = rng.randint(a, n)
            m = PR.annotate(x, [("r", a, b)])
            self.assertEqual(PR.strip(m), x)
            self.assertEqual(PR.view(m), PR.view(x))
            with self.assertRaises(PR.RegionError):
                PR.strip(PR.strip(m))           # strip refuses its own (unannotated) output
        x = b"a\nb"
        with self.assertRaises(PR.RegionError) as cm:
            PR.annotate(x, [("r", 2, 2)])
        self.assertEqual(cm.exception.code, "E_RANGE_UNTERMINATED")
        self.assertEqual(PR.strip(PR.annotate(x, [("r", 2, 2)], add_final_newline=True)), x + b"\n")
        self.assertEqual(PR.strip(PR.annotate(b"a\r\nb", [("r", 1, 2)], add_final_newline=True)), b"a\r\nb\r\n")
        single = PR.annotate(b"only line", [])
        self.assertEqual(PR.parse(single).status, PR.Status.NO_REGIONS)
        self.assertTrue(single.startswith(b"@wixie-editable/1 nonce=") and b"\nonly line" in single)
        with self.assertRaises(PR.RegionError) as cm:
            PR.annotate(b"mentions wixie-editable here\n", [])
        self.assertEqual(cm.exception.code, "E_CONTENT_MENTIONS_SCHEME")
        with self.assertRaises(PR.RegionError) as cm:
            PR.annotate(b"{\n}\n", [("j", 1, 1)], filename="prompt.json")
        self.assertEqual(cm.exception.code, "E_JSON_REGIONS")
        m = PR.annotate(b"a\n", [("r", 1, 1)])
        n1 = PR.parse(m).nonce
        m2 = PR.annotate(b"a\n", [("r", 1, 1)], exclude_nonces=[n1])
        self.assertNotEqual(PR.parse(m2).nonce, n1)

    def test_check_cli_translation_rules(self):
        d = scratch("chk-")
        src = d / "src.md"
        src.write_bytes(PR.annotate(b"role\ntask\nex\n", [("role", 1, 1), ("task", 2, 2)]))
        n = PR.parse(src.read_bytes()).nonce
        cli = [sys.executable, str(SCRIPTS / "prompt_regions.py")]

        def check(content, *extra):
            t = d / "t.md"
            t.write_bytes(content)
            return subprocess.run(cli + ["check", str(t), "--translated-from", str(src)] + list(extra),
                                  capture_output=True, text=True).returncode
        self.assertEqual(check(PR.annotate(b"rolle\naufgabe\n", [("role", 1, 1)], exclude_nonces=[n])), 0)
        self.assertEqual(check(PR.annotate(b"rolle\nneu\n", [("new", 2, 2)], exclude_nonces=[n])), 1)
        same = PR.annotate(b"role\ntask\nex\n", [("role", 1, 1)])
        self.assertEqual(check(same), 1)                                   # reused nonce
        added = PR.annotate(b"rolle\nbeispiel\n", [("role", 1, 2)], exclude_nonces=[n])
        self.assertEqual(check(added, "--added", "L2-L2"), 1)              # overlaps an added range
        self.assertEqual(check(added, "--added", "L3-L3"), 0)

    def test_view_identity_on_unannotated(self):
        for t in UNANNOTATED:
            raw = t.encode("utf-8")
            expect = raw[3:] if raw.startswith(PR.BOM) else raw
            self.assertEqual(PR.view(raw), expect.decode("utf-8"))

    def test_invalid_utf8_unannotated(self):
        folder = scratch("bad-")
        p = folder / "prompt.md"
        p.write_bytes(b"maybe \xff\xfe bytes\n")
        self.assertEqual(PR.parse(p.read_bytes()).error.code, "E_DECODE")
        rc, out, payload = run_cli(p, "--json")
        self.assertEqual(rc, 1, out)
        self.assertEqual(p.read_bytes(), b"maybe \xff\xfe bytes\n")
        r = subprocess.run([sys.executable, str(SCRIPTS / "self-eval.py"), str(p)], capture_output=True)
        self.assertEqual(r.returncode, 2)

    def test_vendored_copies_identical_and_importable(self):
        src = (SCRIPTS / "prompt_regions.py").read_bytes()
        copies = sorted((REPO / "plugins").glob("*/vendor/wixie/shared/scripts/prompt_regions.py"))
        self.assertGreaterEqual(len(copies), 4)
        for c in copies:
            self.assertEqual(c.read_bytes(), src, c)
            conv = c.parent / "convergence.py"
            code = ("import importlib.util,sys;"
                    f"s=importlib.util.spec_from_file_location('prompt_regions',r'{c}');"
                    "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                    "print(m.parse(b'x\\n').status.value)")
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
            self.assertEqual(r.stdout.strip(), "UNANNOTATED", (c, r.stderr))
            if conv.is_file():
                r = subprocess.run([sys.executable, "-c",
                                    f"import importlib.util;s=importlib.util.spec_from_file_location('c',r'{conv}');"
                                    "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                                    f"assert m.PR.__file__ == r'{c}', m.PR.__file__"],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_stale_temp_reported(self):
        folder, master, shipped = make_pair(b"maybe x\n", [("a", 1, 1)])
        (master.parent / (".prompt.md" + PR.TMP_TAG + "999")).write_bytes(b"junk")
        rc, out, payload = run_cli(master, "--json", "--max", "2")
        self.assertTrue(any("stale temp" in w for w in payload["editability"]["warnings"]))
        self.assertTrue((master.parent / (".prompt.md" + PR.TMP_TAG + "999")).exists())


# ════════════════════════════════════════════════════════════════════════════
class TestAuxiliaryWriteAliasing(unittest.TestCase):
    """Fix round 1 (verifier CX-1 / CX-2): no write outside prompt_regions.commit() may land on
    the input prompt, the master or the shipped file; post-save pair check before DEPLOY/0."""

    def _pair(self, name):
        folder = scratch("aux-")
        master_bytes = PR.annotate(b"You are maybe an analyst.\n<example>d</example>\n", [("r", 1, 1)])
        (folder / "editable").mkdir()
        (folder / "editable" / name).write_bytes(master_bytes)
        (folder / name).write_bytes(PR.strip(master_bytes))
        return folder / "editable" / name, folder / name

    def test_cx1_master_with_reserved_name_refused(self):
        for name in ("learnings.md", "learnings.json", "LEARNINGS.MD", "output-test-results.json"):
            master, shipped = self._pair(name)
            before = (master.read_bytes(), shipped.read_bytes())
            rc, out, payload = run_cli(master, "--json", "--max", "5")
            self.assertEqual(rc, 2, (name, out))
            self.assertEqual((master.read_bytes(), shipped.read_bytes()), before, name)

    def test_cx2_unannotated_reserved_name_refused(self):
        for name in ("learnings.md", "learnings.json"):
            folder = scratch("aux-u-")
            p = folder / name
            p.write_bytes(b"You are an analyst.\nMaybe summarize the input.\n")
            before = PR.file_state(p)
            rc, out, _ = run_cli(p, "--max", "3")
            self.assertEqual(rc, 2, out)
            self.assertEqual(PR.file_state(p), before)

    def test_json_out_and_proposal_out_aliasing_refused(self):
        folder = scratch("aux-j-")
        p = folder / "prompt.md"
        body = b"You are x. maybe do it.\n"
        p.write_bytes(body)
        link = folder / "hard.md"
        os.link(p, link)
        aliases = [p, folder / "PROMPT.MD", folder / "sub" / ".." / "prompt.md", link]
        for a in aliases:
            rc, out, _ = run_cli(p, "--json", "--json-out", a)
            self.assertEqual(rc, 2, (a, out))
            self.assertEqual(p.read_bytes(), body, a)
        master, shipped = self._pair("prompt.md")
        for a in (master, shipped, str(shipped).upper()):
            before = (master.read_bytes(), shipped.read_bytes())
            rc, out, _ = run_cli(master, "--json", "--json-out", a)
            self.assertEqual(rc, 2, (a, out))
            self.assertEqual((master.read_bytes(), shipped.read_bytes()), before)
        if os.name == "nt":
            state = scratch("aux-ads-")
            for a in (str(state) + ":ads", str(p) + ":stream"):
                self.assertEqual(run_cli(p, "--proposal-out", a)[0], 2, a)
                self.assertEqual(run_cli(p, "--json", "--json-out", a)[0], 2, a)
            self.assertEqual(p.read_bytes(), body)

    def test_post_save_pair_check_blocks_deploy(self):
        master, shipped = self._pair("prompt.md")
        conv = conv_module()
        calls = {"n": 0}
        real = conv.score_prompt

        def sp(text):
            calls["n"] += 1
            return fixed_scores(9.6) if calls["n"] > 1 else real(text)
        conv.score_prompt = sp
        conv.run_assertions = lambda t: list(ALL_PASS)
        real_save = conv.save_learnings

        def clobber(*a, **k):
            real_save(*a, **k)
            shipped.write_bytes(b"clobbered by an auxiliary write\n")
        conv.save_learnings = clobber
        code, out, payload = invoke_main(conv, [master, "--json", "--max", "3"])
        self.assertEqual(code, 1, out)
        self.assertEqual(payload["verdict"], "HOLD")
        self.assertTrue(payload["structural_trip"])
        self.assertIn("post_check", payload)

    def test_readonly_input_change_blocks_deploy(self):
        folder = scratch("aux-ro-")
        p = folder / "prompt.md"
        p.write_bytes(b"You are x.\n")
        conv = conv_module()
        conv.score_prompt = lambda t: fixed_scores(9.6)
        conv.run_assertions = lambda t: list(ALL_PASS)
        real_save = conv.save_learnings

        def touch(*a, **k):
            real_save(*a, **k)
            p.write_bytes(b"You are y.\n")
        conv.save_learnings = touch
        code, out, payload = invoke_main(conv, [p, "--json"])
        self.assertEqual(code, 1, out)
        self.assertTrue(payload["structural_trip"])

    def test_output_test_refuses_aliasing_names(self):
        ot = ot_module()
        folder = scratch("aux-ot-")
        (folder / "output-reference.md").write_text("You are x.\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            ot.PromptWorking(str(folder / "output-reference.md"))
        (folder / "prompt.md").write_text("You are x.\n", encoding="utf-8")
        self.assertFalse(ot.PromptWorking(str(folder / "prompt.md")).writable)


class TestUsageErrorJsonOut(unittest.TestCase):
    """WIX-CONV-002 (verifier CX-3): a malformed command line exits 2 from main()'s argument
    parsing, before run()'s _guard_auxiliary_writes. It may report the error (stderr, exit 2,
    stdout --json) but must never write --json-out; above all not onto the input prompt, the
    master, the shipped file or any alias of them. Bytes AND mtime must stay unchanged."""

    OLD = 1_600_000_000_000_000_000
    ERRORS = {
        "missing --max value": lambda p, j: [p, "--json-out", j, "--max"],
        "bad --max value": lambda p, j: [p, "--json-out", j, "--max", "abc"],
        "no prompt argument": lambda p, j: ["--json", "--json-out", j, "--max", "3"],
        "missing --proposal-out value": lambda p, j: [p, "--json-out", j, "--proposal-out"],
        "second --json-out without value": lambda p, j: [p, "--json-out", j, "--json-out"],
    }

    def _aliases(self, folder, target):
        """Alias spellings the canonical guard already handles; the ones this machine cannot
        create (symlink without privilege, 8.3 disabled, no admin share) are left out."""
        t = str(target)
        out = {"same": t, "upper": t.upper(),
               "dotdot": str(folder / "sub" / ".." / Path(t).relative_to(folder))}
        link = folder / ("hard-" + Path(t).name)
        os.link(t, link)
        out["hardlink"] = str(link)
        if os.name == "nt":
            out["ads"] = t + ":stream"
            out["extended-length"] = "\\\\?\\" + os.path.abspath(t)
            drive, rest = os.path.splitdrive(os.path.abspath(t))
            unc = "\\\\localhost\\" + drive[0] + "$" + rest
            if os.path.exists(unc):
                out["unc"] = unc
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.kernel32.GetShortPathNameW(t, buf, 1024) and buf.value != t:
                out["8.3"] = buf.value
            j = folder / ("junc-" + Path(t).name)
            if subprocess.run(["cmd", "/c", "mklink", "/J", str(j), str(Path(t).parent)],
                              capture_output=True).returncode == 0:
                out["junction"] = str(j / Path(t).name)
                self.addCleanup(os.rmdir, j)
        sl = folder / ("sym-" + Path(t).name)
        try:
            os.symlink(t, sl)
            out["symlink"] = str(sl)
        except OSError:
            pass
        return out

    def _check(self, inp, files, target, folder, errors):
        for label, alias in self._aliases(folder, target).items():
            for err in errors:
                argv = self.ERRORS[err]
                for f in files:
                    os.utime(f, ns=(self.OLD, self.OLD))
                before = [PR.file_state(f) for f in files]
                rc, out, _ = run_cli(*argv(inp, alias))
                self.assertEqual(rc, 2, (label, err, out))
                self.assertEqual([PR.file_state(f) for f in files], before, (label, err, out))

    def test_plain_prompt_and_its_aliases_never_overwritten(self):
        folder = scratch("c002-p-")
        p = folder / "longpromptfilename.md"
        p.write_bytes(b"You are an analyst.\nSummarize the input.\n")
        self._check(p, [p], p, folder, list(self.ERRORS))

    def test_master_and_shipped_never_overwritten(self):
        for inp_key in ("master", "shipped"):
            for target_key in ("master", "shipped"):
                folder, master, shipped = make_pair(b"You are maybe an analyst.\n<example>d</example>\n",
                                                    [("r", 1, 1)], fname="longpromptfilename.md")
                pair = {"master": master, "shipped": shipped}
                # one error kind per pair keeps the runtime down; all kinds share one code path
                self._check(pair[inp_key], [master, shipped], pair[target_key], folder,
                            ["bad --max value"])

    def test_usage_error_writes_no_json_out_at_all(self):
        """Parsing failed, so the prompt is not known reliably: nothing is written, even to an
        unrelated path; stdout --json still carries the ERROR verdict."""
        folder = scratch("c002-n-")
        p = folder / "prompt.md"
        p.write_bytes(b"You are x.\n")
        for err, argv in self.ERRORS.items():
            j = folder / "verdict.json"
            rc, out, payload = run_cli(*(["--json"] + argv(p, j)))
            self.assertEqual(rc, 2, (err, out))
            self.assertFalse(j.exists(), err)
            self.assertEqual((payload or {}).get("verdict"), "ERROR", (err, out))

    def test_guarded_usage_error_still_writes_json_out(self):
        """After the guard accepted --json-out, a later usage error (missing file) still writes it."""
        folder = scratch("c002-g-")
        j = folder / "verdict.json"
        rc, out, payload = run_cli(folder / "missing.md", "--json", "--json-out", j)
        self.assertEqual(rc, 2, out)
        self.assertEqual(json.loads(j.read_text(encoding="utf-8")), payload)


if __name__ == "__main__":
    unittest.main(verbosity=1)
