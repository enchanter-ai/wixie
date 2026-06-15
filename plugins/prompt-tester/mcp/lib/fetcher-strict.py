#!/usr/bin/env python3
"""Fetcher-Strict: Anthropic SDK structured-output wrapper for the deep-research Haiku fetcher.

Root fix for F11.1 (schema drift). Uses the Anthropic SDK's response_format / JSON schema
enforcement so the model cannot emit non-canonical shapes — schema drift is prevented at the
model level rather than patched in post-process.

Fallback path (documented below): when structured outputs are unavailable in the current SDK
or for the target model, falls back to (a) strong JSON-only system prompt + (b) automatic
pipe through fetcher-normalize.py.

Canonical schema consumed downstream by sources.jsonl — per fetcher.md Step 7:

    [
      {"url": "…", "date": "YYYY-MM-DD|YYYY-MM|YYYY|null",
       "source_type": "official|third-party|community|paper|other",
       "findings": [{"claim": "…", "quote": "…"}]},
      {"url": "…", "error": "unfetchable"}
    ]

Usage:
    python fetcher-strict.py --query "…" --sub-question "…" [--start-id S36] [--sq sq3]

Output: canonical JSONL to stdout, one JSON object per line, with id/sq fields stamped.

Design choices:
    1. Structured outputs via betas.messages.create (header: output-schemas-2025-02-19).
       The response_format uses a top-level "object" wrapper (SDK requires an object at root,
       not a bare array) — the "sources" key is unwrapped before emitting.
    2. Tools array includes computer_use_mobile WebSearch + WebFetch so Haiku actually
       performs the search/fetch steps from fetcher.md (Steps 1-3).
    3. Fallback: if ImportError (old SDK without betas attr) or if the API raises
       BadRequestError / NotFoundError for the beta endpoint, falls back to
       client.messages.create with a tight JSON-only system prompt and pipes the result
       through the normalize() function from fetcher-normalize.py for shape coercion.
    4. Id/sq stamping matches fetcher-normalize.py convention (--start-id S<n>, --sq <id>).
"""

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

# ─── Constants ────────────────────────────────────────────────────────────────

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 4096

# The beta header that unlocks structured outputs / JSON schema enforcement.
# SDK exposes this as client.beta.messages.create(betas=[...]) or via the
# beta header string.
STRUCTURED_OUTPUT_BETA = "output-schemas-2025-02-19"

# Canonical JSON schema for a single source entry.
# The SDK requires the top-level response_format schema to be an object (not array),
# so we wrap the array under a "sources" key and unwrap after the call.
RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["sources"],
    "properties": {
        "sources": {
            "type": "array",
            "description": "One entry per fetched URL.",
            "items": {
                "oneOf": [
                    {
                        "type": "object",
                        "description": "A successfully fetched source with extracted findings.",
                        "required": ["url", "date", "source_type", "findings"],
                        "additionalProperties": False,
                        "properties": {
                            "url": {"type": "string"},
                            "date": {
                                "type": ["string", "null"],
                                "description": "YYYY-MM-DD, YYYY-MM, YYYY, or null.",
                            },
                            "source_type": {
                                "type": "string",
                                "enum": ["official", "third-party", "community", "paper", "other"],
                            },
                            "findings": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["claim", "quote"],
                                    "additionalProperties": False,
                                    "properties": {
                                        "claim": {"type": "string"},
                                        "quote": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                    {
                        "type": "object",
                        "description": "An unfetchable page (paywall, 404, CAPTCHA, etc.).",
                        "required": ["url", "error"],
                        "additionalProperties": False,
                        "properties": {
                            "url": {"type": "string"},
                            "error": {"type": "string", "const": "unfetchable"},
                        },
                    },
                ]
            },
        }
    },
    "additionalProperties": False,
}

# Tools Haiku needs to execute Steps 1-3 of fetcher.md.
TOOLS = [
    {
        "type": "computer_use_20250122",
        "name": "WebSearch",
        "description": "Search the web for URLs relevant to a query. Returns top results with titles and snippets.",
        "input_schema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "The search query."}
            },
        },
    },
    {
        "type": "computer_use_20250122",
        "name": "WebFetch",
        "description": "Fetch the full text content of a web page given its URL.",
        "input_schema": {
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch."},
            },
        },
    },
]

# ─── System prompt (fetcher.md contract, condensed for API call) ───────────────

def build_system_prompt(sub_question: str) -> str:
    return f"""You are a strict web-research fetcher. Governed by the fetcher.md contract.

<task>
For the given query, search the web and extract structured findings. Follow these steps exactly.
</task>

<sub_question>{sub_question}</sub_question>

<steps>
1. Call WebSearch once with the query. Take the top 3 results.
2. Filter: keep only results where BOTH tests pass:
   - Source-type test: official vendor docs, peer-reviewed paper, or major industry publisher.
   - Topicality test: title or snippet contains at least one noun from the sub_question.
   Keep the top 2-3 survivors. If fewer than 2 survive, include those with "low_coverage": true.
3. For each kept URL, call WebFetch. If the response is an HTTP error, login wall, paywall, CAPTCHA,
   or under 500 words, record that URL as unfetchable.
4. Extract date: check meta tags, URL path, copyright footer, in that order. If none found: null.
5. Classify source_type: official / paper / community / third-party / other (apply in that order).
6. Walk paragraphs. For each paragraph, apply three tests:
   A. Topic match: contains a noun from the sub_question.
   B. Claim form: states a specific claim (subject does/is/has something specific).
   C. Quote-able: one sentence ≤200 chars that can be copy-pasted verbatim.
   If all three pass, record one finding: claim (your paraphrase) + quote (verbatim sentence).
   Aim for 1-3 findings per page.
</steps>

<constraints>
- Return ONLY the JSON object. No preamble. No markdown. No extra fields.
- quote = verbatim copy-paste. NEVER paraphrase inside quote.
- NEVER invent a date. If all date checks fail, date is null.
- NEVER invent findings to hit a minimum. findings: [] is valid.
- Unfetchable pages: exactly two keys: url + error: "unfetchable".
- Fetchable pages: exactly four keys: url, date, source_type, findings.
- Each findings entry: exactly two keys: claim, quote.
</constraints>"""


# ─── Fallback system prompt (structured outputs unavailable) ──────────────────

def build_fallback_system_prompt(sub_question: str) -> str:
    base = build_system_prompt(sub_question)
    return base + """

<format>
Your entire response MUST be a valid JSON object of the form:
{"sources": [ ... ]}
where each element is either a fetchable-source object or an unfetchable object.
Do not emit any text outside the JSON object. Do not wrap in markdown code fences.
Begin your response with { and end with }.
</format>"""


# ─── Normalize import (fallback path) ─────────────────────────────────────────

def _load_normalizer():
    """Import normalize() from fetcher-normalize.py (sibling script)."""
    script_dir = Path(__file__).parent
    norm_path = script_dir / "fetcher-normalize.py"
    if not norm_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("fetcher_normalize", norm_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.normalize


# ─── Id / sq stamping ────────────────────────────────────────────────────────

def stamp_entries(
    entries: list[dict],
    sq: str | None,
    start_id: str | None,
    via_structured: bool,
) -> list[dict]:
    """Stamp id and sq fields onto each entry; record which path produced the output."""
    next_id_n: int | None = None
    if start_id and re.fullmatch(r"S\d+", start_id):
        next_id_n = int(start_id[1:])

    out = []
    for entry in entries:
        row: dict = {}
        if sq:
            row["sq"] = sq
        if next_id_n is not None:
            row["id"] = f"S{next_id_n}"
            next_id_n += 1
        row.update(entry)
        row["via"] = "fetcher-strict.py:structured" if via_structured else "fetcher-strict.py:fallback"
        out.append(row)
    return out


# ─── API call — structured output path ────────────────────────────────────────

def call_structured(client, system: str, query: str) -> list[dict]:
    """Call the API with JSON schema response_format (beta endpoint).

    Returns the unwrapped sources array.

    Raises:
        Exception — any SDK error (caller catches and decides whether to fall back).
    """
    # The beta endpoint is accessed via client.beta.messages.create.
    # betas param enables the structured-outputs beta header.
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": query}],
        tools=TOOLS,
        betas=[STRUCTURED_OUTPUT_BETA],
        response_format={"type": "json_schema", "json_schema": RESPONSE_SCHEMA},
    )
    # Extract text from the response content blocks.
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    parsed = json.loads(text)
    if isinstance(parsed, dict) and "sources" in parsed:
        return parsed["sources"]
    if isinstance(parsed, list):
        return parsed
    # Unexpected shape — return as-is for fallback normalizer to handle.
    return [parsed] if isinstance(parsed, dict) else []


# ─── API call — fallback path ──────────────────────────────────────────────────

def call_fallback(client, system: str, query: str, normalize_fn) -> tuple[list[dict], bool]:
    """Call the API with a strong JSON-only system prompt (no response_format).

    Returns (entries, normalized) where normalized=True means the normalizer was run.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": query}],
        tools=TOOLS,
    )

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    # Strip markdown fences if the model added them despite the instruction.
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"[fetcher-strict:fallback] JSON parse error: {e}\n")
        sys.stderr.write(f"[fetcher-strict:fallback] raw text (first 500 chars): {text[:500]}\n")
        return [], False

    # Unwrap {"sources": [...]} if present.
    if isinstance(parsed, dict) and "sources" in parsed:
        raw = parsed["sources"]
    elif isinstance(parsed, list):
        raw = parsed
    else:
        raw = [parsed]

    # Run through normalizer if available.
    if normalize_fn is not None:
        entries = normalize_fn(raw)
        # Strip the "normalized_via" field added by fetcher-normalize.py — we'll add our own via.
        for e in entries:
            e.pop("normalized_via", None)
        return entries, True
    else:
        sys.stderr.write(
            "[fetcher-strict:fallback] fetcher-normalize.py not found; "
            "returning raw parsed output without normalization.\n"
        )
        if isinstance(raw, list):
            return raw, False
        return [raw], False


# ─── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Fetcher-Strict: structured-output Haiku fetcher wrapper. "
            "Root fix for F11.1 (schema drift). "
            "Outputs canonical JSONL to stdout."
        )
    )
    ap.add_argument("--query", required=True, help="WebSearch query string.")
    ap.add_argument("--sub-question", required=True, dest="sub_question",
                    help="The sub-question this query serves (relevance filter).")
    ap.add_argument("--start-id", dest="start_id",
                    help="Stamp sequential ids starting from e.g. S36.")
    ap.add_argument("--sq", help="Stamp this sub-question id on every output line.")
    args = ap.parse_args()

    # ── Import Anthropic SDK ──────────────────────────────────────────────────
    try:
        import anthropic
    except ImportError:
        sys.stderr.write(
            "[fetcher-strict] ERROR: anthropic SDK not installed. "
            "Run: pip install anthropic\n"
        )
        return 1

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.stderr.write(
            "[fetcher-strict] ERROR: ANTHROPIC_API_KEY environment variable not set.\n"
        )
        return 1

    client = anthropic.Anthropic(api_key=api_key)
    normalize_fn = _load_normalizer()

    system_structured = build_system_prompt(args.sub_question)
    system_fallback = build_fallback_system_prompt(args.sub_question)
    query_msg = args.query

    # ── Attempt 1: structured outputs (beta endpoint) ─────────────────────────
    entries: list[dict] = []
    via_structured = False

    use_structured = hasattr(client, "beta") and hasattr(client.beta, "messages")
    if not use_structured:
        sys.stderr.write(
            "[fetcher-strict] SDK lacks client.beta.messages — "
            "structured outputs unavailable; using fallback path.\n"
        )

    if use_structured:
        try:
            entries = call_structured(client, system_structured, query_msg)
            via_structured = True
            sys.stderr.write(
                f"[fetcher-strict] structured-output path succeeded; "
                f"{len(entries)} source entries.\n"
            )
        except Exception as e:
            err_str = str(e)
            # Common reasons structured outputs aren't available for this model/SDK:
            # - BadRequestError: "beta feature not available"
            # - NotFoundError: endpoint doesn't exist for the model
            # - AttributeError: betas attr exists but method doesn't
            sys.stderr.write(
                f"[fetcher-strict] structured-output call failed "
                f"({type(e).__name__}: {err_str[:200]}); "
                f"falling back to JSON-prompt + normalize path.\n"
            )
            use_structured = False

    # ── Attempt 2: fallback (strong JSON system prompt + normalizer) ──────────
    if not use_structured:
        try:
            entries, was_normalized = call_fallback(
                client, system_fallback, query_msg, normalize_fn
            )
            via_structured = False
            norm_note = " (normalized via fetcher-normalize.py)" if was_normalized else " (raw, no normalizer)"
            sys.stderr.write(
                f"[fetcher-strict] fallback path completed; "
                f"{len(entries)} source entries{norm_note}.\n"
            )
        except Exception as e:
            sys.stderr.write(
                f"[fetcher-strict] fallback call failed "
                f"({type(e).__name__}: {str(e)[:200]})\n"
            )
            return 2

    # ── Stamp ids / sq / via ─────────────────────────────────────────────────
    stamped = stamp_entries(entries, args.sq, args.start_id, via_structured)

    # ── Emit JSONL to stdout ──────────────────────────────────────────────────
    for row in stamped:
        print(json.dumps(row, ensure_ascii=False))

    sys.stderr.write(
        f"[fetcher-strict] emitted {len(stamped)} JSONL lines "
        f"({'structured' if via_structured else 'fallback'} path).\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
