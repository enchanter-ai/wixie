#!/usr/bin/env python3
"""Wixie Output Schema Validator — auto-generate structural schemas from prompt
output_format sections, then validate real outputs against them.

Two modes:
  --generate     Parse the prompt and create output-schema.json
  --validate F   Validate an output file against the schema

Usage:
    python output-schema.py <prompt-folder> --generate
    python output-schema.py <prompt-folder> --validate output.md
    python output-schema.py <prompt-folder> --generate --validate output.md

Stdlib only. No API calls.
"""
import sys, os, re, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Display helpers ────────────────────────────────────────────────────────────

RESET = ""
BOLD = ""
DIM = ""
GREEN = ""
RED = ""
YELLOW = ""
CYAN = ""


def _init_colors():
    global RESET, BOLD, DIM, GREEN, RED, YELLOW, CYAN
    if sys.stdout.isatty():
        RESET = "\033[0m"
        BOLD = "\033[1m"
        DIM = "\033[2m"
        GREEN = "\033[32m"
        RED = "\033[31m"
        YELLOW = "\033[33m"
        CYAN = "\033[36m"


def bar(val, mx, width=20):
    filled = min(round((val / mx) * width) if mx else 0, width)
    return "#" * filled + "." * (width - filled)


# ─── Prompt loader ──────────────────────────────────────────────────────────────

def load_prompt(folder):
    """Load prompt text from a prompt folder."""
    folder = os.path.abspath(folder)
    for ext in ["xml", "md", "txt", "json"]:
        candidate = os.path.join(folder, f"prompt.{ext}")
        if os.path.isfile(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read(), folder
    print(f"ERROR: No prompt file found in {folder}", file=sys.stderr)
    sys.exit(1)


def extract_output_format(prompt_text):
    """Extract the <output_format> or <output_structure> section from the prompt."""
    for tag in ["output_format", "output_structure"]:
        match = re.search(rf"<{tag}>(.*?)</{tag}>", prompt_text, re.S)
        if match:
            return match.group(1).strip()
    # Fallback: look for a markdown section titled "Output Format"
    match = re.search(r"(?:^|\n)##?\s+Output\s+Format\s*\n(.*?)(?=\n##?\s|\Z)", prompt_text, re.S | re.I)
    if match:
        return match.group(1).strip()
    return None


# ─── Schema generation ──────────────────────────────────────────────────────────

def _detect_header_pattern(line):
    """Turn a markdown header line into a regex pattern."""
    line = line.strip()
    # Step 1: Replace bracket placeholders like [Name] with a sentinel
    line = re.sub(r"\[.*?\]", "XBRACKETX", line)
    # Step 2: Replace standalone N that looks like a number placeholder
    # (preceded by space, followed by colon/space/end)
    line = re.sub(r"(?<=\s)N(?=\s|:|$)", "XDIGITX", line)
    # Step 3: Escape for regex (only affects . ^ $ * + ? { } [ ] \ | ( ) )
    pattern = re.escape(line)
    # Step 4: Restore sentinels with regex patterns
    pattern = pattern.replace("XBRACKETX", ".*")
    pattern = pattern.replace("XDIGITX", "\\d+")
    return pattern


def _normalize_marker_name(name):
    """Strip trailing punctuation from a marker name."""
    return name.rstrip(".:").strip()


# Common alternative names that models use for the same concept.
# Keys are normalized (lowercase, stripped punctuation).
MARKER_ALIASES = {
    "options comparison": ["Options table", "Options", "Comparison"],
    "prior art": ["Prior Art", "Prior art reference"],
    "recommendation": ["Recommended choice"],
    "pitfall": ["Critical pitfall", "Watch out"],
}


def _build_marker_pattern(name):
    """Build a flexible bold-marker regex that accepts the canonical name and common aliases.

    The pattern matches **Name**, **Name:**, **Name.**, and any alias variants,
    optionally followed by additional text before the closing **.
    """
    normalized = _normalize_marker_name(name)

    # For "Phase N (...)" markers, match just "Phase N" as the core pattern
    # and allow any trailing text.  The model may write "Phase 1: 2-week Sprint"
    # or "Phase 1 (2-week sprint):" or many other variations.
    phase_match = re.match(r"^(Phase\s+\d+)\b", normalized, re.I)
    if phase_match:
        core = phase_match.group(1)
        escaped = re.escape(core)
        return r"\*\*" + escaped + r"[^*]*\*\*"

    # Collect all variant names: the canonical name + any aliases
    variants = [normalized]
    lower = normalized.lower()
    if lower in MARKER_ALIASES:
        variants.extend(MARKER_ALIASES[lower])
    # Build alternation: each variant is escaped, then we allow optional trailing
    # punctuation/text before the closing **
    parts = []
    for v in variants:
        escaped = re.escape(v)
        parts.append(escaped)
    alternation = "|".join(parts)
    # [.:]*  — accept trailing colon, period, or nothing
    # (?:[^*]*)? — accept optional extra text (e.g., "Recommendation — Full Stack Verdict")
    pattern = r"\*\*(?:" + alternation + r")[.:]*(?:[^*]*)?\*\*"
    return pattern


def _detect_elements(block_text):
    """Detect required elements within a section description block."""
    elements = []
    seen_bold = set()

    # Detect bold markers
    for match in re.finditer(r"\*\*([^*]+?):?\*\*", block_text):
        inner = _normalize_marker_name(match.group(1).strip())
        if inner in seen_bold:
            continue
        seen_bold.add(inner)
        pattern = _build_marker_pattern(inner)
        elements.append({"type": "bold_marker", "pattern": pattern, "count": 1})

    # Detect table references
    table_indicators = [
        r"\btable\b", r"\bcolumns?:", r"\brow\b.*\bper\b", r"\bone row per\b",
    ]
    if any(re.search(p, block_text, re.I) for p in table_indicators):
        # Default: header + 1 data row = 2.  Only raise for explicit row counts
        # mentioned with "rows" (not "layers", "items", etc. which describe
        # how many *sections* repeat, not table rows).
        min_rows = 2
        row_match = re.search(r"(\d+)\s*(?:rows?|entries)\b", block_text, re.I)
        if row_match:
            min_rows = max(2, int(row_match.group(1)))
        # Check for "one row per layer" type patterns combined with known counts
        elements.append({"type": "table", "min_rows": min_rows})

    # Detect code block references
    code_indicators = [
        r"\bcode\s*block\b", r"```", r"\bformat:?\s*\n\s*```",
        r"\bexample\s+format\b", r"\bfollowing?\s+format\b",
    ]
    has_code_block = any(re.search(p, block_text, re.I) for p in code_indicators)
    if has_code_block:
        elements.append({"type": "code_block", "count": 1})

    # If the section is about diagrams, the model may produce a code block
    # (ASCII art) OR prose.  Add code_block if not already detected and lower
    # the prose threshold.
    is_diagram_section = bool(re.search(r"\bdiagram(?:ming)?\b", block_text, re.I))
    if is_diagram_section and not has_code_block:
        elements.append({"type": "code_block", "count": 1})

    # Detect paragraph / prose requirements.
    # Skip paragraph requirement for diagram sections — the model will typically
    # produce the diagram as a code block (ASCII art) with minimal surrounding prose.
    prose_indicators = [
        r"\bdescribe\b.*\bdetail\b", r"\benough\s+detail\b",
        r"\b\d+-paragraph\b", r"\b1-paragraph\b",
    ]
    if not is_diagram_section and any(re.search(p, block_text, re.I) for p in prose_indicators):
        min_words = 50
        word_match = re.search(r"(\d+)\s*words?", block_text, re.I)
        if word_match:
            min_words = int(word_match.group(1))
        elements.append({"type": "paragraph", "min_words": min_words})

    return elements


def generate_schema(prompt_text):
    """Parse the prompt's output_format section and generate a structural schema."""
    format_text = extract_output_format(prompt_text)
    if not format_text:
        print("ERROR: No <output_format> or <output_structure> section found in prompt.",
              file=sys.stderr)
        sys.exit(1)

    sections = []
    lines = format_text.split("\n")

    # ── Phase 1: Find all header patterns and their associated descriptions ──
    header_blocks = []
    current_header = None
    current_block = []

    for line in lines:
        header_match = re.match(r"^(#{1,4})\s+(.+)", line)
        if header_match:
            # Save previous block
            if current_header:
                header_blocks.append((current_header, "\n".join(current_block)))
            current_header = line.strip()
            current_block = []
        else:
            current_block.append(line)

    # Save last block
    if current_header:
        header_blocks.append((current_header, "\n".join(current_block)))

    # ── Phase 2: Build section entries ──
    # Check for a "for each of N" pattern that applies to numbered sections
    repeated_count = 1
    repeat_match = re.search(
        r"[Ff]or\s+each\s+(?:of\s+(?:the\s+)?)?(\d+)\s+(\w+)", format_text
    )
    if repeat_match:
        repeated_count = int(repeat_match.group(1))

    for header_line, block_text in header_blocks:
        pattern = _detect_header_pattern(header_line)
        elements = _detect_elements(block_text)

        # Determine expected count
        if "\\d+" in pattern:
            count = repeated_count
        else:
            count = 1

        section = {"pattern": pattern, "count": count}
        if elements:
            section["required_elements"] = elements

        sections.append(section)

    # ── Phase 3: Also scan the full prompt for additional structural hints ──
    # Look for bold markers mentioned in <instructions> that describe per-section elements.
    # Only enrich numbered (repeated) sections that have NO elements from Phase 2,
    # since the output_format section's own markers are the authoritative source.
    instructions_match = re.search(r"<instructions>(.*?)</instructions>", prompt_text, re.S)
    if instructions_match:
        instructions_text = instructions_match.group(1)
        # Find "Provide these N elements for each layer" type blocks
        elements_block = re.search(
            r"[Pp]rovide\s+these\s+\w+\s+elements?.*?:\s*\n((?:\s*\d+\.\s+\*\*.*?\n)+)",
            instructions_text, re.S
        )
        if elements_block:
            per_layer_elements = _detect_elements(elements_block.group(1))
            for section in sections:
                if "\\d+" in section["pattern"] and not section.get("required_elements"):
                    section["required_elements"] = list(per_layer_elements)

    schema = {"sections": sections}
    return schema


# ─── Schema persistence ─────────────────────────────────────────────────────────

def save_schema(schema, folder):
    path = os.path.join(folder, "output-schema.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    return path


def load_schema(folder):
    path = os.path.join(folder, "output-schema.json")
    if not os.path.isfile(path):
        print(f"ERROR: No output-schema.json found in {folder}.", file=sys.stderr)
        print("  Run with --generate first to create the schema.", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f), path


# ─── Validation engine ──────────────────────────────────────────────────────────

def _pattern_to_label(pattern, index=None):
    """Convert a regex pattern back to a readable label, optionally substituting a number."""
    label = pattern
    if index is not None:
        label = label.replace("\\d+", str(index), 1)
    else:
        label = label.replace("\\d+", "N")
    label = label.replace(".*", "[...]")
    return label


def _element_label(short_section_label, element):
    """Build a human-readable label for an element check."""
    etype = element.get("type", "?")
    if etype == "bold_marker":
        # Extract a readable name from the bold marker pattern
        marker_name = element.get("pattern", "")
        # Remove \*\* wrappers and regex anchors
        marker_name = re.sub(r"\\\*\\\*|\*\*", "", marker_name)
        # Extract just the first variant from alternation groups like (?:A|B|C)
        alt_match = re.search(r"\(\?:([^|)]+)", marker_name)
        if alt_match:
            marker_name = alt_match.group(1)
        # Remove remaining regex syntax
        marker_name = re.sub(r"\[\.:][*+]|\(\?\:[^)]*\)\?|\[\^[^\]]*\][*+]\?", "", marker_name)
        # Unescape remaining characters
        marker_name = re.sub(r"\\(.)", r"\1", marker_name)
        marker_name = marker_name.strip(":?.* ")
        return f"{short_section_label}: {marker_name}"
    return f"{short_section_label}: {etype}"


def _find_section_positions(output_text, pattern, expected_count):
    """Find all positions where a section header matches."""
    matches = []
    for m in re.finditer(pattern, output_text, re.M):
        matches.append(m.start())
    return matches


def _extract_section_body(output_text, start_pos):
    """Extract the body of a section from its header position to the next same-or-higher-level header."""
    # Find the header line at start_pos
    line_end = output_text.find("\n", start_pos)
    if line_end == -1:
        line_end = len(output_text)
    header_line = output_text[start_pos:line_end]

    # Determine header level
    level_match = re.match(r"^(#{1,6})\s", header_line)
    level = len(level_match.group(1)) if level_match else 2

    # Find next header of same or higher level
    rest = output_text[line_end:]
    next_header = re.search(r"^(#{1," + str(level) + r"})\s", rest, re.M)
    if next_header:
        end_pos = line_end + next_header.start()
    else:
        end_pos = len(output_text)

    return output_text[line_end:end_pos]


def _validate_element(body, element):
    """Validate a single required element against a section body. Returns (passed, detail)."""
    etype = element.get("type", "")

    if etype == "bold_marker":
        pattern = element.get("pattern", "")
        expected = element.get("count", 1)
        found = len(re.findall(pattern, body))
        if found >= expected:
            return True, f"marker found ({found}x)"
        return False, f"marker missing (found {found}, need {expected})"

    if etype == "table":
        min_rows = element.get("min_rows", 2)
        # A markdown table has rows starting with |
        table_rows = [l for l in body.split("\n") if l.strip().startswith("|")]
        # Subtract separator rows (e.g., |---|---|)
        data_rows = [
            r for r in table_rows
            if not re.match(r"^\s*\|[\s:|-]+\|\s*$", r)
        ]
        if len(data_rows) >= min_rows:
            return True, f"table with {len(data_rows)} rows"
        if data_rows:
            return False, f"table too small ({len(data_rows)} rows, need {min_rows})"
        return False, "table missing"

    if etype == "code_block":
        expected = element.get("count", 1)
        found = len(re.findall(r"```", body)) // 2  # opening + closing pairs
        if found >= expected:
            return True, f"code block found ({found}x)"
        return False, f"code block missing (found {found}, need {expected})"

    if etype == "paragraph":
        min_words = element.get("min_words", 50)
        # Count words in non-header, non-table, non-code prose
        prose_lines = []
        in_code = False
        for line in body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            if stripped.startswith("|") or stripped.startswith("#"):
                continue
            prose_lines.append(stripped)
        word_count = len(" ".join(prose_lines).split())
        if word_count >= min_words:
            return True, f"prose with {word_count} words"
        return False, f"prose too short ({word_count} words, need {min_words})"

    return True, f"unknown element type: {etype}"


def validate_output(output_text, schema):
    """Validate an output against the schema. Returns structured results."""
    sections = schema.get("sections", [])

    section_results = []
    element_results = []
    section_positions = {}  # pattern -> list of positions (for ordering check)

    total_sections = 0
    total_elements = 0
    passed_sections = 0
    passed_elements = 0

    for sec in sections:
        pattern = sec["pattern"]
        expected_count = sec.get("count", 1)
        positions = _find_section_positions(output_text, pattern, expected_count)
        found_count = len(positions)

        # For repeated sections (count > 1), check we have enough
        checks_needed = expected_count
        total_sections += checks_needed

        if found_count >= checks_needed:
            passed_sections += checks_needed
            for i in range(checks_needed):
                idx = (i + 1) if checks_needed > 1 else None
                label = _pattern_to_label(pattern, idx)
                section_results.append((True, label))
        else:
            passed_sections += found_count
            for i in range(found_count):
                idx = (i + 1) if checks_needed > 1 else None
                label = _pattern_to_label(pattern, idx)
                section_results.append((True, label))
            for i in range(found_count, checks_needed):
                idx = (i + 1) if checks_needed > 1 else None
                label = _pattern_to_label(pattern, idx)
                section_results.append((False, label))

        # Store positions for ordering check
        section_positions[pattern] = positions

        # Element validation: check elements in each found section
        required_elements = sec.get("required_elements", [])
        for idx, pos in enumerate(positions[:checks_needed]):
            body = _extract_section_body(output_text, pos)
            num = (idx + 1) if checks_needed > 1 else None
            section_label = _pattern_to_label(pattern, num)
            short_label = section_label.lstrip("#").strip()
            if len(short_label) > 35:
                short_label = short_label[:32] + "..."

            for elem in required_elements:
                total_elements += 1
                passed, detail = _validate_element(body, elem)
                if passed:
                    passed_elements += 1
                elem_label = _element_label(short_label, elem)
                element_results.append((passed, elem_label, detail))

        # For missing sections, count their elements as failed
        for idx in range(found_count, checks_needed):
            num = (idx + 1) if checks_needed > 1 else None
            section_label = _pattern_to_label(pattern, num)
            short_label = section_label.lstrip("#").strip()
            if len(short_label) > 35:
                short_label = short_label[:32] + "..."
            for elem in required_elements:
                total_elements += 1
                elem_label = _element_label(short_label, elem)
                element_results.append((False, elem_label, "section missing"))

    # ── Ordering check ──
    ordering_ok = True
    prev_max_pos = -1
    for sec in sections:
        positions = section_positions.get(sec["pattern"], [])
        if positions:
            min_pos = min(positions)
            if min_pos < prev_max_pos:
                ordering_ok = False
            prev_max_pos = max(max(positions), prev_max_pos)

    return {
        "section_results": section_results,
        "element_results": element_results,
        "total_sections": total_sections,
        "passed_sections": passed_sections,
        "total_elements": total_elements,
        "passed_elements": passed_elements,
        "ordering_ok": ordering_ok,
    }


# ─── Rendering ───────────────────────────────────────────────────────────────────

def render_generate(schema, schema_path):
    """Render the schema generation summary."""
    sections = schema.get("sections", [])
    total_elements = sum(
        len(s.get("required_elements", [])) * s.get("count", 1)
        for s in sections
    )
    total_section_checks = sum(s.get("count", 1) for s in sections)

    lines = [
        "",
        "=" * 60,
        f"  {BOLD}WIXIE OUTPUT SCHEMA GENERATOR{RESET}",
        "=" * 60,
        "",
        f"  Generated: {os.path.basename(schema_path)}",
        f"  Sections:  {len(sections)} patterns, {total_section_checks} expected matches",
        f"  Elements:  {total_elements} required elements",
        "",
    ]

    for sec in sections:
        pattern_display = sec["pattern"]
        # Simplify for display: replace regex patterns with readable placeholders
        pattern_display = pattern_display.replace("\\d+", "N")
        pattern_display = pattern_display.replace(".*", "[...]")
        count = sec.get("count", 1)
        elems = sec.get("required_elements", [])
        count_str = f" (x{count})" if count > 1 else ""
        lines.append(f"  {CYAN}{pattern_display}{count_str}{RESET}")
        for elem in elems:
            etype = elem.get("type", "?")
            detail = ""
            if etype == "bold_marker":
                marker_name = re.sub(r"\\?\*\\?\*", "", elem.get("pattern", ""))
                # Extract first variant from alternation groups
                alt_match = re.search(r"\(\?:([^|)]+)", marker_name)
                if alt_match:
                    marker_name = alt_match.group(1)
                marker_name = re.sub(r"\[\.:][*+]|\(\?\:[^)]*\)\?|\[\^[^\]]*\][*+]\?", "", marker_name)
                marker_name = re.sub(r"\\(.)", r"\1", marker_name)
                detail = f"  {marker_name.strip(':?.* ')}"
            elif etype == "table":
                detail = f"  min {elem.get('min_rows', 2)} rows"
            elif etype == "code_block":
                detail = f"  x{elem.get('count', 1)}"
            elif etype == "paragraph":
                detail = f"  min {elem.get('min_words', 50)} words"
            lines.append(f"    {DIM}{etype}{detail}{RESET}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def render_validate(results, schema_path):
    """Render the validation report."""
    sr = results["section_results"]
    er = results["element_results"]
    ts = results["total_sections"]
    ps = results["passed_sections"]
    te = results["total_elements"]
    pe = results["passed_elements"]
    ordering = results["ordering_ok"]

    schema_name = os.path.basename(schema_path)

    lines = [
        "",
        "=" * 60,
        f"  {BOLD}WIXIE OUTPUT SCHEMA VALIDATOR{RESET}",
        "=" * 60,
        "",
        f"  Schema: {schema_name} ({ts} sections, {te} elements)",
        "",
    ]

    # Section validation
    lines.append(f"  {BOLD}Section validation:{RESET}")
    for passed, label in sr:
        icon = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        status = "[found]" if passed else "[missing]"
        lines.append(f"    {icon}  {label} {DIM}{status}{RESET}")

    lines.append("")

    # Element validation
    if er:
        lines.append(f"  {BOLD}Element validation:{RESET}")
        for passed, label, detail in er:
            icon = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
            lines.append(f"    {icon}  {label} {DIM}{detail}{RESET}")
        lines.append("")

    # Ordering
    if not ordering:
        lines.append(f"  {YELLOW}WARNING:{RESET} Sections are out of expected order")
        lines.append("")

    # Summary
    sec_pct = round(ps / ts * 100) if ts else 0
    elem_pct = round(pe / te * 100) if te else 0

    lines.append(f"  Sections: {ps}/{ts} ({sec_pct}%)  {bar(ps, ts)}")
    if te:
        lines.append(f"  Elements: {pe}/{te} ({elem_pct}%)  {bar(pe, te)}")

    # Verdict
    lines.append("")
    missing_sections = ts - ps
    missing_elements = te - pe
    if missing_sections == 0 and missing_elements == 0 and ordering:
        lines.append(f"  {GREEN}{BOLD}VERDICT: PASS{RESET}")
    else:
        details = []
        if missing_sections:
            details.append(f"{missing_sections} section{'s' if missing_sections != 1 else ''} missing")
        if missing_elements:
            details.append(f"{missing_elements} element{'s' if missing_elements != 1 else ''} missing")
        if not ordering:
            details.append("sections out of order")
        lines.append(f"  {RED}{BOLD}VERDICT: FAIL{RESET} ({', '.join(details)})")

    lines.append("=" * 60)
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    _init_colors()

    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    folder = args[0]
    do_generate = "--generate" in args
    validate_file = None
    if "--validate" in args:
        vi = args.index("--validate")
        if vi + 1 >= len(args):
            print("ERROR: --validate requires an output file argument.", file=sys.stderr)
            sys.exit(2)
        validate_file = args[vi + 1]

    if not do_generate and not validate_file:
        print("ERROR: Specify --generate, --validate <file>, or both.", file=sys.stderr)
        sys.exit(2)

    if not os.path.isdir(folder):
        print(f"ERROR: {folder} is not a directory.", file=sys.stderr)
        sys.exit(1)

    folder = os.path.abspath(folder)

    # ── Generate mode ──
    if do_generate:
        prompt_text, folder = load_prompt(folder)
        schema = generate_schema(prompt_text)
        schema_path = save_schema(schema, folder)
        print(render_generate(schema, schema_path))

    # ── Validate mode ──
    if validate_file:
        # Resolve validate_file relative to cwd if not absolute
        if not os.path.isabs(validate_file):
            validate_file = os.path.join(os.getcwd(), validate_file)
        if not os.path.isfile(validate_file):
            # Also try relative to prompt folder
            alt_path = os.path.join(folder, os.path.basename(validate_file))
            if os.path.isfile(alt_path):
                validate_file = alt_path
            else:
                print(f"ERROR: Output file not found: {validate_file}", file=sys.stderr)
                sys.exit(1)

        with open(validate_file, "r", encoding="utf-8") as f:
            output_text = f.read()

        if not output_text.strip():
            print("ERROR: Output file is empty.", file=sys.stderr)
            sys.exit(1)

        schema, schema_path = load_schema(folder)
        results = validate_output(output_text, schema)
        print(render_validate(results, schema_path))

        # Exit code
        if results["passed_sections"] < results["total_sections"] or \
           results["passed_elements"] < results["total_elements"] or \
           not results["ordering_ok"]:
            sys.exit(1)

    sys.exit(0)


# ─── API for hybrid orchestrator ────────────────────────────────────────────────

def validate(output_text, schema):
    """API wrapper: validate output against schema and return results dict."""
    return validate_output(output_text, schema)


if __name__ == "__main__":
    main()
