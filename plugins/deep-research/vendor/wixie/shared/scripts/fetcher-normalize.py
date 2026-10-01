#!/usr/bin/env python3
"""Fetcher-Normalize: deterministic shape-coercion for Haiku deep-research fetcher returns.

Closes the F11.1 gap: tightening fetcher.md as a contract did not enforce schema; 9 of 10
round-3 Haiku fetchers returned non-canonical shapes despite the hardened spec. This
script post-processes any fetcher's JSON output into the canonical shape consumed by
sources.jsonl.

Canonical shape (per fetcher.md Step 7):

    [
      {
        "url": "<url>",
        "date": "<YYYY-MM-DD|YYYY-MM|YYYY|null>",
        "source_type": "official|third-party|community|paper|other",
        "findings": [{"claim": "<paraphrase>", "quote": "<verbatim sentence>"}]
      }
    ]

Or, for unfetchable pages:

    [{"url": "<url>", "error": "unfetchable"}]

Usage (CLI):
    python fetcher-normalize.py < raw.json > sources_block.jsonl
    cat raw.json | python fetcher-normalize.py --sq sq3 --start-id S36

Usage (library):
    from fetcher_normalize import normalize
    canonical = normalize(raw_json, sq="sq3", start_id="S36")
"""
import json
import re
import sys
import argparse
from typing import Any, Iterable

VALID_SOURCE_TYPES = {"official", "third-party", "community", "paper", "other"}


URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")


def coerce_url(obj: dict) -> str | None:
    """Find a URL in any of the common drift-shape keys.

    Walks: direct keys, list-typed values (sources: [url, url]), and regex-extracts
    from descriptive strings like 'METR (arxiv 2503.14499) https://...'.
    """
    # Direct URL keys
    for key in ("url", "URL", "href", "link"):
        v = obj.get(key)
        if isinstance(v, str):
            m = URL_RE.search(v)
            if m:
                return m.group(0)

    # `source` key — sometimes a URL, sometimes a label, sometimes a list
    for key in ("source", "sources", "primary_source", "evidence_source"):
        v = obj.get(key)
        if isinstance(v, str):
            m = URL_RE.search(v)
            if m:
                return m.group(0)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    m = URL_RE.search(item)
                    if m:
                        return m.group(0)

    # Last resort: regex-search every string value
    for v in obj.values():
        if isinstance(v, str):
            m = URL_RE.search(v)
            if m:
                return m.group(0)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    m = URL_RE.search(item)
                    if m:
                        return m.group(0)
    return None


def coerce_date(obj: dict) -> str | None:
    """Pick a date in known formats. Reject narrative strings."""
    for key in ("date", "published", "year", "freshness"):
        v = obj.get(key)
        if v is None:
            continue
        s = str(v)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return s
        if re.fullmatch(r"\d{4}-\d{2}", s):
            return s
        if re.fullmatch(r"\d{4}", s):
            return s
    return None


def coerce_source_type(obj: dict) -> str:
    """Pick a source_type from drift shapes; default to other."""
    for key in ("source_type", "type", "source_class", "doc_type"):
        v = obj.get(key)
        if isinstance(v, str):
            s = v.strip().lower()
            if s in VALID_SOURCE_TYPES:
                return s
            # Map common drift values
            if "vendor" in s or "official" in s or "docs" in s:
                return "official"
            if "paper" in s or "arxiv" in s or "preprint" in s:
                return "paper"
            if "blog" in s or "third" in s or "tech media" in s:
                return "third-party"
            if "community" in s or "forum" in s or "medium" in s or "substack" in s:
                return "community"
    return "other"


def coerce_findings(obj: dict) -> list[dict]:
    """Reshape any drift-shape findings into [{claim, quote}, ...].

    Strategy: walk the object looking for text fields that pair as claim+quote.
    Drift shapes observed:
      - {claim, quote} — already canonical
      - {claim, source, confidence} — use claim, drop source/confidence; quote = ""
      - {claim, verbatim} — verbatim → quote
      - {claim, evidence} — evidence → quote (paraphrased flag set externally)
      - {failure_mode, description, prevalence} — synthesize claim from failure_mode + prevalence
      - {study_id, title, claim, ...} — use claim; quote = ""
      - {claim, supporting, source} — drop supporting/source, use claim
    """
    # Direct findings array if present
    findings = obj.get("findings")
    if isinstance(findings, list):
        out = []
        for f in findings:
            if not isinstance(f, dict):
                continue
            claim = f.get("claim") or f.get("description") or f.get("text") or ""
            quote = f.get("quote") or f.get("verbatim") or f.get("evidence") or ""
            if not isinstance(claim, str):
                claim = str(claim)
            if not isinstance(quote, str):
                quote = str(quote)
            if claim:
                out.append({"claim": claim.strip(), "quote": quote.strip()})
        return out

    # Drift shape: top-level dict with claim/quote at root → wrap as single finding
    claim = obj.get("claim") or obj.get("description")
    quote = obj.get("quote") or obj.get("verbatim") or obj.get("evidence")
    if claim:
        if not isinstance(claim, str):
            claim = str(claim)
        if not isinstance(quote, str):
            quote = str(quote) if quote else ""
        return [{"claim": claim.strip(), "quote": quote.strip()}]

    # Drift shape: failure_mode + description
    fm = obj.get("failure_mode")
    if fm:
        prev = obj.get("prevalence", "") or obj.get("description", "")
        return [{"claim": f"{fm}: {prev}".strip(": "), "quote": str(prev) if prev else ""}]

    return []


def is_unfetchable(obj: dict) -> bool:
    err = obj.get("error")
    if isinstance(err, str) and "unfetchable" in err.lower():
        return True
    return False


def normalize_one(obj: dict) -> dict | None:
    """Coerce one drift-shape object into canonical shape. Returns None if no URL."""
    url = coerce_url(obj)
    if not url:
        return None

    if is_unfetchable(obj):
        return {"url": url, "error": "unfetchable"}

    return {
        "url": url,
        "date": coerce_date(obj),
        "source_type": coerce_source_type(obj),
        "findings": coerce_findings(obj),
    }


def normalize(raw: Any, sq: str | None = None, start_id: str | None = None) -> list[dict]:
    """Top-level normalize: takes raw JSON (parsed) and returns canonical sources list.

    If sq + start_id provided, also stamps id and sq fields for direct sources.jsonl insert.
    """
    # Accept array or single dict
    if isinstance(raw, dict):
        items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        return []

    out = []
    next_id_n = None
    if start_id and re.fullmatch(r"S\d+", start_id):
        next_id_n = int(start_id[1:])

    for item in items:
        if not isinstance(item, dict):
            continue
        norm = normalize_one(item)
        if norm is None:
            continue
        if sq:
            norm = {"sq": sq, **norm}
        if next_id_n is not None:
            norm = {"id": f"S{next_id_n}", **norm}
            next_id_n += 1
        norm["normalized_via"] = "fetcher-normalize.py"
        out.append(norm)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Normalize fetcher returns to canonical schema")
    ap.add_argument("--sq", help="Stamp this sub-question id on every output line")
    ap.add_argument("--start-id", help="Stamp sequential ids starting from e.g. S36")
    ap.add_argument("--input", help="Read from file instead of stdin")
    args = ap.parse_args()

    src = sys.stdin if not args.input else open(args.input, encoding="utf-8")
    try:
        raw = json.load(src)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"[fetcher-normalize] JSON parse error: {e}\n")
        return 2

    canonical = normalize(raw, sq=args.sq, start_id=args.start_id)
    for c in canonical:
        print(json.dumps(c, ensure_ascii=False))
    sys.stderr.write(f"[fetcher-normalize] emitted {len(canonical)} canonical entries\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
