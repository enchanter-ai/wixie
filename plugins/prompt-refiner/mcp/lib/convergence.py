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

Stdlib only. No pip installs.
"""
import sys, os, re, json, copy
from datetime import datetime
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

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
    return scores["overall"] >= 9.0 and all(scores[a] >= 7.0 for a in AXES)


# ─── Binary Assertions ────────────────────────────────────────────────────────

def run_assertions(text):
    """Binary pass/fail checks. More stable than numeric scores for detecting issues."""
    results = []
    tl = text.lower()

    results.append(("has_role", bool(re.search(r'\b(you are|act as|role:|your role|your job)\b', tl)),
                     "Prompt defines a role or persona"))
    results.append(("has_task", bool(re.search(r'\b(task:|objective:|goal:|your job|you will|you should|analyze|generate|create|build)\b', tl)),
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


# ─── Fix functions ─────────────────────────────────────────────────────────────

def fix_clarity(text):
    hedges = [(r'\bmaybe\s+', ''), (r'\bperhaps\s+', ''), (r'\bpossibly\s+', ''),
              (r'\bsomewhat\s+', ''), (r'\btry to\s+', ''), (r'\bif possible,?\s*', ''),
              (r'\bmight want to\s+', '')]
    for p, r in hedges:
        text = re.sub(p, r, text, flags=re.I)
    lines = text.split('\n')
    new = []
    for line in lines:
        if len(line.split()) > 50 and ('; ' in line or ', and ' in line):
            line = re.sub(r';\s+', '.\n', line, count=1)
        new.append(line)
    return '\n'.join(new)


def fix_completeness(text):
    tl = text.lower()
    if not re.search(r'\b(you are|act as|role:|your role)\b', tl):
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if line.strip() and not line.strip().startswith(('<', '#', '---')):
                lines.insert(i, "You are a domain expert.\n")
                break
        text = '\n'.join(lines)
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
        text = re.sub(f, '', text, flags=re.I)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = '\n'.join(line.rstrip() for line in text.split('\n'))
    return text


def fix_model_fit(text):
    tl = text.lower()
    claude = bool(re.search(r'\b(claude|anthropic)\b|<(instructions|context|example)>', tl))
    gpt = bool(re.search(r'\b(gpt-4|gpt-5|openai|chatgpt)\b', tl))
    oseries = bool(re.search(r'\b(o1|o3|o4-mini|o-series)\b', tl))
    if claude and 'think thoroughly' not in tl:
        text = re.sub(r'(</instructions>)', '\nThink thoroughly before responding.\n\\1', text, count=1)
        if '</instructions>' not in text:
            text += "\n\nThink thoroughly before responding.\n"
        text = re.sub(r'\bthink step by step\b', 'think thoroughly', text, flags=re.I)
    if gpt and not re.search(r'\b(step by step|think through)\b', tl):
        text += "\n\nThink step by step through your analysis before providing the final answer.\n"
    if oseries:
        text = re.sub(r'\n.*think step by step.*\n', '\n', text, flags=re.I)
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

def run(prompt_path, max_iterations=100, verbose=False):
    if not os.path.isfile(prompt_path):
        print(f"Error: {prompt_path} not found", file=sys.stderr)
        sys.exit(2)

    with open(prompt_path, "r", encoding="utf-8") as f:
        text = f.read()

    if not text.strip():
        print("Error: Empty prompt file.", file=sys.stderr)
        sys.exit(2)

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
    print(f"  Target: DEPLOY (overall >= 9.0, all axes >= 7.0)")
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

        # Check DEPLOY (scores + all assertions pass)
        if is_deploy(scores) and len(failed) == 0:
            print(f"  Iteration {iteration}: {overall}/10 — DEPLOY ({len(passed)}/{len(assertions)} assertions pass)")
            _save(prompt_path, best_text)
            _print_final(scores, assertions, iteration)
            save_learnings(prompt_dir, learnings, prev_learnings, best_text)
            return scores

        # Check DEPLOY by scores only (assertions are bonus)
        if is_deploy(scores):
            print(f"  Iteration {iteration}: {overall}/10 — DEPLOY (scores OK, {len(failed)} assertion(s) remaining)")
            _save(prompt_path, best_text)
            _print_final(scores, assertions, iteration)
            save_learnings(prompt_dir, learnings, prev_learnings, best_text)
            return scores

        # Plateau detection
        if len(history) >= 3 and history[-1] == history[-2] == history[-3]:
            plateau_count += 1
            if plateau_count >= 1:
                print(f"  Iteration {iteration}: {overall}/10 — PLATEAU")
                _save(prompt_path, best_text)
                _print_final(scores, assertions, iteration)
                save_learnings(prompt_dir, learnings, prev_learnings, best_text)
                return scores

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

        if new_scores["overall"] < overall - 0.5:
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
    _save(prompt_path, best_text)
    scores = score_prompt(best_text)
    _print_final(scores, run_assertions(best_text), max_iterations)
    save_learnings(prompt_dir, learnings, prev_learnings, best_text)
    return scores


def _save(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _print_final(scores, assertions, iterations):
    print(f"\n{'=' * 60}")
    print(f"  FINAL SCORES (after {iterations} iteration{'s' if iterations != 1 else ''})")
    print(f"{'=' * 60}")
    for a in AXES:
        val = scores[a]
        pct = round((val / 10) * 20)
        bar = "#" * pct + "." * (20 - pct)
        print(f"  {(a + ':').ljust(22)}{val:4.0f}/10  {bar}")
    print(f"\n  {'OVERALL:'.ljust(22)}{scores['overall']:4.1f}/10")

    # Assertions summary
    passed = sum(1 for a in assertions if a[1])
    total = len(assertions)
    print(f"  {'ASSERTIONS:'.ljust(22)}{passed}/{total} pass")
    for name, ok, desc in assertions:
        print(f"    {'PASS' if ok else 'FAIL'}  {desc}")

    deploy = is_deploy(scores)
    print(f"\n  VERDICT: {'DEPLOY' if deploy else 'BEST EFFORT'}")
    print(f"{'=' * 60}\n")


def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    max_iter = 100
    args = []
    skip_next = False
    for i, a in enumerate(sys.argv[1:]):
        if skip_next:
            skip_next = False
            continue
        if a == "--max":
            max_iter = int(sys.argv[i + 2])
            skip_next = True
            continue
        if a.startswith("--") or a == "-v":
            continue
        args.append(a)

    if not args:
        print("Usage: python convergence.py <prompt-file> [--max N] [--verbose]", file=sys.stderr)
        sys.exit(2)

    scores = run(args[0], max_iterations=max_iter, verbose=verbose)
    sys.exit(0 if is_deploy(scores) else 1)


if __name__ == "__main__":
    main()
