#!/usr/bin/env python3
"""Wixie Convergence Engine — autonomous prompt perfection with hypothesis-driven iteration.

Like gradient descent for prompts. Each iteration:
1. Scores the prompt (5 axes)
2. Runs binary assertions (pass/fail checks)
3. Forms a hypothesis about the weakest axis
4. Applies a targeted fix
5. Re-scores and checks for regression (auto-revert if worse)
6. Logs learnings for persistence across sessions

Usage:
    python convergence.py <prompt-file>
    python convergence.py <prompt-file> --max 50
    python convergence.py <prompt-file> --verbose
    python convergence.py <prompt-file> --json                  # also print a machine-readable
                                                                  # verdict line to stdout
    python convergence.py <prompt-file> --json-out <path>        # also write the machine-readable
                                                                  # verdict as JSON to <path>

Exit codes (WIX-EVAL-004 — the printed VERDICT line, the exit code, and the --json/--json-out
payload always agree; none of them can be read as a full DEPLOY when another disagrees):
    0  DEPLOY — the FULL documented bar was met: overall >= 9.0, every axis >= 7.0, sigma <=
       the dynamic floor, AND 8/8 SAT assertions pass (see deploy_verdict()). This is a
       HEURISTIC verdict only (self-eval's regex/structure scorers, zero model API calls) —
       it is NOT a measured DEPLOY. The converge skill requires a real efficacy-replay pass
       (shared/scripts/efficacy-replay.py) before a prompt may be called DEPLOY in the
       product sense.
    1  HOLD — the full bar above was not met (score, an axis, sigma, or an assertion failed).
       A run that never reaches a final report is also treated as HOLD: absence of a stamped
       verdict never means success.
    2  Usage / bad input — no prompt-file argument, the file does not exist, or the file is
       empty. Nothing was scored.
    3  Internal error — an unexpected exception was raised while scoring, fixing, or saving.
       Distinct from HOLD: HOLD means the prompt WAS scored and fell short; 3 means scoring
       did not complete at all, so a consumer must not read it as either DEPLOY or HOLD.

Stdlib only. No pip installs.
"""
import sys, os, re, json, copy, statistics, bisect, functools
from datetime import datetime
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Exit codes (WIX-EVAL-004) ──────────────────────────────────────────────────
# Named so the printed verdict, the exit code and the --json/--json-out payload are all
# derived from the same four values instead of three independent computations drifting apart.
EXIT_DEPLOY = 0
EXIT_HOLD = 1
EXIT_USAGE_ERROR = 2
EXIT_INTERNAL_ERROR = 3

# The heuristic verdict is a linter, not a measurement. Every machine-readable payload carries
# this note so a downstream consumer cannot mistake "DEPLOY" here for a measured, model-verified
# result (see converge SKILL.md Step 2.5 / efficacy-replay.py).
MACHINE_VERDICT_NOTE = (
    "Heuristic verdict from self-eval's regex/structure scorers and the 8 SAT assertions. "
    "Zero model API calls were made. This is NOT a measured DEPLOY -- the converge skill "
    "requires a real efficacy-replay pass (shared/scripts/efficacy-replay.py) against the "
    "deploy-bar corpus before a prompt may be called DEPLOY in the product sense."
)

# ─── Import scoring functions from self-eval ───────────────────────────────────

def _import_scorer():
    import importlib.util
    spec = importlib.util.spec_from_file_location("self_eval", os.path.join(SCRIPT_DIR, "self-eval.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_eval = _import_scorer()
AXES = _eval.AXES
SCORERS = _eval.SCORERS


def score_prompt(text):
    scores = {a: round(fn(text), 1) for a, fn in zip(AXES, SCORERS)}
    scores["overall"] = round(sum(scores[a] for a in AXES) / len(AXES), 1)
    return scores


def is_deploy(scores):
    """Scores gate only. The full DEPLOY bar (sigma + 8/8 assertions) is deploy_verdict()."""
    return scores["overall"] >= 9.0 and all(scores[a] >= 7.0 for a in AXES)


def deploy_verdict(scores, assertions, text):
    """The full DEPLOY bar per the contract: overall >= 9.0 AND every axis >= 7.0 AND
    sigma <= the dynamic floor (self-eval.dynamic_sigma_floor) AND all 8 SAT assertions
    pass. Returns (deploy_bool, sigma, floor). Honest-numbers contract: a prompt that
    fails sigma or any assertion is HOLD, not DEPLOY — regardless of overall score."""
    sigma = statistics.pstdev([scores[a] for a in AXES])
    floor = _eval.dynamic_sigma_floor(text)
    all_assertions_pass = all(a[1] for a in assertions)
    deploy = is_deploy(scores) and sigma <= floor and all_assertions_pass
    return deploy, sigma, floor


# ─── Binary Assertions ────────────────────────────────────────────────────────

def run_assertions(text):
    """Binary pass/fail checks. More stable than numeric scores for detecting issues."""
    results = []
    tl = text.lower()

    results.append(("has_role", bool(re.search(r'\b(you are|act as|role:|your role|your job)\b', tl)),
                     "Prompt defines a role or persona"))
    results.append(("has_task", bool(re.search(r'\b(task:|objective:|goal:|your job|you will|you should|analyze|generate|create|build|extract|classify|summari[sz]e|translate|rewrite|convert|parse|identify|detect|evaluate|score|rank|label|produce|write|compose|answer|respond)\b', tl)),
                     "Prompt defines a clear task"))
    results.append(("has_format", bool(re.search(r'\b(output format|respond in|format:|json|xml|markdown)\b|<output|<format', tl)),
                     "Prompt specifies output format"))
    results.append(("has_constraints", bool(re.search(r"\b(do not|don't|never|avoid|constraint|must not)\b", tl)),
                     "Prompt has constraints/guardrails"))
    results.append(("has_edge_cases", bool(re.search(r'\b(if.{0,20}(empty|invalid|error|missing)|edge case|fallback|if unsure)\b', tl)),
                     "Prompt handles edge cases"))
    results.append(("no_hedge_words", not bool(re.search(r'\b(maybe|perhaps|possibly|somewhat|might want to)\b', tl)),
                     "No hedge words (maybe, perhaps, possibly)"))
    results.append(("no_filler", not bool(re.search(r"(it's worth noting|please note that|keep in mind|in order to)", tl)),
                     "No filler phrases"))
    results.append(("has_structure", bool(re.search(r'(^#{1,3}\s|\n#{1,3}\s|<\w+>)', text)),
                     "Prompt has structural markup (headers or XML tags)"))

    return results


# ─── Editable-prose allow-list (WIX-CONV-001) ──────────────────────────────────
# Text-rewriting fixers may modify ONLY "editable prose". Everything else is frozen,
# and the gate compares a structural fingerprint of the frozen content. The design is
# a POSITIVE allow-list: nothing is editable unless it is positively known to be prose.
#
# Editable prose is:
#   * top-level prose lines (outside every XML/HTML-like element), and
#   * prose lines inside a PAIRED XML element whose tag name (case-insensitive) is in
#     EDITABLE_XML_SECTIONS below -- the instruction sections Wixie's Claude-format
#     prompts are built from.
#
# Non-editable (frozen) content is:
#   * fenced code blocks (``` or ~~~, any language, any indentation; an unterminated
#     fence runs to end of document),
#   * top-level indented code blocks (4 spaces / tab after a blank line),
#   * Markdown/GFM tables and blockquotes,
#   * a bracket block: a line whose first character is '{' or '[' and whose bracket
#     closes on a later line or ends the line (multi-line or stand-alone JSON/arrays),
#   * the entire content of any PAIRED element whose tag name is NOT in
#     EDITABLE_XML_SECTIONS (unknown tags default to frozen -- this is how XML/JSON data
#     examples such as <sample_json>, <output>, <data> stay content-equal), and always
#     the paired <example>/<examples> blocks (ALWAYS_FROZEN_XML_ELEMENTS) however their
#     tags are placed (alone on a line, sharing a line, or both on one line),
#   * every tag token itself (so tag names/attributes can never change).
#   An UNPAIRED tag (e.g. the word "<example>" mentioned in prose) freezes only its own
#   characters, never the text after it.
#
# Within an editable line, an edit may not land inside an inline span: a (), [], {}
# bracket span, a "..." / curly-quote span, or a `backtick` code span (an unclosed
# opener runs to end of line). A line whose only candidate edit position is inside
# such a span is simply skipped; it is not frozen for other safe edits.
#
# Every parser below is iterative and linear in the input (explicit stacks, no
# recursion, no per-bracket JSON decoding), so deeply nested or adversarial input
# cannot overflow the stack or go quadratic.
EDITABLE_XML_SECTIONS = frozenset({
    "role", "persona", "task", "objective", "goal", "goals", "purpose",
    "instructions", "instruction", "context", "background", "constraints", "rules",
    "guidelines", "requirements", "steps", "process", "approach", "edge_cases",
    "failure_modes", "preconditions", "success_criteria", "tone", "style", "audience",
})
ALWAYS_FROZEN_XML_ELEMENTS = frozenset({"example", "examples"})

_FENCE_RE = re.compile(r'^[ \t]*(`{3,}|~{3,})(.*)$')
_TABLE_DELIM_RE = re.compile(r'^\s{0,3}\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$')
_BLOCKQUOTE_RE = re.compile(r'^[ \t]*>')
_INDENT_CODE_RE = re.compile(r'^(?: {4}|\t)')
_TAG_RE = re.compile(  # attribute values may be quoted and then contain '<' / '>'
    r'<(/?)([A-Za-z_][\w.:-]*)((?:\s(?:[^<>"\'\n]|"[^"\n]*"|\'[^\'\n]*\')*?)?)(/?)>')
_BACKTICK_RUN_RE = re.compile(r'`+')
_JSON_CHARS_RE = re.compile(r'[\[\]{}"\\]')
_LOCAL_CHARS_RE = re.compile('[\\[\\](){}"\\\\“”]')
_CLOSER_OF = {']': '[', '}': '{', ')': '('}


def _normalize_newlines(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _merge_intervals(items):
    """Sort (start, end, kind) intervals and merge overlapping ones; the merged interval
    keeps the kind of its outermost (earliest-starting, longest) member."""
    items = sorted(items, key=lambda r: (r[0], -r[1]))
    out = []
    for s, e, k in items:
        if out and s < out[-1][1]:
            if e > out[-1][1]:
                out[-1] = (out[-1][0], e, out[-1][2])
        else:
            out.append((s, e, k))
    return out


def _backtick_spans(seg):
    """Inline code spans in one line: a run of N backticks closed by the next run of
    exactly N backticks. Linear (next-same-length index precomputed)."""
    runs = [(m.start(), m.end()) for m in _BACKTICK_RUN_RE.finditer(seg)]
    if len(runs) < 2:
        return []
    nxt = [None] * len(runs)
    last = {}
    for k in range(len(runs) - 1, -1, -1):
        length = runs[k][1] - runs[k][0]
        nxt[k] = last.get(length)
        last[length] = k
    out = []
    k = 0
    while k < len(runs):
        j = nxt[k]
        if j is not None:
            out.append((runs[k][0], runs[j][1]))
            k = j + 1
        else:
            k += 1
    return out


def _local_spans(text, s, e):
    """No-edit inline spans inside text[s:e] (one editable line segment): backtick code
    spans, "..." / curly-quote spans, and (), [], {} bracket spans. Iterative, linear;
    an unclosed opener runs to the end of the segment. Returns absolute (start, end)."""
    seg = text[s:e]
    bts = _backtick_spans(seg)
    spans = list(bts)
    stack = []
    counts = {'(': 0, '[': 0, '{': 0}
    in_q = None
    start = None
    skip_to = -1
    bi = 0
    for m in _LOCAL_CHARS_RE.finditer(seg):
        p = m.start()
        if p < skip_to:
            continue
        while bi < len(bts) and bts[bi][1] <= p:
            bi += 1
        if bi < len(bts) and bts[bi][0] <= p:
            continue
        ch = m.group()
        if in_q is not None:
            if ch == '\\':
                skip_to = p + 2
            elif (in_q == '"' and ch == '"') or (in_q == '“' and ch == '”'):
                in_q = None
                if not stack:
                    spans.append((start, p + 1))
                    start = None
            continue
        if ch == '"' or ch == '“':
            if not stack:
                start = p
            in_q = ch
        elif ch in '([{':
            if not stack:
                start = p
            stack.append(ch)
            counts[ch] += 1
        elif ch in ')]}':
            want = _CLOSER_OF[ch]
            if not counts[want]:
                continue
            while stack:
                top = stack.pop()
                counts[top] -= 1
                if top == want:
                    break
            if not stack:
                spans.append((start, p + 1))
                start = None
    if start is not None:
        spans.append((start, len(seg)))
    return [(s + a, s + b) for a, b in spans]


class _Structure(object):
    """Result of analyze_structure(): frozen block intervals, inline no-edit spans,
    XML elements, tag tokens, and the structural fingerprint. Treat as immutable."""
    __slots__ = ("text", "frozen", "_frozen_starts", "inline", "no_edit", "_no_edit_starts",
                 "elements", "tags", "fingerprint")

    def touches_frozen(self, s, e):
        """True if [s, e) overlaps a frozen block region (inline spans ignored)."""
        k = bisect.bisect_left(self._frozen_starts, e) - 1
        return k >= 0 and self.frozen[k][1] > s

    def blocked(self, s, e):
        """True if the edit range [s, e) touches any frozen or inline no-edit span."""
        spans = self.no_edit
        k = bisect.bisect_left(self._no_edit_starts, e) - 1
        return k >= 0 and spans[k][1] > s

    def live_close_tag(self, name):
        """Start offset of the closing tag of the first PAIRED `name` element that is
        not itself inside frozen content, or None."""
        for o_s, o_e, c_s, c_e, nm in self.elements:
            if nm.lower() != name:
                continue
            k = bisect.bisect_right(self._no_edit_starts, c_s) - 1
            if k >= 0 and self.no_edit[k][0] < c_s < self.no_edit[k][1]:
                continue  # inside a larger frozen interval (e.g. inside an <example>)
            if k >= 0 and self.no_edit[k][0] == c_s and self.no_edit[k][1] > c_e:
                continue
            return c_s
        return None


def _free_segments(lines, starts, intervals):
    """Yield (line_index, [(s, e), ...]) -- the parts of each line not covered by the
    sorted, disjoint `intervals`. One pointer sweep: linear."""
    p = 0
    m = len(intervals)
    for i, line in enumerate(lines):
        ls = starts[i]
        le = ls + len(line)
        while p < m and intervals[p][1] <= ls:
            p += 1
        if le == ls:
            covered = p < m and intervals[p][0] <= ls
            yield i, ([] if covered else [(ls, ls)])
            continue
        segs = []
        cur = ls
        q = p
        while q < m and intervals[q][0] < le:
            a, b = intervals[q][0], intervals[q][1]
            if a > cur:
                segs.append((cur, a))
            cur = max(cur, b)
            if b > le:
                break
            q += 1
        if cur < le:
            segs.append((cur, le))
        yield i, segs


@functools.lru_cache(maxsize=32)
def analyze_structure(text):
    """Classify `text` ('\\n'-normalized) into editable prose vs frozen content (see
    the EDITABLE_XML_SECTIONS comment block). Linear time, no recursion."""
    lines = text.split('\n')
    n = len(lines)
    starts = [0] * n
    pos = 0
    for i, line in enumerate(lines):
        starts[i] = pos
        pos += len(line) + 1

    def line_end(i):
        return starts[i] + len(lines[i])

    def line_of(offset):
        return bisect.bisect_right(starts, offset) - 1

    raw = []  # (start, end, kind) frozen intervals, merged at the end

    # 1) Fenced code blocks (highest priority; one forward pass).
    fence_line = bytearray(n)
    i = 0
    while i < n:
        m = _FENCE_RE.match(lines[i])
        if m and not (m.group(1)[0] == '`' and '`' in m.group(2)):
            ch, length = m.group(1)[0], len(m.group(1))
            j = i + 1
            close = None
            while j < n:
                cm = _FENCE_RE.match(lines[j])
                if cm and cm.group(1)[0] == ch and len(cm.group(1)) >= length and not cm.group(2).strip():
                    close = j
                    break
                j += 1
            last = close if close is not None else n - 1
            for k in range(i, last + 1):
                fence_line[k] = 1
            raw.append((starts[i], line_end(last), "fenced_code"))
            i = last + 1
            continue
        i += 1

    # 2) Tag tokens on non-fence lines, outside inline backtick code.
    tokens = []  # (start, end, name, kind) kind: 'open' | 'close' | 'self'
    bt_by_line = {}
    for i, line in enumerate(lines):
        if fence_line[i] or '<' not in line and '`' not in line:
            continue
        bts = _backtick_spans(line) if '`' in line else []
        if bts:
            bt_by_line[i] = bts
        if '<' not in line:
            continue
        bi = 0
        for m in _TAG_RE.finditer(line):
            a, b = m.span()
            while bi < len(bts) and bts[bi][1] <= a:
                bi += 1
            if bi < len(bts) and bts[bi][0] < b:
                continue
            kind = 'close' if m.group(1) else ('self' if m.group(4) else 'open')
            if kind == 'close' and m.group(4):
                kind = 'self'
            tokens.append((starts[i] + a, starts[i] + b, m.group(2), kind))

    # 3) Pair tags with an explicit stack (linear, amortized): a close tag pairs with
    #    the nearest open tag of the same name; opens skipped over stay unpaired.
    elements = []
    stack = []
    open_count = {}
    for t in tokens:
        name = t[2]
        if t[3] == 'open':
            stack.append(t)
            open_count[name] = open_count.get(name, 0) + 1
        elif t[3] == 'close' and open_count.get(name):
            while stack:
                top = stack.pop()
                open_count[top[2]] -= 1
                if top[2] == name:
                    elements.append((top[0], top[1], t[0], t[1], name))
                    break
    elements.sort()

    for o_s, o_e, c_s, c_e, name in elements:
        lname = name.lower()
        if lname in ALWAYS_FROZEN_XML_ELEMENTS:
            raw.append((o_s, c_e, "example"))
        elif lname not in EDITABLE_XML_SECTIONS:
            raw.append((o_s, c_e, "xml_element"))
    for t in tokens:
        raw.append((t[0], t[1], "tag"))

    hard = _merge_intervals(raw)

    # Lines in an allow-listed section (for the top-level-only indented-code rule).
    diff = [0] * (n + 1)
    for o_s, o_e, c_s, c_e, name in elements:
        if name.lower() in EDITABLE_XML_SECTIONS and name.lower() not in ALWAYS_FROZEN_XML_ELEMENTS:
            diff[line_of(o_s)] += 1
            diff[line_of(c_s) + 1] -= 1
    in_section = bytearray(n)
    run = 0
    for i in range(n):
        run += diff[i]
        in_section[i] = 1 if run > 0 else 0

    # Lines touching any hard-frozen interval, and bracket matching for bracket blocks.
    touched = bytearray(n)
    free_by_line = {}
    for i, segs in _free_segments(lines, starts, hard):
        if segs != [(starts[i], line_end(i))]:
            touched[i] = 1
        free_by_line[i] = segs
    for i in range(n):
        if fence_line[i]:
            touched[i] = 1

    match = {}
    need_match = any(
        not touched[i] and lines[i].lstrip()[:1] in ('{', '[') for i in range(n))
    if need_match:
        bstack = []
        bcount = {'{': 0, '[': 0}
        for i in range(n):
            if fence_line[i]:
                continue
            bts = bt_by_line.get(i, ())
            in_str = False
            skip_to = -1
            for s, e in free_by_line.get(i, ()):
                bi = 0
                for m in _JSON_CHARS_RE.finditer(text, s, e):
                    p = m.start()
                    if p < skip_to:
                        continue
                    rel = p - starts[i]
                    while bi < len(bts) and bts[bi][1] <= rel:
                        bi += 1
                    if bi < len(bts) and bts[bi][0] <= rel:
                        continue
                    ch = m.group()
                    if in_str:
                        if ch == '\\':
                            skip_to = p + 2
                        elif ch == '"':
                            in_str = False
                        continue
                    if ch == '"':
                        in_str = True
                    elif ch in '{[':
                        bstack.append((p, ch))
                        bcount[ch] += 1
                    elif ch in '}]':
                        want = _CLOSER_OF[ch]
                        if not bcount[want]:
                            continue
                        while bstack:
                            op, oc = bstack.pop()
                            bcount[oc] -= 1
                            if oc == want:
                                match[op] = p
                                break

    # 4) Block constructs on lines untouched by fences/elements/tags.
    blocks = []
    i = 0
    while i < n:
        line = lines[i]
        if touched[i] or not line.strip():
            i += 1
            continue
        if ('|' in line and i + 1 < n and not touched[i + 1] and '|' in lines[i + 1]
                and _TABLE_DELIM_RE.match(lines[i + 1].strip())):
            j = i + 2
            while j < n and not touched[j] and lines[j].strip() and '|' in lines[j]:
                j += 1
            blocks.append((starts[i], line_end(j - 1), "table"))
            i = j
            continue
        if _BLOCKQUOTE_RE.match(line):
            # A '>' run plus its lazy-continuation lines (non-blank lines directly after
            # it without a '>' -- Markdown renders them inside the same quote).
            j = i + 1
            while j < n and not touched[j] and lines[j].strip():
                j += 1
            blocks.append((starts[i], line_end(j - 1), "blockquote"))
            i = j
            continue
        if (not in_section[i] and _INDENT_CODE_RE.match(line)
                and (i == 0 or not lines[i - 1].strip())):
            j = i + 1
            last = i
            while (j < n and not touched[j] and not in_section[j]
                   and (not lines[j].strip() or _INDENT_CODE_RE.match(lines[j]))):
                if lines[j].strip():
                    last = j
                j += 1
            blocks.append((starts[i], line_end(last), "indented_code"))
            i = last + 1
            continue
        stripped = line.lstrip()
        if stripped[:1] in ('{', '['):
            p = starts[i] + len(line) - len(stripped)
            c = match.get(p)
            if c is not None:
                j = line_of(c)
                if j > i or text[c + 1:line_end(i)].strip() in ('', ',', ';'):
                    blocks.append((starts[i], line_end(j), "json"))
                    i = j + 1
                    continue
        i += 1

    frozen = _merge_intervals(hard + blocks)

    # 5) Inline no-edit spans on the editable remainder of every line.
    inline = []
    for i, segs in _free_segments(lines, starts, frozen):
        if fence_line[i]:
            continue
        for s, e in segs:
            if e > s:
                inline.extend(_local_spans(text, s, e))
    inline = _merge_intervals([(s, e, "inline") for s, e in inline])

    st = _Structure()
    st.text = text
    st.frozen = frozen
    st._frozen_starts = [r[0] for r in frozen]
    st.inline = inline
    st.no_edit = [(s, e) for s, e, _k in _merge_intervals(frozen + inline)]
    st._no_edit_starts = [s for s, _e in st.no_edit]
    st.elements = elements
    st.tags = tuple(re.sub(r'\s+', ' ', text[t[0]:t[1]]) for t in tokens)
    st.fingerprint = (tuple(text[s:e] for s, e in st.no_edit), st.tags)
    return st


def structure_fingerprint(text):
    """Structural fingerprint (WIX-CONV-001): the ordered contents of every non-editable
    region (frozen blocks + inline no-edit spans) plus the ordered tag sequence. Two
    versions of a document with equal fingerprints differ only in editable prose."""
    return analyze_structure(_normalize_newlines(text)).fingerprint


def find_protected_regions(text):
    """Sorted, disjoint (start, end, kind) frozen block regions of `text`
    ('\\n'-normalized offsets). Inline no-edit spans are not included."""
    return list(analyze_structure(_normalize_newlines(text)).frozen)


def protected_regions_equal(before_text, after_text):
    """The structural gate (WIX-CONV-001): True iff both texts have the same structural
    fingerprint (line endings normalized). A candidate failing it must be reverted
    regardless of its heuristic score."""
    return structure_fingerprint(before_text) == structure_fingerprint(after_text)


def _keep_if_structure_same(before, after):
    """Per-step guard used inside every fixer: an edit step whose result changes the
    structural fingerprint is dropped (the fixer continues from `before`)."""
    if after == before:
        return before
    return after if protected_regions_equal(before, after) else before


def _safe_sub(pattern, repl, text, count=0, allow_newline=False):
    """re.sub restricted to editable prose: a match touching any frozen region or inline
    no-edit span is skipped, and (unless allow_newline) so is a match containing a line
    break. The whole step is then checked with _keep_if_structure_same."""
    if not pattern.search(text):
        return text
    st = analyze_structure(text)
    out = []
    last = 0
    done = 0
    for m in pattern.finditer(text):
        if count and done >= count:
            break
        s, e = m.span()
        if e == s or (not allow_newline and '\n' in m.group(0)) or st.blocked(s, e):
            continue
        out.append(text[last:s])
        out.append(m.expand(repl))
        last = e
        done += 1
    if not done:
        return text
    out.append(text[last:])
    return _keep_if_structure_same(text, ''.join(out))


def _append_safely(text, addition):
    """Additive fixers append a new section at the end -- only if doing so leaves every
    existing non-editable region unchanged (e.g. not inside an unterminated fence). If
    appending directly would change a region (e.g. become a blockquote's lazy
    continuation), a blank-line-separated append is tried before giving up."""
    for candidate in (text + addition, text + "\n" + addition):
        if protected_regions_equal(text, candidate):
            return candidate
    return text


def _insert_before_close(text, name, insertion):
    """Insert `insertion` right before the closing tag of the first live, paired
    `name` element. Returns (new_text, inserted_bool)."""
    c = analyze_structure(text).live_close_tag(name)
    if c is None:
        return text, False
    new = _keep_if_structure_same(text, text[:c] + insertion + text[c:])
    return new, new != text


# ─── Fix functions ─────────────────────────────────────────────────────────────
# Every text-rewriting edit goes through the editable-prose allow-list above
# (_safe_sub / analyze_structure().blocked) and every step is fingerprint-checked.
# The hard guarantee is still the gate in run() plus the exit-path backstop.

_HEDGE_RE = re.compile(
    r'\b(?:maybe|perhaps|possibly|somewhat|try to|might want to)(?:[ \t]+|(?=\n)|\Z)'
    r'|\bif possible,?[ \t]*', re.I)
_SPLIT_RE = re.compile(r';\s+')
_BLOCK_START_CHARS = ('>', '|', '{', '[', '```', '~~~')


def fix_clarity(text):
    text = _safe_sub(_HEDGE_RE, '', text)
    st = analyze_structure(text)
    lines = text.split('\n')
    pos = 0
    new = []
    changed = False
    for line in lines:
        start = pos
        pos += len(line) + 1
        if len(line.split()) > 50 and ('; ' in line or ', and ' in line):
            for m in _SPLIT_RE.finditer(line):
                rest = line[m.end():]
                if (not rest.strip() or rest.lstrip().startswith(_BLOCK_START_CHARS)
                        or st.blocked(start + m.start(), start + m.end())):
                    continue
                line = line[:m.start()] + '.\n' + rest
                changed = True
                break
        new.append(line)
    if not changed:
        return text
    return _keep_if_structure_same(text, '\n'.join(new))


def fix_completeness(text):
    tl = text.lower()
    if not re.search(r'\b(you are|act as|role:|your role)\b', tl):
        st = analyze_structure(text)
        pos = 0
        for idx, line in enumerate(text.split('\n')):
            start = pos
            pos += len(line) + 1
            if (line.strip() and not line.strip().startswith(('<', '#', '---'))
                    and not st.touches_frozen(start, start + len(line))):
                text = _keep_if_structure_same(
                    text, text[:start] + "You are a domain expert.\n\n" + text[start:])
                break
    if not re.search(r'\b(task:|objective:|goal:|your job|you will|you should)\b', tl):
        text = _safe_sub(re.compile(re.escape("You are a domain expert.\n")),
                         "You are a domain expert. Your job is to complete the following task.\n",
                         text, count=1, allow_newline=True)
    if not re.search(r'\b(output format|respond in|format:|json|xml|markdown|<output|<format)\b', tl):
        text = _append_safely(text, "\n\nOutput format: structure your response clearly with headers and sections.\n")
    if not re.search(r"\b(do not|don't|never|must not|avoid)\b", tl):
        text = _append_safely(text, "\nDo not include information you are unsure about.\n")
    return text


_FILLER_RE = re.compile(
    r"it's worth noting that[ \t]*|please note that[ \t]*|as an AI,?[ \t]*|I want you to[ \t]*"
    r"|I need you to[ \t]*|please make sure[ \t]*(?:to[ \t]*)?|it is important to note that[ \t]*"
    r"|keep in mind that[ \t]*|I would like you to[ \t]*|please ensure that[ \t]*"
    r"|in order to(?:[ \t]+|(?=\n))", re.I)
_BLANK_RUN_RE = re.compile(r'\n{3,}')
_TRAILING_WS_RE = re.compile(r'[ \t]+$')


def fix_efficiency(text):
    text = _safe_sub(_FILLER_RE, '', text)
    text = _safe_sub(_BLANK_RUN_RE, '\n\n', text, allow_newline=True)
    st = analyze_structure(text)
    pos = 0
    new = []
    changed = False
    for line in text.split('\n'):
        start = pos
        pos += len(line) + 1
        m = _TRAILING_WS_RE.search(line)
        if m and not st.blocked(start + m.start(), start + m.end()):
            line = line[:m.start()]
            changed = True
        new.append(line)
    if not changed:
        return text
    return _keep_if_structure_same(text, '\n'.join(new))


def fix_model_fit(text):
    tl = text.lower()
    claude = bool(re.search(r'\b(claude|anthropic)\b|<(instructions|context|example)>', tl))
    gpt = bool(re.search(r'\b(gpt-4|gpt-5|openai|chatgpt)\b', tl))
    oseries = bool(re.search(r'\b(o1|o3|o4-mini|o-series)\b', tl))
    if claude and 'think thoroughly' not in tl:
        text, inserted = _insert_before_close(
            text, "instructions", "\nThink thoroughly before responding.\n")
        if not inserted:
            text = _append_safely(text, "\n\nThink thoroughly before responding.\n")
        text = _safe_sub(re.compile(r'\bthink step by step\b', re.I), 'think thoroughly', text)
    if gpt and not re.search(r'\b(step by step|think through)\b', tl):
        text = _append_safely(text, "\n\nThink step by step through your analysis before providing the final answer.\n")
    if oseries:
        text = _safe_sub(re.compile(r'\n.*think step by step.*\n', re.I), '\n', text, allow_newline=True)
    return text


def fix_failure_resilience(text):
    tl = text.lower()
    additions = []
    if not re.search(r'\bif\b.{0,30}\b(error|fail|cannot|unable|unclear|missing|invalid|empty)\b', tl):
        additions.append("If the input is empty or invalid, report the error clearly and explain what input is expected.")
    if not re.search(r'\b(edge case|corner case|special case|exception|unexpected)\b', tl):
        additions.append("Handle unexpected edge cases gracefully rather than failing silently.")
    if not re.search(r'\b(fallback|default to|if unsure|if you cannot|when in doubt)\b', tl):
        additions.append("If unsure about any information, state your uncertainty explicitly rather than guessing.")
    if not re.search(r'\b(validate|verify|check that|ensure that|confirm|if unclear)\b', tl):
        additions.append("Verify your output against the requirements before delivering the final response.")
    if additions:
        inserted = False
        if '<edge_cases>' in text:
            text, inserted = _insert_before_close(
                text, "edge_cases", '\n' + '\n'.join(additions) + '\n')
        if not inserted:
            text = _append_safely(text, '\n\n' + '\n'.join(additions) + '\n')
    return text


FIXERS = {
    "Clarity": fix_clarity,
    "Completeness": fix_completeness,
    "Efficiency": fix_efficiency,
    "Model Fit": fix_model_fit,
    "Failure Resilience": fix_failure_resilience,
}


# ─── Learnings Persistence ─────────────────────────────────────────────────────

def load_learnings(prompt_dir):
    """Load the full learning history for this prompt."""
    path = os.path.join(prompt_dir, "learnings.json") if prompt_dir else None
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError):
            pass
    return {
        "sessions": [],
        "strategy_stats": {},
        "patterns": [],
        "fix_history": [],           # what specific text changes were made + WHY
        "negative_examples": [],     # failing outputs + why they failed (avoid bank)
        "weakness_profile": {},      # co-occurring weakness patterns
        "recommendations": [],       # actionable advice for next session
        "prompt_fingerprint": {},    # word count, section count, domain, model
        "confidence_scores": {},     # per-strategy confidence with decay
    }


def save_learnings(prompt_dir, log_entries, prev_learnings=None, prompt_text="", metadata=None):
    """Save rich learnings with fix details, weakness profiling, and recommendations.

    Gauss Convergence Method: accumulate deep knowledge across sessions.
    Not just "Clarity was fixed" — but "removed 3 hedge words from edge_cases
    section, which improved Clarity from 7 to 8 on a coding prompt for Claude Opus."
    """
    if not prompt_dir:
        return

    data = prev_learnings or {
        "sessions": [], "strategy_stats": {}, "patterns": [],
        "fix_history": [], "weakness_profile": {}, "recommendations": [],
        "prompt_fingerprint": {},
    }

    # Prompt fingerprint — what kind of prompt is this?
    if prompt_text:
        data["prompt_fingerprint"] = {
            "words": len(prompt_text.split()),
            "lines": prompt_text.count("\n") + 1,
            "sections": len(re.findall(r'(^#{1,3}\s|\n#{1,3}\s|<\w+>)', prompt_text)),
            "has_examples": bool(re.search(r'<example|### Example', prompt_text, re.I)),
            "has_xml": bool(re.search(r'<\w+>', prompt_text)),
            "has_markdown": bool(re.search(r'^#{1,3}\s', prompt_text, re.M)),
        }
    if metadata:
        data["prompt_fingerprint"]["domain"] = metadata.get("task_domain", "unknown")
        data["prompt_fingerprint"]["model"] = metadata.get("target_model", "unknown")

    # Session with rich entries
    start = log_entries[0].get("start_score", 0) if log_entries else 0
    end = log_entries[-1].get("end_score", start) if log_entries else start
    session = {
        "timestamp": datetime.now().isoformat(),
        "iterations": len(log_entries),
        "start_score": start,
        "end_score": end,
        "improved": end > start,
        "delta": round(end - start, 1),
        "entries": log_entries,
    }
    data["sessions"].append(session)

    # Strategy stats with per-fix detail
    for entry in log_entries:
        axis = entry.get("axis", "unknown")
        result = entry.get("result", "unknown")
        if axis not in data["strategy_stats"]:
            data["strategy_stats"][axis] = {
                "applied": 0, "reverted": 0, "total_delta": 0.0,
                "best_delta": 0.0, "worst_delta": 0.0,
                "last_result": "", "consecutive_failures": 0,
            }
        stats = data["strategy_stats"][axis]
        delta = entry.get("delta", 0)
        if result == "applied":
            stats["applied"] += 1
            stats["total_delta"] += delta
            stats["best_delta"] = max(stats["best_delta"], delta)
            stats["consecutive_failures"] = 0
            stats["last_result"] = "applied"
        elif result == "reverted":
            stats["reverted"] += 1
            stats["worst_delta"] = min(stats["worst_delta"], delta)
            stats["consecutive_failures"] += 1
            stats["last_result"] = "reverted"

    # Fix history — what changed, WHY, and what happened (last 30)
    for entry in log_entries:
        data["fix_history"].append({
            "timestamp": datetime.now().isoformat()[:19],
            "axis": entry.get("axis", "?"),
            "hypothesis": entry.get("hypothesis", ""),
            "reasoning": entry.get("reasoning", ""),
            "result": entry.get("result", "?"),
            "delta": entry.get("delta", 0),
            "score_before": entry.get("start_score", 0),
            "score_after": entry.get("end_score", 0),
            "axis_changes": entry.get("axis_changes", {}),
            "assertions_fixed": entry.get("assertions_fixed", []),
        })
    data["fix_history"] = data["fix_history"][-30:]

    # Negative example bank — store WHY fixes failed so we can avoid them (last 15)
    for entry in log_entries:
        if entry.get("result") == "reverted":
            data["negative_examples"].append({
                "axis": entry.get("axis", "?"),
                "why_failed": entry.get("why_failed", "unknown regression"),
                "score_at_attempt": entry.get("start_score", 0),
                "reasoning": entry.get("reasoning", ""),
            })
    data["negative_examples"] = data["negative_examples"][-15:]

    # Confidence decay — strategies lose confidence if not re-confirmed within 3 sessions
    session_count = len(data["sessions"])
    for axis, s in data["strategy_stats"].items():
        total = s["applied"] + s["reverted"]
        if total == 0:
            continue
        base_confidence = s["applied"] / total
        # Decay: reduce confidence by 10% per session since last success
        sessions_since_use = 0
        for sess in reversed(data["sessions"]):
            if any(e.get("axis") == axis for e in sess.get("entries", [])):
                break
            sessions_since_use += 1
        decay = max(0.0, 1.0 - (sessions_since_use * 0.1))
        data["confidence_scores"][axis] = round(base_confidence * decay, 2)

    # Weakness profiling — which axes are consistently weak together?
    if log_entries:
        weak_axes = set()
        for entry in log_entries:
            if entry.get("start_score", 10) < 8:
                weak_axes.add(entry.get("axis", "unknown"))
        if len(weak_axes) >= 2:
            key = "+".join(sorted(weak_axes))
            data["weakness_profile"][key] = data["weakness_profile"].get(key, 0) + 1

    # Detect patterns and generate recommendations
    data["patterns"] = _detect_patterns(data)
    data["recommendations"] = _generate_recommendations(data)

    # Save
    json_path = os.path.join(prompt_dir, "learnings.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    md_path = os.path.join(prompt_dir, "learnings.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_render_learnings_md(data))


def _detect_patterns(data):
    """Deep pattern analysis across all sessions."""
    patterns = []
    stats = data.get("strategy_stats", {})

    for axis, s in stats.items():
        total = s["applied"] + s["reverted"]
        if total == 0:
            continue
        success_rate = s["applied"] / total
        avg_delta = s["total_delta"] / s["applied"] if s["applied"] > 0 else 0

        if success_rate == 1.0 and total >= 2:
            patterns.append({
                "type": "reliable",
                "axis": axis,
                "confidence": "high",
                "message": f"{axis}: {total}/{total} succeeded, avg +{avg_delta:.1f}. Always try this first.",
            })
        elif success_rate < 0.5 and total >= 3:
            patterns.append({
                "type": "unreliable",
                "axis": axis,
                "confidence": "high",
                "message": f"{axis}: reverted {s['reverted']}/{total} times. Skip automated fix — needs manual rewrite.",
            })
        elif s["consecutive_failures"] >= 2:
            patterns.append({
                "type": "currently_stuck",
                "axis": axis,
                "confidence": "medium",
                "message": f"{axis}: {s['consecutive_failures']} consecutive failures. Automated fixer cannot solve this — escalate to orchestrator.",
            })

    # Plateau detection
    sessions = data.get("sessions", [])
    if len(sessions) >= 2:
        recent = sessions[-3:] if len(sessions) >= 3 else sessions[-2:]
        if all(not s.get("improved", False) for s in recent):
            patterns.append({
                "type": "persistent_plateau",
                "confidence": "high",
                "message": f"No improvement in last {len(recent)} sessions. Structural rewrite needed — incremental fixes exhausted.",
            })

    # Weakness co-occurrence
    wp = data.get("weakness_profile", {})
    for combo, count in wp.items():
        if count >= 2:
            patterns.append({
                "type": "co_occurring_weakness",
                "confidence": "medium",
                "message": f"{combo} appear weak together ({count} times). Fixing one may fix both — they share a root cause.",
            })

    return patterns


def _generate_recommendations(data):
    """Generate actionable advice for the next session based on all accumulated knowledge."""
    recs = []
    stats = data.get("strategy_stats", {})
    patterns = data.get("patterns", [])
    fp = data.get("prompt_fingerprint", {})

    # Based on strategy stats
    for axis, s in stats.items():
        total = s["applied"] + s["reverted"]
        if total == 0:
            continue
        if s["consecutive_failures"] >= 2:
            recs.append(f"SKIP automated {axis} fixes — they've failed {s['consecutive_failures']} times in a row. Rewrite the {axis.lower()}-related sections manually.")
        elif s["applied"] > 0 and s["total_delta"] / s["applied"] > 0.3:
            recs.append(f"PRIORITIZE {axis} fixes — avg improvement of +{s['total_delta']/s['applied']:.1f} per application.")

    # Based on patterns
    for p in patterns:
        if p["type"] == "persistent_plateau":
            recs.append("RESTRUCTURE the prompt — tables instead of prose, shorter sentences, more imperative verbs. The current structure has reached its ceiling.")
        if p["type"] == "co_occurring_weakness":
            recs.append(f"FIX root cause for {p['message'].split(' appear')[0]} — they share a root cause, likely verbose descriptive writing style.")

    # Based on prompt fingerprint
    if fp.get("words", 0) > 1500 and not fp.get("has_examples"):
        recs.append("ADD examples — prompts over 1500 words without examples score lower on Completeness and Model Fit.")
    if fp.get("has_xml") and not fp.get("has_markdown"):
        recs.append("VERIFY target model prefers XML — if targeting GPT, switch to Markdown headers.")
    if fp.get("sections", 0) < 5 and fp.get("words", 0) > 500:
        recs.append("ADD more section headers — long prompts without structure score lower on Efficiency.")

    # Based on session trajectory
    sessions = data.get("sessions", [])
    if len(sessions) >= 3:
        deltas = [s.get("delta", 0) for s in sessions[-3:]]
        if all(d <= 0 for d in deltas):
            recs.append("DIMINISHING RETURNS — 3 sessions with no improvement. Consider: different techniques, different model target, or accepting current score as ceiling.")
        elif deltas[-1] > deltas[-2] > 0:
            recs.append("MOMENTUM — improvement accelerating. Keep iterating with current strategy.")

    return recs


def _render_learnings_md(data):
    """Render human-readable learnings that actually help the next session."""
    lines = [
        "# Gauss Convergence Learnings",
        "",
        f"Sessions: {len(data['sessions'])} | Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    # Recommendations FIRST — the most important section
    recs = data.get("recommendations", [])
    if recs:
        lines.append("## Recommendations for Next Session")
        lines.append("")
        for r in recs:
            lines.append(f"- {r}")
        lines.append("")

    # Strategy stats
    stats = data.get("strategy_stats", {})
    if stats:
        lines.append("## Strategy Performance")
        lines.append("")
        lines.append("| Axis | Applied | Reverted | Rate | Avg Delta | Best | Streak |")
        lines.append("|------|---------|----------|------|-----------|------|--------|")
        for axis, s in stats.items():
            total = s["applied"] + s["reverted"]
            rate = f"{s['applied']/total:.0%}" if total > 0 else "N/A"
            avg = f"+{s['total_delta']/s['applied']:.1f}" if s["applied"] > 0 else "N/A"
            best = f"+{s['best_delta']:.1f}" if s["best_delta"] > 0 else "0"
            streak = f"{s['consecutive_failures']} fails" if s["consecutive_failures"] > 0 else "OK"
            lines.append(f"| {axis} | {s['applied']} | {s['reverted']} | {rate} | {avg} | {best} | {streak} |")
        lines.append("")

    # Patterns
    patterns = data.get("patterns", [])
    if patterns:
        lines.append("## Detected Patterns")
        lines.append("")
        for p in patterns:
            conf = p.get("confidence", "?")
            lines.append(f"- [{conf}] {p['message']}")
        lines.append("")

    # Weakness co-occurrence
    wp = data.get("weakness_profile", {})
    if wp:
        lines.append("## Weakness Co-occurrence")
        lines.append("")
        for combo, count in sorted(wp.items(), key=lambda x: -x[1]):
            lines.append(f"- {combo}: seen {count} time(s)")
        lines.append("")

    # Recent fix history
    fh = data.get("fix_history", [])
    if fh:
        lines.append("## Recent Fix History (last 10)")
        lines.append("")
        lines.append("| Axis | Hypothesis | Result | Delta | Score |")
        lines.append("|------|-----------|--------|-------|-------|")
        for f in fh[-10:]:
            hyp = f.get("hypothesis", "")[:50]
            lines.append(f"| {f.get('axis','?')} | {hyp} | {f.get('result','?')} | {f.get('delta',0):+.1f} | {f.get('score_before',0)}->{f.get('score_after',0)} |")
        lines.append("")

    # Negative example bank (avoid these)
    negs = data.get("negative_examples", [])
    if negs:
        lines.append("## Negative Examples (avoid these)")
        lines.append("")
        for n in negs[-5:]:
            lines.append(f"- **{n.get('axis', '?')}** at score {n.get('score_at_attempt', '?')}: {n.get('why_failed', '?')}")
        lines.append("")

    # Confidence scores
    conf = data.get("confidence_scores", {})
    if conf:
        lines.append("## Strategy Confidence (with decay)")
        lines.append("")
        for axis, score in sorted(conf.items(), key=lambda x: -x[1]):
            bar = "#" * int(score * 10) + "." * (10 - int(score * 10))
            lines.append(f"- {axis}: {score:.0%} [{bar}]")
        lines.append("")

    # Prompt fingerprint
    fp = data.get("prompt_fingerprint", {})
    if fp:
        lines.append("## Prompt Profile")
        lines.append("")
        lines.append(f"- Words: {fp.get('words', '?')} | Sections: {fp.get('sections', '?')} | Domain: {fp.get('domain', '?')} | Model: {fp.get('model', '?')}")
        lines.append(f"- XML: {'yes' if fp.get('has_xml') else 'no'} | Markdown: {'yes' if fp.get('has_markdown') else 'no'} | Examples: {'yes' if fp.get('has_examples') else 'no'}")
        lines.append("")

    # Session trajectory
    sessions = data.get("sessions", [])
    if sessions:
        lines.append("## Session Trajectory")
        lines.append("")
        for i, s in enumerate(sessions[-5:], 1):
            arrow = "^" if s.get("improved") else "=" if s.get("delta", 0) == 0 else "v"
            lines.append(f"- [{arrow}] {s.get('start_score', '?')} -> {s.get('end_score', '?')} ({s.get('delta', 0):+.1f}) in {s.get('iterations', '?')} iterations ({s.get('timestamp', '?')[:10]})")
        lines.append("")

    return "\n".join(lines)


# ─── Main Loop ─────────────────────────────────────────────────────────────────

def run(prompt_path, max_iterations=100, verbose=False, want_json=False, json_out=None):
    if not os.path.isfile(prompt_path):
        _usage_error(f"{prompt_path} not found", want_json, json_out)

    text, original_lines, original_terms, bom = _read_text_preserving(prompt_path)
    with open(prompt_path, "rb") as f:
        original_raw = f.read()  # restored verbatim if any exit-path check trips
    io_state = (original_lines, original_terms, bom, original_raw)

    if not text.strip():
        _usage_error("Empty prompt file.", want_json, json_out)

    # WIX-CONV-001: the structural baseline every exit path is checked against.
    # Never reassigned -- it is the file's content the moment run() started.
    original_text = text
    original_fp = structure_fingerprint(original_text)

    prompt_dir = os.path.dirname(os.path.abspath(prompt_path))
    history = []
    plateau_count = 0
    best_score = 0
    best_text = text
    learnings = []
    prev_learnings = load_learnings(prompt_dir)

    # Use prior learnings for intelligent strategy selection
    skip_axes = set()
    prioritize_axes = []
    neg_examples = prev_learnings.get("negative_examples", [])
    confidence = prev_learnings.get("confidence_scores", {})

    for p in prev_learnings.get("patterns", []):
        if p.get("type") == "unreliable":
            skip_axes.add(p.get("axis", ""))
        if p.get("type") == "reliable":
            prioritize_axes.append(p.get("axis", ""))

    # Negative examples: don't repeat strategies that failed at similar scores
    for neg in neg_examples:
        neg_axis = neg.get("axis", "")
        neg_score = neg.get("score_at_attempt", 0)
        # If we failed fixing this axis at a similar score range before, skip it
        if neg_axis and neg_score > 0:
            skip_axes.add(neg_axis)  # conservative — skip any previously-failed axis

    num_sessions = len(prev_learnings.get("sessions", []))
    num_negs = len(neg_examples)
    recs = prev_learnings.get("recommendations", [])

    print(f"\n{'=' * 60}")
    print(f"  WIXIE CONVERGENCE ENGINE (Gauss Method)")
    # N3: "(heuristic bar)" — this target is self-eval's regex/structure scorer, never a
    # measured DEPLOY. See converge SKILL.md Step 2.5 / shared/scripts/efficacy-replay.py.
    print(f"  Target: DEPLOY (heuristic bar — overall >= 9.0, all axes >= 7.0, sigma <= floor, 8/8 assertions)")
    print(f"  Max iterations: {max_iterations}")
    if num_sessions:
        print(f"  Prior knowledge: {num_sessions} sessions, {num_negs} negative examples, {len(confidence)} confidence scores")
    if skip_axes:
        print(f"  Skipping (learned): {', '.join(skip_axes)}")
    if prioritize_axes:
        print(f"  Prioritizing (learned): {', '.join(prioritize_axes)}")
    if recs:
        print(f"  Top recommendation: {recs[0][:70]}...")
    print(f"{'=' * 60}\n")

    for iteration in range(1, max_iterations + 1):
        scores = score_prompt(text)
        overall = scores["overall"]
        history.append(overall)

        # Binary assertions
        assertions = run_assertions(text)
        failed = [a for a in assertions if not a[1]]
        passed = [a for a in assertions if a[1]]

        # Track best version
        if overall > best_score:
            best_score = overall
            best_text = text

        # DEPLOY only when the FULL bar is met: scores + sigma <= floor + 8/8 assertions.
        # (Previously this deployed on scores alone, ignoring sigma and failed assertions —
        # an honest-numbers violation: it shipped prompts the DEPLOY bar rejects.)
        deploy, sigma, floor = deploy_verdict(scores, assertions, text)
        if deploy:
            # WIX-CONV-001: DEPLOY / exit 0 is impossible while the structural check fails.
            # The write goes through _write_exit_file (fingerprint check before the write
            # AND on the written file); on any mismatch the original bytes are restored and
            # the verdict is forced to HOLD.
            written, structurally_ok = _write_exit_file(prompt_path, text, original_text, io_state)
            if not structurally_ok:
                print(f"  Iteration {iteration}: STRUCTURAL SAFETY TRIP at DEPLOY save -- the "
                      f"original, unmodified prompt was kept and the verdict forced to HOLD "
                      f"(WIX-CONV-001).")
                learnings.append(_structural_trip_entry("DEPLOY", iteration, overall))
                safe_scores = score_prompt(written)
                _print_final(safe_scores, run_assertions(written), iteration, written, force_hold=True)
                save_learnings(prompt_dir, learnings, prev_learnings, written)
                return safe_scores
            print(f"  Iteration {iteration}: {overall}/10 — DEPLOY ({len(passed)}/{len(assertions)} assertions, sigma {sigma:.2f} <= {floor:.2f})")
            _print_final(scores, assertions, iteration, text)
            save_learnings(prompt_dir, learnings, prev_learnings, text)
            return scores

        # Plateau detection — stalled with the bar unmet: report HOLD honestly, don't fake DEPLOY.
        if len(history) >= 3 and history[-1] == history[-2] == history[-3]:
            plateau_count += 1
            if plateau_count >= 1:
                print(f"  Iteration {iteration}: {overall}/10 — PLATEAU (HOLD — bar not met)")
                written, structurally_ok = _write_exit_file(prompt_path, best_text, original_text, io_state)
                if not structurally_ok:
                    print("  STRUCTURAL SAFETY TRIP at PLATEAU save -- the original, unmodified "
                          "prompt was kept (WIX-CONV-001).")
                    learnings.append(_structural_trip_entry("PLATEAU", iteration, overall))
                safe_scores = score_prompt(written)
                _print_final(safe_scores, run_assertions(written), iteration, written,
                             force_hold=not structurally_ok)
                save_learnings(prompt_dir, learnings, prev_learnings, written)
                return safe_scores

        # Form hypothesis — Gauss Method: target weakest axis, weighted by confidence
        axes_by_score = sorted(AXES, key=lambda a: scores[a])
        # Filter out axes that are known-unreliable (unless critically low)
        viable = [a for a in axes_by_score if a not in skip_axes or scores[a] < 5]
        if not viable:
            viable = axes_by_score
        # Among viable, prefer axes with higher historical confidence
        if confidence:
            viable.sort(key=lambda a: (scores[a], -(confidence.get(a, 0.5))))
        weakest = viable[0]
        hypothesis = f"Fixing {weakest} (currently {scores[weakest]}/10) will improve overall from {overall}"

        # Progress update
        if verbose or iteration <= 3 or iteration % 10 == 0:
            fail_names = ", ".join(a[0] for a in failed) if failed else "none"
            print(f"  Iteration {iteration}: {overall}/10 — hypothesis: fix {weakest} | failed assertions: {fail_names}")

        # Save pre-fix state for auto-revert
        pre_fix_text = text

        # Apply fix
        for axis in axes_by_score:
            if scores[axis] < 9.0 and axis in FIXERS:
                text = FIXERS[axis](text)

        # Also fix failed binary assertions directly
        for name, passed_flag, desc in failed:
            if name == "has_role" and "Completeness" not in [axes_by_score[0]]:
                text = fix_completeness(text)
            elif name == "has_edge_cases":
                text = fix_failure_resilience(text)
            elif name == "no_hedge_words":
                text = fix_clarity(text)
            elif name == "no_filler":
                text = fix_efficiency(text)

        # Check for regression — Gauss revert: reject if deviation increased
        new_scores = score_prompt(text)
        new_assertions = run_assertions(text)
        new_failed = [a for a in new_assertions if not a[1]]

        # Build reasoning chain — WHY did we choose this fix?
        reasoning = f"Targeted {weakest} ({scores[weakest]}/10) because it was the lowest axis."
        if weakest in skip_axes:
            reasoning += " (Historically unreliable but score was critically low.)"
        if failed:
            reasoning += f" Also had {len(failed)} failing assertion(s): {', '.join(a[0] for a in failed)}."

        # Structural gate (WIX-CONV-001): a candidate whose structural fingerprint (all
        # non-editable content + the tag sequence, see analyze_structure) differs from
        # the input's is reverted regardless of score -- this check runs BEFORE
        # and independently of the score-drop check below, so a candidate that raises
        # `overall` (or leaves it flat) is not exempt.
        structurally_ok = _candidate_is_structurally_safe(text, original_fp)

        if not structurally_ok:
            text = pre_fix_text
            delta = new_scores["overall"] - overall
            outcome = ("REVERTED — structural gate: the fixer changed non-editable content "
                       "(structural fingerprint mismatch)")
            learnings.append({
                "iteration": iteration, "axis": weakest, "hypothesis": hypothesis,
                "reasoning": reasoning,
                "result": "reverted", "outcome": outcome, "delta": delta,
                "start_score": overall, "end_score": overall,
                "why_failed": f"Fixer for {weakest} changed non-editable content (fenced/indented "
                               f"code, table, blockquote, bracket block, frozen XML element, "
                               f"<example> block, inline span or tag sequence); reverted "
                               f"regardless of score delta ({overall} -> {new_scores['overall']}) "
                               f"per WIX-CONV-001.",
            })
        elif new_scores["overall"] < overall - 0.5:
            text = pre_fix_text
            delta = new_scores["overall"] - overall
            outcome = f"REVERTED — regression from {overall} to {new_scores['overall']}"
            learnings.append({
                "iteration": iteration, "axis": weakest, "hypothesis": hypothesis,
                "reasoning": reasoning,
                "result": "reverted", "outcome": outcome, "delta": delta,
                "start_score": overall, "end_score": overall,
                "why_failed": f"Fix caused {weakest} regression: {scores[weakest]}->{new_scores[weakest]}. Other axes affected: {', '.join(a for a in AXES if new_scores[a] < scores[a])}",
            })
        else:
            delta = new_scores["overall"] - overall
            outcome = f"{'improved' if delta > 0 else 'unchanged'} ({overall} → {new_scores['overall']})"
            # Track which specific axes improved/degraded
            axis_changes = {a: round(new_scores[a] - scores[a], 1) for a in AXES if new_scores[a] != scores[a]}
            learnings.append({
                "iteration": iteration, "axis": weakest, "hypothesis": hypothesis,
                "reasoning": reasoning,
                "result": "applied", "outcome": outcome, "delta": delta,
                "start_score": overall, "end_score": new_scores["overall"],
                "axis_changes": axis_changes,
                "assertions_fixed": [a[0] for a in failed if a[0] not in [nf[0] for nf in new_failed]],
            })

    # Max iterations
    print(f"\n  Max iterations ({max_iterations}) reached. Best: {best_score}/10")
    written, structurally_ok = _write_exit_file(prompt_path, best_text, original_text, io_state)
    if not structurally_ok:
        print("  STRUCTURAL SAFETY TRIP at MAX-ITERATIONS save -- the original, unmodified "
              "prompt was kept (WIX-CONV-001).")
        learnings.append(_structural_trip_entry("MAX-ITERATIONS", max_iterations, best_score))
    scores = score_prompt(written)
    _print_final(scores, run_assertions(written), max_iterations, written,
                 force_hold=not structurally_ok)
    save_learnings(prompt_dir, learnings, prev_learnings, written)
    return scores


_LINE_TERM_RE = re.compile(r'\r\n|\n|\r')


def _split_keepends_and_strip(raw_text):
    """Split `raw_text` (already str-decoded) into (lines, terminators): `lines[i]`
    is physical line i with its terminator removed, `terminators[i]` is exactly
    what followed it ("\\r\\n", "\\n", "\\r", or "" for a final line with no
    trailing terminator at all). Only CR/LF are line terminators -- U+2028, form
    feed, etc. stay inside their line. Round-trips any mix of line-ending styles."""
    lines, terms = [], []
    pos = 0
    for m in _LINE_TERM_RE.finditer(raw_text):
        lines.append(raw_text[pos:m.start()])
        terms.append(m.group())
        pos = m.end()
    if pos < len(raw_text):
        lines.append(raw_text[pos:])
        terms.append("")
    return lines, terms


def _read_text_preserving(path):
    """Read a prompt file preserving its original per-line line-ending convention
    and any UTF-8 BOM, so `_save` can restore both exactly -- including a MIXED
    file (some lines CRLF, some LF) -- instead of normalizing the whole file to
    one style (WIX-CONV-001 item 5). Internal processing always works on
    '\\n'-joined text; `original_lines`/`original_terms`/`bom` are threaded
    through to `_save`, which reconstructs each line's original terminator for
    every line that comes out unchanged and only falls back to a default for
    genuinely new/modified lines."""
    with open(path, "rb") as f:
        raw = f.read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    if bom:
        raw = raw[3:]
    raw_text = raw.decode("utf-8")
    original_lines, original_terms = _split_keepends_and_strip(raw_text)
    text = "\n".join(original_lines)
    return text, original_lines, original_terms, bom


def _safe_text_for_save(original_text, candidate_text):
    """Defense-in-depth backstop for every exit path (WIX-CONV-001 item 3). The
    per-iteration accept/revert gate should already guarantee `candidate_text`'s
    protected regions match `original_text`'s; this re-checks right before a write
    so that even a bug elsewhere can never persist structural damage -- it falls
    back to the untouched original instead. Returns (text_to_save, structurally_ok)."""
    if protected_regions_equal(original_text, candidate_text):
        return candidate_text, True
    return original_text, False


def _candidate_is_structurally_safe(candidate_text, original_fp):
    """Per-iteration accept/revert gate (WIX-CONV-001): the candidate's structural
    fingerprint must equal the input's. Independent of the exit-path backstop
    (_write_exit_file), which re-checks with protected_regions_equal."""
    return structure_fingerprint(candidate_text) == original_fp


def _structural_trip_entry(stage, iteration, score):
    """learnings.json entry for an exit-path backstop trip (distinguishable from a
    score regression and from a per-iteration structural revert)."""
    return {
        "iteration": iteration, "axis": "n/a", "hypothesis": "n/a",
        "reasoning": f"structural safety trip before {stage} save",
        "result": "reverted", "outcome": "REVERTED — structural gate tripped at save time",
        "delta": 0, "start_score": score, "end_score": score,
        "why_failed": (f"The structural fingerprint of the text to be written at the {stage} "
                       f"exit (or of the file as written) differed from the input's; the "
                       f"original file was kept and the verdict forced to HOLD (WIX-CONV-001)."),
    }


def _written_file_matches(path, original_text):
    """Re-read the file just written and compare its structural fingerprint with the
    input's -- the check runs on the WRITTEN FILE, not only on the in-memory text."""
    try:
        written_text = _read_text_preserving(path)[0]
    except (OSError, UnicodeDecodeError):
        return False
    return protected_regions_equal(original_text, written_text)


def _write_exit_file(path, candidate, original_text, io_state):
    """Every exit path writes through here (WIX-CONV-001). The candidate is written only
    if its fingerprint matches the input's, and the written file is then re-read and
    checked again; on any mismatch the ORIGINAL bytes are restored verbatim.
    Returns (text_now_on_disk, structurally_ok)."""
    original_lines, original_terms, bom, original_raw = io_state
    safe, ok = _safe_text_for_save(original_text, candidate)
    if ok:
        _save(path, safe, original_lines=original_lines, original_terms=original_terms, bom=bom)
        if _written_file_matches(path, original_text):
            return safe, True
    _atomic_write_bytes(path, original_raw)
    return original_text, False


def _atomic_write_bytes(path, data):
    """Write via a temp file + os.replace so a crash mid-write never leaves a
    partially written prompt on disk."""
    tmp = f"{path}.convergence-tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _save(path, text, original_lines=None, original_terms=None, bom=False):
    """Write `text` ('\\n'-joined working text) back to `path`. Every output line
    that is unchanged from the original file (by position, or by exact content if
    its position shifted -- e.g. an inserted line pushed it down) keeps EXACTLY
    the terminator it originally had; a MIXED-line-ending input is therefore never
    normalized to one style (WIX-CONV-001 item 5 / OBS-05). A genuinely new or
    modified line gets the file's most common original terminator (or preserves
    "no trailing newline" if that was true of the original's last line and this
    is still the last line). `original_lines`/`original_terms` default to "no
    prior file" (a brand new document, every line gets the default terminator)."""
    original_lines = original_lines or []
    original_terms = original_terms or []

    term_by_content = {}
    for ln, tm in zip(original_lines, original_terms):
        if ln not in term_by_content:
            term_by_content[ln] = tm

    non_empty_terms = [t for t in original_terms if t]
    if non_empty_terms:
        default_term = Counter(non_empty_terms).most_common(1)[0][0]
    else:
        default_term = "\n"
    orig_ends_without_newline = bool(original_terms) and original_terms[-1] == ""

    out_lines = text.split('\n')
    n = len(out_lines)
    pieces = []
    for i, ln in enumerate(out_lines):
        is_last = (i == n - 1)
        if is_last and ln == "" and n > 1:
            # This trailing empty element just means the joined text ends with a
            # '\n' -- the previous piece already carries its own terminator.
            continue
        if i < len(original_lines) and ln == original_lines[i]:
            term = original_terms[i]
        elif ln in term_by_content:
            term = term_by_content[ln]
        elif is_last:
            term = "" if orig_ends_without_newline else default_term
        else:
            term = default_term
        pieces.append(ln + term)

    data = "".join(pieces).encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    _atomic_write_bytes(path, data)


def _verdict_payload(scores=None, deploy=False, sigma=0.0, floor=0.0, passed=0, total=0,
                      exit_code=EXIT_HOLD, error=None):
    """Build the machine-readable verdict dict. Its fields are derived from the SAME
    (deploy, sigma, floor, passed, total) tuple that produced the printed VERDICT line and
    the process exit code, so a --json/--json-out consumer can never see a different
    answer than the operator who read the terminal output (WIX-EVAL-004)."""
    payload = {
        "verdict": "ERROR" if error is not None else ("DEPLOY" if deploy else "HOLD"),
        "deploy": bool(deploy) if error is None else False,
        "exit_code": exit_code,
        "measured": False,
        "note": MACHINE_VERDICT_NOTE,
    }
    if error is not None:
        payload["error"] = error
    else:
        payload["overall"] = scores.get("overall")
        payload["axes"] = {a: scores.get(a) for a in AXES}
        payload["sigma"] = round(sigma, 4)
        payload["sigma_floor"] = round(floor, 4)
        payload["sigma_pass"] = sigma <= floor
        payload["assertions_passed"] = passed
        payload["assertions_total"] = total
    return payload


def _emit_machine_verdict(payload, want_json, json_out):
    """Opt-in only: nothing is written or printed unless the caller asked for it via
    --json / --json-out, so a plain `convergence.py <file>` run has zero new side effects."""
    if want_json:
        print("VERDICT_JSON " + json.dumps(payload, sort_keys=True))
    if json_out:
        try:
            with open(json_out, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
        except OSError as e:
            print(f"Warning: could not write --json-out {json_out}: {e}", file=sys.stderr)


def _verdict_payload_from_scores(scores, exit_code):
    """Build the machine verdict from a scores dict _print_final has already stamped
    (_deploy/_sigma/_sigma_floor/_assertions_passed/_assertions_total). Used by main() as
    the single emission point after run() returns (N1)."""
    return _verdict_payload(
        scores,
        deploy=scores.get("_deploy", False),
        sigma=scores.get("_sigma", 0.0),
        floor=scores.get("_sigma_floor", 0.0),
        passed=scores.get("_assertions_passed", 0),
        total=scores.get("_assertions_total", 0),
        exit_code=exit_code,
    )


def _usage_error(msg, want_json, json_out, show_usage=False):
    """Bad input / usage error (N2): validate arguments explicitly instead of letting
    int()/index errors raise uncaught — an uncaught exception in main()'s CLI parsing exits
    1, which the documented exit codes define as HOLD. This always exits EXIT_USAGE_ERROR (2)
    and, like every other exit path, emits the machine verdict once if requested."""
    if show_usage:
        print("Usage: python convergence.py <prompt-file> [--max N] [--verbose] [--json] [--json-out PATH]",
              file=sys.stderr)
    print(f"Error: {msg}", file=sys.stderr)
    _emit_machine_verdict(_verdict_payload(exit_code=EXIT_USAGE_ERROR, error=msg), want_json, json_out)
    sys.exit(EXIT_USAGE_ERROR)


def _print_final(scores, assertions, iterations, text, force_hold=False):
    print(f"\n{'=' * 60}")
    print(f"  FINAL SCORES (after {iterations} iteration{'s' if iterations != 1 else ''})")
    print(f"{'=' * 60}")
    for a in AXES:
        val = scores[a]
        pct = round((val / 10) * 20)
        bar = "#" * pct + "." * (20 - pct)
        print(f"  {(a + ':').ljust(22)}{val:4.0f}/10  {bar}")
    print(f"\n  {'OVERALL:'.ljust(22)}{scores['overall']:4.1f}/10")

    # WIX-EVAL-004: deploy/sigma/floor come from deploy_verdict() — the SAME function main()
    # gates the exit code on — instead of a second, independent recomputation here. One source
    # of truth means the printed line and the exit code cannot drift apart again.
    deploy, sigma, floor = deploy_verdict(scores, assertions, text)
    if force_hold:
        # WIX-CONV-001: an exit-path structural trip can never be reported as DEPLOY.
        deploy = False
    sigma_pass = sigma <= floor
    print(f"  {'SIGMA:'.ljust(22)}{sigma:4.2f} (floor {floor:.2f})  {'PASS' if sigma_pass else 'FAIL'}")

    # Assertions summary
    passed = sum(1 for a in assertions if a[1])
    total = len(assertions)
    print(f"  {'ASSERTIONS:'.ljust(22)}{passed}/{total} pass")
    for name, ok, desc in assertions:
        print(f"    {'PASS' if ok else 'FAIL'}  {desc}")

    # Full DEPLOY bar: scores + sigma + all assertions. Anything short is HOLD. "(heuristic)"
    # (N3) flags that even a DEPLOY here is self-eval's regex/structure scorer, never a
    # measured DEPLOY — see converge SKILL.md Step 2.5 / shared/scripts/efficacy-replay.py.
    print(f"\n  VERDICT: {'DEPLOY (heuristic)' if deploy else 'HOLD'}")
    print(f"{'=' * 60}\n")

    # WIX-EVAL-004: stamp the verdict this function just printed onto the scores dict so
    # main() can exit on the SAME verdict the operator just read, instead of re-deriving it
    # from the score-only is_deploy() gate. A missing stamp is treated as HOLD by main().
    #
    # N1: the machine verdict (VERDICT_JSON / --json-out) is emitted exactly ONCE — by main(),
    # after run() returns — and NOT here. Emitting it here too meant that when save_learnings()
    # raised right after this printed (e.g. learnings.json made read-only), stdout carried a
    # first, scored VERDICT_JSON (DEPLOY, exit_code 0) followed by a second, contradictory one
    # from main()'s crash handler (ERROR, exit_code 3) — two machine verdicts for one process
    # exit. _print_final() now only ever produces the stamp; main() is the single emitter.
    scores["_deploy"] = deploy
    scores["_sigma"] = sigma
    scores["_sigma_floor"] = floor
    scores["_assertions_passed"] = passed
    scores["_assertions_total"] = total
    return deploy


def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    want_json = "--json" in sys.argv
    max_iter = 100
    json_out = None
    args = []
    skip_next = False
    argv_tail = sys.argv[1:]
    for i, a in enumerate(argv_tail):
        if skip_next:
            skip_next = False
            continue
        if a == "--max":
            # N2: a missing/non-integer --max value used to raise IndexError/ValueError
            # uncaught, which exits 1 — the documented HOLD code. Validate explicitly instead.
            if i + 1 >= len(argv_tail):
                _usage_error("--max requires a value", want_json, json_out)
            raw = argv_tail[i + 1]
            try:
                max_iter = int(raw)
            except ValueError:
                _usage_error(f"--max value must be an integer, got {raw!r}", want_json, json_out)
            skip_next = True
            continue
        if a == "--json-out":
            # N2: same for a missing --json-out value.
            if i + 1 >= len(argv_tail):
                _usage_error("--json-out requires a path value", want_json, json_out)
            json_out = argv_tail[i + 1]
            skip_next = True
            continue
        if a.startswith("--") or a == "-v":
            continue
        args.append(a)

    if not args:
        _usage_error("no prompt-file argument given", want_json, json_out, show_usage=True)

    # WIX-EVAL-004: an unexpected exception during scoring/fixing/saving is neither DEPLOY nor
    # HOLD — the prompt was never fully scored, so it must not exit 1 and collide with a clean
    # HOLD (previously a crash and a HOLD were indistinguishable from the exit code alone).
    try:
        scores = run(args[0], max_iterations=max_iter, verbose=verbose, want_json=want_json, json_out=json_out)
    except SystemExit:
        raise
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"Error: convergence crashed unexpectedly ({msg})", file=sys.stderr)
        _emit_machine_verdict(
            _verdict_payload(exit_code=EXIT_INTERNAL_ERROR, error=msg),
            want_json, json_out)
        sys.exit(EXIT_INTERNAL_ERROR)

    # WIX-EVAL-004: exit on the FULL DEPLOY bar _print_final stamped, not the score-only
    # is_deploy() gate. is_deploy() ignores sigma and the 8 SAT assertions, so using it here
    # let a run print "VERDICT: HOLD" and still exit 0 — which automation reads as DEPLOY.
    # _deploy is the verdict _print_final actually printed. Absent (no final report was
    # reached) is treated as HOLD: never assume success.
    #
    # N1: this is the ONLY place the machine verdict is emitted on the success path — once,
    # after run() has fully returned — so a later failure can never produce a second,
    # contradictory VERDICT_JSON/--json-out payload for the same process exit.
    exit_code = EXIT_DEPLOY if scores.get("_deploy") is True else EXIT_HOLD
    _emit_machine_verdict(_verdict_payload_from_scores(scores, exit_code), want_json, json_out)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
