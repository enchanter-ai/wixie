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
    python convergence.py <prompt-file> --proposal-out <path>    # unannotated prompts: write the
                                                                  # fixers' proposals (never applied)
    python convergence.py <prompt-file> --no-shipped             # annotated file with no shipped pair

Editability (WIX-CONV-001, D15; shared/scripts/prompt_regions.py): fixers edit ONLY the bodies of
regions the prompt explicitly marks with "@wixie-editable/1" marker lines. A master lives at
<prompt folder>/editable/<shipped filename>; every write goes through prompt_regions.commit(),
which writes the master and the shipped file (= strip(master)) as a pair. A prompt with no
editable region (unannotated legacy prompt, header-only master) is scored and critiqued but never
written; a malformed annotation is never scored or written (HOLD / exit 1).

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
    2  Usage / bad input — no prompt-file argument, the file does not exist, the file is
       empty, an annotated file outside editable/ (without --no-shipped), a file under editable/
       with no header, a master without its shipped file or disagreeing with it, or a bad
       --proposal-out. Nothing was scored or written.
    3  Internal error — an unexpected exception was raised while scoring, fixing, or saving.
       Distinct from HOLD: HOLD means the prompt WAS scored and fell short; 3 means scoring
       did not complete at all, so a consumer must not read it as either DEPLOY or HOLD.

Stdlib only. No pip installs.
"""
import sys, os, re, json, copy, statistics, hashlib
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


# ─── Explicit editability contract (WIX-CONV-001, D15) ─────────────────────────
# Fixers may change ONLY the bodies of regions the prompt file explicitly marks as editable
# (prompt_regions.py: exact "@wixie-editable/1" marker lines with a per-file nonce). No
# Markdown/XML syntax is inferred. A fixer receives a FixContext -- the stripped view (for
# decisions only) and the region bodies ('\n'-normalised) -- and returns one new body text or
# None per region. It has no way to address anything outside a body. fix_document() rebuilds
# the file byte-exactly outside the bodies (prompt_regions.apply) and re-checks it with the
# single invariant (prompt_regions.verify); a candidate that fails is dropped.

def _load_prompt_regions():
    mod = sys.modules.get("prompt_regions")
    if mod is not None:
        return mod
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "prompt_regions", os.path.join(SCRIPT_DIR, "prompt_regions.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["prompt_regions"] = mod
    spec.loader.exec_module(mod)
    return mod


PR = _load_prompt_regions()


class FixContext(object):
    """What a fixer sees: `view` (the stripped document; decisions only) and `bodies`
    (prompt_regions.RegionView per region, in order)."""

    def __init__(self, view, bodies):
        self.view = view
        self.bodies = list(bodies)


def _norm_nl(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _editable_indices(ctx):
    return [i for i, b in enumerate(ctx.bodies) if b.editable]


def _prepend(ctx, new, addition):
    idx = _editable_indices(ctx)
    if not idx:
        return new
    i = idx[0]
    cur = new[i] if new[i] is not None else ctx.bodies[i].text
    new[i] = addition + cur
    return new


def _append(ctx, new, addition):
    """Append to the end of the LAST editable region (bodies are '' or end with '\\n')."""
    idx = _editable_indices(ctx)
    if not idx:
        return new
    i = idx[-1]
    cur = new[i] if new[i] is not None else ctx.bodies[i].text
    add = addition.lstrip('\n') if not cur else addition
    if not add.endswith('\n'):
        add += '\n'
    new[i] = cur + add
    return new


def _map_bodies(ctx, fn):
    out = []
    for b in ctx.bodies:
        if not b.editable:
            out.append(None)
            continue
        t = fn(b.text)
        out.append(t if t != b.text else None)
    return out


# ─── Fix functions (body level) ────────────────────────────────────────────────

_HEDGE_RE = re.compile(
    r'\b(?:maybe|perhaps|possibly|somewhat|try to|might want to)(?:[ \t]+|(?=\n)|\Z)'
    r'|\bif possible,?[ \t]*', re.I)
_SPLIT_RE = re.compile(r';[ \t]+')
_BLOCK_START_CHARS = ('>', '|', '{', '[', '```', '~~~')


def _clarity_body(text):
    text = _HEDGE_RE.sub('', text)
    lines = text.split('\n')
    for k, line in enumerate(lines):
        if len(line.split()) > 50 and ('; ' in line or ', and ' in line):
            for m in _SPLIT_RE.finditer(line):
                rest = line[m.end():]
                if not rest.strip() or rest.lstrip().startswith(_BLOCK_START_CHARS):
                    continue
                lines[k] = line[:m.start()] + '.\n' + rest
                break
    return '\n'.join(lines)


def fix_clarity(ctx):
    return _map_bodies(ctx, _clarity_body)


def fix_completeness(ctx):
    tl = ctx.view.lower()
    new = [None] * len(ctx.bodies)
    if not re.search(r'\b(you are|act as|role:|your role)\b', tl):
        role = "You are a domain expert.\n"
        if not re.search(r'\b(task:|objective:|goal:|your job|you will|you should)\b', tl):
            role = "You are a domain expert. Your job is to complete the following task.\n"
        new = _prepend(ctx, new, role + "\n")
    if not re.search(r'\b(output format|respond in|format:|json|xml|markdown|<output|<format)\b', tl):
        new = _append(ctx, new, "\nOutput format: structure your response clearly with headers and sections.\n")
    if not re.search(r"\b(do not|don't|never|must not|avoid)\b", tl):
        new = _append(ctx, new, "Do not include information you are unsure about.\n")
    return new


_FILLER_RE = re.compile(
    r"it's worth noting that[ \t]*|please note that[ \t]*|as an AI,?[ \t]*|I want you to[ \t]*"
    r"|I need you to[ \t]*|please make sure[ \t]*(?:to[ \t]*)?|it is important to note that[ \t]*"
    r"|keep in mind that[ \t]*|I would like you to[ \t]*|please ensure that[ \t]*"
    r"|in order to(?:[ \t]+|(?=\n))", re.I)
_BLANK_RUN_RE = re.compile(r'\n{3,}')
_TRAILING_WS_RE = re.compile(r'[ \t]+$', re.M)


def _efficiency_body(text):
    text = _FILLER_RE.sub('', text)
    text = _BLANK_RUN_RE.sub('\n\n', text)
    return _TRAILING_WS_RE.sub('', text)


def fix_efficiency(ctx):
    return _map_bodies(ctx, _efficiency_body)


def fix_model_fit(ctx):
    tl = ctx.view.lower()
    claude = bool(re.search(r'\b(claude|anthropic)\b|<(instructions|context|example)>', tl))
    gpt = bool(re.search(r'\b(gpt-4|gpt-5|openai|chatgpt)\b', tl))
    oseries = bool(re.search(r'\b(o1|o3|o4-mini|o-series)\b', tl))
    new = [None] * len(ctx.bodies)
    if claude and 'think thoroughly' not in tl:
        sub = re.compile(r'\bthink step by step\b', re.I)
        for i in _editable_indices(ctx):
            t = sub.sub('think thoroughly', ctx.bodies[i].text)
            if t != ctx.bodies[i].text:
                new[i] = t
        new = _append(ctx, new, "\nThink thoroughly before responding.\n")
    if gpt and not re.search(r'\b(step by step|think through)\b', tl):
        new = _append(ctx, new, "\nThink step by step through your analysis before providing the final answer.\n")
    if oseries:
        for i in _editable_indices(ctx):
            cur = new[i] if new[i] is not None else ctx.bodies[i].text
            kept = [ln for ln in cur.split('\n') if not re.search(r'think step by step', ln, re.I)]
            t = '\n'.join(kept)
            if t != cur:
                new[i] = t
    return new


def fix_failure_resilience(ctx):
    tl = ctx.view.lower()
    additions = []
    if not re.search(r'\bif\b.{0,30}\b(error|fail|cannot|unable|unclear|missing|invalid|empty)\b', tl):
        additions.append("If the input is empty or invalid, report the error clearly and explain what input is expected.")
    if not re.search(r'\b(edge case|corner case|special case|exception|unexpected)\b', tl):
        additions.append("Handle unexpected edge cases gracefully rather than failing silently.")
    if not re.search(r'\b(fallback|default to|if unsure|if you cannot|when in doubt)\b', tl):
        additions.append("If unsure about any information, state your uncertainty explicitly rather than guessing.")
    if not re.search(r'\b(validate|verify|check that|ensure that|confirm|if unclear)\b', tl):
        additions.append("Verify your output against the requirements before delivering the final response.")
    new = [None] * len(ctx.bodies)
    if additions:
        new = _append(ctx, new, '\n' + '\n'.join(additions) + '\n')
    return new


FIXERS = {
    "Clarity": fix_clarity,
    "Completeness": fix_completeness,
    "Efficiency": fix_efficiency,
    "Model Fit": fix_model_fit,
    "Failure Resilience": fix_failure_resilience,
}


def fix_document(raw, axis, orig_doc=None, fixer=None):
    """THE one entry point for applying a fixer (convergence loop, output-test try_offline_fix).
    `raw` is the working master bytes; returns new bytes, or `raw` unchanged when the file has
    no editable region, the fixer changes nothing, or the result breaks the contract (checked
    against `orig_doc`, the run's baseline, when given)."""
    doc = PR.parse(raw)
    if doc.status is not PR.Status.ANNOTATED or not doc.editable_regions:
        return raw
    fn = fixer or FIXERS.get(axis)
    if fn is None:
        return raw
    ctx = FixContext(_norm_nl(PR.view(raw)), PR.bodies(doc))
    try:
        cand = PR.apply(doc, fn(ctx))
        PR.verify(orig_doc or doc, cand)
    except PR.RegionViolation:
        return raw
    return cand


def propose_whole_text(text, axis):
    """Unannotated prompts: what the fixer WOULD do to the whole text, in memory only
    (proposal artifact; never written to the prompt, never verified against structure)."""
    ctx = FixContext(text, [PR.RegionView("__whole__", _norm_nl(text), True)])
    new = FIXERS[axis](ctx)[0]
    return text if new is None else new

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

def _sha(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _scoring_text(raw):
    """What the scorers see: the stripped view with line endings normalised (the scorers have
    always seen '\\n'-joined text)."""
    return _norm_nl(PR.view(raw))


def _check_proposal_out(proposal_out, prompt_path, shipped_path, prompt_folder, want_json, json_out):
    """--proposal-out may never alias the prompt: refuse any path inside the prompt folder
    (which contains the master and the shipped file) and any existing file (RC-14)."""
    real = os.path.realpath(proposal_out)
    folder = os.path.realpath(prompt_folder)
    if os.path.normcase(real).startswith(os.path.normcase(folder.rstrip("\\/") + os.sep)) \
            or os.path.normcase(real) == os.path.normcase(folder):
        _usage_error(f"--proposal-out {proposal_out} is inside the prompt folder {prompt_folder}; "
                     f"proposals belong in state/", want_json, json_out)
    if os.path.exists(proposal_out):
        for other in (prompt_path, shipped_path):
            if other and os.path.exists(other) and os.path.samefile(proposal_out, other):
                _usage_error(f"--proposal-out {proposal_out} is the prompt file", want_json, json_out)
        _usage_error(f"--proposal-out {proposal_out} already exists (never overwritten)", want_json, json_out)


def _learnings_paths(prompt_folder):
    return [os.path.join(prompt_folder, "learnings.json"), os.path.join(prompt_folder, "learnings.md")]


def _guard_auxiliary_writes(prompt_path, json_out, proposal_out, want_json):
    """WIX-CONV-001 fix round 1: every write this run makes outside prompt_regions.commit()
    (learnings.json / learnings.md, --json-out, --proposal-out) must not resolve to the input
    prompt, the master or the shipped file, and none of those may carry a reserved auxiliary
    name. Checked before any work; a refused --json-out is never written."""
    protected = [prompt_path]
    if PR.is_master(prompt_path):
        protected.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(prompt_path))),
                                      os.path.basename(prompt_path)))
    else:
        protected.append(PR.master_for(prompt_path))
    aux = _learnings_paths(PR.prompt_folder_of(prompt_path)) + [json_out, proposal_out]
    problems = PR.aux_write_problems(protected, aux)
    if problems:
        bad_json_out = bool(json_out) and any(json_out in pr for pr in problems)
        _usage_error("refusing to run: " + "; ".join(problems), want_json,
                     None if bad_json_out else json_out)


def _verify_committed_pair(prompt_path, shipped_path, extra):
    """Defence in depth before any exit that reports DEPLOY or mutation 'applied': the files on
    disk NOW must be a consistent pair whose hashes are the payload's. Returns '' or a reason."""
    m = PR.file_state(prompt_path)
    if m is None:
        return "master unreadable"
    if _sha(m[0]) != extra.get("master_sha256"):
        return "master on disk differs from the committed bytes (payload master_sha256)"
    if shipped_path is not None:
        s_ = PR.file_state(shipped_path)
        if s_ is None:
            return "shipped file unreadable"
        try:
            if PR.strip(m[0]) != s_[0]:
                return "shipped file on disk != strip(master)"
        except PR.RegionError as e:
            return f"master on disk no longer strips: {e}"
        if _sha(s_[0]) != extra.get("shipped_sha256"):
            return "shipped file on disk differs from the payload shipped_sha256"
    return ""


def _force_hold_after_check(scores, extra, reason):
    extra["structural_trip"] = True
    extra["post_check"] = reason
    scores["_deploy"] = False
    print(f"  POST-SAVE INTEGRITY CHECK FAILED: {reason}")
    print(f"  VERDICT: HOLD (final; overrides any verdict printed above -- WIX-CONV-001)")


def _write_proposal(proposal_out, raw, status, scores, assertions):
    import difflib
    text = _scoring_text(raw)
    per_axis = []
    for axis in sorted(AXES, key=lambda a: scores[a]):
        proposed = propose_whole_text(text, axis)
        diff = "".join(difflib.unified_diff(
            text.splitlines(True), proposed.splitlines(True), "current", f"proposed-{axis}"))
        per_axis.append({"axis": axis, "score": scores[axis], "diff": diff})
    doc = {
        "schema": "wixie-converge-proposal/1",
        "input_sha256": _sha(raw),
        "editability_status": status,
        "scores": {a: scores[a] for a in AXES + ["overall"]},
        "assertions": [{"name": n, "pass": bool(ok), "desc": d} for n, ok, d in assertions],
        "per_axis": per_axis,
        "note": ("unverified: may touch data; apply manually. The prompt has no explicit "
                 "editable region, so convergence does not write it (WIX-CONV-001 / D15)."),
    }
    os.makedirs(os.path.dirname(os.path.abspath(proposal_out)), exist_ok=True)
    with open(proposal_out, "x", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
    print(f"  Proposal written (not applied): {proposal_out}")


def run(prompt_path, max_iterations=100, verbose=False, want_json=False, json_out=None,
        proposal_out=None, no_shipped=False):
    _guard_auxiliary_writes(prompt_path, json_out, proposal_out, want_json)
    if not os.path.isfile(prompt_path):
        _usage_error(f"{prompt_path} not found", want_json, json_out)

    with open(prompt_path, "rb") as f:
        orig_raw = f.read()
    orig_state = PR.file_state(prompt_path)
    doc = PR.parse(orig_raw)
    is_master = PR.is_master(prompt_path)

    if doc.status is not PR.Status.MALFORMED and not PR.view(orig_raw).strip():
        _usage_error("Empty prompt file.", want_json, json_out)

    warnings = list(doc.warnings)
    shipped_path = None
    exp_shipped = None
    annotated_like = doc.status in (PR.Status.ANNOTATED, PR.Status.NO_REGIONS)
    if is_master:
        if doc.status is PR.Status.UNANNOTATED:
            _usage_error(f"{prompt_path} is under editable/ but carries no wixie-editable header: "
                         f"not a valid master", want_json, json_out)
        if annotated_like and not no_shipped:
            try:
                shipped_path = PR.shipped_for(prompt_path)
            except PR.RegionError as e:
                _usage_error(str(e), want_json, json_out)
            if not os.path.isfile(shipped_path):
                _usage_error(f"master {prompt_path} has no shipped file {shipped_path} "
                             f"(pass --no-shipped to write the master only)", want_json, json_out)
            with open(shipped_path, "rb") as f:
                exp_shipped = f.read()
            if exp_shipped != PR.strip(orig_raw):
                _usage_error(f"{shipped_path} != strip({prompt_path}): the shipped file and the master "
                             f"disagree; decide which one wins before converging", want_json, json_out)
    else:
        if annotated_like and not no_shipped:
            _usage_error(f"{prompt_path} is annotated but not under editable/; put the master at "
                         f"<prompt folder>/editable/<name> or pass --no-shipped", want_json, json_out)
        if doc.status is PR.Status.UNANNOTATED:
            m = PR.master_for(prompt_path)
            if m:
                warnings.append(f"master exists at {m}; run convergence on it (this file is read-only here)")
    for p in (prompt_path, shipped_path):
        if p:
            for stale in PR.stale_temp_files(p):
                warnings.append(f"stale temp file (from an interrupted commit): {stale}")

    prompt_folder = PR.prompt_folder_of(prompt_path)
    if proposal_out:
        _check_proposal_out(proposal_out, prompt_path, shipped_path, prompt_folder, want_json, json_out)

    owns_master = is_master or (no_shipped and annotated_like)
    editability = {
        "scheme": PR.SCHEME,
        "status": doc.status.value,
        "is_master": is_master,
        "regions": [r.id for r in doc.regions],
        "editable_regions": len(doc.editable_regions),
        "frozen_regions": {r.id: r.frozen_reason for r in doc.regions if not r.editable},
        "warnings": warnings,
        "code": doc.error.code if doc.error else None,
        "line": doc.error.line if doc.error else None,
    }
    extra = {
        "editability": editability,
        "mutation": "none",
        "structural_trip": False,
        "master_sha256": _sha(orig_raw) if owns_master else None,
        "shipped_sha256": _sha(exp_shipped) if owns_master else _sha(orig_raw),
    }

    print(f"\n{'=' * 60}")
    print(f"  WIXIE CONVERGENCE ENGINE (Gauss Method)")
    print(f"  Target: DEPLOY (heuristic bar — overall >= 9.0, all axes >= 7.0, sigma <= floor, 8/8 assertions)")
    print(f"  Editability: {doc.status.value}"
          + (f" — {len(doc.editable_regions)} editable region(s): {', '.join(r.id for r in doc.editable_regions)}"
             if doc.regions else ""))
    for w in warnings:
        print(f"  Warning: {w}")

    if doc.status is PR.Status.MALFORMED:
        print(f"  MALFORMED annotation: {doc.error} -- nothing was scored or written (WIX-CONV-001).")
        print(f"{'=' * 60}\n")
        print(f"\n  VERDICT: HOLD")
        return {"_deploy": False, "_scored": False, "_extra": extra}

    if doc.status is not PR.Status.ANNOTATED or not doc.editable_regions:
        return _run_readonly(prompt_path, prompt_folder, orig_raw, doc, proposal_out, extra, max_iterations,
                             orig_state)
    return _run_loop(prompt_path, prompt_folder, orig_raw, doc, shipped_path, exp_shipped,
                     max_iterations, verbose, extra)


def _run_readonly(prompt_path, prompt_folder, raw, doc, proposal_out, extra, max_iterations, orig_state):
    """UNANNOTATED / NO_REGIONS (D15): score, critique, optionally propose -- never write the
    prompt. DEPLOY is possible only when the unmodified input already meets the bar
    (mutation "none": nothing was written, the verdict is score-only on the exact input)."""
    print(f"  Mode: read-only (no explicit editable region) -- critique and proposals only")
    print(f"{'=' * 60}\n")
    prev_learnings = load_learnings(prompt_folder)
    text = _scoring_text(raw)
    scores = score_prompt(text)
    assertions = run_assertions(text)
    failed = [a for a in assertions if not a[1]]
    weakest = sorted(AXES, key=lambda a: scores[a])
    print(f"  Critique: weakest axes {', '.join(f'{a} {scores[a]}' for a in weakest[:3])}; "
          f"failed assertions: {', '.join(a[0] for a in failed) if failed else 'none'}")
    if proposal_out:
        _write_proposal(proposal_out, raw, doc.status.value, scores, assertions)
    _print_final(scores, assertions, 1, text)
    save_learnings(prompt_folder, [], prev_learnings, text)
    if PR.file_state(prompt_path) != orig_state:
        _force_hold_after_check(scores, extra, "the read-only input changed on disk during the run "
                                               "(bytes or mtime); nothing may write it")
    scores["_extra"] = extra
    return scores


def _run_loop(prompt_path, prompt_folder, orig_raw, doc, shipped_path, exp_shipped,
              max_iterations, verbose, extra):
    history = []
    plateau_count = 0
    best_score = 0
    cur = orig_raw
    best_raw = orig_raw
    learnings = []
    prev_learnings = load_learnings(prompt_folder)

    skip_axes = set()
    prioritize_axes = []
    neg_examples = prev_learnings.get("negative_examples", [])
    confidence = prev_learnings.get("confidence_scores", {})
    for p in prev_learnings.get("patterns", []):
        if p.get("type") == "unreliable":
            skip_axes.add(p.get("axis", ""))
        if p.get("type") == "reliable":
            prioritize_axes.append(p.get("axis", ""))
    for neg in neg_examples:
        neg_axis = neg.get("axis", "")
        neg_score = neg.get("score_at_attempt", 0)
        if neg_axis and neg_score > 0:
            skip_axes.add(neg_axis)  # conservative — skip any previously-failed axis

    num_sessions = len(prev_learnings.get("sessions", []))
    recs = prev_learnings.get("recommendations", [])
    print(f"  Max iterations: {max_iterations}")
    if num_sessions:
        print(f"  Prior knowledge: {num_sessions} sessions, {len(neg_examples)} negative examples, {len(confidence)} confidence scores")
    if skip_axes:
        print(f"  Skipping (learned): {', '.join(skip_axes)}")
    if prioritize_axes:
        print(f"  Prioritizing (learned): {', '.join(prioritize_axes)}")
    if recs:
        print(f"  Top recommendation: {recs[0][:70]}...")
    print(f"{'=' * 60}\n")

    def finish(candidate, stage, iteration, scores=None, assertions=None):
        """Every exit writes through prompt_regions.commit (verify -> atomic write of master
        and shipped -> re-read -> CAS restore on failure). A failure forces HOLD."""
        res = None
        ok = True
        try:
            res = PR.commit(doc, prompt_path, shipped_path, candidate, (orig_raw, exp_shipped))
        except (PR.RegionViolation, PR.RegionError, PR.ConcurrentModification, OSError) as e:
            ok = False
            print(f"  STRUCTURAL SAFETY TRIP at {stage} save ({type(e).__name__}: {e}) -- the files "
                  f"on disk were left as they were / restored; verdict forced to HOLD (WIX-CONV-001).")
            learnings.append(_structural_trip_entry(stage, iteration, best_score, str(e)))
            extra["structural_trip"] = True
        on_disk = candidate if ok else orig_raw
        if ok:
            extra["mutation"] = "applied" if res["written"] else "none"
            extra["master_sha256"] = res["master_sha256"]
            extra["shipped_sha256"] = res["shipped_sha256"]
        try:
            text = _scoring_text(on_disk)
            if not (ok and stage == "DEPLOY" and scores is not None):
                scores = score_prompt(text)
                assertions = run_assertions(text)
            _print_final(scores, assertions, iteration, text, force_hold=not ok)
            save_learnings(prompt_folder, learnings, prev_learnings, text)
            if ok and (scores.get("_deploy") or extra["mutation"] == "applied"):
                reason = _verify_committed_pair(prompt_path, shipped_path, extra)
                if reason:
                    _force_hold_after_check(scores, extra, reason)
                    if res is not None and res["written"]:
                        PR.cas_restore(prompt_path, candidate, orig_raw)
                        if shipped_path is not None:
                            PR.cas_restore(shipped_path, res["shipped"], exp_shipped)
        except BaseException:
            # Crash after a verified write (exit 3): restore the originals, but only where the
            # disk still holds this run's bytes (compare-then-replace, single writer; RC-08).
            if res is not None and res["written"]:
                PR.cas_restore(prompt_path, candidate, orig_raw)
                if shipped_path is not None:
                    PR.cas_restore(shipped_path, res["shipped"], exp_shipped)
            raise
        scores["_extra"] = extra
        return scores

    for iteration in range(1, max_iterations + 1):
        text = _scoring_text(cur)
        scores = score_prompt(text)
        overall = scores["overall"]
        history.append(overall)
        assertions = run_assertions(text)
        failed = [a for a in assertions if not a[1]]
        passed = [a for a in assertions if a[1]]

        if overall > best_score:
            best_score = overall
            best_raw = cur

        deploy, sigma, floor = deploy_verdict(scores, assertions, text)
        if deploy:
            print(f"  Iteration {iteration}: {overall}/10 — DEPLOY candidate ({len(passed)}/{len(assertions)} assertions, sigma {sigma:.2f} <= {floor:.2f})")
            return finish(cur, "DEPLOY", iteration, scores, assertions)

        if len(history) >= 3 and history[-1] == history[-2] == history[-3]:
            plateau_count += 1
            if plateau_count >= 1:
                print(f"  Iteration {iteration}: {overall}/10 — PLATEAU (HOLD — bar not met)")
                return finish(best_raw, "PLATEAU", iteration)

        axes_by_score = sorted(AXES, key=lambda a: scores[a])
        viable = [a for a in axes_by_score if a not in skip_axes or scores[a] < 5]
        if not viable:
            viable = axes_by_score
        if confidence:
            viable.sort(key=lambda a: (scores[a], -(confidence.get(a, 0.5))))
        weakest = viable[0]
        hypothesis = f"Fixing {weakest} (currently {scores[weakest]}/10) will improve overall from {overall}"

        if verbose or iteration <= 3 or iteration % 10 == 0:
            fail_names = ", ".join(a[0] for a in failed) if failed else "none"
            print(f"  Iteration {iteration}: {overall}/10 — hypothesis: fix {weakest} | failed assertions: {fail_names}")

        pre_fix = cur
        for axis in axes_by_score:
            if scores[axis] < 9.0 and axis in FIXERS:
                cur = fix_document(cur, axis, doc)
        for name, _ok, _desc in failed:
            if name == "has_role" and "Completeness" not in [axes_by_score[0]]:
                cur = fix_document(cur, "Completeness", doc)
            elif name == "has_edge_cases":
                cur = fix_document(cur, "Failure Resilience", doc)
            elif name == "no_hedge_words":
                cur = fix_document(cur, "Clarity", doc)
            elif name == "no_filler":
                cur = fix_document(cur, "Efficiency", doc)

        new_text = _scoring_text(cur)
        new_scores = score_prompt(new_text)
        new_assertions = run_assertions(new_text)
        new_failed = [a for a in new_assertions if not a[1]]

        reasoning = f"Targeted {weakest} ({scores[weakest]}/10) because it was the lowest axis."
        if weakest in skip_axes:
            reasoning += " (Historically unreliable but score was critically low.)"
        if failed:
            reasoning += f" Also had {len(failed)} failing assertion(s): {', '.join(a[0] for a in failed)}."

        # Region-contract gate (WIX-CONV-001): independent re-parse of the candidate against the
        # run's baseline, before and regardless of the score comparison.
        try:
            PR.verify(doc, cur)
            contract_ok = True
        except PR.RegionViolation as e:
            contract_ok = False
            contract_err = str(e)

        if not contract_ok:
            cur = pre_fix
            learnings.append({
                "iteration": iteration, "axis": weakest, "hypothesis": hypothesis,
                "reasoning": reasoning, "result": "reverted",
                "outcome": "REVERTED — region contract: the candidate changed bytes outside the explicit editable regions",
                "delta": new_scores["overall"] - overall, "start_score": overall, "end_score": overall,
                "why_failed": f"prompt_regions.verify rejected the candidate ({contract_err}); reverted "
                              f"regardless of score per WIX-CONV-001.",
            })
        elif new_scores["overall"] < overall - 0.5:
            cur = pre_fix
            delta = new_scores["overall"] - overall
            learnings.append({
                "iteration": iteration, "axis": weakest, "hypothesis": hypothesis,
                "reasoning": reasoning, "result": "reverted",
                "outcome": f"REVERTED — regression from {overall} to {new_scores['overall']}",
                "delta": delta, "start_score": overall, "end_score": overall,
                "why_failed": f"Fix caused {weakest} regression: {scores[weakest]}->{new_scores[weakest]}. Other axes affected: {', '.join(a for a in AXES if new_scores[a] < scores[a])}",
            })
        else:
            delta = new_scores["overall"] - overall
            axis_changes = {a: round(new_scores[a] - scores[a], 1) for a in AXES if new_scores[a] != scores[a]}
            learnings.append({
                "iteration": iteration, "axis": weakest, "hypothesis": hypothesis,
                "reasoning": reasoning, "result": "applied",
                "outcome": f"{'improved' if delta > 0 else 'unchanged'} ({overall} → {new_scores['overall']})",
                "delta": delta, "start_score": overall, "end_score": new_scores["overall"],
                "axis_changes": axis_changes,
                "assertions_fixed": [a[0] for a in failed if a[0] not in [nf[0] for nf in new_failed]],
            })

    print(f"\n  Max iterations ({max_iterations}) reached. Best: {best_score}/10")
    return finish(best_raw, "MAX-ITERATIONS", max_iterations)


def _structural_trip_entry(stage, iteration, score, detail=""):
    """learnings.json entry for an exit-path trip (distinguishable from a score regression and
    from a per-iteration region-contract revert)."""
    return {
        "iteration": iteration, "axis": "n/a", "hypothesis": "n/a",
        "reasoning": f"structural safety trip before {stage} save",
        "result": "reverted", "outcome": "REVERTED — region contract tripped at save time",
        "delta": 0, "start_score": score, "end_score": score,
        "why_failed": (f"prompt_regions.commit refused or failed at the {stage} exit ({detail}); the "
                       f"files on disk were kept or restored and the verdict forced to HOLD (WIX-CONV-001)."),
    }

def _verdict_payload(scores=None, deploy=False, sigma=0.0, floor=0.0, passed=0, total=0,
                      exit_code=EXIT_HOLD, error=None, extra=None, scored=True):
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
    elif not scored:
        payload["scored"] = False
    else:
        payload["scored"] = True
        payload["overall"] = scores.get("overall")
        payload["axes"] = {a: scores.get(a) for a in AXES}
        payload["sigma"] = round(sigma, 4)
        payload["sigma_floor"] = round(floor, 4)
        payload["sigma_pass"] = sigma <= floor
        payload["assertions_passed"] = passed
        payload["assertions_total"] = total
    if error is None and extra:
        payload.update(extra)
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
        extra=scores.get("_extra"),
        scored=scores.get("_scored", True),
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
        print("Usage: python convergence.py <prompt-file> [--max N] [--verbose] [--json] [--json-out PATH] "
              "[--proposal-out PATH] [--no-shipped]",
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
    proposal_out = None
    no_shipped = "--no-shipped" in sys.argv
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
        if a == "--proposal-out":
            if i + 1 >= len(argv_tail):
                _usage_error("--proposal-out requires a path value", want_json, json_out)
            proposal_out = argv_tail[i + 1]
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
        scores = run(args[0], max_iterations=max_iter, verbose=verbose, want_json=want_json, json_out=json_out,
                     proposal_out=proposal_out, no_shipped=no_shipped)
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
