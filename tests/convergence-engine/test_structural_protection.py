#!/usr/bin/env python3
"""
WIX-CONV-001 — convergence.py's fixers (fix_clarity's '; ' -> '.\\n' split on lines over
50 words, fix_efficiency's blank-line/whitespace rewrite, etc.) must never modify content
inside a "protected region" -- a fenced code block (any language), a Markdown/GFM table,
a blockquote, or an <example>...</example> block -- and the accept/revert gate must revert
any candidate whose protected regions differ from the previous iteration's text, regardless
of whether the heuristic score improved. The same guarantee must hold for every exit path
(DEPLOY, plateau, max-iterations) and for output-test.py's try_offline_fix, which applies
the same fixers with no gate of its own. Line endings and encoding of the input file must
be preserved on save (the pre-fix bug used to rewrite the whole file to CRLF on Windows,
unconditionally, via _save()'s text-mode open()).

These are the implementer's own fixtures (not the investigator's or the independent
verifier's held-out ones) covering every protected construct named in the finding, every
exit path, try_offline_fix, CRLF and LF inputs, and a plain-prose control that must still
be editable.

Usage: python test_structural_protection.py <REPO_ROOT>   (exit 0 = pass)
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

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


def load_convergence(repo_root: Path):
    path = repo_root / "shared" / "scripts" / "convergence.py"
    spec = importlib.util.spec_from_file_location("convergence_uut", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_output_test(repo_root: Path):
    path = repo_root / "shared" / "scripts" / "output-test.py"
    spec = importlib.util.spec_from_file_location("output_test_uut", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── Shared fixtures ─────────────────────────────────────────────────────────────
# Each protected construct below carries exactly one physical line of more than 50
# words containing "; " -- the exact shape fix_clarity's split targets -- plus a
# closing prose-control paragraph with the same shape OUTSIDE any construct, so a
# single fixture proves both "protected content never changes" and "legitimate
# prose edits elsewhere still work" (requirement 6).

LONG_SEMI_JSON = (
    '{"note": "This is a fairly long descriptive sentence about the process that goes '
    'on and on and on and on and on and on for quite a while just to pad it out; and '
    'then it continues after the semicolon with more words to reach the fifty word '
    'threshold reliably here for the test fixture body content padding words."}'
)

LONG_SEMI_PYTHON = (
    'message = ("This is a fairly long descriptive sentence about the process that '
    'goes on and on and on and on and on and on for quite a while to pad it out; and '
    'then it continues after the semicolon with more words to reach the fifty word '
    'threshold reliably here for the test fixture body content padding.")'
)

LONG_SEMI_TABLE_CELL = (
    'This is a fairly long descriptive table cell that goes on and on and on and on '
    'and on and on and on for quite a while just to pad it out; and then it continues '
    'after the semicolon with more words to reach the fifty word threshold reliably '
    'here for the test fixture padding words padding.'
)

LONG_SEMI_BLOCKQUOTE = (
    '> This is a fairly long descriptive blockquote line that goes on and on and on '
    'and on and on and on and on for quite a while just to pad it out; and then it '
    'continues after the semicolon with more words to reach the fifty word threshold '
    'reliably here for the test fixture padding words padding words.'
)

LONG_SEMI_EXAMPLE = (
    'This is a fairly long descriptive example line that goes on and on and on and on '
    'and on and on and on for quite a while just to pad it out; and then it continues '
    'after the semicolon with more words to reach the fifty word threshold reliably '
    'here for the test fixture padding words padding words padding.'
)

LONG_SEMI_PROSE_CONTROL = (
    'This is a fairly long descriptive plain-prose control sentence that goes on and '
    'on and on and on and on and on and on for quite a while just to pad it out; and '
    'then it continues after the semicolon with more words to reach the fifty word '
    'threshold reliably here for the test fixture padding words padding words.'
)

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
{LONG_SEMI_EXAMPLE}
</example>

{LONG_SEMI_PROSE_CONTROL}
"""


def assert_word_count_over_50(label, line):
    assert len(line.split()) > 50, f"{label} fixture line must be >50 words to trigger fix_clarity's split, got {len(line.split())}"


for _label, _line in [
    ("json", LONG_SEMI_JSON), ("python", LONG_SEMI_PYTHON),
    ("table", LONG_SEMI_TABLE_CELL), ("blockquote", LONG_SEMI_BLOCKQUOTE),
    ("example", LONG_SEMI_EXAMPLE), ("prose", LONG_SEMI_PROSE_CONTROL),
]:
    assert_word_count_over_50(_label, _line)


# ─── Scanner-level tests ─────────────────────────────────────────────────────────

def test_scanner_finds_all_five_construct_kinds(mod):
    regions = mod.find_protected_regions(MULTI_CONSTRUCT_FIXTURE)
    kinds = [k for _s, _e, k in regions]
    assert kinds.count("fenced_code") == 2, kinds  # json + python fences
    assert kinds.count("table") == 1, kinds
    assert kinds.count("blockquote") == 1, kinds
    assert kinds.count("example") == 1, kinds
    # Regions must be sorted, non-overlapping, and in document order.
    for (s1, e1, _), (s2, e2, _) in zip(regions, regions[1:]):
        assert e1 <= s2, f"overlapping/out-of-order regions: ({s1},{e1}) then ({s2},{e2})"
    # The prose control paragraph must NOT be captured as a protected region.
    for s, e, _k in regions:
        assert LONG_SEMI_PROSE_CONTROL not in MULTI_CONSTRUCT_FIXTURE[s:e], \
            "prose control leaked into a protected region"


def test_scanner_nesting_fence_swallows_lookalike_markers(mod):
    """A fenced code block containing lines that merely LOOK like a table divider or
    a blockquote marker must not spawn separate, overlapping regions -- the fence
    takes priority and swallows everything until its own close."""
    text = (
        "prose before\n\n"
        "```text\n"
        "| not | a | table |\n"
        "|---|---|---|\n"
        "> not a blockquote either\n"
        "```\n\n"
        "prose after\n"
    )
    regions = mod.find_protected_regions(text)
    assert len(regions) == 1, f"expected exactly one region (the fence), got {regions}"
    assert regions[0][2] == "fenced_code"
    content = text[regions[0][0]:regions[0][1]]
    assert "| not | a | table |" in content and "> not a blockquote either" in content


def test_scanner_unterminated_fence_runs_to_eof(mod):
    text = "prose\n\n```python\nprint('never closed')\n"
    regions = mod.find_protected_regions(text)
    assert len(regions) == 1
    s, e, kind = regions[0]
    assert kind == "fenced_code"
    assert e == len(text), "an unterminated fence must run to end of document, not vanish"


def test_scanner_tilde_fence_and_mismatched_fence_char(mod):
    text = "```\nnot closed by tildes\n~~~\nstill inside\n```\nprose after\n"
    regions = mod.find_protected_regions(text)
    assert len(regions) == 1, regions
    assert "~~~" in text[regions[0][0]:regions[0][1]]
    assert "prose after" not in text[regions[0][0]:regions[0][1]]


def test_scanner_example_same_line_open_close(mod):
    text = "prose <example>inline example; with a semicolon</example> more prose\n"
    regions = mod.find_protected_regions(text)
    assert len(regions) == 1 and regions[0][2] == "example"
    assert text[regions[0][0]:regions[0][1]] == "<example>inline example; with a semicolon</example>"


def test_protected_regions_equal_detects_content_change(mod):
    a = "```\nfixed\n```\n"
    b = "```\nCHANGED\n```\n"
    assert mod.protected_regions_equal(a, a) is True
    assert mod.protected_regions_equal(a, b) is False


def test_protected_regions_equal_ignores_line_ending_style(mod):
    a = "```\nline one\nline two\n```\n"
    b = a.replace("\n", "\r\n")
    assert mod.protected_regions_equal(a, b) is True, \
        "CRLF vs LF alone must not count as a structural difference"


def test_protected_regions_equal_allows_unrelated_prose_changes(mod):
    a = "prose before\n\n```\nfixed\n```\n\nprose after\n"
    b = "totally different prose before\n\n```\nfixed\n```\n\nand different prose after too\n"
    assert mod.protected_regions_equal(a, b) is True


# ─── Fixer-level tests (requirement 1 + 6) ────────────────────────────────────────

def test_fix_clarity_protects_all_constructs_but_splits_prose(mod):
    out = mod.fix_clarity(MULTI_CONSTRUCT_FIXTURE)
    assert mod.protected_regions_equal(MULTI_CONSTRUCT_FIXTURE, out), \
        "fix_clarity must not change any protected region"
    # The JSON fence must still be valid, byte-identical JSON.
    m = re.search(r'```json\n(.*?)\n```', out, re.S)
    assert json.loads(m.group(1)) == json.loads(LONG_SEMI_JSON)
    assert m.group(1) == LONG_SEMI_JSON
    # The prose control sentence must have been split (legitimate edit still works).
    assert LONG_SEMI_PROSE_CONTROL not in out, "prose control should have been split"
    assert LONG_SEMI_PROSE_CONTROL.split("; ")[0] + ".\n" in out


def test_fix_efficiency_protects_regions_but_cleans_prose(mod):
    text = (
        "please note that this outside filler is removed.   \n\n"
        "```\n"
        "code line with trailing space   \n"
        "please note that this filler stays literal inside the fence\n"
        "\n\n\n"
        "still inside after extra blank lines\n"
        "```\n\n\n\n"
        "prose after with trailing space   \n"
    )
    out = mod.fix_efficiency(text)
    assert mod.protected_regions_equal(text, out), "fix_efficiency must not touch fence content"
    fence = re.search(r'```\n(.*?)\n```', text, re.S).group(1)
    fence_out = re.search(r'```\n(.*?)\n```', out, re.S).group(1)
    assert fence == fence_out, "fenced content (including trailing whitespace/blank lines) must be byte-identical"
    assert "this outside filler is removed." in out and "please note that" not in out.split("```")[0]
    assert "prose after with trailing space\n" in out, "trailing whitespace OUTSIDE a fence must still be stripped"


def test_fix_completeness_insertion_skips_protected_first_line(mod):
    """If the first substantive line of the document is itself a fenced block, the
    role-sentence insertion must not land inside it."""
    text = "```\nnot a role line\n```\n\nsome real prose without a role statement.\n"
    out = mod.fix_completeness(text)
    fence_before = re.search(r'```\n(.*?)\n```', text, re.S).group(1)
    fence_after = re.search(r'```\n(.*?)\n```', out, re.S).group(1)
    assert fence_before == fence_after
    assert "domain expert" in out


def test_fix_model_fit_protects_regions(mod):
    text = (
        "You are using Claude for this task. <instructions>Do the thing.</instructions>\n\n"
        "```\nthink step by step inside code stays literal\n```\n"
    )
    out = mod.fix_model_fit(text)
    assert mod.protected_regions_equal(text, out)
    fence = re.search(r'```\n(.*?)\n```', out, re.S).group(1)
    assert fence == "think step by step inside code stays literal"


# ─── run() integration: the accept/revert gate (requirement 2) ───────────────────

def test_gate_reverts_structural_damage_even_when_heuristic_score_improves(mod, tmp_path):
    """Directly reproduces the finding's mechanism: a fixer that damages a protected
    region, paired with a scorer that rates the damaged candidate HIGHER than the
    pre-fix text (i.e. the OLD score-only gate at convergence.py:732 would have kept
    it). The new structural gate must revert it anyway."""
    prompt_dir = tmp_path / "gate_test"
    prompt_dir.mkdir()
    prompt_path = prompt_dir / "prompt.md"
    fixture = (
        "maybe you are a domain expert. try to analyze the input.\n\n"
        f"```json\n{LONG_SEMI_JSON}\n```\n"
    )
    prompt_path.write_text(fixture, encoding="utf-8")

    marker = "for quite a while just to pad it out; and then it continues"
    assert marker in fixture

    # A hostile Clarity "fixer" that reproduces the ORIGINAL, unprotected line-split
    # bug verbatim -- no awareness of protected regions at all.
    def hostile_clarity(text):
        lines = text.split('\n')
        new = []
        for line in lines:
            if len(line.split()) > 50 and ('; ' in line or ', and ' in line):
                line = re.sub(r';\s+', '.\n', line, count=1)
            new.append(line)
        return '\n'.join(new)

    mod.FIXERS = dict(mod.FIXERS)
    mod.FIXERS["Clarity"] = hostile_clarity

    real_score_prompt = mod.score_prompt

    def biased_score_prompt(t):
        s = real_score_prompt(t)
        if marker not in t:
            # The hostile split happened: rate it as a clear IMPROVEMENT, exactly
            # what the finding says the real self-eval scorer does in practice.
            s = dict(s)
            s["Clarity"] = 10.0
            s["overall"] = round(sum(s[a] for a in AXES) / len(AXES), 1)
        return s

    mod.score_prompt = biased_score_prompt

    scores = mod.run(str(prompt_path), max_iterations=3, verbose=False, want_json=False, json_out=None)

    saved = prompt_path.read_text(encoding="utf-8")
    assert marker in saved, "the damaging split must NOT have been persisted to disk"
    fence = re.search(r'```json\n(.*?)\n```', saved, re.S).group(1)
    assert fence == LONG_SEMI_JSON, "the JSON fence must be byte-identical to the input"
    json.loads(fence)  # must still parse

    learnings_path = prompt_dir / "learnings.json"
    learnings = json.loads(learnings_path.read_text(encoding="utf-8"))
    all_entries = [e for sess in learnings["sessions"] for e in sess["entries"]]
    structural_reverts = [e for e in all_entries
                           if e.get("result") == "reverted" and "structural" in e.get("outcome", "").lower()]
    assert structural_reverts, f"expected a structural-gate revert recorded in learnings: {all_entries}"


def test_safe_text_for_save_backstop(mod):
    """Direct unit test of the defense-in-depth backstop used at every save site:
    if the candidate about to be written differs structurally from the original,
    it must never be returned -- the original is returned instead."""
    original = "prose\n\n```\nfixed\n```\n"
    damaged = "prose\n\n```\nCHANGED\n```\n"
    safe, ok = mod._safe_text_for_save(original, damaged)
    assert ok is False
    assert safe == original

    clean = "different prose\n\n```\nfixed\n```\n"
    safe2, ok2 = mod._safe_text_for_save(original, clean)
    assert ok2 is True
    assert safe2 == clean


# ─── run() integration: every exit path (requirement 3) ──────────────────────────

def test_deploy_exit_preserves_protected_regions(mod, tmp_path):
    """Forces the DEPLOY exit on iteration 2, after a REAL fixer pass ran on
    iteration 1 against real fixture text containing a protected fenced block."""
    prompt_dir = tmp_path / "deploy_test"
    prompt_dir.mkdir()
    prompt_path = prompt_dir / "prompt.md"
    fixture = (
        "maybe you are a helper. try to do the task if possible.\n\n"
        f"```json\n{LONG_SEMI_JSON}\n```\n"
    )
    prompt_path.write_text(fixture, encoding="utf-8")

    # call0 = top-of-loop, iteration 1: two axes below 9.0 so real fixers actually run.
    # call1 = post-fix score for iteration 1 (must not trigger a score-based revert).
    # call2 = top-of-loop, iteration 2: uniform axes (sigma == 0, comfortably under
    # any dynamic floor) so DEPLOY triggers deterministically regardless of the
    # sigma floor's exact value for this fixture's length.
    score_sequence = [
        {"Clarity": 8.0, "Completeness": 8.0, "Efficiency": 9.5, "Model Fit": 9.5,
         "Failure Resilience": 9.5, "overall": 7.0},
        {"Clarity": 8.0, "Completeness": 8.0, "Efficiency": 9.5, "Model Fit": 9.5,
         "Failure Resilience": 9.5, "overall": 7.5},
        {"Clarity": 9.5, "Completeness": 9.5, "Efficiency": 9.5, "Model Fit": 9.5,
         "Failure Resilience": 9.5, "overall": 9.5},
    ]
    call_index = {"i": 0}

    def scripted_score_prompt(t):
        i = min(call_index["i"], len(score_sequence) - 1)
        call_index["i"] += 1
        return dict(score_sequence[i])

    mod.score_prompt = scripted_score_prompt
    mod.run_assertions = lambda t: list(BASE_ASSERTIONS_ALL_PASS)

    scores = mod.run(str(prompt_path), max_iterations=5, verbose=False, want_json=False, json_out=None)
    assert scores.get("_deploy") is True, "this scenario must reach the DEPLOY exit"

    saved = prompt_path.read_text(encoding="utf-8")
    fence = re.search(r'```json\n(.*?)\n```', saved, re.S).group(1)
    assert fence == LONG_SEMI_JSON, "protected fence must survive the DEPLOY save byte-identical"
    json.loads(fence)


def test_max_iterations_exit_preserves_protected_regions(repo_root, tmp_path):
    """Real, unpatched subprocess run capped at --max 2 so it exhausts iterations
    without deploying or plateauing (real fixer(s) run at least once)."""
    prompt_dir = tmp_path / "max_iter_test"
    prompt_dir.mkdir()
    prompt_path = prompt_dir / "prompt.md"
    fixture = (
        "maybe you are a helper. try to do the task if possible.\n\n"
        f"```json\n{LONG_SEMI_JSON}\n```\n\n"
        f"{LONG_SEMI_BLOCKQUOTE}\n"
    )
    prompt_path.write_text(fixture, encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(repo_root / "shared" / "scripts" / "convergence.py"),
         str(prompt_path), "--max", "2"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    assert "Max iterations (2) reached" in proc.stdout, proc.stdout[-600:]

    saved = prompt_path.read_text(encoding="utf-8")
    fence = re.search(r'```json\n(.*?)\n```', saved, re.S).group(1)
    assert fence == LONG_SEMI_JSON
    json.loads(fence)
    assert LONG_SEMI_BLOCKQUOTE in saved or LONG_SEMI_BLOCKQUOTE.replace("\n", "\r\n") in saved


def test_plateau_exit_preserves_protected_regions(mod, tmp_path):
    """Scripts a deterministic plateau (three equal top-of-iteration overall scores)
    on iteration 4, after a real fixer pass changed best_text on iteration 2."""
    prompt_dir = tmp_path / "plateau_test"
    prompt_dir.mkdir()
    prompt_path = prompt_dir / "prompt.md"
    fixture = (
        "maybe you are a helper. try to do the task if possible.\n\n"
        f"```json\n{LONG_SEMI_JSON}\n```\n"
    )
    prompt_path.write_text(fixture, encoding="utf-8")

    axis_fixed = {"Clarity": 8.0, "Completeness": 8.0, "Efficiency": 9.5,
                  "Model Fit": 9.5, "Failure Resilience": 9.5}
    # top1, post1, top2(best updates), post2, top3, post3, top4(plateau: [8,8,8])
    overall_sequence = [7.0, 7.0, 8.0, 8.0, 8.0, 8.0, 8.0]
    call_index = {"i": 0}

    def scripted_score_prompt(t):
        i = min(call_index["i"], len(overall_sequence) - 1)
        call_index["i"] += 1
        d = dict(axis_fixed)
        d["overall"] = overall_sequence[i]
        return d

    mod.score_prompt = scripted_score_prompt
    mod.run_assertions = lambda t: list(BASE_ASSERTIONS_ALL_PASS)

    scores = mod.run(str(prompt_path), max_iterations=20, verbose=False, want_json=False, json_out=None)
    assert scores.get("_deploy") is False

    saved = prompt_path.read_text(encoding="utf-8")
    fence = re.search(r'```json\n(.*?)\n```', saved, re.S).group(1)
    assert fence == LONG_SEMI_JSON, "protected fence must survive the PLATEAU save byte-identical"
    json.loads(fence)


# ─── Line ending / encoding preservation (requirement 5) ─────────────────────────

def test_crlf_input_preserved_end_to_end(repo_root, tmp_path):
    fixture = f"maybe you are a helper.\n\n```json\n{LONG_SEMI_JSON}\n```\n"
    crlf = fixture.replace("\n", "\r\n")
    prompt_path = tmp_path / "crlf" / "prompt.md"
    prompt_path.parent.mkdir()
    prompt_path.write_bytes(crlf.encode("utf-8"))

    proc = subprocess.run(
        [sys.executable, str(repo_root / "shared" / "scripts" / "convergence.py"),
         str(prompt_path), "--max", "5"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    raw = prompt_path.read_bytes()
    assert b"\r\n" in raw, "CRLF input must stay CRLF"
    bare_lf = raw.replace(b"\r\n", b"").count(b"\n")
    assert bare_lf == 0, f"found {bare_lf} bare LF byte(s) in a CRLF-input file"
    m = re.search(rb'```json\r?\n(.*?)\r?\n```', raw, re.S)
    assert json.loads(m.group(1).decode("utf-8")) == json.loads(LONG_SEMI_JSON)


def test_lf_input_preserved_end_to_end(repo_root, tmp_path):
    fixture = f"maybe you are a helper.\n\n```json\n{LONG_SEMI_JSON}\n```\n"
    prompt_path = tmp_path / "lf" / "prompt.md"
    prompt_path.parent.mkdir()
    prompt_path.write_bytes(fixture.encode("utf-8"))

    subprocess.run(
        [sys.executable, str(repo_root / "shared" / "scripts" / "convergence.py"),
         str(prompt_path), "--max", "5"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    raw = prompt_path.read_bytes()
    assert b"\r" not in raw, "LF-only input must never gain CRLF (this is the OBS-05 regression)"


# ─── output-test.py try_offline_fix (requirement 4) ───────────────────────────────

def test_try_offline_fix_refuses_structural_damage(conv_mod, ot_mod):
    text = f"maybe you are a helper.\n\n```json\n{LONG_SEMI_JSON}\n```\n"

    def hostile_fixer(t):
        lines = t.split('\n')
        new = []
        for line in lines:
            if len(line.split()) > 50 and ('; ' in line or ', and ' in line):
                line = re.sub(r';\s+', '.\n', line, count=1)
            new.append(line)
        return '\n'.join(new)

    conv_mod.FIXERS = dict(conv_mod.FIXERS)
    conv_mod.FIXERS["Clarity"] = hostile_fixer

    class FakeSelfEval:
        AXES = ["Clarity"]
        SCORERS = [staticmethod(lambda t: 1.0)]

    real_try_import = ot_mod._try_import

    def fake_try_import(filename, module_name):
        if filename == "convergence.py":
            return conv_mod
        return real_try_import(filename, module_name)

    ot_mod._try_import = fake_try_import
    ot_mod._self_eval = FakeSelfEval()

    details = {"test_results": [{"passed": False, "name": "x"}]}
    new_text, applied, desc = ot_mod.try_offline_fix(text, {}, details)

    assert new_text == text, "a structurally damaging offline fix must never be returned"
    assert applied is False, f"applied must be False, got desc={desc!r}"


def test_try_offline_fix_still_applies_legitimate_fix(conv_mod, ot_mod):
    text = "maybe you should try to write something possibly helpful.\n"

    class FakeSelfEval:
        AXES = ["Clarity"]
        SCORERS = [staticmethod(lambda t: 1.0)]

    real_try_import = ot_mod._try_import

    def fake_try_import(filename, module_name):
        if filename == "convergence.py":
            return conv_mod
        return real_try_import(filename, module_name)

    ot_mod._try_import = fake_try_import
    ot_mod._self_eval = FakeSelfEval()

    details = {"test_results": [{"passed": False, "name": "x"}]}
    new_text, applied, desc = ot_mod.try_offline_fix(text, {}, details)

    assert applied is True, f"a real, non-damaging fixer must still be applied, desc={desc!r}"
    assert new_text != text
    assert "maybe" not in new_text.lower()


# ─── harness ───────────────────────────────────────────────────────────────────

def main():
    repo_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(".").resolve()

    pure_tests = [
        test_scanner_finds_all_five_construct_kinds,
        test_scanner_nesting_fence_swallows_lookalike_markers,
        test_scanner_unterminated_fence_runs_to_eof,
        test_scanner_tilde_fence_and_mismatched_fence_char,
        test_scanner_example_same_line_open_close,
        test_protected_regions_equal_detects_content_change,
        test_protected_regions_equal_ignores_line_ending_style,
        test_protected_regions_equal_allows_unrelated_prose_changes,
        test_fix_clarity_protects_all_constructs_but_splits_prose,
        test_fix_efficiency_protects_regions_but_cleans_prose,
        test_fix_completeness_insertion_skips_protected_first_line,
        test_fix_model_fit_protects_regions,
        test_safe_text_for_save_backstop,
    ]
    for t in pure_tests:
        mod = load_convergence(repo_root)
        t(mod)
        print(f"  PASS  {t.__name__}")

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)

        for t in [test_gate_reverts_structural_damage_even_when_heuristic_score_improves,
                  test_deploy_exit_preserves_protected_regions,
                  test_plateau_exit_preserves_protected_regions]:
            mod = load_convergence(repo_root)
            sub = tmp_path / t.__name__
            sub.mkdir(exist_ok=True)
            t(mod, sub)
            print(f"  PASS  {t.__name__}")

        sub = tmp_path / "max_iter"
        sub.mkdir(exist_ok=True)
        test_max_iterations_exit_preserves_protected_regions(repo_root, sub)
        print("  PASS  test_max_iterations_exit_preserves_protected_regions")

        sub = tmp_path / "crlf_e2e"
        sub.mkdir(exist_ok=True)
        test_crlf_input_preserved_end_to_end(repo_root, sub)
        print("  PASS  test_crlf_input_preserved_end_to_end")

        sub = tmp_path / "lf_e2e"
        sub.mkdir(exist_ok=True)
        test_lf_input_preserved_end_to_end(repo_root, sub)
        print("  PASS  test_lf_input_preserved_end_to_end")

        conv_mod = load_convergence(repo_root)
        ot_mod = load_output_test(repo_root)
        test_try_offline_fix_refuses_structural_damage(conv_mod, ot_mod)
        print("  PASS  test_try_offline_fix_refuses_structural_damage")

        conv_mod2 = load_convergence(repo_root)
        ot_mod2 = load_output_test(repo_root)
        test_try_offline_fix_still_applies_legitimate_fix(conv_mod2, ot_mod2)
        print("  PASS  test_try_offline_fix_still_applies_legitimate_fix")

    print("test_structural_protection: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
