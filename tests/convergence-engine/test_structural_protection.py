#!/usr/bin/env python3
"""
WIX-CONV-001 -- convergence.py's fixers may modify ONLY "editable prose": top-level prose
lines and prose lines inside an XML element whose tag name is in the documented
instruction-section allow-list (convergence.EDITABLE_XML_SECTIONS). Everything else is
frozen and must come out content-equal: fenced and top-level indented code, tables,
blockquotes, bracket blocks (multi-line / stand-alone JSON), the content of any element
whose tag is NOT allow-listed (unknown tags default to frozen -- XML/JSON data examples),
paired <example>/<examples> blocks however their tags are placed, and every tag token.
Within an editable line no edit may land inside a bracket / brace / paren / quote /
backtick span; such a line is skipped, not frozen for other safe edits. An unpaired
"<example>" mention freezes nothing but its own characters.

The accept/revert gate compares a linear-time structural fingerprint of the non-editable
content (plus the tag sequence) on every candidate; every exit path re-checks before AND
after writing and keeps the original bytes on a mismatch, forcing HOLD (never DEPLOY /
exit 0). output-test.py's try_offline_fix shares the gate and fails closed. Line endings
(LF / CRLF / mixed, per line) and a UTF-8 BOM are preserved. Parsing is iterative and
linear: 5000 nested brackets and a 200 KB prompt finish quickly without a crash.

All fixtures are the implementer's own. Usage:
    python test_structural_protection.py <REPO_ROOT>     (exit 0 = all pass)
Every test runs even if an earlier one fails; failures are listed at the end.
"""
import contextlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import time
import traceback
import types
from pathlib import Path

# Private temp root (WIX-TEST-ENV-001, tests/_test_root.py): scratch never lands in shared temp.
_root_spec = importlib.util.spec_from_file_location(
    "wixie_test_root", Path(__file__).resolve().parents[1] / "_test_root.py")
_root_mod = importlib.util.module_from_spec(_root_spec)
_root_spec.loader.exec_module(_root_mod)
_root_mod.ensure_test_root()

AXES = ["Clarity", "Completeness", "Efficiency", "Model Fit", "Failure Resilience"]

BASE_ASSERTIONS_ALL_PASS = [
    ("has_role", True, "Prompt defines a role or persona"),
    ("has_task", True, "Prompt defines a clear task"),
    ("has_format", True, "Prompt specifies output format"),
    ("has_constraints", True, "Prompt has constraints/guardrails"),
    ("has_edge_cases", True, "Prompt handles edge cases"),
    ("no_hedge_words", True, "No hedge words (maybe, perhaps, possibly)"),
    ("no_filler", True, "No filler phrases"),
    ("has_structure", True, "Prompt has structural markup (headers or XML tags)"),
]

REPO_ROOT = None


def load_convergence():
    path = REPO_ROOT / "shared" / "scripts" / "convergence.py"
    spec = importlib.util.spec_from_file_location("convergence_uut", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_output_test():
    path = REPO_ROOT / "shared" / "scripts" / "output-test.py"
    spec = importlib.util.spec_from_file_location("output_test_uut", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_cli(prompt_path, *extra, timeout=120):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "shared" / "scripts" / "convergence.py"),
         str(prompt_path), *extra],
        cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout)


def run_quiet(mod, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return mod.run(*args, **kwargs)


def call_main(mod, argv):
    """Run mod.main() in-process; returns (exit_code, stdout)."""
    saved = sys.argv
    buf = io.StringIO()
    sys.argv = ["convergence.py"] + list(argv)
    code = None
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            mod.main()
    except SystemExit as e:
        code = e.code
    finally:
        sys.argv = saved
    return code, buf.getvalue()


# ─── Shared fixtures ─────────────────────────────────────────────────────────────
# Each long line is > 50 words and contains "; " -- the exact shape fix_clarity's
# split targets -- so "unchanged" proves protection and "split" proves liveness.

def long_line(label):
    return (f"This is a fairly long descriptive {label} line that goes on and on and on and "
            f"on and on and on and on for quite a while just to pad it out; and then it "
            f"continues after the semicolon with more words to reach the fifty word threshold "
            f"reliably here for the test fixture padding words padding words.")


PROSE = long_line("plain-prose control")
PROSE_SPLIT_HEAD = PROSE.split("; ")[0] + ".\n"
EXAMPLE = long_line("example")
LONG_SEMI_JSON = json.dumps({"note": long_line("json value")})
LONG_SEMI_PYTHON = f'message = ("{long_line("python string")}")'
LONG_SEMI_TABLE_CELL = long_line("table cell")
LONG_SEMI_BLOCKQUOTE = "> " + long_line("blockquote")

for _l in (PROSE, EXAMPLE, LONG_SEMI_JSON, LONG_SEMI_PYTHON, LONG_SEMI_TABLE_CELL, LONG_SEMI_BLOCKQUOTE):
    assert len(_l.split()) > 50 and "; " in _l

MULTI_CONSTRUCT_FIXTURE = f"""maybe you are a domain expert. try to analyze the input.

```json
{LONG_SEMI_JSON}
```

```python
{LONG_SEMI_PYTHON}
```

| Col A | Col B |
|-------|-------|
| {LONG_SEMI_TABLE_CELL} | short |

{LONG_SEMI_BLOCKQUOTE}

<example>
{EXAMPLE}
</example>

{PROSE}
"""


def split_applied(out, line=PROSE):
    return line not in out and (line.split("; ")[0] + ".\n") in out


def hostile_split(text):
    """The ORIGINAL, unprotected fix_clarity line split, verbatim."""
    new = []
    for line in text.split('\n'):
        if len(line.split()) > 50 and ('; ' in line or ', and ' in line):
            line = re.sub(r';\s+', '.\n', line, count=1)
        new.append(line)
    return '\n'.join(new)


def gate_equal(a, b):
    return load_convergence().protected_regions_equal(a, b)


# ─── Scanner / fingerprint ───────────────────────────────────────────────────────

def test_scanner_finds_all_construct_kinds():
    mod = load_convergence()
    regions = mod.find_protected_regions(MULTI_CONSTRUCT_FIXTURE)
    kinds = [k for _s, _e, k in regions]
    assert kinds.count("fenced_code") == 2, kinds
    assert kinds.count("table") == 1, kinds
    assert kinds.count("blockquote") == 1, kinds
    assert kinds.count("example") == 1, kinds
    for (s1, e1, _), (s2, e2, _) in zip(regions, regions[1:]):
        assert e1 <= s2, "regions must be sorted and non-overlapping"
    for s, e, _k in regions:
        assert PROSE not in MULTI_CONSTRUCT_FIXTURE[s:e], "prose control leaked into a region"


def test_scanner_nesting_fence_swallows_lookalike_markers():
    mod = load_convergence()
    text = ("prose before\n\n```text\n| not | a | table |\n|---|---|---|\n"
            "> not a blockquote either\n```\n\nprose after\n")
    regions = mod.find_protected_regions(text)
    assert len(regions) == 1 and regions[0][2] == "fenced_code", regions


def test_scanner_unterminated_fence_runs_to_eof():
    mod = load_convergence()
    text = "prose\n\n```python\nprint('never closed')\n"
    regions = mod.find_protected_regions(text)
    assert len(regions) == 1 and regions[0][2] == "fenced_code"
    assert regions[0][1] == len(text)


def test_scanner_tilde_fence_and_mismatched_fence_char():
    mod = load_convergence()
    text = "```\nnot closed by tildes\n~~~\nstill inside\n```\nprose after\n"
    regions = mod.find_protected_regions(text)
    assert len(regions) == 1, regions
    assert "~~~" in text[regions[0][0]:regions[0][1]]
    assert "prose after" not in text[regions[0][0]:regions[0][1]]


def test_protected_regions_equal_basics():
    mod = load_convergence()
    a = "prose before\n\n```\nfixed\n```\n\nprose after\n"
    assert mod.protected_regions_equal(a, a)
    assert not mod.protected_regions_equal(a, a.replace("fixed", "CHANGED"))
    assert mod.protected_regions_equal(a, a.replace("\n", "\r\n")), "EOL style alone is not a change"
    assert mod.protected_regions_equal(a, a.replace("prose before", "other words")), \
        "editable prose changes must not count"


def test_tag_rename_or_attribute_change_is_detected():
    mod = load_convergence()
    a = '<context source="doc1">text</context>\n'
    assert mod.protected_regions_equal(a, a)
    assert not mod.protected_regions_equal(a, '<context source="doc1">text</ctx>\n')
    assert not mod.protected_regions_equal(a, '<context source="doc2">text</context>\n')
    quoted_gt = f'<context note="a > b; c">{PROSE}</context>\n'
    out = mod.fix_clarity(quoted_gt)
    assert '<context note="a > b; c">' in out, "a quoted '>' must not end the tag token"
    assert PROSE_SPLIT_HEAD in out


def test_allow_list_constant_documented():
    mod = load_convergence()
    allowed = mod.EDITABLE_XML_SECTIONS
    for name in ("role", "task", "instructions", "context", "constraints", "rules",
                 "guidelines", "objective", "steps", "edge_cases", "persona", "background"):
        assert name in allowed, name
    for name in ("example", "examples", "sample_json", "json", "output", "data"):
        assert name not in allowed, name


# ─── fix_clarity: allow-list behaviour ───────────────────────────────────────────

def test_fix_clarity_protects_all_constructs_but_splits_prose():
    mod = load_convergence()
    out = mod.fix_clarity(MULTI_CONSTRUCT_FIXTURE)
    assert mod.protected_regions_equal(MULTI_CONSTRUCT_FIXTURE, out)
    for frozen in (LONG_SEMI_JSON, LONG_SEMI_PYTHON, LONG_SEMI_TABLE_CELL, LONG_SEMI_BLOCKQUOTE, EXAMPLE):
        assert frozen in out, frozen[:40]
    assert split_applied(out), "the prose control must still be split"


def test_same_line_example_pair_is_frozen():
    """Paired <example>...</example> on ONE line with prose around it: the example
    content is frozen, the prose part of the same line stays editable."""
    mod = load_convergence()
    text = f"{PROSE} <example>{EXAMPLE}</example> trailing words.\n"
    out = mod.fix_clarity(text)
    assert f"<example>{EXAMPLE}</example>" in out, "inline example content changed"
    assert PROSE_SPLIT_HEAD in out, "prose before the inline example must still be split"
    assert mod.protected_regions_equal(text, out)

    only = f"Sample: <example>{EXAMPLE}</example>\n"
    out2 = mod.fix_clarity(only)
    assert out2 == only, "a line whose only '; ' is inside an inline example must be untouched"


def test_example_open_tag_sharing_a_line_is_frozen():
    mod = load_convergence()
    text = f"Here is one: <example>{EXAMPLE}\nsecond line; with more\n</example>\n\n{PROSE}\n"
    out = mod.fix_clarity(text)
    assert f"<example>{EXAMPLE}\nsecond line; with more\n</example>" in out
    assert split_applied(out)

    text2 = f"<examples>\n{EXAMPLE}</examples> and after.\n"
    out2 = mod.fix_clarity(text2)
    assert EXAMPLE in out2, "<examples> content with a close tag sharing a line must be frozen"


def test_unpaired_example_mention_freezes_nothing_after_it():
    mod = load_convergence()
    text = f"Wrap the final answer in an <example> tag as shown below.\n\n{PROSE}\n"
    out = mod.fix_clarity(text)
    assert split_applied(out), "prose after an unpaired mention must stay editable"
    same_line = f"Use an <example> tag here, {PROSE}\n"
    assert PROSE_SPLIT_HEAD in mod.fix_clarity(same_line), \
        "an unpaired mention on the same line must not freeze the line"


def test_citation_and_empty_braces_in_prose_stay_editable():
    """'[1]' and '{}' are JSON-valid literals; they must not freeze a prose line."""
    mod = load_convergence()
    text = f"As reported in [1] and with an empty {{}} object, {PROSE}\n"
    out = mod.fix_clarity(text)
    assert PROSE_SPLIT_HEAD in out, "a prose line containing [1] / {} must still be split"
    assert "[1]" in out and "{}" in out


def test_split_point_inside_quotes_or_backticks_is_skipped():
    mod = load_convergence()
    quoted = f'The user said "{PROSE}" and nothing else.\n'
    assert mod.fix_clarity(quoted) == quoted, "the only '; ' is inside a quote span"
    ticked = f"Run `{PROSE}` exactly.\n"
    assert mod.fix_clarity(ticked) == ticked, "the only '; ' is inside a backtick span"
    bracketed = f"Note ({PROSE}) done.\n"
    assert mod.fix_clarity(bracketed) == bracketed, "the only '; ' is inside a paren span"

    # A '; ' inside a span is skipped, but a later safe '; ' on the same line is used.
    mixed = 'Say "a; b" or `c; d` first, then ' + PROSE + "\n"
    out = mod.fix_clarity(mixed)
    assert '"a; b"' in out and "`c; d`" in out
    assert PROSE_SPLIT_HEAD in out, "the safe '; ' after the spans must still be split"


def test_allow_listed_vs_unknown_xml_tags():
    mod = load_convergence()
    for tag in ("instructions", "background", "Constraints", "edge_cases"):
        text = f"<{tag}>\n{PROSE}\n</{tag}>\n"
        out = mod.fix_clarity(text)
        assert split_applied(out), f"prose inside allow-listed <{tag}> must be editable"
        assert out.startswith(f"<{tag}>\n") and out.rstrip().endswith(f"</{tag}>")
    for tag in ("sample_json", "output", "data", "json", "customer"):
        text = f"<{tag}>\n{PROSE}\n</{tag}>\n"
        assert mod.fix_clarity(text) == text, f"content of unknown <{tag}> must be frozen"


def test_xml_and_json_data_examples_stay_content_equal():
    mod = load_convergence()
    xml_example = (f'<customer id="7">\n  <name>{long_line("name")}</name>\n'
                   f'  <note>short; note</note>\n</customer>')
    json_example = ("<sample_json>\n" + json.dumps({"summary": long_line("summary")}, indent=2)
                    + "\n</sample_json>")
    text = f"<instructions>\n{PROSE}\n</instructions>\n\n{xml_example}\n\n{json_example}\n"
    out = mod.fix_clarity(mod.fix_efficiency(text))
    assert xml_example in out, "XML data example changed"
    assert json_example in out, "JSON data example changed"
    json.loads(out.split("<sample_json>\n")[1].split("\n</sample_json>")[0])
    assert split_applied(out)


def test_bare_json_inline_and_multiline_are_protected():
    mod = load_convergence()
    inline_json = json.dumps({"summary": long_line("inline json")})
    text = f"Here is sample output: {inline_json} That covers the format.\n"
    out = mod.fix_clarity(text)
    assert inline_json in out
    json.loads(out[out.index('{'):out.rindex('}') + 1])

    multi = json.dumps({"a": long_line("multi a"), "b": [1, {"c": "x; y"}]}, indent=2)
    text2 = f"Output shape:\n\n{multi}\n\n{PROSE}\n"
    out2 = mod.fix_efficiency(mod.fix_clarity(text2))
    assert multi in out2, "multi-line bare JSON must be frozen"
    assert split_applied(out2)

    braces_in_strings = '{"note": "a { b } c", "list": [1, 2, {"x": "}"}]}\n'
    regions = mod.find_protected_regions(braces_in_strings)
    assert len(regions) == 1 and regions[0][2] == "json", regions


def test_invalid_json_template_frozen_prose_after_editable():
    mod = load_convergence()
    template = '{\n  "name": <string>,\n  "age": <number>; always an integer\n}'
    text = f"{template}\n\n{PROSE}\n"
    out = mod.fix_clarity(text)
    assert template in out
    assert split_applied(out)


def test_indented_code_frozen_at_top_level():
    mod = load_convergence()
    code = "    def f():\n        return 1;   \n    x = f(); y = 2"
    text = f"Intro paragraph.\n\n{code}\n\n{PROSE}   \n"
    out = mod.fix_efficiency(mod.fix_clarity(text))
    assert code in out, "indented code must be byte-identical (incl. trailing spaces)"
    assert split_applied(out)


def test_blocks_inside_allow_listed_sections_and_lazy_blockquote():
    mod = load_convergence()
    table = f"| Col | Note |\n|---|---|\n| a | {LONG_SEMI_TABLE_CELL} |"
    nested = f"<data>\n{EXAMPLE}\n</data>"
    quote = f"{LONG_SEMI_BLOCKQUOTE}\n{long_line('lazy continuation')}"
    text = f"<instructions>\n{table}\n\n{nested}\n\n{quote}\n\n{PROSE}\n</instructions>\n"
    out = mod.fix_efficiency(mod.fix_clarity(text))
    for frozen in (table, nested, quote):
        assert frozen in out, frozen[:40]
    assert split_applied(out)

    ends_in_quote = "Do the task well and never guess.\n> quoted line"
    out2 = mod.fix_completeness(ends_in_quote)
    assert "> quoted line\n" in out2 and "Output format:" in out2
    assert mod.protected_regions_equal(ends_in_quote, out2)


# ─── fix_efficiency / other fixers ───────────────────────────────────────────────

def test_fix_efficiency_protects_regions_but_cleans_prose():
    mod = load_convergence()
    text = ("please note that this outside filler is removed.   \n\n"
            "```\ncode line with trailing space   \n"
            "please note that this filler stays literal inside the fence\n\n\n\n"
            "still inside after extra blank lines\n```\n\n\n\n"
            "<data>\nplease note that data stays   \n\n\n\nsame\n</data>\n"
            'prose after "quoted trailing   \n')
    out = mod.fix_efficiency(text)
    assert mod.protected_regions_equal(text, out)
    fence = re.search(r'```\n(.*?)\n```', text, re.S).group(1)
    assert fence in out, "fence content must be byte-identical"
    assert "<data>\nplease note that data stays   \n\n\n\nsame\n</data>" in out
    assert out.startswith("this outside filler is removed.\n")
    assert '"quoted trailing   ' in out, "trailing space inside an unclosed quote span stays"
    assert "```\n\n<data>" in out, "blank-line runs in prose are still collapsed"


def test_fix_completeness_additions_skip_frozen_regions():
    mod = load_convergence()
    text = "```\nnot a role line\n```\n\nsome real prose without a role statement.\n"
    out = mod.fix_completeness(text)
    assert "```\nnot a role line\n```" in out and "domain expert" in out

    unterminated = "Some prose.\n\n```python\nprint('never closed')"
    out2 = mod.fix_completeness(unterminated)
    assert mod.protected_regions_equal(unterminated, out2), \
        "an append must not land inside an unterminated fence"
    assert "print('never closed')" in out2


def test_fix_model_fit_inserts_only_in_live_instructions():
    mod = load_convergence()
    text = ("You are using Claude. <instructions>Do the thing.</instructions>\n\n"
            "```\nthink step by step inside code stays literal\n</instructions>\n```\n")
    out = mod.fix_model_fit(text)
    assert mod.protected_regions_equal(text, out)
    assert "Do the thing.\nThink thoroughly before responding.\n</instructions>" in out
    assert "think step by step inside code stays literal\n</instructions>\n```" in out

    in_example = "Claude prompt.\n<example>\n<instructions>x</instructions>\n</example>\n"
    out2 = mod.fix_model_fit(in_example)
    assert "<example>\n<instructions>x</instructions>\n</example>" in out2
    assert out2.rstrip().endswith("Think thoroughly before responding.")


def test_fix_failure_resilience_edge_cases_handling():
    mod = load_convergence()
    unclosed = "Do the task.\n<edge_cases> are described elsewhere\n"
    out = mod.fix_failure_resilience(unclosed)
    assert "report the error clearly" in out
    live = "Do the task.\n<edge_cases>\nNone yet.\n</edge_cases>\n"
    out2 = mod.fix_failure_resilience(live)
    assert re.search(r"None yet\.\n\n?If the input is empty", out2)
    assert out2.rstrip().endswith("</edge_cases>")
    frozen = "Do the task.\n<example>\n<edge_cases>\nx\n</edge_cases>\n</example>\n"
    out3 = mod.fix_failure_resilience(frozen)
    assert "<example>\n<edge_cases>\nx\n</edge_cases>\n</example>" in out3


# ─── Performance / robustness ────────────────────────────────────────────────────

def test_deep_nesting_does_not_crash_and_prose_still_edits():
    mod = load_convergence()
    for nested in ("[" * 5000 + "]" * 5000, "{" * 5000 + "}" * 5000, "[" * 5000, "(" * 5000 + " x"):
        text = f"{nested}\n\n{PROSE}\n"
        t0 = time.time()
        out = mod.fix_clarity(text)
        assert time.time() - t0 < 5, "deep nesting must be handled quickly"
        assert nested in out
        assert split_applied(out)


def test_deep_nesting_cli_run_exits_cleanly(tmp):
    p = tmp / "deep" / "prompt.md"
    p.parent.mkdir()
    text = "[" * 5000 + "]" * 5000 + f"\n\nmaybe you are a helper.\n\n{PROSE}\n"
    p.write_bytes(text.encode("utf-8"))
    t0 = time.time()
    proc = run_cli(p, "--max", "3", timeout=120)
    assert proc.returncode in (0, 1), f"exit {proc.returncode}: {proc.stderr[-400:]}"
    assert time.time() - t0 < 60
    saved = p.read_text(encoding="utf-8")
    assert "[" * 5000 + "]" * 5000 in saved
    assert split_applied(saved)


def test_large_and_adversarial_inputs_are_fast(tmp):
    mod = load_convergence()
    chunk = (f"<instructions>\n{PROSE}\n</instructions>\n```json\n{LONG_SEMI_JSON}\n```\n\n"
             f"| a | b |\n|---|---|\n| 1; 2 | 2 |\n\n{PROSE} [1] {{}} `a; b`\n\n")
    big = chunk * (200_000 // len(chunk) + 1)
    assert len(big) >= 200_000
    adversarial = [
        big,
        "{\n\n" * 70_000,
        "<a " * 60_000,
        "`` ` ``` " * 20_000,
        '"' + "[{(" * 60_000,
        ("<x>" * 20_000) + ("</y>" * 20_000),
    ]
    for text in adversarial:
        t0 = time.time()
        out = mod.fix_efficiency(mod.fix_clarity(text))
        mod.protected_regions_equal(text, out)
        assert time.time() - t0 < 20, f"too slow on {text[:20]!r}...: {time.time() - t0:.1f}s"
    out = mod.fix_clarity(big)
    assert out.count(PROSE_SPLIT_HEAD) == 2 * big.count(chunk), "every prose sentence split"
    assert out.count(LONG_SEMI_JSON) == big.count(LONG_SEMI_JSON)

    p = tmp / "big" / "prompt.md"
    p.parent.mkdir()
    p.write_bytes(big.encode("utf-8"))
    t0 = time.time()
    proc = run_cli(p, "--max", "3", timeout=180)
    assert proc.returncode in (0, 1), f"exit {proc.returncode}: {proc.stderr[-400:]}"
    assert time.time() - t0 < 90, f"200 KB run took {time.time() - t0:.1f}s"
    saved = p.read_text(encoding="utf-8")
    assert saved.count(LONG_SEMI_JSON) == big.count(LONG_SEMI_JSON)


# ─── run(): gate and exit paths ──────────────────────────────────────────────────

def _learning_entries(prompt_dir):
    data = json.loads((prompt_dir / "learnings.json").read_text(encoding="utf-8"))
    return [e for sess in data["sessions"] for e in sess["entries"]]


def test_gate_reverts_structural_damage_even_when_score_improves(tmp):
    mod = load_convergence()
    d = tmp / "gate"
    d.mkdir()
    p = d / "prompt.md"
    p.write_text(f"maybe you are a domain expert.\n\nSample: <example>{EXAMPLE}</example>\n",
                 encoding="utf-8")
    mod.FIXERS = dict(mod.FIXERS)
    mod.FIXERS["Clarity"] = hostile_split
    real = mod.score_prompt

    def biased(t):
        s = dict(real(t))
        if EXAMPLE not in t:
            s["Clarity"] = 10.0
            s["overall"] = round(sum(s[a] for a in AXES) / len(AXES), 1)
        return s
    mod.score_prompt = biased
    run_quiet(mod, str(p), max_iterations=3)
    assert f"<example>{EXAMPLE}</example>" in p.read_text(encoding="utf-8")
    reverts = [e for e in _learning_entries(d)
               if e.get("result") == "reverted" and "structural gate" in e.get("outcome", "")]
    assert reverts, "a structural revert must be recorded distinguishably"


def test_safe_text_for_save_backstop():
    mod = load_convergence()
    original = "prose\n\n```\nfixed\n```\n"
    safe, ok = mod._safe_text_for_save(original, "prose\n\n```\nCHANGED\n```\n")
    assert ok is False and safe == original
    clean = "different prose\n\n```\nfixed\n```\n"
    safe2, ok2 = mod._safe_text_for_save(original, clean)
    assert ok2 is True and safe2 == clean


def _scripted(mod, overall_seq, axes):
    idx = {"i": 0}

    def fake(_t):
        i = min(idx["i"], len(overall_seq) - 1)
        idx["i"] += 1
        d = dict(axes[min(i, len(axes) - 1)] if isinstance(axes, list) else axes)
        d["overall"] = overall_seq[i]
        return d
    mod.score_prompt = fake
    mod.run_assertions = lambda t: list(BASE_ASSERTIONS_ALL_PASS)


LOW = {"Clarity": 8.0, "Completeness": 8.0, "Efficiency": 9.5, "Model Fit": 9.5, "Failure Resilience": 9.5}
HIGH = {a: 9.5 for a in AXES}
EXIT_FIXTURE = (f"maybe you are a helper. try to do the task if possible.\n\n"
                f"Sample: <example>{EXAMPLE}</example>\n\n{PROSE}\n")

# (name, scripted top/post overall sequence, axes, max_iterations)
EXIT_PATHS = [
    ("DEPLOY", [7.0, 7.5, 9.5], [LOW, LOW, HIGH], 5),
    ("PLATEAU", [7.0, 7.0, 8.0, 8.0, 8.0, 8.0, 8.0], LOW, 20),
    ("MAX", [6.0, 6.0, 7.0, 7.0, 8.0, 8.0], LOW, 3),
]


def test_every_exit_path_keeps_frozen_content_and_edits_prose(tmp):
    for name, seq, axes, max_it in EXIT_PATHS:
        mod = load_convergence()
        d = tmp / f"exit_ok_{name}"
        d.mkdir()
        p = d / "prompt.md"
        p.write_text(EXIT_FIXTURE, encoding="utf-8")
        _scripted(mod, seq, axes)
        scores = run_quiet(mod, str(p), max_iterations=max_it)
        saved = p.read_text(encoding="utf-8")
        assert f"<example>{EXAMPLE}</example>" in saved, name
        assert split_applied(saved), f"{name}: prose edit should persist"
        assert scores.get("_deploy") is (name == "DEPLOY"), name


def test_every_exit_path_backstop_keeps_original_and_forces_hold(tmp):
    """Disable only the per-iteration gate and inject the old unprotected split: the
    exit-path backstop must keep the ORIGINAL bytes and force HOLD on every exit."""
    for name, seq, axes, max_it in EXIT_PATHS:
        mod = load_convergence()
        d = tmp / f"exit_trip_{name}"
        d.mkdir()
        p = d / "prompt.md"
        raw = EXIT_FIXTURE.replace("\n", "\r\n").encode("utf-8")
        p.write_bytes(raw)
        mod._candidate_is_structurally_safe = lambda t, fp: True
        mod.FIXERS = {a: hostile_split for a in AXES}
        _scripted(mod, seq, axes)
        scores = run_quiet(mod, str(p), max_iterations=max_it)
        assert p.read_bytes() == raw, f"{name}: original bytes must be kept"
        assert scores.get("_deploy") is False, f"{name}: must be HOLD"
        trips = [e for e in _learning_entries(d) if "tripped at save time" in e.get("outcome", "")]
        assert trips, f"{name}: backstop trip must be recorded in learnings"


def test_written_file_is_rechecked(tmp):
    """A writer that corrupts the file on disk must be caught by the post-write check."""
    mod = load_convergence()
    d = tmp / "written"
    d.mkdir()
    p = d / "prompt.md"
    p.write_text(EXIT_FIXTURE, encoding="utf-8")
    raw = p.read_bytes()
    real_save = mod._save

    def corrupting_save(path, text, **kw):
        real_save(path, hostile_split(text), **kw)
    mod._save = corrupting_save
    _scripted(mod, *EXIT_PATHS[0][1:3])
    scores = run_quiet(mod, str(p), max_iterations=5)
    assert p.read_bytes() == raw
    assert scores.get("_deploy") is False


def test_deploy_trip_cli_contract_exit_1_hold(tmp):
    """WIX-EVAL-004 + WIX-CONV-001: a DEPLOY-exit trip prints HOLD, exits 1, and the
    VERDICT_JSON / --json-out payloads agree."""
    mod = load_convergence()
    d = tmp / "cli_trip"
    d.mkdir()
    p = d / "prompt.md"
    p.write_text(EXIT_FIXTURE, encoding="utf-8")
    raw = p.read_bytes()
    jout = d / "verdict.json"
    mod._candidate_is_structurally_safe = lambda t, fp: True
    mod.FIXERS = {a: hostile_split for a in AXES}
    _scripted(mod, *EXIT_PATHS[0][1:3])
    code, out = call_main(mod, [str(p), "--max", "5", "--json", "--json-out", str(jout)])
    assert code == 1, code
    assert "VERDICT: HOLD" in out and "VERDICT: DEPLOY" not in out
    lines = [l for l in out.splitlines() if l.startswith("VERDICT_JSON ")]
    assert len(lines) == 1
    payload = json.loads(lines[0][len("VERDICT_JSON "):])
    assert payload["verdict"] == "HOLD" and payload["exit_code"] == 1 and payload["deploy"] is False
    assert json.loads(jout.read_text(encoding="utf-8"))["verdict"] == "HOLD"
    assert p.read_bytes() == raw


def test_crash_path_leaves_file_untouched(tmp):
    d = tmp / "crash"
    d.mkdir()
    p = d / "prompt.md"
    p.write_text(EXIT_FIXTURE, encoding="utf-8")
    raw = p.read_bytes()
    mod = load_convergence()
    calls = {"n": 0}
    real = mod.score_prompt

    def boom(t):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("scorer exploded")
        return real(t)
    mod.score_prompt = boom
    code, out = call_main(mod, [str(p), "--json"])
    assert code == 3, code
    assert p.read_bytes() == raw
    assert not list(d.glob("*.convergence-tmp"))


def test_real_cli_runs_preserve_frozen_content(tmp):
    """Unpatched subprocess runs (real scorer) on mixed fixtures: exit 0/1 only, every
    frozen construct content-equal on disk, prose edits applied, one machine verdict."""
    fixtures = {
        "inline_example": f"maybe you are an assistant.\n\n{PROSE} <example>{EXAMPLE}</example> end.\n",
        "xml_data": (f"<role>You are an analyst.</role>\n<instructions>\nmaybe {PROSE}\n</instructions>\n"
                     f"<output>\n{EXAMPLE}\n</output>\n"),
        "json_block": ("maybe respond in JSON:\n\n" + json.dumps({"a": long_line("x")}, indent=2)
                       + f"\n\n{PROSE}\n"),
        "multi": MULTI_CONSTRUCT_FIXTURE,
    }
    for name, text in fixtures.items():
        p = tmp / f"cli_{name}" / "prompt.md"
        p.parent.mkdir()
        p.write_bytes(text.encode("utf-8"))
        proc = run_cli(p, "--max", "6", "--json")
        assert proc.returncode in (0, 1), f"{name}: exit {proc.returncode}"
        saved = p.read_text(encoding="utf-8")
        assert gate_equal(text, saved), f"{name}: frozen content changed on disk"
        assert split_applied(saved), f"{name}: prose split missing"
        verdicts = [l for l in proc.stdout.splitlines() if l.startswith("VERDICT_JSON ")]
        assert len(verdicts) == 1
        assert json.loads(verdicts[0][len("VERDICT_JSON "):])["exit_code"] == proc.returncode


# ─── Line endings / BOM ──────────────────────────────────────────────────────────

def _eol_run(tmp, name, raw_in):
    p = tmp / name / "prompt.md"
    p.parent.mkdir()
    p.write_bytes(raw_in)
    run_cli(p, "--max", "5")
    return p.read_bytes()


def test_lf_and_crlf_inputs_preserved(tmp):
    base = f"maybe you are a helper.\n\n<example>\n{EXAMPLE}\n</example>\n\n{PROSE}\n"
    out = _eol_run(tmp, "lf", base.encode("utf-8"))
    assert b"\r" not in out
    out = _eol_run(tmp, "crlf", base.replace("\n", "\r\n").encode("utf-8"))
    assert out.replace(b"\r\n", b"").count(b"\n") == 0 and b"\r\n" in out
    assert out.decode("utf-8").replace("\r\n", "\n").count(EXAMPLE) == 1


def test_mixed_line_endings_preserved_per_line(tmp):
    parts = [("maybe you are a helper.", "\r\n"), ("", "\n"), ("```json", "\r\n"),
             (LONG_SEMI_JSON, "\n"), ("```", "\r\n"), ("", "\n"), (PROSE, "\r\n")]
    out = _eol_run(tmp, "mixed", "".join(l + t for l, t in parts).encode("utf-8"))
    assert b"```json\r\n" in out and (LONG_SEMI_JSON + "\n").encode() in out and b"```\r\n" in out
    assert out.replace(b"\r\n", b"").count(b"\n") > 0


def test_bom_crlf_and_bom_mixed_preserved(tmp):
    text = f"maybe you are a helper.\n\n<sample_json>\n{LONG_SEMI_JSON}\n</sample_json>\n\n{PROSE}\n"
    out = _eol_run(tmp, "bom_crlf", b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))
    assert out.startswith(b"\xef\xbb\xbf") and not out[3:].startswith(b"\xef\xbb\xbf")
    assert out.replace(b"\r\n", b"").count(b"\n") == 0
    body = out[3:].decode("utf-8").replace("\r\n", "\n")
    assert LONG_SEMI_JSON in body and split_applied(body)

    mixed = ("maybe you are a helper.\r\n\n<sample_json>\r\n" + LONG_SEMI_JSON
             + "\n</sample_json>\r\n\n" + PROSE + "\n")
    out2 = _eol_run(tmp, "bom_mixed", b"\xef\xbb\xbf" + mixed.encode("utf-8"))
    assert out2.startswith(b"\xef\xbb\xbf")
    assert b"<sample_json>\r\n" in out2
    assert (LONG_SEMI_JSON + "\n</sample_json>\r\n").encode() in out2


def test_unicode_line_separator_stays_inside_its_line(tmp):
    text = f"maybe you are a helper. still the same line\x0c\n\n{PROSE}\n"
    out = _eol_run(tmp, "u2028", text.encode("utf-8"))
    assert " still the same line\x0c\n".encode("utf-8") in out


# ─── output-test.py try_offline_fix ──────────────────────────────────────────────

class _FakeSelfEval:
    AXES = ["Clarity"]
    SCORERS = [staticmethod(lambda t: 1.0)]


def _offline(conv_mod, text):
    ot = load_output_test()
    real = ot._try_import
    ot._try_import = lambda f, m: conv_mod if f == "convergence.py" else real(f, m)
    ot._self_eval = _FakeSelfEval()
    return ot.try_offline_fix(text, {}, {"test_results": [{"passed": False, "name": "x"}]})


def test_try_offline_fix_real_fixer_keeps_frozen_content():
    conv = load_convergence()
    text = f"{PROSE} <example>{EXAMPLE}</example>\n<sample_json>\n{LONG_SEMI_JSON}\n</sample_json>\n"
    new, applied, _d = _offline(conv, text)
    assert applied is True
    assert f"<example>{EXAMPLE}</example>" in new and LONG_SEMI_JSON in new
    assert PROSE_SPLIT_HEAD in new


def test_try_offline_fix_refuses_damaging_fixer():
    for text in (f"maybe.\n\n```json\n{LONG_SEMI_JSON}\n```\n",
                 f"Sample: <example>{EXAMPLE}</example>\n",
                 f"Here: {json.dumps({'s': long_line('bare')})} ok\n"):
        conv = load_convergence()
        conv.FIXERS = dict(conv.FIXERS)
        conv.FIXERS["Clarity"] = hostile_split
        new, applied, _d = _offline(conv, text)
        assert new == text and applied is False, text[:40]


def test_try_offline_fix_fails_closed_without_gate():
    conv = load_convergence()
    stub = types.SimpleNamespace(FIXERS=dict(conv.FIXERS))  # a convergence without the gate
    new, applied, _d = _offline(stub, "maybe you should try to write something possibly helpful.\n")
    assert applied is False


def test_try_offline_fix_still_applies_legitimate_fix():
    conv = load_convergence()
    new, applied, _d = _offline(conv, "maybe you should try to write something possibly helpful.\n")
    assert applied is True and "maybe" not in new.lower()


# ─── harness ─────────────────────────────────────────────────────────────────────

def main():
    global REPO_ROOT
    REPO_ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(".").resolve()
    only = set(sys.argv[2:])
    tests = [(n, f) for n, f in globals().items()
             if n.startswith("test_") and callable(f) and (not only or n in only)]
    failures = []
    with tempfile.TemporaryDirectory() as td:
        for name, fn in tests:
            try:
                if fn.__code__.co_argcount:
                    sub = Path(td) / name
                    sub.mkdir()
                    fn(sub)
                else:
                    fn()
                print(f"  PASS  {name}")
            except Exception:
                failures.append(name)
                tb = traceback.format_exc().splitlines(True)[-3:]
                print(f"  FAIL  {name}\n" + "".join("        " + l for l in tb))
    if failures:
        print(f"test_structural_protection: {len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print(f"test_structural_protection: OK ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
