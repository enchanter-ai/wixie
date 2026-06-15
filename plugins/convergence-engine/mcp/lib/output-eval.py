#!/usr/bin/env python3
"""Wixie Output Evaluator — heuristic-based output scorer. Stdlib only, zero API calls."""
import sys, re, os, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── CLI parsing ───────────────────────────────────────────────────────────────

def parse_args():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        print("""Usage:
    python output-eval.py <prompt-folder>                    # reads output-reference.md
    python output-eval.py <prompt-folder> --output <file>    # reads specific output file
    cat output.md | python output-eval.py <prompt-folder>    # reads from stdin
    python output-eval.py <prompt-folder> --verbose          # show per-layer detail""")
        sys.exit(0)

    folder = args[0]
    output_file = None
    verbose = False

    i = 1
    while i < len(args):
        if args[i] == "--output" and i + 1 < len(args):
            output_file = args[i + 1]
            i += 2
        elif args[i] == "--verbose":
            verbose = True
            i += 1
        else:
            i += 1

    return folder, output_file, verbose

# ─── Loaders ───────────────────────────────────────────────────────────────────

def load_folder(folder):
    """Load metadata.json and tests.json from a prompt folder."""
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        print(f"Error: {folder} is not a directory.", file=sys.stderr)
        sys.exit(2)

    meta_path = os.path.join(folder, "metadata.json")
    meta = {}
    if os.path.isfile(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    tests_path = os.path.join(folder, "tests.json")
    tests = []
    if os.path.isfile(tests_path):
        with open(tests_path, "r", encoding="utf-8") as f:
            tests = json.load(f)

    return meta, tests, folder


def load_output(folder, output_file):
    """Load the output text from a file or stdin."""
    # Explicit --output file
    if output_file:
        path = os.path.abspath(output_file)
        if not os.path.isfile(path):
            print(f"Error: Output file not found: {path}", file=sys.stderr)
            sys.exit(2)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    # Default: output-reference.md in the prompt folder
    ref_path = os.path.join(folder, "output-reference.md")
    if os.path.isfile(ref_path):
        with open(ref_path, "r", encoding="utf-8") as f:
            return f.read()

    # Fallback: stdin
    if not sys.stdin.isatty():
        return sys.stdin.read()

    print("Error: No output to evaluate. Provide --output <file>, "
          "place output-reference.md in the prompt folder, or pipe via stdin.",
          file=sys.stderr)
    sys.exit(2)

# ─── Scoring axes ──────────────────────────────────────────────────────────────

def score_structural_completeness(text, meta, verbose):
    """Score A: Does the output have all required sections?"""
    details = []

    # Count ## Layer N headers
    layer_headers = re.findall(r"^##\s+Layer\s+\d+", text, re.M)
    layer_count = len(layer_headers)
    expected_layers = 10
    layer_ratio = min(layer_count / expected_layers, 1.0)
    details.append(f"  Layer headers: {layer_count}/{expected_layers}")

    # Check closing sections
    closing_sections = [
        ("Full Stack Summary", r"(?:Full\s+Stack\s+Summary|Recommended\s+Full\s+Stack)"),
        ("Architecture Diagram", r"Architecture\s+Diagram"),
        ("Stack Debate Verdict", r"Stack\s+Debate\s+Verdict"),
        ("Language Boundary Map", r"Language\s+Boundary\s+Map"),
        ("MVP", r"MVP\s|Phase\s+1|Minimum\s+Viable"),
    ]
    closing_found = 0
    for name, pattern in closing_sections:
        found = bool(re.search(pattern, text, re.I))
        if found:
            closing_found += 1
        details.append(f"  {name}: {'found' if found else 'MISSING'}")
    closing_ratio = closing_found / len(closing_sections) if closing_sections else 1.0

    # Check for tables (| ... | ... | pattern)
    table_rows = re.findall(r"^\|.+\|.+\|", text, re.M)
    table_count = len(table_rows)
    has_tables = table_count >= 3  # expect at least a few table rows
    details.append(f"  Table rows: {table_count} ({'OK' if has_tables else 'few/none'})")

    # Check for Recommendation: and Pitfall: markers per layer
    recommendations = re.findall(r"\*\*Recommend(?:ation|ed)[:.]\*\*|\bRecommendation[:.]\s", text, re.I)
    pitfalls = re.findall(r"\*\*Pitfall[:.]\*\*|\bPitfall[:.]\s", text, re.I)
    rec_count = len(recommendations)
    pit_count = len(pitfalls)
    # We expect roughly 1 per layer (10)
    marker_ratio = min((rec_count + pit_count) / (expected_layers * 2), 1.0)
    details.append(f"  Recommendation markers: {rec_count}, Pitfall markers: {pit_count}")

    # Weighted score: layers are most important
    score = (layer_ratio * 0.40 + closing_ratio * 0.30 +
             marker_ratio * 0.20 + (1.0 if has_tables else 0.3) * 0.10) * 10.0

    return max(1.0, min(10.0, round(score, 1))), details


def score_specificity(text, meta, verbose):
    """Score B: Does it name real tools, not generic categories?"""
    details = []

    # Specific tool/library mentions (case-sensitive where appropriate)
    specific_tools = [
        r"\bRedis\b", r"\bPostgreSQL\b", r"\bNATS\b", r"\bKafka\b",
        r"\bRabbitMQ\b", r"\bvLLM\b", r"\bLangGraph\b", r"\bDocker\b",
        r"\bKubernetes\b", r"\bK8s\b", r"\bgRPC\b", r"\bProtobuf\b",
        r"\bWebSocket[s]?\b", r"\bGraphQL\b", r"\bReact\b", r"\bAngular\b",
        r"\bSvelte\b", r"\bSolid\b", r"\bBlazor\b",
        r"\bEntity Framework\b", r"\bDapper\b", r"\bSignalR\b",
        r"\bOpenSearch\b", r"\bElasticsearch\b", r"\bSQLite\b",
        r"\bMSSQL\b", r"\bMongoDB\b", r"\bCassandra\b",
        r"\bNginx\b", r"\bCaddy\b", r"\bTraefik\b", r"\bHAProxy\b",
        r"\bOllama\b", r"\bTGI\b", r"\bCrewAI\b",
        r"\bPrometheus\b", r"\bGrafana\b", r"\bOpenTelemetry\b",
        r"\bJaeger\b", r"\bLoki\b", r"\bFluentd\b", r"\bFilebeat\b",
        r"\bAG Grid\b", r"\bD3\b", r"\bCanvas\b", r"\bWebGL\b",
        r"\bAeron\b", r"\bLMAX\b", r"\bSBE\b",
        r"\bWASM\b", r"\bLuaJIT\b",
        r"\bmTLS\b", r"\bAES\b", r"\bRSA\b", r"\bChaCha20\b",
        r"\bWireGuard\b", r"\bHasura\b",
        r"\.NET\b", r"\bASP\.NET\b",
    ]

    specific_count = 0
    found_tools = []
    for pattern in specific_tools:
        matches = re.findall(pattern, text)
        if matches:
            specific_count += len(matches)
            found_tools.append(matches[0])

    unique_tools = len(found_tools)
    details.append(f"  Unique specific tools: {unique_tools}")
    details.append(f"  Total specific mentions: {specific_count}")

    # Penalize generic phrases
    generic_phrases = [
        r"\ba message queue\b", r"\ban in-memory store\b",
        r"\ba frontend framework\b", r"\ba database\b",
        r"\ba web framework\b", r"\ba caching layer\b",
        r"\ba container orchestrat(?:or|ion)\b",
        r"\ba programming language\b", r"\ba search engine\b",
        r"\ba load balancer\b", r"\ba monitoring tool\b",
        r"\bsome kind of\b", r"\bany(?:\s+suitable)?\s+(?:framework|library|tool)\b",
    ]
    generic_count = 0
    for pattern in generic_phrases:
        generic_count += len(re.findall(pattern, text, re.I))
    details.append(f"  Generic phrases: {generic_count}")

    score = 10.0 - (generic_count * 1.5) + (unique_tools * 0.3)
    # Bonus for high tool diversity
    if unique_tools >= 20:
        score += 1.0
    elif unique_tools < 5:
        score -= 2.0

    return max(1.0, min(10.0, round(score, 1))), details


def score_prior_art(text, meta, verbose):
    """Score C: Does it reference real systems?"""
    details = []

    # Real C2/SOC frameworks
    frameworks = {
        "Mythic": r"\bMythic\b",
        "Sliver": r"\bSliver\b",
        "Cobalt Strike": r"\bCobalt\s*Strike\b",
        "Nighthawk": r"\bNighthawk\b",
        "Velociraptor": r"\bVelociraptor\b",
        "Caldera": r"\bCaldera\b",
        "Covenant": r"\bCovenant\b",
        "PoshC2": r"\bPoshC2\b",
        "Wazuh": r"\bWazuh\b",
        "Elastic": r"\bElastic(?:\s+Security)?\b",
        "TheHive": r"\bTheHive\b",
        "Darktrace": r"\bDarktrace\b",
    }

    found_frameworks = {}
    for name, pattern in frameworks.items():
        matches = re.findall(pattern, text)
        if matches:
            found_frameworks[name] = len(matches)

    total_refs = sum(found_frameworks.values())
    unique_refs = len(found_frameworks)
    details.append(f"  Unique frameworks referenced: {unique_refs}/{len(frameworks)}")
    details.append(f"  Total framework mentions: {total_refs}")
    if found_frameworks:
        top3 = sorted(found_frameworks.items(), key=lambda x: -x[1])[:3]
        details.append(f"  Top referenced: {', '.join(f'{n}({c})' for n, c in top3)}")

    # Check per-layer prior art coverage
    # Split text into layer sections
    layer_sections = re.split(r"^##\s+Layer\s+\d+", text, flags=re.M)
    layers_with_refs = 0
    total_layer_sections = max(len(layer_sections) - 1, 1)  # first split is preamble

    for i, section in enumerate(layer_sections[1:], 1):
        has_ref = False
        for pattern in frameworks.values():
            if re.search(pattern, section):
                has_ref = True
                break
        if has_ref:
            layers_with_refs += 1
        elif verbose:
            details.append(f"  Layer {i}: no framework reference")

    coverage = layers_with_refs / min(total_layer_sections, 10)
    details.append(f"  Layers with prior art: {layers_with_refs}/{min(total_layer_sections, 10)}")

    # Score: combination of diversity and coverage
    diversity_score = min(unique_refs / 8.0, 1.0)  # expect at least 8 of the 12
    score = (diversity_score * 0.5 + coverage * 0.5) * 10.0

    return max(1.0, min(10.0, round(score, 1))), details


def score_assertion_tests(text, tests, verbose):
    """Score D: Run expected_contains checks from tests.json."""
    details = []

    if not tests:
        details.append("  No tests.json found — skipping (neutral score)")
        return 5.0, details

    total = 0
    passed = 0
    text_lower = text.lower()

    for test in tests:
        name = test.get("name", "unnamed")
        expected = test.get("expected_contains", [])
        missing = []
        for keyword in expected:
            total += 1
            if keyword.lower() in text_lower:
                passed += 1
            else:
                missing.append(keyword)
        if missing:
            details.append(f"  FAIL {name}: missing {missing}")
        else:
            details.append(f"  PASS {name}")

    if total == 0:
        return 5.0, details

    score = (passed / total) * 10.0
    details.insert(0, f"  Assertions: {passed}/{total} passed")

    return max(1.0, min(10.0, round(score, 1))), details


def score_coherence(text, meta, verbose):
    """Score E: Check for contradictions across layers."""
    details = []

    # Split into layer sections
    layer_pattern = re.compile(r"^##\s+Layer\s+(\d+)", re.M)
    splits = list(layer_pattern.finditer(text))

    layer_texts = {}
    for i, match in enumerate(splits):
        layer_num = int(match.group(1))
        start = match.end()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
        layer_texts[layer_num] = text[start:end]

    if len(layer_texts) < 2:
        details.append("  Too few layers to check coherence — neutral score")
        return 5.0, details

    # Extract technology mentions per layer
    tech_patterns = {
        "lang_csharp": r"\bC#\b|\.NET\b|ASP\.NET\b",
        "lang_go": r"\bGo\b(?:\s+(?:lang|language)|\s+\()",
        "lang_python": r"\bPython\b",
        "lang_rust": r"\bRust\b",
        "lang_java": r"\bJava\b(?!Script)",
        "lang_typescript": r"\bTypeScript\b",
        "mq_nats": r"\bNATS\b",
        "mq_rabbitmq": r"\bRabbitMQ\b",
        "mq_kafka": r"\bKafka\b",
        "db_postgres": r"\bPostgreSQL\b|\bPostgres\b",
        "db_sqlite": r"\bSQLite\b",
        "db_mongo": r"\bMongoDB\b",
        "cache_redis": r"\bRedis\b",
        "fw_react": r"\bReact\b",
        "fw_angular": r"\bAngular\b",
        "fw_svelte": r"\bSvelte\b",
        "fw_blazor": r"\bBlazor\b",
        "search_elastic": r"\bElasticsearch\b",
        "search_opensearch": r"\bOpenSearch\b",
    }

    layer_techs = {}
    for layer_num, section in layer_texts.items():
        techs = set()
        for tech_name, pattern in tech_patterns.items():
            if re.search(pattern, section):
                techs.add(tech_name)
        layer_techs[layer_num] = techs

    penalties = 0
    conflict_msgs = []

    # Check message queue consistency: if one MQ is recommended, it should
    # appear in layers that reference event buses
    mq_choices = set()
    for layer_num, techs in layer_techs.items():
        for t in techs:
            if t.startswith("mq_"):
                mq_choices.add(t)

    # Multiple MQs mentioned across layers is acceptable (comparison vs recommendation)
    # but check if the recommended one appears in data layer (Layer 4) and AI layer (Layer 10)
    if 1 in layer_techs and 4 in layer_techs:
        mq_in_1 = {t for t in layer_techs[1] if t.startswith("mq_")}
        mq_in_4 = {t for t in layer_techs[4] if t.startswith("mq_")}
        if mq_in_1 and mq_in_4 and not mq_in_1.intersection(mq_in_4):
            penalties += 1
            conflict_msgs.append(
                f"  MQ mismatch: Layer 1 uses {mq_in_1}, Layer 4 uses {mq_in_4}")

    # Check frontend framework consistency between Layer 3 (stack) and Layer 6 (frontend)
    if 3 in layer_techs and 6 in layer_techs:
        fw_in_3 = {t for t in layer_techs[3] if t.startswith("fw_")}
        fw_in_6 = {t for t in layer_techs[6] if t.startswith("fw_")}
        # If Layer 3 recommends one framework and Layer 6 uses a different one
        # Only flag if each layer has exactly one and they differ
        if len(fw_in_3) == 1 and len(fw_in_6) == 1 and fw_in_3 != fw_in_6:
            penalties += 1
            conflict_msgs.append(
                f"  Frontend mismatch: Layer 3 picks {fw_in_3}, Layer 6 picks {fw_in_6}")

    # Check database consistency between Layer 2 and Layer 4
    if 2 in layer_techs and 4 in layer_techs:
        db_in_2 = {t for t in layer_techs[2] if t.startswith("db_")}
        db_in_4 = {t for t in layer_techs[4] if t.startswith("db_")}
        if db_in_2 and db_in_4 and not db_in_2.intersection(db_in_4):
            penalties += 1
            conflict_msgs.append(
                f"  DB mismatch: Layer 2 uses {db_in_2}, Layer 4 uses {db_in_4}")

    # Check core language consistency: the recommended backend language should
    # appear in most layers
    backend_langs = {"lang_csharp", "lang_go", "lang_java"}
    # Find which backend language is mentioned most (the "primary" choice)
    lang_counts = {}
    for techs in layer_techs.values():
        for t in techs:
            if t in backend_langs:
                lang_counts[t] = lang_counts.get(t, 0) + 1
    if lang_counts:
        primary_lang = max(lang_counts, key=lang_counts.get)
        primary_count = lang_counts[primary_lang]
        details.append(f"  Primary backend language: {primary_lang} ({primary_count} layers)")

    # Check for explicit contradictions in recommendations
    # Look for "use X" in one place and "avoid X" or "do not use X" in another
    rec_sections = re.findall(
        r"\*\*Recommend(?:ation|ed)[:.]\*\*\s*(.*?)(?=\n\*\*|\n##|\Z)",
        text, re.S | re.I)
    recommended_techs = set()
    for rec in rec_sections:
        for tech_name, pattern in tech_patterns.items():
            if re.search(pattern, rec):
                recommended_techs.add(tech_name)

    # Look for "avoid" or "do not" near tech names
    avoid_patterns = re.findall(
        r"(?:avoid|do not use|don't use|reject|not recommended)\s+.{0,40}",
        text, re.I)
    avoided_techs = set()
    for phrase in avoid_patterns:
        for tech_name, pattern in tech_patterns.items():
            if re.search(pattern, phrase):
                avoided_techs.add(tech_name)

    contradictions = recommended_techs.intersection(avoided_techs)
    if contradictions:
        penalties += len(contradictions)
        conflict_msgs.append(
            f"  Contradictions: {contradictions} both recommended and avoided")

    # Check Full Stack Summary consistency with layer recommendations
    summary_match = re.search(
        r"(?:Full\s+Stack\s+Summary|Recommended\s+Full\s+Stack)(.*?)(?=###|\Z)",
        text, re.S | re.I)
    if summary_match:
        summary_techs = set()
        summary_text = summary_match.group(1)
        for tech_name, pattern in tech_patterns.items():
            if re.search(pattern, summary_text):
                summary_techs.add(tech_name)
        # Check that primary technologies in summary match layer recommendations
        if recommended_techs and summary_techs:
            # Key techs from recommendations that are missing from summary
            key_missing = recommended_techs - summary_techs
            # Filter to important categories only
            key_cats = {"lang_", "mq_", "db_", "cache_", "fw_"}
            important_missing = {t for t in key_missing
                                 if any(t.startswith(c) for c in key_cats)}
            if len(important_missing) > 3:
                penalties += 1
                conflict_msgs.append(
                    f"  Summary missing key techs: {important_missing}")

    for msg in conflict_msgs:
        details.append(msg)

    score = 10.0 - (penalties * 2.0)
    if not conflict_msgs:
        details.append("  No contradictions detected")

    return max(1.0, min(10.0, round(score, 1))), details

# ─── Display ───────────────────────────────────────────────────────────────────

AXES = [
    "Structural Completeness",
    "Specificity",
    "Prior Art Grounding",
    "Assertion Tests",
    "Coherence",
]

SUGGESTIONS = {
    "Structural Completeness": "Output is missing required sections. Check for Layer headers, closing sections (Full Stack Summary, Architecture Diagram, Stack Debate Verdict, Language Boundary Map, MVP), tables, and per-layer Recommendation/Pitfall markers.",
    "Specificity": "Output uses too many generic phrases. Replace 'a message queue' with 'NATS JetStream 2.10'. Name specific tools, libraries, and versions.",
    "Prior Art Grounding": "Output lacks references to real systems. Each layer should cite at least one production system (Mythic, Sliver, Cobalt Strike, etc.) that validates the recommendation.",
    "Assertion Tests": "Output failed expected_contains assertions from tests.json. Check which keywords are missing.",
    "Coherence": "Output has contradictions across layers. Ensure the same technology choice is used consistently (e.g., if NATS is chosen in Layer 1, it should appear in Layer 4).",
}


def bar(val, w=20):
    f = round((val / 10) * w)
    return "#" * f + "." * (w - f)


def render(scores, all_details, verbose):
    overall = sum(scores[a] for a in AXES) / len(AXES)
    low = [a for a in AXES if scores[a] < 6]
    lines = ["", "=" * 60, "  WIXIE OUTPUT EVALUATION", "=" * 60, ""]
    for a in AXES:
        lines.append(f"  {(a + ':').ljust(28)}{scores[a]:4.0f}/10  {bar(scores[a])}")
    lines += ["", f"  {'OVERALL:'.ljust(28)}{overall:4.1f}/10"]
    lines.append(f"  STATUS: {'[!] NEEDS IMPROVEMENT (' + ', '.join(low) + ' below 6)' if low else '[OK] PASS'}")
    lines.append("")
    if low:
        lines.append("  Suggestions:")
        for a in low:
            lines.append(f"  - {a}: {SUGGESTIONS[a]}")
        lines.append("")
    if verbose:
        lines.append("-" * 60)
        lines.append("  DETAILED BREAKDOWN")
        lines.append("-" * 60)
        for a in AXES:
            lines.append(f"\n  {a} ({scores[a]}/10):")
            for detail in all_details.get(a, []):
                lines.append(detail)
        lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    folder, output_file, verbose = parse_args()
    meta, tests, folder = load_folder(folder)
    text = load_output(folder, output_file)

    if not text.strip():
        print("Error: Empty output provided.", file=sys.stderr)
        sys.exit(2)

    scores = {}
    all_details = {}

    # A. Structural Completeness
    s, d = score_structural_completeness(text, meta, verbose)
    scores["Structural Completeness"] = s
    all_details["Structural Completeness"] = d

    # B. Specificity
    s, d = score_specificity(text, meta, verbose)
    scores["Specificity"] = s
    all_details["Specificity"] = d

    # C. Prior Art Grounding
    s, d = score_prior_art(text, meta, verbose)
    scores["Prior Art Grounding"] = s
    all_details["Prior Art Grounding"] = d

    # D. Assertion Tests
    s, d = score_assertion_tests(text, tests, verbose)
    scores["Assertion Tests"] = s
    all_details["Assertion Tests"] = d

    # E. Coherence
    s, d = score_coherence(text, meta, verbose)
    scores["Coherence"] = s
    all_details["Coherence"] = d

    print(render(scores, all_details, verbose))
    sys.exit(1 if any(scores[a] < 6 for a in AXES) else 0)


# ─── API for hybrid orchestrator ────────────────────────────────────────────────

def evaluate(output_text, prompt_text, meta=None, tests=None):
    """API wrapper: score an output and return results dict."""
    if meta is None:
        meta = {}
    if tests is None:
        tests = []
    scores = {}
    s, _ = score_structural_completeness(output_text, meta, False)
    scores["structural"] = s
    s, _ = score_specificity(output_text, meta, False)
    scores["specificity"] = s
    s, _ = score_prior_art(output_text, meta, False)
    scores["prior_art"] = s
    s, _ = score_assertion_tests(output_text, tests, False)
    scores["assertions"] = s
    s, _ = score_coherence(output_text, meta, False)
    scores["coherence"] = s
    overall = round(sum(scores.values()) / len(scores), 1) if scores else 0
    scores["overall"] = overall
    return scores


if __name__ == "__main__":
    main()
