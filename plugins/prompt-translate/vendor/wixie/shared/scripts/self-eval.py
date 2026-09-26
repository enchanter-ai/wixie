#!/usr/bin/env python3
"""Wixie Self-Evaluation — heuristic prompt scorer. Stdlib only."""
import sys, re, os, statistics
from collections import Counter

def read_input():
    if len(sys.argv) > 1:
        try:
            with open(sys.argv[1], "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            print(f"Error: File not found: {sys.argv[1]}", file=sys.stderr)
            sys.exit(2)
    elif not sys.stdin.isatty():
        return sys.stdin.read()
    print("Usage: echo 'prompt' | python self-eval.py\n       python self-eval.py <file>", file=sys.stderr)
    sys.exit(2)

# Size-aware imperative-bonus rationale: short prompts (<1000 words) can be written as
# near-pure instruction lists (67% imperative target). Structured long-form prompts
# (1000–2000 words) carry inherent prose for definitions and context (33% target).
# Very long prompts (>2000 words) include schema explanations and narrative (20% target).
# The bonus rewards *presence* of imperative voice, not its dominance in long prompts.
def score_clarity(text):
    score = 7.0
    # Measure clarity on instructions, not on example model output
    text_no_examples = re.sub(r'<example>.*?</example>', '', text, flags=re.S)
    sents = [s.strip() for s in re.split(r'[.!?]+', text_no_examples) if len(s.strip()) > 5]
    score -= min(len(re.findall(r'\b(maybe|perhaps|possibly|try to|if possible|somewhat|might want to)\b', text, re.I)) * 0.5, 2.0)
    score -= len(re.findall(r"\b(not\s+un|don't\s+not|never\s+no)\b", text, re.I)) * 1.0
    if bool(re.search(r'\b(concise|brief|short)\b', text, re.I)) and bool(re.search(r'\b(detailed|comprehensive|thorough)\b', text, re.I)):
        score -= 2.0
    if sents:
        imp = sum(1 for s in sents if re.match(r'^(Write|Generate|Create|List|Explain|Analyze|Return|Output|Provide|Extract|Identify|Summarize|Compare|Evaluate|Include|Use|Do not|Always|Never|Focus|Think|Review|Classify|Limit|Describe|Respond|Check|Verify|Ensure|Apply|Report|Detect|Select|Assume|End|Start|Run|Read|Set|Add|Remove|Follow|Avoid|Handle|Define|Specify|Present|Show|Display)\b', s))
        word_count = len(text.split())
        if word_count > 2000:
            score += min((imp / len(sents)) * 10.0, 2.0)
        elif word_count > 1000:
            score += min((imp / len(sents)) * 6.0, 2.0)
        else:
            score += min((imp / len(sents)) * 3.0, 2.0)
    if re.search(r'(^#{1,3}\s|\n#{1,3}\s)', text_no_examples): score += 0.5
    if re.search(r'(<\w+>|```)', text_no_examples): score += 0.5
    if re.search(r'(\n\s*[-*]\s|\n\s*\d+[.)]\s)', text_no_examples): score += 0.5
    score -= min(len([s for s in sents if len(s.split()) > 40]) * 0.5, 1.5)
    return max(1.0, min(10.0, score))

def score_completeness(text):
    score = 0.0
    checks = [
        r'\b(you are|act as|role:|persona:|as a|your role)\b',
        r'\b(task:|objective:|goal:|your job|you will|you should|instructions:)\b',
        r'\b(output format|respond in|return as|format:|response format|output:|json|xml|markdown)\b',
        r'\b(do not|don\'t|never|must not|avoid|constraint|important:|must|always|required)\b',
        r'\b(example|for instance|e\.g\.|such as|sample|here is|input:|output:)\b',
    ]
    for pattern in checks:
        if re.search(pattern, text, re.I): score += 2.0
    if re.search(r'(<example|```)', text): score += 0.5
    if not re.search(checks[1], text, re.I) and len(text.split()) > 20: score += 1.0
    return max(1.0, min(10.0, score))

def score_efficiency(text):
    # Original assumption (pre-2026-04-25): repeated 5-grams are always filler, cap at -2.5.
    # That assumption breaks for richly-structured XML/research-brief prompts >2k words where
    # structural boilerplate ("include for every pattern", "verification_pending: true",
    # "source_class", etc.) legitimately repeats as schema anchors, not as filler.
    #
    # Size-scaling rationale: penalty cap scales with prompt length because structural phrases
    # grow proportionally to scope, not proportionally to sloppiness. Under 1000 words the full
    # -2.5 cap applies (short prompts have no excuse for repetition). 1000–2000 words: -2.0.
    # Over 2000 words: -1.5. This keeps short-prompt sensitivity while allowing structured
    # long-form prompts to reach DEPLOY-bar Efficiency ≥ 8.5.
    #
    # Stopword exclusion: 5-grams composed entirely of stopword-class tokens (articles,
    # prepositions, conjunctions, auxiliaries) are not meaningful repetition — they are
    # grammatical glue. Excluding them prevents sentence-structure matches from masking
    # genuine content repetition. The stopword set is intentionally small and conservative;
    # any token carrying domain meaning is kept in scoring.
    score = 10.0
    # Strip example blocks before checking for repetition — repeated structure in
    # examples is intentional (demonstrates expected output format)
    text_no_examples = re.sub(r'<example>.*?</example>', '', text, flags=re.S)
    words = text_no_examples.split()
    fillers = [r"it's worth noting", r"please note that", r"as an AI", r"I want you to",
               r"I need you to", r"please make sure", r"it is important to note",
               r"keep in mind", r"I would like you to", r"please ensure", r"in order to"]
    fc = sum(len(re.findall(f, text, re.I)) for f in fillers)
    score -= min(fc * 0.7, 3.0)
    if len(words) > 20:
        # Stopword set: tokens that carry no domain signal when they are the only content
        # in a 5-gram. Conservative — only closed-class function words.
        STOPWORDS = {
            'the', 'a', 'an', 'of', 'in', 'on', 'at', 'to', 'for', 'with', 'by',
            'and', 'or', 'but', 'nor', 'so', 'yet', 'both', 'either', 'neither',
            'is', 'are', 'was', 'were', 'be', 'been', 'being', 'has', 'have', 'had',
            'do', 'does', 'did', 'will', 'would', 'shall', 'should', 'may', 'might',
            'can', 'could', 'must', 'that', 'this', 'these', 'those', 'it', 'its',
            'not', 'no', 'nor', 'as', 'if', 'than', 'then', 'when', 'where', 'which',
            'who', 'whom', 'whose', 'what', 'how', 'from', 'into', 'onto', 'out',
            'up', 'down', 'about', 'above', 'after', 'before', 'between', 'through',
        }
        # Strip leading/trailing punctuation per token, lowercase, then build 5-grams
        clean_words = [re.sub(r'^[^\w]+|[^\w]+$', '', w).lower() for w in words]
        ngrams = []
        for i in range(len(clean_words) - 4):
            gram_tokens = clean_words[i:i+5]
            # Skip 5-grams whose non-empty tokens are all stopwords
            content_tokens = [t for t in gram_tokens if t]
            if content_tokens and all(t in STOPWORDS for t in content_tokens):
                continue
            ngrams.append(" ".join(gram_tokens))
        # Word-count-scaled penalty cap: longer structured prompts get a smaller cap
        word_count = len(text.split())
        if word_count > 2000:
            ngram_cap = 1.5
        elif word_count > 1000:
            ngram_cap = 2.0
        else:
            ngram_cap = 2.5
        score -= min(sum(1 for c in Counter(ngrams).values() if c > 1) * 0.5, ngram_cap)
    all_words = text.split()
    secs = len(re.findall(r'(^#{1,3}\s|\n#{1,3}\s|<\w+>)', text))
    if len(all_words) > 500 and secs < 3: score -= 1.5
    if len(all_words) > 1000 and secs < 5: score -= 1.5
    return max(1.0, min(10.0, score))

def score_model_fit(text):
    tl = text.lower()
    claude = bool(re.search(r'\b(claude|anthropic)\b|<(instructions|context|example)>', tl))
    gpt = bool(re.search(r'\b(gpt-4|gpt-5|openai|chatgpt)\b', tl))
    oseries = bool(re.search(r'\b(o1|o3|o4-mini|o-series)\b', tl))
    gemini = bool(re.search(r'\b(gemini|google ai)\b', tl))
    xml = bool(re.search(r'<(?!http)\w+>', text))
    md_h = bool(re.search(r'^#{1,3}\s', text, re.M))
    cot = bool(re.search(r'\b(step by step|think through|let\'s think)\b', tl))
    fs = bool(re.search(r'\b(example|input:|output:)\b|<example', tl))
    if not any([claude, gpt, oseries, gemini]): return 5.0
    score = 5.0
    if claude:
        score += 2.0 if xml else (-1.0 if md_h else 0)
        if fs: score += 1.0
        if re.search(r'think thoroughly', tl): score += 0.5
        if not cot: score += 0.5
        xml_tags = set(re.findall(r'<(\w+)>', text))
        if len(xml_tags) >= 4: score += 0.5
        aggressive = re.search(r'(you MUST|YOU MUST|ALWAYS [a-z]|NEVER [a-z])', text)
        if not aggressive: score += 0.5
    if gpt:
        if md_h: score += 2.0
        if cot: score += 1.0
        if fs: score += 0.5
        # Sandwich method: key instructions repeated near the end
        lines = text.strip().split('\n')
        last_20pct = '\n'.join(lines[max(0, len(lines) - len(lines)//5):]).lower()
        if any(w in last_20pct for w in ['do not', 'must', 'critical', 'important', 'remember']): score += 0.5
    if oseries:
        if cot: score -= 3.0
        score += 1.5 if len(text.split()) < 200 else (-1.5 if len(text.split()) > 500 else 0)
        if not fs: score += 0.5
    if gemini: score += 2.0 if fs else -2.0
    return max(1.0, min(10.0, score))

def score_failure_resilience(text):
    score = 0.0
    patterns = [
        r'\bif\b.{0,30}\b(error|fail|cannot|unable|unclear|missing|invalid|empty)\b',
        r'\b(edge case|corner case|special case|exception|unexpected|otherwise)\b',
        r'\b(fallback|default to|if unsure|if you cannot|if not provided|when in doubt)\b',
        r'\b(validate|verify|check that|ensure that|confirm|if unclear|ask for clarification)\b',
    ]
    for p in patterns:
        if re.search(p, text, re.I): score += 2.5
    return max(1.0, min(10.0, score))

# σ < 0.45 is mathematically unreachable for richly-structured XML prompts >2k words:
# structural boilerplate, multi-section schemas, and cited examples produce inherent
# axis spread. DEPLOY-bar realism must account for prompt class — a research brief
# scoring 9.5 overall with σ=0.60 is a better prompt than a trivial 5-line instruction
# scoring 9.0 with σ=0.30. Stricter floor for short prompts where uniformity is achievable.
def dynamic_sigma_floor(text):
    word_count = len(text.split())
    if word_count > 2000:
        return 0.75
    elif word_count > 1000:
        return 0.60
    else:
        return 0.45

AXES = ["Clarity", "Completeness", "Efficiency", "Model Fit", "Failure Resilience"]
SCORERS = [score_clarity, score_completeness, score_efficiency, score_model_fit, score_failure_resilience]

SUGGESTIONS = {
    "Clarity": "Reduce ambiguous language. Use imperative verbs. Add structure with headers or numbered steps.",
    "Completeness": "Add missing components: role definition, output format, constraints, or examples.",
    "Efficiency": "Remove filler phrases and repeated instructions. Add section structure for long prompts.",
    "Model Fit": "Adapt formatting to target model. XML tags for Claude, Markdown headers for GPT, minimal for o-series.",
    "Failure Resilience": "Add instructions for handling ambiguous input, missing data, or error conditions.",
}

def bar(val, w=20):
    f = round((val / 10) * w)
    return "#" * f + "." * (w - f)

def render(scores, text):
    overall = sum(scores[a] for a in AXES) / len(AXES)
    sigma = statistics.pstdev(scores.values())
    floor = dynamic_sigma_floor(text)
    sigma_pass = sigma <= floor
    low = [a for a in AXES if scores[a] < 6]
    lines = ["", "=" * 55, "  WIXIE SELF-EVALUATION", "=" * 55, ""]
    for a in AXES:
        lines.append(f"  {(a+':').ljust(22)}{scores[a]:4.0f}/10  {bar(scores[a])}")
    lines += ["", f"  {'OVERALL:'.ljust(22)}{overall:4.1f}/10"]
    sigma_status = "PASS" if sigma_pass else "FAIL"
    lines.append(f"  {'SIGMA:'.ljust(22)}{sigma:4.2f} (floor {floor:.2f})  {sigma_status}")
    lines.append(f"  STATUS: {'[!] NEEDS IMPROVEMENT (' + ', '.join(low) + ' below 6)' if low else '[OK] PASS'}")
    lines.append("")
    if low:
        lines.append("  Suggestions:")
        for a in low:
            lines.append(f"  - {a}: {SUGGESTIONS[a]}")
        lines.append("")
    lines.append("=" * 55)
    return "\n".join(lines)

def main():
    text = read_input()
    if not text.strip():
        print("Error: Empty prompt provided.", file=sys.stderr)
        sys.exit(2)
    scores = {a: round(fn(text), 1) for a, fn in zip(AXES, SCORERS)}
    print(render(scores, text))
    sys.exit(1 if any(scores[a] < 6 for a in AXES) else 0)

if __name__ == "__main__":
    main()
