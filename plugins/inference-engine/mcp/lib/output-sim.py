#!/usr/bin/env python3
"""Wixie Output Simulator — dry-run prediction of LLM output structure. Stdlib only.

Parses a prompt folder to extract expected output structure, estimates token usage,
checks budget fit, and predicts quality — all without calling any API.

Usage:
    python output-sim.py <prompt-folder>
    python output-sim.py <prompt-folder> --verbose
"""
import sys, re, os, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(SCRIPT_DIR, "..", "models-registry.json")

# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_registry():
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("models", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def estimate_tokens(text):
    """Same heuristic as token-count.py — words * 1.3 + markup bonus."""
    words = len(text.split())
    code_blocks = len(re.findall(r'```', text))
    xml_tags = len(re.findall(r'<\w+', text))
    markup_bonus = (code_blocks + xml_tags) * 2
    return int(words * 1.3 + markup_bonus)


def bar(val, maxval, w=20):
    """ASCII progress bar, val out of maxval."""
    if maxval <= 0:
        return "." * w
    f = min(round((val / maxval) * w), w)
    return "#" * f + "." * (w - f)


def pct_bar(ratio, w=20):
    """ASCII bar from 0.0-1.0 ratio."""
    f = min(round(ratio * w), w)
    return "#" * f + "." * (w - f)


# ─── Prompt Parsing ──────────────────────────────────────────────────────────

def read_prompt_folder(folder):
    """Read prompt.xml and metadata.json from a prompt folder."""
    prompt_path = os.path.join(folder, "prompt.xml")
    meta_path = os.path.join(folder, "metadata.json")

    if not os.path.isfile(prompt_path):
        print(f"Error: prompt.xml not found in {folder}", file=sys.stderr)
        sys.exit(2)
    if not os.path.isfile(meta_path):
        print(f"Error: metadata.json not found in {folder}", file=sys.stderr)
        sys.exit(2)

    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read()
    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    return prompt, metadata


def extract_tag(text, tag):
    """Extract content between <tag>...</tag>."""
    m = re.search(rf'<{tag}>(.*?)</{tag}>', text, re.S)
    return m.group(1).strip() if m else ""


def extract_tag_any(text, tags):
    """Try multiple tag names, return first match."""
    for tag in tags:
        content = extract_tag(text, tag)
        if content:
            return content
    return ""


# ─── Structure Analysis ──────────────────────────────────────────────────────

def parse_output_format(prompt):
    """Parse <output_format> or <output_structure> to extract expected sections."""
    fmt = extract_tag_any(prompt, ["output_format", "output_structure"])
    if not fmt:
        return None

    # Identify layers with explicit numbers (## Layer 1: Name)
    layers = []
    for m in re.finditer(r'(?:^|\n)\s*#{1,3}\s+Layer\s+(\d+)\s*[:\-]\s*(.*?)$', fmt, re.M):
        layers.append({"num": int(m.group(1)), "name": m.group(2).strip()})

    # Detect expected layer count from phrases like "For each of the 10 layers"
    expected_layer_count = len(layers)
    count_match = re.search(r'(?:each|all)\s+(?:of\s+the\s+)?(\d+)\s+layers?', fmt, re.I)
    if count_match:
        expected_layer_count = max(expected_layer_count, int(count_match.group(1)))

    # Identify closing sections (### headings that are NOT layer templates)
    closing = []
    layer_names = {l["name"] for l in layers}
    for m in re.finditer(r'(?:^|\n)\s*(#{2,3})\s+(.+?)$', fmt, re.M):
        name = m.group(2).strip()
        # Skip layer headings: numbered layers AND template patterns like "Layer N:"
        if re.match(r'Layer\s+\d+\s*[:\-]', name):
            continue
        if re.match(r'Layer\s+\w+\s*[:\-]', name):
            continue  # catches "Layer N: [Name]" template
        if name in layer_names:
            continue
        if name:
            closing.append(name)

    # Per-layer elements expected
    per_layer_elements = []
    element_keywords = [
        ("prior_art", r'\b[Pp]rior\s+[Aa]rt\b'),
        ("options_table", r'\b[Oo]ptions?\s+[Cc]omparison\b|\b[Tt]able\b'),
        ("recommendation", r'\b[Rr]ecommend(?:ation|ed)?\b'),
        ("pitfall", r'\b[Pp]itfall\b'),
    ]
    for key, pat in element_keywords:
        if re.search(pat, fmt):
            per_layer_elements.append(key)

    # Detect numbered output steps (e.g., "1. marketplace.json", "2. All hook scripts")
    numbered_steps = re.findall(r'(?:^|\n)\s*(\d+)\.\s+(.+?)$', fmt, re.M)

    # Count expected tables
    table_indicators = len(re.findall(r'\|.*\|.*\|', fmt))
    table_mentions = len(re.findall(r'\b[Tt]able\b', fmt))

    return {
        "raw": fmt,
        "layers": layers,
        "expected_layer_count": expected_layer_count,
        "closing_sections": closing,
        "numbered_steps": numbered_steps,
        "per_layer_elements": per_layer_elements,
        "table_indicators": max(table_indicators, table_mentions),
    }


def parse_success_criteria(prompt):
    """Parse <success_criteria> tag into individual criteria."""
    sc = extract_tag(prompt, "success_criteria")
    if not sc:
        return []
    criteria = []
    for m in re.finditer(r'(\d+)\.\s*(.+?)(?=\n\d+\.|\Z)', sc, re.S):
        criteria.append({"num": int(m.group(1)), "text": m.group(2).strip()})
    return criteria


def parse_constraints(prompt):
    """Parse <constraints> tag into individual constraints."""
    ct = extract_tag(prompt, "constraints")
    if not ct:
        return []
    constraints = []
    for line in ct.split('\n'):
        line = line.strip()
        if line.startswith('-'):
            constraints.append(line[1:].strip())
    return constraints


def parse_instructions_layers(prompt):
    """Parse <instructions> to count how many layers/sections are requested."""
    inst = extract_tag(prompt, "instructions")
    if not inst:
        return []
    layers = []
    for m in re.finditer(r'\*\*Layer\s+(\d+)\s*[:\-]\s*(.*?)\*\*', inst):
        layers.append({"num": int(m.group(1)), "name": m.group(2).strip()})
    return layers


# ─── Output Skeleton Builder ─────────────────────────────────────────────────

def build_skeleton(fmt_info, inst_layers, metadata):
    """Build a structural map of what the output SHOULD look like."""
    lines = []
    layers = fmt_info["layers"] if fmt_info else []
    closing = fmt_info["closing_sections"] if fmt_info else []
    elements = fmt_info["per_layer_elements"] if fmt_info else []

    # Use instruction layers if output_format has none
    if not layers and inst_layers:
        layers = inst_layers

    # If still no explicit layers but expected_layer_count is set, generate placeholders
    if not layers and fmt_info and fmt_info.get("expected_layer_count", 0) > 0:
        layers = [{"num": i + 1, "name": "[title]"} for i in range(fmt_info["expected_layer_count"])]

    num_layers = len(layers)
    for layer in layers:
        lines.append(f"## Layer {layer['num']}: {layer['name'] or '[title]'}")
        if "prior_art" in elements:
            lines.append("**Prior art:** [paragraph]")
        if "options_table" in elements:
            lines.append("| Option | Strengths | Weaknesses | Real-World Precedent |")
            lines.append("| [row 1] | ... | ... | ... |")
            lines.append("| [row 2] | ... | ... | ... |")
            lines.append("| [row 3] | ... | ... | ... |")
        if "recommendation" in elements:
            lines.append("**Recommendation:** [paragraph]")
        if "pitfall" in elements:
            lines.append("**Pitfall:** [paragraph]")
        lines.append("---")
        lines.append("")

    for section in closing:
        lines.append(f"### {section}")
        lines.append("[table or paragraphs]")
        lines.append("")

    return "\n".join(lines), num_layers, len(closing)


# ─── Token Estimation for Expected Output ────────────────────────────────────

def estimate_output_tokens(num_layers, num_closing, per_layer_elements, metadata,
                           num_steps=0):
    """Estimate how many tokens the output will consume based on structure.

    Calibrated against real Opus 4.6 outputs on architecture/analysis prompts.
    Models tend to write more than the minimum — paragraphs are 3-5 sentences,
    tables have contextual notes, pitfalls include backstory.
    """
    # Tokens per element — calibrated for real model verbosity
    tokens_per_element = {
        "prior_art": 200,       # 1-2 paragraphs with system references
        "options_table": 500,   # 3-row table + column headers + contextual notes
        "recommendation": 250,  # 1 paragraph with justification and citations
        "pitfall": 200,         # 1 paragraph with specific project reference
    }
    base_per_layer = 80  # heading + separator + transitional text

    per_layer = base_per_layer + sum(tokens_per_element.get(e, 150) for e in per_layer_elements)
    layer_total = per_layer * num_layers

    # Closing sections are typically denser (tables, diagrams, summaries)
    closing_tokens = num_closing * 450

    # For step-based outputs (code gen), estimate per step
    step_tokens = num_steps * 800 if num_layers == 0 else 0  # code blocks are ~800 tokens avg

    # Add overhead for intro/conclusion/transitions
    overhead = 300

    total = layer_total + closing_tokens + step_tokens + overhead

    return total, per_layer


# ─── Risk Assessment ─────────────────────────────────────────────────────────

def assess_risks(num_layers, num_closing, est_tokens, max_tokens, success_criteria,
                 fmt_info, constraints, per_layer_elements, verbose):
    """Evaluate risks and predict which criteria might fail."""
    risks = []
    ok = []

    # Token budget
    if max_tokens <= 0:
        risks.append("[??] max_tokens not set in metadata.json — cannot verify budget")
    elif est_tokens > max_tokens:
        overshoot = ((est_tokens - max_tokens) / max_tokens) * 100
        risks.append(f"[!!] Estimated output ({est_tokens:,} tokens) EXCEEDS budget ({max_tokens:,}) by {overshoot:.0f}%")
    elif est_tokens > max_tokens * 0.85:
        risks.append(f"[!!] Tight budget — estimated output uses {est_tokens/max_tokens*100:.0f}% of max_tokens. Risk of truncation")
    else:
        headroom = ((max_tokens - est_tokens) / max_tokens) * 100
        ok.append(f"[OK] Token budget sufficient ({headroom:.0f}% headroom)")

    # Success criteria addressability
    criteria_risks = []
    for sc in success_criteria:
        text_lower = sc["text"].lower()
        # Check if the structure can satisfy common criteria patterns
        if "all" in text_lower and "layer" in text_lower:
            if num_layers < 1:
                criteria_risks.append(f"  Criterion {sc['num']}: requires layers but none found in format spec")
        if "table" in text_lower:
            if not fmt_info or fmt_info["table_indicators"] < 1:
                criteria_risks.append(f"  Criterion {sc['num']}: requires table(s) but format has no table structure")
        if "no contradiction" in text_lower:
            if num_layers > 8:
                criteria_risks.append(f"  Criterion {sc['num']}: contradiction risk increases with {num_layers} layers — model must track cross-references")

    if criteria_risks:
        for cr in criteria_risks:
            risks.append(f"[!!] {cr}")
    else:
        ok.append("[OK] All success criteria addressable")

    # Layer-specific risks
    if num_layers >= 8:
        risks.append(f"[!!] Layer {num_layers} has most content — may be truncated if model runs long on earlier layers")

    # Constraint complexity
    if len(constraints) > 8:
        risks.append(f"[!]  {len(constraints)} constraints — complex constraint set increases compliance difficulty")

    # Per-layer element coverage
    if len(per_layer_elements) >= 4:
        ok.append(f"[OK] Rich per-layer structure ({len(per_layer_elements)} elements/layer)")
    elif len(per_layer_elements) >= 2:
        ok.append(f"[OK] Adequate per-layer structure ({len(per_layer_elements)} elements/layer)")
    elif len(per_layer_elements) == 0 and num_layers > 0:
        risks.append("[!]  No per-layer element structure detected — output format may be underspecified")

    return ok, risks


# ─── Quality Prediction ──────────────────────────────────────────────────────

def predict_quality(num_layers, num_closing, per_layer_elements, success_criteria,
                    constraints, est_tokens, max_tokens, prompt, metadata):
    """Predict output quality score on a 1-10 scale.

    Calibrated so that a well-structured prompt with rich grounding scores
    ~8.5, not 10. A 10/10 would require verified execution data.
    """
    score = 5.0

    # Structure clarity bonus (max +1.5)
    if num_layers > 0:
        score += 0.7
    if num_closing > 0:
        score += 0.3
    if len(per_layer_elements) >= 3:
        score += 0.5
    elif len(per_layer_elements) >= 1:
        score += 0.25

    # Success criteria defined (max +0.7)
    if len(success_criteria) >= 5:
        score += 0.7
    elif len(success_criteria) >= 2:
        score += 0.4

    # Constraints defined (max +0.3)
    if len(constraints) >= 3:
        score += 0.3

    # Budget fitness (max +0.5 / min -1.5)
    if max_tokens > 0:
        ratio = est_tokens / max_tokens
        if ratio < 0.5:
            score += 0.5  # comfortable
        elif ratio < 0.8:
            score += 0.25
        elif ratio > 1.0:
            score -= 1.5  # over budget
        else:
            score -= 0.5  # tight

    # Prior art / grounding in prompt (max +0.5)
    prior_art = extract_tag_any(prompt, ["prior_art", "context"])
    if prior_art and len(prior_art.split()) > 200:
        score += 0.5  # rich grounding

    # Examples in prompt (max +0.3)
    examples = extract_tag_any(prompt, ["examples", "example"])
    if examples:
        score += 0.3

    # Edge cases / fallback defined (max +0.2)
    fallback = extract_tag_any(prompt, ["fallback", "edge_cases"])
    if fallback:
        score += 0.2

    # Complexity penalty — more layers = harder to maintain consistency
    if num_layers > 8:
        score -= 0.3
    if num_layers > 12:
        score -= 0.3

    return max(1.0, min(10.0, round(score, 1)))


# ─── Verbose Skeleton Renderer ───────────────────────────────────────────────

def render_skeleton(skeleton, title="SIMULATED OUTPUT SKELETON"):
    """Render the skeleton for --verbose mode."""
    lines = ["", f"  {title}", "  " + "-" * len(title)]
    for sline in skeleton.split("\n"):
        lines.append(f"  {sline}")
    lines.append("")
    return "\n".join(lines)


# ─── Main Render ──────────────────────────────────────────────────────────────

def render(prompt_name, model, num_layers, num_closing, per_layer_elements,
           est_tokens, max_tokens, ok_items, risk_items, quality, fmt_info,
           skeleton, verbose):
    """Render the final report."""
    lines = []
    w = 60

    lines.append("")
    lines.append("=" * w)
    lines.append("  WIXIE OUTPUT SIMULATOR")
    model_display = model or "unknown"
    lines.append(f"  Prompt: {prompt_name} | Model: {model_display}")
    lines.append("=" * w)
    lines.append("")

    # Expected structure
    num_steps = len(fmt_info.get("numbered_steps", [])) if fmt_info else 0
    total_sections = num_layers + num_closing + (num_steps if num_layers == 0 else 0)
    expected_tables = "0"
    if fmt_info:
        ti = fmt_info["table_indicators"]
        if num_layers > 0 and ti > 0:
            expected_tables = f"{num_layers}+ ({num_layers} per-layer + closing)"
        elif ti > 0:
            expected_tables = f"{ti}+"
    headroom_pct = ((max_tokens - est_tokens) / max_tokens * 100) if max_tokens > 0 else 0

    if num_layers > 0:
        lines.append(f"  Expected sections:       {total_sections} ({num_layers} layers + {num_closing} closing)")
    elif num_steps > 0:
        lines.append(f"  Expected sections:       {total_sections} ({num_steps} output steps)")
    else:
        lines.append(f"  Expected sections:       {total_sections}")
    lines.append(f"  Expected tables:         {expected_tables}")
    lines.append(f"  Expected tokens:         ~{est_tokens:,}")
    if max_tokens > 0:
        lines.append(f"  Token budget:            {max_tokens:,}")
        lines.append(f"  Budget headroom:         {headroom_pct:.0f}%")
    else:
        lines.append(f"  Token budget:            not set")
    lines.append("")

    # Structural forecast
    lines.append("  Structural forecast:")
    if num_layers > 0:
        lines.append(f"    Layers found in format:     {num_layers:>2}/{num_layers}  {pct_bar(1.0)}")
    else:
        lines.append(f"    Layers found in format:      0/?  {pct_bar(0.0)}")
    if num_closing > 0:
        lines.append(f"    Closing sections found:     {num_closing:>2}/{num_closing}  {pct_bar(1.0)}")
    elif num_steps > 0:
        lines.append(f"    Output steps found:         {num_steps:>2}/{num_steps}  {pct_bar(1.0)}")
    else:
        lines.append(f"    Closing sections found:      0/?  {pct_bar(0.0)}")
    elem_count = len(per_layer_elements)
    if elem_count > 0:
        lines.append(f"    Per-layer elements:         {elem_count:>2}/{elem_count}  {pct_bar(1.0)}")
    elif num_layers == 0:
        pass  # skip per-layer elements line when there are no layers
    else:
        lines.append(f"    Per-layer elements:          0/?  {pct_bar(0.0)}")
    lines.append("")

    # Risk assessment
    lines.append("  Risk assessment:")
    for item in ok_items:
        lines.append(f"    {item}")
    for item in risk_items:
        lines.append(f"    {item}")
    if not ok_items and not risk_items:
        lines.append("    [--] Insufficient data for risk assessment")
    lines.append("")

    # Quality prediction
    lines.append(f"  PREDICTED QUALITY:       {quality}/10")

    # Verbose: show skeleton
    if verbose:
        lines.append("")
        lines.append("-" * w)
        lines.append(render_skeleton(skeleton))

    lines.append("=" * w)
    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def resolve_folder(arg):
    """Resolve prompt folder from argument — accepts folder name or path."""
    if os.path.isdir(arg):
        return os.path.abspath(arg)
    # Try under prompts/ relative to project root
    project_root = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
    candidate = os.path.join(project_root, "prompts", arg)
    if os.path.isdir(candidate):
        return candidate
    print(f"Error: Prompt folder not found: {arg}", file=sys.stderr)
    print(f"  Tried: {arg}", file=sys.stderr)
    print(f"  Tried: {candidate}", file=sys.stderr)
    sys.exit(2)


def main():
    verbose = "--verbose" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not args:
        print("Usage: python output-sim.py <prompt-folder> [--verbose]", file=sys.stderr)
        print("       python output-sim.py redteam-ops-architecture --verbose", file=sys.stderr)
        sys.exit(2)

    folder = resolve_folder(args[0])
    prompt_name = os.path.basename(folder)

    # Read inputs
    prompt, metadata = read_prompt_folder(folder)
    registry = load_registry()

    # Extract model info
    model = metadata.get("target_model", "")
    max_tokens = metadata.get("config", {}).get("max_tokens", 0)

    # Parse prompt structure
    fmt_info = parse_output_format(prompt)
    success_criteria = parse_success_criteria(prompt)
    constraints = parse_constraints(prompt)
    inst_layers = parse_instructions_layers(prompt)

    # Determine layer/section counts
    # Priority: explicit layers in output_format > instruction layers > expected count
    if fmt_info and fmt_info["layers"]:
        layers = fmt_info["layers"]
    elif inst_layers:
        layers = inst_layers
    else:
        layers = []

    num_layers = len(layers)
    # If output_format says "for each of the N layers" but no explicit layers found,
    # use the expected count from the format spec
    if fmt_info and num_layers == 0 and fmt_info.get("expected_layer_count", 0) > 0:
        num_layers = fmt_info["expected_layer_count"]

    closing = fmt_info["closing_sections"] if fmt_info else []
    num_closing = len(closing)
    per_layer_elements = fmt_info["per_layer_elements"] if fmt_info else []

    # Build skeleton
    skeleton, _, _ = build_skeleton(fmt_info, inst_layers, metadata)

    # Estimate output tokens
    num_steps = len(fmt_info.get("numbered_steps", [])) if fmt_info else 0
    est_tokens, per_layer_tokens = estimate_output_tokens(
        num_layers, num_closing, per_layer_elements, metadata, num_steps
    )

    # Run risk assessment
    ok_items, risk_items = assess_risks(
        num_layers, num_closing, est_tokens, max_tokens,
        success_criteria, fmt_info, constraints, per_layer_elements, verbose
    )

    # Predict quality
    quality = predict_quality(
        num_layers, num_closing, per_layer_elements, success_criteria,
        constraints, est_tokens, max_tokens, prompt, metadata
    )

    # Render
    print(render(
        prompt_name, model, num_layers, num_closing, per_layer_elements,
        est_tokens, max_tokens, ok_items, risk_items, quality, fmt_info,
        skeleton, verbose
    ))

    # Exit code: 0 if no critical risks, 1 if any [!!] risks
    has_critical = any("[!!]" in r for r in risk_items)
    sys.exit(1 if has_critical else 0)


# ─── API for hybrid orchestrator ────────────────────────────────────────────────

def simulate(prompt_text, max_tokens=16384):
    """API wrapper: simulate output structure and return results dict."""
    fmt_info = parse_output_format(prompt_text)
    success_criteria = parse_success_criteria(prompt_text)
    constraints = parse_constraints(prompt_text)
    inst_layers = parse_instructions_layers(prompt_text)
    layers = (fmt_info["layers"] if fmt_info and fmt_info["layers"] else inst_layers) or []
    num_layers = len(layers)
    if fmt_info and num_layers == 0 and fmt_info.get("expected_layer_count", 0) > 0:
        num_layers = fmt_info["expected_layer_count"]
    closing = fmt_info["closing_sections"] if fmt_info else []
    per_layer_elements = fmt_info["per_layer_elements"] if fmt_info else []
    num_steps = len(fmt_info.get("numbered_steps", [])) if fmt_info else 0
    est_tokens, _ = estimate_output_tokens(num_layers, len(closing), per_layer_elements, {}, num_steps)
    headroom = round((1 - est_tokens / max_tokens) * 100) if max_tokens > 0 else 0
    ok_items, risk_items = assess_risks(num_layers, len(closing), est_tokens, max_tokens, success_criteria, fmt_info, constraints, per_layer_elements, False)
    quality = predict_quality(num_layers, len(closing), per_layer_elements, success_criteria, constraints, est_tokens, max_tokens, prompt_text, {})
    return {
        "num_layers": num_layers, "num_closing": len(closing),
        "per_layer_elements": len(per_layer_elements),
        "est_tokens": est_tokens, "max_tokens": max_tokens, "headroom_pct": headroom,
        "risks": risk_items, "ok": ok_items, "quality": quality,
        "has_critical": any("[!!]" in r for r in risk_items),
    }

def forecast(prompt_text, schema=None):
    """API wrapper: forecast output quality."""
    result = simulate(prompt_text)
    return {"predicted_quality": result["quality"], "risks": result["risks"], "headroom_pct": result["headroom_pct"]}


if __name__ == "__main__":
    main()
