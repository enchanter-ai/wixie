#!/usr/bin/env python3
"""Wixie Self-Check Inject -- inject a <self_check> rubric into any prompt.

The model validates its own output before finishing. Zero extra API cost --
the model does its own QA as part of the same generation.

Stdlib only. No API calls.

Usage:
    python self-check-inject.py <prompt-file> --inject         # inject self-check
    python self-check-inject.py <prompt-file> --dry-run        # preview injection
    python self-check-inject.py <prompt-file> --remove         # remove self-check
    python self-check-inject.py <prompt-file> --extract <file> # parse results from output
"""
import sys, re, os, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(SCRIPT_DIR, "..", "models-registry.json")

# ---- Token estimation (matches token-count.py) --------------------------------

def estimate_tokens(text):
    words = len(text.split())
    code_blocks = len(re.findall(r'```', text))
    xml_tags = len(re.findall(r'<\w+', text))
    markup_bonus = (code_blocks + xml_tags) * 2
    return int(words * 1.3 + markup_bonus)


def load_context_window():
    """Load the smallest common context window from the registry for the 5% check."""
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        windows = [
            info.get("context_window", 0)
            for info in data.get("models", {}).values()
            if info.get("context_window", 0) > 0
        ]
        # Use the most common window as default (200k for most models)
        if windows:
            return min(windows)
        return 200000
    except (FileNotFoundError, json.JSONDecodeError):
        return 200000


# ---- Prompt parsing -----------------------------------------------------------

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(2)


def write_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def extract_tag_content(text, tag):
    """Extract content between <tag> and </tag>. Returns None if not found."""
    pattern = rf'<{tag}>(.*?)</{tag}>'
    m = re.search(pattern, text, re.S)
    return m.group(1) if m else None


def parse_success_criteria(text):
    """Extract numbered criteria from <success_criteria>."""
    content = extract_tag_content(text, "success_criteria")
    if not content:
        return []
    criteria = []
    for m in re.finditer(r'^\s*(\d+)\.\s+(.+?)$', content, re.M):
        criteria.append(m.group(2).strip())
    return criteria


def parse_output_format(text):
    """Extract structural elements from <output_format>.

    Detects:
    - Repeated layer/section patterns (e.g. "## Layer N:" or "## Section N:")
    - Per-layer sub-elements (e.g. "**Prior art:**", "**Recommendation.**")
    - Closing sections (headers after the repeated pattern)
    """
    content = extract_tag_content(text, "output_format")
    if not content:
        return {"layers": None, "layer_label": None, "per_layer": [], "closing": []}

    # Detect repeated pattern: "## Layer N:" or "## Section N:" etc.
    layer_match = re.search(
        r'(?:each|all)\s+(?:of\s+)?(?:the\s+)?(\d+)\s+(\w+)',
        content, re.I
    )
    layer_count = None
    layer_label = None
    if layer_match:
        layer_count = int(layer_match.group(1))
        layer_label = layer_match.group(2).rstrip('s')  # "layers" -> "layer"

    # If not found via "each of the N X", look for "## X N:" pattern
    if layer_count is None:
        section_headers = re.findall(r'##\s+(\w+)\s+(\d+)\s*:', content)
        if section_headers:
            layer_label = section_headers[0][0]
            nums = [int(h[1]) for h in section_headers]
            layer_count = max(nums) if nums else None

    # If still not found, look for "N layers" or "N sections" phrasing
    if layer_count is None:
        count_match = re.search(r'(\d+)\s+(layer|section|step|part|phase|chapter)s?\b', content, re.I)
        if count_match:
            layer_count = int(count_match.group(1))
            layer_label = count_match.group(2)

    # Extract per-layer sub-elements (bold labels like **Prior art:** or **Recommendation.**)
    per_layer = []
    # Look for bold items that appear in the per-layer description
    per_layer_section = content
    closing_marker = re.search(r'(?:after|following)\s+(?:all|the)\s+\d+\s+\w+', content, re.I)
    if closing_marker:
        per_layer_section = content[:closing_marker.start()]
    for m in re.finditer(r'\*\*([^*]+?)[.:]\*\*', per_layer_section):
        label = m.group(1).strip()
        if label and label not in per_layer:
            per_layer.append(label)

    # Extract closing sections (### headers after the layers)
    closing = []
    if closing_marker:
        closing_section = content[closing_marker.start():]
    else:
        # Fall back: look for ### headers that aren't part of the repeated pattern
        closing_section = content
    for m in re.finditer(r'###\s+(.+?)$', closing_section, re.M):
        name = m.group(1).strip()
        if name:
            closing.append(name)

    return {
        "layers": layer_count,
        "layer_label": layer_label,
        "per_layer": per_layer,
        "closing": closing,
    }


def has_self_check(text):
    """Check if the prompt already contains a <self_check> section."""
    return bool(re.search(r'<self_check>', text))


# ---- Self-check generation ----------------------------------------------------

def generate_self_check(prompt_text):
    """Build the <self_check> XML section from parsed prompt structure."""
    structure = parse_output_format(prompt_text)
    criteria = parse_success_criteria(prompt_text)

    lines = []
    lines.append("<self_check>")
    lines.append("Before finalizing your response, verify each of these checks. "
                  "Append a brief compliance report at the end of your output.")
    lines.append("")

    # ---- Structural checks ----
    structural = []

    layer_count = structure["layers"]
    layer_label = structure["layer_label"] or "section"
    label_cap = layer_label.capitalize()

    if layer_count:
        structural.append(
            f'All {layer_count} {layer_label}s have a "## {label_cap} N:" header'
        )

    if structure["per_layer"]:
        items = ", ".join(structure["per_layer"])
        skip_note = " (or skip justification)" if len(structure["per_layer"]) > 2 else ""
        structural.append(
            f"Each {layer_label} has: {items}{skip_note}"
        )

    of_content = extract_tag_content(prompt_text, "output_format") or ""
    for section_name in structure["closing"]:
        # Find the paragraph under this ### header
        section_re = re.compile(
            rf'###\s+{re.escape(section_name)}\s*\n(.*?)(?=\n###|\Z)',
            re.S
        )
        section_match = section_re.search(of_content)
        detail = ""
        if section_match:
            body = section_match.group(1).strip()
            # Detect sub-items (bullet points, key phrases)
            sub_items = re.findall(r'[-*]\s+\*\*([^*]+)\*\*', body)
            if sub_items:
                detail = " with " + " and ".join(sub_items[:3])
            elif len(body) < 120:
                # Short description -- summarize
                first_line = body.split('\n')[0].strip()
                if first_line:
                    detail = " -- " + first_line
        structural.append(f'Closing section: "{section_name}" present{detail}')

    if structural:
        lines.append("Structural checks:")
        for check in structural:
            lines.append(f"- [ ] {check}")
        lines.append("")

    # ---- Content checks ----
    content_checks = []

    for criterion in criteria:
        # Clean up the criterion text for use as a checklist item
        # Remove leading "The output is complete when:" type prefixes
        c = criterion.strip()
        # Shorten overly long criteria
        if len(c) > 120:
            c = c[:117] + "..."
        content_checks.append(c)

    if content_checks:
        lines.append("Content checks:")
        for check in content_checks:
            lines.append(f"- [ ] {check}")
        lines.append("")

    # ---- Fallback if nothing was parsed ----
    if not structural and not content_checks:
        lines.append("General checks:")
        lines.append("- [ ] All sections requested in the prompt are present")
        lines.append("- [ ] Every recommendation names a specific technology or approach")
        lines.append("- [ ] No contradictions between sections")
        lines.append("- [ ] Examples or evidence provided where requested")
        lines.append("")

    # ---- Format instructions ----
    lines.append("Format: append a checklist at the end of your response:")
    lines.append("```")

    lines.append("## Self-Check")
    # Generate example entries
    if structural:
        lines.append(f"- [x] {structural[0]}")
        if len(structural) > 1:
            lines.append(f"- [x] {structural[1]}")
    if content_checks:
        lines.append(f"- [ ] MISSING: {content_checks[-1]}")
    if not structural and not content_checks:
        lines.append("- [x] All sections present")
        lines.append("- [ ] MISSING: evidence for recommendation in section 3")
    lines.append("...")
    lines.append("```")

    lines.append("</self_check>")

    return "\n".join(lines)


# ---- Injection / removal ------------------------------------------------------

def inject_self_check(prompt_text, self_check_block):
    """Inject <self_check> into the prompt.

    Placement: right before </success_criteria> if it exists,
    otherwise at the end of the prompt.
    If <self_check> already exists, replace it.
    """
    # Remove existing self_check if present
    prompt_text = remove_self_check_block(prompt_text)

    if '</success_criteria>' in prompt_text:
        return prompt_text.replace(
            '</success_criteria>',
            '\n' + self_check_block + '\n</success_criteria>'
        )
    else:
        return prompt_text.rstrip() + '\n\n' + self_check_block + '\n'


def remove_self_check_block(text):
    """Remove the <self_check>...</self_check> section from text."""
    # Remove the block and any surrounding blank lines it created
    cleaned = re.sub(r'\n*<self_check>.*?</self_check>\n*', '\n', text, flags=re.S)
    return cleaned


# ---- Extract mode: parse model output ------------------------------------------

def extract_self_check(output_text):
    """Parse the ## Self-Check section from model output.

    Returns (passed, failed, failed_items, total).
    """
    # Find the Self-Check section
    m = re.search(r'##\s*Self[- ]?Check\s*\n(.*)', output_text, re.S | re.I)
    if not m:
        return None

    section = m.group(1)

    passed_items = re.findall(r'- \[x\]\s+(.+)', section, re.I)
    failed_items = re.findall(r'- \[ \]\s+(.+)', section)

    passed = len(passed_items)
    failed = len(failed_items)
    total = passed + failed

    return {
        "passed": passed,
        "failed": failed,
        "total": total,
        "passed_items": passed_items,
        "failed_items": failed_items,
    }


def render_extract(results):
    """Render extraction results as ASCII report (matches self-eval.py style)."""
    if results is None:
        return "\n".join([
            "",
            "=" * 60,
            "  WIXIE SELF-CHECK RESULTS",
            "=" * 60,
            "",
            "  No ## Self-Check section found in the output.",
            "  The model may not have appended the compliance report.",
            "",
            "=" * 60,
        ])

    p = results["passed"]
    f = results["failed"]
    t = results["total"]
    pct = (p / t * 100) if t > 0 else 0

    def bar(val, total, w=20):
        filled = round((val / total) * w) if total > 0 else 0
        return "#" * filled + "." * (w - filled)

    if pct >= 100:
        verdict = "FULL PASS (100%)"
    elif pct >= 80:
        verdict = f"PARTIAL PASS ({pct:.0f}%)"
    elif pct >= 50:
        verdict = f"PARTIAL FAIL ({pct:.0f}%)"
    else:
        verdict = f"FAIL ({pct:.0f}%)"

    lines = [
        "",
        "=" * 60,
        "  WIXIE SELF-CHECK RESULTS",
        "=" * 60,
        "",
        f"  Checks passed:  {p:3d}/{t:<3d}  {bar(p, t)}",
        f"  Checks failed:  {f:3d}/{t:<3d}  {bar(f, t)}",
    ]

    if results["failed_items"]:
        lines.append("")
        lines.append("  Failed checks:")
        for item in results["failed_items"]:
            lines.append(f"    [ ] {item}")

    lines.append("")
    lines.append(f"  VERDICT: {verdict}")
    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


# ---- Token budget warning ------------------------------------------------------

def check_token_budget(original_text, injected_text):
    """Warn if injected section pushes prompt over 5% of smallest context window."""
    original_tokens = estimate_tokens(original_text)
    injected_tokens = estimate_tokens(injected_text)
    added_tokens = injected_tokens - original_tokens

    context_window = load_context_window()
    threshold = context_window * 0.05

    if added_tokens > threshold:
        pct = (added_tokens / context_window) * 100
        print(
            f"  [!] WARNING: Self-check adds ~{added_tokens:,} tokens "
            f"({pct:.1f}% of {context_window:,} context window).",
            file=sys.stderr
        )
        print(
            f"       This exceeds the 5% budget ({int(threshold):,} tokens).",
            file=sys.stderr
        )
        print(
            f"       Consider trimming the prompt or using a larger-window model.",
            file=sys.stderr
        )
        return True
    return False


# ---- CLI -----------------------------------------------------------------------

def parse_args():
    """Parse CLI arguments. Returns (prompt_path, mode, extract_path)."""
    args = sys.argv[1:]
    if not args:
        print_usage()
        sys.exit(2)

    prompt_path = None
    mode = None
    extract_path = None

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--inject":
            mode = "inject"
        elif a == "--dry-run":
            mode = "dry-run"
        elif a == "--remove":
            mode = "remove"
        elif a == "--extract":
            mode = "extract"
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                i += 1
                extract_path = args[i]
            else:
                print("Error: --extract requires an output file argument.", file=sys.stderr)
                sys.exit(2)
        elif not a.startswith("--") and prompt_path is None:
            prompt_path = a
        else:
            print(f"Error: Unknown argument: {a}", file=sys.stderr)
            sys.exit(2)
        i += 1

    if prompt_path is None:
        print("Error: No prompt file specified.", file=sys.stderr)
        print_usage()
        sys.exit(2)

    if mode is None:
        print("Error: No mode specified. Use --inject, --dry-run, --remove, or --extract.", file=sys.stderr)
        print_usage()
        sys.exit(2)

    return prompt_path, mode, extract_path


def print_usage():
    print("Usage:", file=sys.stderr)
    print("  python self-check-inject.py <prompt-file> --inject         # inject self-check", file=sys.stderr)
    print("  python self-check-inject.py <prompt-file> --dry-run        # preview injection", file=sys.stderr)
    print("  python self-check-inject.py <prompt-file> --remove         # remove self-check", file=sys.stderr)
    print("  python self-check-inject.py <prompt-file> --extract <file> # parse results", file=sys.stderr)


def main():
    prompt_path, mode, extract_path = parse_args()

    if mode == "extract":
        output_text = read_file(extract_path)
        results = extract_self_check(output_text)
        print(render_extract(results))
        if results is None:
            sys.exit(2)
        sys.exit(0 if results["failed"] == 0 else 1)

    prompt_text = read_file(prompt_path)

    if not prompt_text.strip():
        print("Error: Empty prompt file.", file=sys.stderr)
        sys.exit(2)

    if mode == "remove":
        if not has_self_check(prompt_text):
            print("No <self_check> section found. Nothing to remove.")
            sys.exit(0)
        cleaned = remove_self_check_block(prompt_text)
        write_file(prompt_path, cleaned)
        print(f"Removed <self_check> from {prompt_path}")
        sys.exit(0)

    # -- inject or dry-run --
    self_check_block = generate_self_check(prompt_text)

    if mode == "dry-run":
        print()
        print("=" * 60)
        print("  WIXIE SELF-CHECK INJECT (DRY RUN)")
        print("=" * 60)
        print()
        print(f"  Source:   {prompt_path}")
        already = has_self_check(prompt_text)
        print(f"  Exists:   {'Yes (will be replaced)' if already else 'No (will be added)'}")
        print()

        structure = parse_output_format(prompt_text)
        criteria = parse_success_criteria(prompt_text)

        if structure["layers"]:
            print(f"  Detected: {structure['layers']} {structure['layer_label']}s")
        if structure["per_layer"]:
            print(f"  Per-{structure['layer_label'] or 'section'}: {', '.join(structure['per_layer'])}")
        if structure["closing"]:
            print(f"  Closing:  {', '.join(structure['closing'])}")
        print(f"  Criteria: {len(criteria)} success criteria parsed")

        added_tokens = estimate_tokens(self_check_block)
        print(f"  Tokens:   ~{added_tokens:,} added by self-check")
        print()
        print("-" * 60)
        print(self_check_block)
        print("-" * 60)

        # Check budget
        injected = inject_self_check(prompt_text, self_check_block)
        check_token_budget(prompt_text, injected)

        print()
        print("  Use --inject to apply.")
        print()
        print("=" * 60)
        sys.exit(0)

    if mode == "inject":
        injected = inject_self_check(prompt_text, self_check_block)

        # Token budget warning
        check_token_budget(prompt_text, injected)

        write_file(prompt_path, injected)

        already = has_self_check(prompt_text)
        action = "Updated" if already else "Injected"

        print()
        print("=" * 60)
        print("  WIXIE SELF-CHECK INJECT")
        print("=" * 60)
        print()
        print(f"  {action} <self_check> in {prompt_path}")

        structure = parse_output_format(prompt_text)
        criteria = parse_success_criteria(prompt_text)

        structural_count = 0
        if structure["layers"]:
            structural_count += 1
        if structure["per_layer"]:
            structural_count += 1
        structural_count += len(structure["closing"])

        total_checks = structural_count + len(criteria)
        print(f"  Structural checks: {structural_count}")
        print(f"  Content checks:    {len(criteria)}")
        print(f"  Total checks:      {total_checks}")
        print()
        print("=" * 60)
        sys.exit(0)


# ─── API for hybrid orchestrator ────────────────────────────────────────────────

def inject(prompt_text):
    """API wrapper: inject self-check into prompt text and return modified text."""
    structure = parse_output_format(prompt_text)
    criteria = parse_success_criteria(prompt_text)
    block = generate_self_check(structure, criteria)
    return inject_self_check(prompt_text, block)

def extract(output_text):
    """API wrapper: extract self-check results from output and return dict."""
    return extract_self_check(output_text)


if __name__ == "__main__":
    main()
