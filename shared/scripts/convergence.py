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
import sys, os, re, json, copy, statistics
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


# ─── Protected-region scanner (WIX-CONV-001) ────────────────────────────────────
# Fixers must never edit inside a "protected region": a fenced code block (any
# language, ``` or ~~~), a Markdown/GFM table, a blockquote, or an <example>...
# </example> block. This is one left-to-right, line-oriented tokenizer over the
# whole document -- not a set of independent regexes applied line by line -- so a
# construct nested inside another (a fenced code block inside an <example> block,
# a line that merely *looks* like a table divider or a blockquote marker while
# inside an open fence) is resolved once, in document order, instead of each
# regex re-discovering it from scratch and disagreeing. Fences and <example>
# blocks take priority: once one is open, nothing else is recognized until its
# own close marker (or end of document).

_FENCE_RE = re.compile(r'^(\s{0,3})(`{3,}|~{3,})(.*)$')
_TABLE_DELIM_RE = re.compile(r'^\s{0,3}\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$')
_BLOCKQUOTE_RE = re.compile(r'^\s{0,3}>')
_EXAMPLE_OPEN_RE = re.compile(r'<example\b[^>]*>', re.I)
_EXAMPLE_CLOSE_RE = re.compile(r'</example\s*>', re.I)

PROTECTED_KINDS = ("fenced_code", "example", "table", "blockquote")


def _line_spans(text):
    """(line_text_without_newline, start_offset, end_offset_incl_newline) for every
    physical line, so callers can map a line back to its position in `text`."""
    spans = []
    pos = 0
    for line in text.split('\n'):
        start = pos
        end = start + len(line)
        spans.append((line, start, end))
        pos = end + 1  # +1 for the '\n' the split() consumed
    return spans


def find_protected_regions(text):
    """Single left-to-right scan. Returns a sorted, non-overlapping list of
    (start, end, kind) character-offset spans (end exclusive), kind in
    PROTECTED_KINDS. An unterminated fence or <example> block runs to end of
    document rather than silently vanishing."""
    lines = _line_spans(text)
    n = len(lines)
    regions = []
    i = 0
    while i < n:
        line, start, end = lines[i]

        # 1) Fenced code block -- highest priority; swallows everything until its
        #    own matching close (same fence char, length >= opening length, and
        #    nothing but the fence itself on that line).
        m = _FENCE_RE.match(line)
        if m:
            fence_char = m.group(2)[0]
            fence_len = len(m.group(2))
            j = i + 1
            close_end = None
            while j < n:
                jline, jstart, jend = lines[j]
                jm = _FENCE_RE.match(jline)
                if jm and jm.group(2)[0] == fence_char and len(jm.group(2)) >= fence_len and not jm.group(3).strip():
                    close_end = jend
                    i = j
                    break
                j += 1
            if close_end is None:
                close_end = lines[n - 1][2]
                i = n - 1
            regions.append((start, close_end, "fenced_code"))
            i += 1
            continue

        # 2) <example> block -- second priority. The opening tag may share a
        #    line with other prose; only the tag-to-tag span is protected.
        om = _EXAMPLE_OPEN_RE.search(line)
        if om:
            region_start = start + om.start()
            close_m = _EXAMPLE_CLOSE_RE.search(line, om.end())
            if close_m:
                regions.append((region_start, start + close_m.end(), "example"))
                i += 1
                continue
            j = i + 1
            region_end = None
            while j < n:
                jline, jstart, jend = lines[j]
                cm = _EXAMPLE_CLOSE_RE.search(jline)
                if cm:
                    region_end = jstart + cm.end()
                    i = j
                    break
                j += 1
            if region_end is None:
                region_end = lines[n - 1][2]
                i = n - 1
            regions.append((region_start, region_end, "example"))
            i += 1
            continue

        # 3) Markdown/GFM table -- a '|' row immediately followed by a valid
        #    delimiter row, then any further contiguous non-blank '|' rows.
        if '|' in line and i + 1 < n:
            next_line = lines[i + 1][0]
            if '|' in next_line and _TABLE_DELIM_RE.match(next_line.strip()):
                region_end = lines[i + 1][2]
                j = i + 2
                while j < n and lines[j][0].strip() and '|' in lines[j][0]:
                    region_end = lines[j][2]
                    j += 1
                regions.append((start, region_end, "table"))
                i = j
                continue

        # 4) Blockquote -- a maximal run of '>' -prefixed lines.
        if _BLOCKQUOTE_RE.match(line):
            region_end = end
            j = i + 1
            while j < n and _BLOCKQUOTE_RE.match(lines[j][0]):
                region_end = lines[j][2]
                j += 1
            regions.append((start, region_end, "blockquote"))
            i = j
            continue

        i += 1

    regions.sort(key=lambda r: r[0])
    return regions


def _overlaps_any(s, e, spans):
    for rs, re_, _kind in spans:
        if s < re_ and e > rs:
            return True
    return False


def _protected_safe_sub(pattern, repl, text, spans, flags=0, count=0):
    """Like re.sub, but any match that overlaps a protected span is left
    untouched instead of substituted. Recomputing `spans` on the exact `text`
    passed in (not a stale/original copy) is the caller's responsibility."""
    if isinstance(pattern, str):
        pattern = re.compile(pattern, flags)
    out = []
    last = 0
    n_done = 0
    for m in pattern.finditer(text):
        if count and n_done >= count:
            break
        s, e = m.span()
        if _overlaps_any(s, e, spans):
            continue
        out.append(text[last:s])
        out.append(m.expand(repl) if isinstance(repl, str) else repl(m))
        last = e
        n_done += 1
    out.append(text[last:])
    return ''.join(out)


def _normalize_newlines(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def extract_protected_contents(text):
    """Ordered list of (kind, content) for every protected region in `text`,
    content newline-normalized. Comparing two of these lists is how two
    versions of a document are checked for structural equivalence -- same
    regions, same order, same content -- regardless of what legitimately
    changed in the prose around them."""
    norm = _normalize_newlines(text)
    return [(kind, norm[s:e]) for s, e, kind in find_protected_regions(norm)]


def protected_regions_equal(before_text, after_text):
    """True iff `after_text` preserves every protected region of `before_text`
    verbatim (line-ending-normalized), in the same order and count. This is
    the structural gate (WIX-CONV-001): a candidate that fails this check
    must be reverted regardless of its heuristic score."""
    return extract_protected_contents(before_text) == extract_protected_contents(after_text)


# ─── Fix functions ─────────────────────────────────────────────────────────────
# Every fixer below is protected-region-aware: it recomputes spans on its current
# `text` before each transformation and routes substitutions through
# `_protected_safe_sub` / explicit span checks so it never edits inside a fenced
# code block, table, blockquote, or <example> block. This is a best-effort
# guarantee inside the fixers themselves; the hard guarantee is the accept/revert
# gate in run() (protected_regions_equal), which reverts any candidate that slips
# through regardless of cause.

def fix_clarity(text):
    hedges = [(r'\bmaybe\s+', ''), (r'\bperhaps\s+', ''), (r'\bpossibly\s+', ''),
              (r'\bsomewhat\s+', ''), (r'\btry to\s+', ''), (r'\bif possible,?\s*', ''),
              (r'\bmight want to\s+', '')]
    for p, r in hedges:
        spans = find_protected_regions(text)
        text = _protected_safe_sub(p, r, text, spans, flags=re.I)
    spans = find_protected_regions(text)
    new = []
    for line, start, end in _line_spans(text):
        if (not _overlaps_any(start, end, spans)
                and len(line.split()) > 50 and ('; ' in line or ', and ' in line)):
            line = re.sub(r';\s+', '.\n', line, count=1)
        new.append(line)
    return '\n'.join(new)


def fix_completeness(text):
    tl = text.lower()
    if not re.search(r'\b(you are|act as|role:|your role)\b', tl):
        spans = find_protected_regions(text)
        for idx, (line, start, end) in enumerate(_line_spans(text)):
            if (line.strip() and not line.strip().startswith(('<', '#', '---'))
                    and not _overlaps_any(start, end, spans)):
                parts = text.split('\n')
                parts.insert(idx, "You are a domain expert.\n")
                text = '\n'.join(parts)
                break
    if not re.search(r'\b(task:|objective:|goal:|your job|you will|you should)\b', tl):
        text = text.replace("You are a domain expert.\n", "You are a domain expert. Your job is to complete the following task.\n", 1)
    if not re.search(r'\b(output format|respond in|format:|json|xml|markdown|<output|<format)\b', tl):
        text += "\n\nOutput format: structure your response clearly with headers and sections.\n"
    if not re.search(r"\b(do not|don't|never|must not|avoid)\b", tl):
        text += "\nDo not include information you are unsure about.\n"
    return text


def fix_efficiency(text):
    fillers = [r"it's worth noting that\s*", r"please note that\s*", r"as an AI,?\s*",
               r"I want you to\s*", r"I need you to\s*", r"please make sure\s*(to\s*)?",
               r"it is important to note that\s*", r"keep in mind that\s*",
               r"I would like you to\s*", r"please ensure that\s*", r"in order to\s+"]
    for f in fillers:
        spans = find_protected_regions(text)
        text = _protected_safe_sub(f, '', text, spans, flags=re.I)
    spans = find_protected_regions(text)
    text = _protected_safe_sub(r'\n{3,}', '\n\n', text, spans)
    spans = find_protected_regions(text)
    new_lines = []
    for line, start, end in _line_spans(text):
        if _overlaps_any(start, end, spans):
            new_lines.append(line)
        else:
            new_lines.append(line.rstrip())
    return '\n'.join(new_lines)


def fix_model_fit(text):
    tl = text.lower()
    claude = bool(re.search(r'\b(claude|anthropic)\b|<(instructions|context|example)>', tl))
    gpt = bool(re.search(r'\b(gpt-4|gpt-5|openai|chatgpt)\b', tl))
    oseries = bool(re.search(r'\b(o1|o3|o4-mini|o-series)\b', tl))
    if claude and 'think thoroughly' not in tl:
        spans = find_protected_regions(text)
        text = _protected_safe_sub(r'(</instructions>)', r'\nThink thoroughly before responding.\n\1', text, spans, count=1)
        if '</instructions>' not in text:
            text += "\n\nThink thoroughly before responding.\n"
        spans = find_protected_regions(text)
        text = _protected_safe_sub(r'\bthink step by step\b', 'think thoroughly', text, spans, flags=re.I)
    if gpt and not re.search(r'\b(step by step|think through)\b', tl):
        text += "\n\nThink step by step through your analysis before providing the final answer.\n"
    if oseries:
        spans = find_protected_regions(text)
        text = _protected_safe_sub(r'\n.*think step by step.*\n', '\n', text, spans, flags=re.I)
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
        if '<edge_cases>' in text:
            idx = text.index('</edge_cases>')
            text = text[:idx] + '\n' + '\n'.join(additions) + '\n' + text[idx:]
        else:
            text += '\n\n' + '\n'.join(additions) + '\n'
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

    text, newline, bom = _read_text_preserving(prompt_path)

    if not text.strip():
        _usage_error("Empty prompt file.", want_json, json_out)

    # WIX-CONV-001: the structural baseline every exit path is checked against.
    # Never reassigned -- it is the file's content the moment run() started.
    original_text = text

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
            # WIX-CONV-001 item 3: DEPLOY / exit 0 is impossible while a protected-region
            # check fails. The per-iteration gate below should already guarantee `text`'s
            # protected regions match `original_text`'s -- this is a defense-in-depth
            # backstop, checked again right before the DEPLOY save.
            safe_text, structurally_ok = _safe_text_for_save(original_text, text)
            if not structurally_ok:
                print(f"  Iteration {iteration}: STRUCTURAL SAFETY TRIP -- a protected region "
                      f"changed right before DEPLOY save. Falling back to the original, "
                      f"unmodified prompt and forcing HOLD (WIX-CONV-001).")
                safe_scores = score_prompt(safe_text)
                safe_assertions = run_assertions(safe_text)
                _save(prompt_path, safe_text, newline=newline, bom=bom)
                _print_final(safe_scores, safe_assertions, iteration, safe_text)
                learnings.append({
                    "iteration": iteration, "axis": "n/a",
                    "hypothesis": "n/a", "reasoning": "structural safety trip before DEPLOY save",
                    "result": "reverted", "outcome": "REVERTED — structural gate tripped at save time",
                    "delta": 0, "start_score": overall, "end_score": overall,
                    "why_failed": "A protected region (fenced code / table / blockquote / "
                                   "<example> block) differed from the input right before a "
                                   "DEPLOY save; forced HOLD instead of persisting damage.",
                })
                save_learnings(prompt_dir, learnings, prev_learnings, safe_text)
                return safe_scores
            print(f"  Iteration {iteration}: {overall}/10 — DEPLOY ({len(passed)}/{len(assertions)} assertions, sigma {sigma:.2f} <= {floor:.2f})")
            _save(prompt_path, text, newline=newline, bom=bom)
            _print_final(scores, assertions, iteration, text)
            save_learnings(prompt_dir, learnings, prev_learnings, text)
            return scores

        # Plateau detection — stalled with the bar unmet: report HOLD honestly, don't fake DEPLOY.
        if len(history) >= 3 and history[-1] == history[-2] == history[-3]:
            plateau_count += 1
            if plateau_count >= 1:
                print(f"  Iteration {iteration}: {overall}/10 — PLATEAU (HOLD — bar not met)")
                safe_best_text, structurally_ok = _safe_text_for_save(original_text, best_text)
                if not structurally_ok:
                    print("  STRUCTURAL SAFETY TRIP at PLATEAU save -- falling back to the "
                          "original, unmodified prompt (WIX-CONV-001).")
                safe_scores = score_prompt(safe_best_text)
                safe_assertions = run_assertions(safe_best_text)
                _save(prompt_path, safe_best_text, newline=newline, bom=bom)
                _print_final(safe_scores, safe_assertions, iteration, safe_best_text)
                save_learnings(prompt_dir, learnings, prev_learnings, safe_best_text)
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

        # Structural gate (WIX-CONV-001): a candidate whose protected regions (fenced
        # code, tables, blockquotes, <example> blocks) differ from the previous
        # iteration's text is reverted regardless of score -- this check runs BEFORE
        # and independently of the score-drop check below, so a candidate that raises
        # `overall` (or leaves it flat) is not exempt.
        structurally_ok = protected_regions_equal(pre_fix_text, text)

        if not structurally_ok:
            text = pre_fix_text
            delta = new_scores["overall"] - overall
            outcome = "REVERTED — structural gate: a protected region (fenced code / " \
                      "table / blockquote / <example> block) was changed by the fixer"
            learnings.append({
                "iteration": iteration, "axis": weakest, "hypothesis": hypothesis,
                "reasoning": reasoning,
                "result": "reverted", "outcome": outcome, "delta": delta,
                "start_score": overall, "end_score": overall,
                "why_failed": f"Fixer for {weakest} modified a protected region; reverted "
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
    safe_best_text, structurally_ok = _safe_text_for_save(original_text, best_text)
    if not structurally_ok:
        print("  STRUCTURAL SAFETY TRIP at MAX-ITERATIONS save -- falling back to the "
              "original, unmodified prompt (WIX-CONV-001).")
    _save(prompt_path, safe_best_text, newline=newline, bom=bom)
    scores = score_prompt(safe_best_text)
    _print_final(scores, run_assertions(safe_best_text), max_iterations, safe_best_text)
    save_learnings(prompt_dir, learnings, prev_learnings, safe_best_text)
    return scores


def _read_text_preserving(path):
    """Read a prompt file preserving its original line-ending convention and any
    UTF-8 BOM, so `_save` can restore both exactly (WIX-CONV-001 item 5). Internal
    processing always works on '\\n'-normalized text; `newline`/`bom` are threaded
    through to `_save`."""
    with open(path, "rb") as f:
        raw = f.read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    if bom:
        raw = raw[3:]
    text = raw.decode("utf-8")
    if "\r\n" in text:
        newline = "\r\n"
    elif "\r" in text:
        newline = "\r"
    else:
        newline = "\n"
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, newline, bom


def _safe_text_for_save(original_text, candidate_text):
    """Defense-in-depth backstop for every exit path (WIX-CONV-001 item 3). The
    per-iteration accept/revert gate should already guarantee `candidate_text`'s
    protected regions match `original_text`'s; this re-checks right before a write
    so that even a bug elsewhere can never persist structural damage -- it falls
    back to the untouched original instead. Returns (text_to_save, structurally_ok)."""
    if protected_regions_equal(original_text, candidate_text):
        return candidate_text, True
    return original_text, False


def _save(path, text, newline="\n", bom=False):
    """Write `text` back to `path`, restoring the original line-ending convention
    and BOM instead of letting Windows text-mode `open(..., "w")` silently rewrite
    every line ending to CRLF (WIX-CONV-001 item 5 / OBS-05)."""
    out = text.replace("\r\n", "\n").replace("\r", "\n")
    if newline != "\n":
        out = out.replace("\n", newline)
    data = out.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    with open(path, "wb") as f:
        f.write(data)


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


def _print_final(scores, assertions, iterations, text):
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
