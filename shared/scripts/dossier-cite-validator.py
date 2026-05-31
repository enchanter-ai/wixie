#!/usr/bin/env python3
"""dossier-cite-validator.py — Phase 6 trace-check (Test A + Test B) at write-time.

Author: Enchanter Labs

Closes G-4 in the deep-research gaps roadmap: catches synthesis-prose cites
that don't trace to a supporting finding in sources.jsonl BEFORE the Phase 6
verifier rejects the brief.

Mechanical reproduction of `plugins/deep-research/agents/verifier.md` Steps 2-4
(web-citation branch only — Test C interval-overlap is out of scope here; the
target is markdown dossier prose, not code citations).

Two modes:
  --mode dossier (default, legacy): walks `report.md` prose, extracts S-cite
    references, and for each cite confirms it resolves to `sources.jsonl` with
    a finding that passes Test A (subject match) + Test B (action match).
  --mode claims (G-V5): walks `claims.json#claims[]`, for each claim iterates
    its `supporting[]` S-id list, confirms each S-id resolves in
    `sources.jsonl`, and confirms the source's `findings[]` mention the claim's
    subject + action mechanically (same Test A + Test B logic as the dossier
    mode, with the claim's `claim` field as the supported_text).

Inputs:
  --mode    dossier|claims  pick the validation surface (default: dossier)
  --dossier <path.md>       dossier markdown to scan (mode=dossier)
  --claims  <path.json>     claims.json to walk (mode=claims; also accepted as
                            OPTIONAL sanity-check input under mode=dossier)
  --sources <path.jsonl>    sources.jsonl with findings[].claim + findings[].quote

Backward compat:
  - If `--mode` is omitted and `--dossier` is supplied, mode defaults to
    `dossier`. Existing callers (`--dossier <p> --sources <p> [--claims <p>]`)
    keep working unchanged.
  - If `--mode claims` is passed, `--claims` becomes required and `--dossier`
    is ignored (warned in stderr if also supplied).

Output:
  - mode=dossier: JSON to stdout with violations[].{cite, line, claim_excerpt, reason}.
  - mode=claims:  JSON to stdout with violations[].{claim_id, cite, claim_excerpt, reason}.
    One human-readable violation line per offending (claim_id, S-id) printed to
    stdout AFTER the JSON block (so machines can parse the JSON head and humans
    can scan the tail).
  Exit code:
    0 = no violations (pass)
    1 = one or more violations (claims mode only — dossier mode is advisory and
        always exits 0 for backward compat with the Phase 5.5 pre-flight wiring)
    2 = required input file missing

Honest-numbers contract:
  - No fuzzy semantic matching. Tests A+B reduce to substring / synonym checks
    over a small built-in synonym table — paraphrase tolerance only where the
    verifier spec explicitly allows ("uses X" ↔ "employs X"; "5-stage" ↔ "five-stage").
  - A cite PASSES if AT LEAST ONE finding in the cited source passes BOTH
    Test A (subject match) AND Test B (action/property match).
  - Stdlib only — no external deps.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Reconfigure stdout/stderr to UTF-8 with replacement so em-dashes and other
# unicode glyphs in claim text don't crash the validator on Windows cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    # Pre-3.7 or non-tty: best-effort only.
    pass


# ---------- citation extraction ---------------------------------------------

# Match S<n> tokens in dossier prose. Accepts: S14, (S14), [S14], (S14, S15),
# [S14, S15], cite=S14. Excludes runs that look like SHA fragments or unrelated
# capitalized words by requiring digit-only suffix.
CITE_TOKEN_RE = re.compile(r"\bS(\d+)\b")

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\*\(\[])")


@dataclass
class Cite:
    cite_id: str          # e.g. "S14"
    supported_text: str   # the surrounding sentence (or table cell / list item)
    line_no: int          # 1-based line number for diagnostics


def _split_into_units(markdown: str) -> list[tuple[int, str]]:
    """Walk the markdown line-by-line. Treat each line as the unit of cite
    context, since dossier tables and bullet lists put each claim on one line.
    Skip code fences."""
    units: list[tuple[int, str]] = []
    in_fence = False
    for i, line in enumerate(markdown.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped:
            continue
        units.append((i, line))
    return units


def _claim_cell_from_table_row(line: str) -> str:
    """For a markdown table row `| claim text | source col | engine | ...`,
    return the FIRST cell (the claim text). Outside table context, return the
    whole line. The Phase 6 verifier scopes supported_text to the *claim*, not
    the cite column."""
    s = line.lstrip()
    if not s.startswith("|"):
        return line
    # Drop leading pipe, split on `|`. Tables also include separator rows
    # like `|---|---|`; ignore those by returning empty.
    cells = [c.strip() for c in s.split("|")]
    # The first element is "" because of the leading pipe.
    cells = [c for c in cells if c != ""]
    if not cells:
        return line
    if re.fullmatch(r"-+:?|:?-+:?", cells[0]):
        return ""  # separator row
    return cells[0]


def extract_cites(markdown: str) -> list[Cite]:
    cites: list[Cite] = []
    for line_no, line in _split_into_units(markdown):
        # For table rows, the claim is in the first cell. For bullets/prose
        # the whole sentence is the supported_text.
        is_table_row = line.lstrip().startswith("|")
        claim_text = _claim_cell_from_table_row(line) if is_table_row else line

        for m in CITE_TOKEN_RE.finditer(line):
            cite_id = f"S{m.group(1)}"
            if is_table_row:
                supported = claim_text
            else:
                sentences = SENTENCE_SPLIT_RE.split(line)
                if len(sentences) > 1:
                    pos = 0
                    supported = line
                    for s in sentences:
                        end = pos + len(s)
                        if pos <= m.start() <= end + 4:
                            supported = s
                            break
                        pos = end + 1
                else:
                    supported = line
            cites.append(Cite(cite_id=cite_id, supported_text=supported.strip(), line_no=line_no))
    return cites


# ---------- sources index ----------------------------------------------------

def load_sources(path: Path) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"WARN: malformed sources.jsonl line: {e}", file=sys.stderr)
                continue
            sid = obj.get("id")
            if not sid:
                continue
            idx[sid] = obj
    return idx


# ---------- Test A: subject match -------------------------------------------

ARTICLES_AND_PRONOUNS = {
    "the", "a", "an", "this", "that", "these", "those",
    "it", "its", "they", "them", "their", "he", "she", "his", "her",
    "we", "us", "our", "you", "your", "i", "my",
    "what", "which", "who", "whose", "where", "when", "why", "how",
    "is", "are", "was", "were", "be", "been", "being",
    "and", "but", "or", "so", "yet", "for", "nor",
    "in", "on", "at", "of", "to", "by", "with", "from", "as",
}

# Tokens we strip from the front of a supported_text to get to the subject.
# Markdown table rows often start with bold tokens, pipes, etc.
def _clean_for_subject(text: str) -> str:
    # strip markdown structural noise
    t = text.lstrip("|*-# \t")
    # remove leading bold markers and parenthetical openers
    t = re.sub(r"^\*{1,3}", "", t)
    # collapse whitespace
    t = re.sub(r"\s+", " ", t)
    return t.strip()


# Adjectives that often lead a claim heading but don't carry subject identity.
# Verifier spec says "first noun or proper noun" — these are descriptive
# adjectives that should be skipped to find the actual noun phrase.
LEADING_ADJECTIVES = {
    "quadratic", "hybrid", "layered", "interpretable", "native", "multi",
    "cross", "single", "double", "open", "closed", "deep", "shallow", "raw",
    "new", "old", "current", "recent", "latest", "early", "late",
    "fast", "slow", "lightweight", "heavyweight",
    "manual", "automatic", "automated", "explicit", "implicit",
    "linear", "nonlinear", "global", "local", "static", "dynamic",
    "small", "large", "huge", "tiny", "mini", "macro", "micro",
}

# Extra proper-noun fragments not in the synonym table. The full set is built
# lazily at first call to extract_subject() to avoid module-load ordering issues.
_EXTRA_PROPER_NOUNS = {
    "owasp", "cve", "github", "sat-diff", "open swe", "sweep",
    "memoryarena", "voyager", "promptguard", "memento", "promptlayer",
    "phoenix", "arize", "pezzo", "opik", "puaro", "openssl",
    "cvss", "cwe", "rce", "json", "yaml", "toml", "css", "sbom",
}

_KNOWN_PROPER_NOUNS_CACHE: set[str] | None = None


def _known_proper_nouns() -> set[str]:
    global _KNOWN_PROPER_NOUNS_CACHE
    if _KNOWN_PROPER_NOUNS_CACHE is not None:
        return _KNOWN_PROPER_NOUNS_CACHE
    out: set[str] = set(_EXTRA_PROPER_NOUNS)
    for canon, group in SUBJECT_SYNONYMS.items():
        out.add(canon.lower())
        for syn in group:
            out.add(syn.lower())
    _KNOWN_PROPER_NOUNS_CACHE = out
    return out


def extract_subject(supported_text: str) -> str:
    """Verifier Step 4 Test A: the first noun or proper noun that isn't an
    article or a pronoun. Approximation:
      1. Tokenize the cleaned claim.
      2. Look for a known proper-noun fragment anywhere in the first ~6
         content tokens — it wins (matches the verifier's "obvious synonym"
         leeway in identifying the real subject).
      3. Else pick the first non-stopword, non-leading-adjective capitalized token.
      4. Else first non-stopword content token of len ≥ 3.
    """
    candidates = extract_subject_candidates(supported_text, k=1)
    return candidates[0] if candidates else ""


# Throwaway tokens that often start a claim but never carry subject identity.
# These are skipped over when sweeping for proper-noun candidates so the
# extractor doesn't anchor on temporal qualifiers, headers, or metadata words.
LEADING_NON_SUBJECTS = LEADING_ADJECTIVES | {
    "as", "of", "in", "on", "at", "by", "to", "for", "from", "with",
    "may", "june", "july", "august", "september", "october", "november",
    "december", "january", "february", "march", "april",
    "documented", "published", "anthropic-side", "server-side", "client-side",
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "one", "first", "second", "third", "fourth", "fifth",
    "stable", "beta", "experimental", "ga", "deprecated",
    "automated", "manual", "explicit", "implicit",
    "common", "documented", "known", "reported",
    "model", "models", "version", "versions", "type", "types",
    "as", "of", "the", "a", "an",
}


def extract_subject_candidates(supported_text: str, k: int = 4) -> list[str]:
    """Return up to k candidate subjects, best-first. Mode=claims iterates the
    list and PASSES on the first candidate whose Test A+B clears on any
    finding. This is the spec's "obvious synonym counts" leeway translated
    into a small search — claim text from `claims.json` is more verbose than
    dossier prose ("As of May 2026 the Anthropic Computer Use API…") so a
    single hard-coded first-noun pick under-counts the real subject.
    """
    cleaned = _clean_for_subject(supported_text)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9._\-+/]*", cleaned)
    content = [t for t in tokens if t.lower() not in ARTICLES_AND_PRONOUNS]

    out: list[str] = []
    seen: set[str] = set()

    def push(c: str) -> None:
        c = c.strip()
        if not c:
            return
        key = c.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(c)

    # Pass 1: known proper-noun fragments anywhere in the first 12 content tokens
    # (multi-word groups checked first via length-desc sort).
    window = " ".join(content[:12]).lower()
    for proper in sorted(_known_proper_nouns(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(proper)}\b", window):
            push(proper)
            if len(out) >= k:
                return out

    # Pass 2: capitalized non-stopword non-leading-non-subject tokens, in order.
    for tok in content:
        if tok.lower() in LEADING_NON_SUBJECTS:
            continue
        if tok[0].isupper() and len(tok) > 1:
            push(tok)
            if len(out) >= k:
                return out

    # Pass 3: first non-leading-non-subject content token of len >= 3.
    for tok in content:
        if tok.lower() in LEADING_NON_SUBJECTS:
            continue
        if len(tok) >= 3:
            push(tok)
            if len(out) >= k:
                return out

    # Pass 4: anything len >= 3 (fallback — covers leading-adjective-only claims).
    for tok in content:
        if len(tok) >= 3:
            push(tok)
            if len(out) >= k:
                return out

    return out


# Light synonym table — verifier explicitly cites "Perplexity ↔ Perplexity's
# system", "the agent ↔ agents", "GPT-5 ↔ gpt-5". Keep this conservative.
SUBJECT_SYNONYMS: dict[str, set[str]] = {
    "semgrep": {"semgrep", "semgrep ce", "semgrep pro"},
    "codeql": {"codeql"},
    "trufflehog": {"trufflehog"},
    "gitleaks": {"gitleaks"},
    "dspy": {"dspy", "miprov2", "mipro", "bootstrapfewshot"},
    "openhands": {"openhands", "open hands", "swe-agent"},
    "langgraph": {"langgraph"},
    "smolagents": {"smolagents"},
    "langfuse": {"langfuse"},
    "langsmith": {"langsmith"},
    "helicone": {"helicone"},
    "opentelemetry": {"opentelemetry", "otel", "gen_ai", "genai"},
    "litellm": {"litellm"},
    "openrouter": {"openrouter"},
    "conventional": {"conventional", "conventional-commits", "conventional commits"},
    "semantic-release": {"semantic-release", "semantic release"},
    "commitizen": {"commitizen"},
    "commitlint": {"commitlint"},
    "echoleak": {"echoleak", "cve-2025-32711"},
    "osv-scanner": {"osv-scanner", "osv.dev"},
    "syft": {"syft"},
    "grype": {"grype"},
    "gumtree": {"gumtree"},
    "ast-grep": {"ast-grep", "tree-sitter"},
    "joern": {"joern", "code property graph", "cpg"},
    "sourcegraph": {"sourcegraph"},
    "promptfoo": {"promptfoo"},
    "garak": {"garak"},
    "nemo": {"nemo", "nemo guardrails"},
    "agents.md": {"agents.md", "agents md"},
    "codeowners": {"codeowners"},
    "wayback": {"wayback", "wayback machine"},
    "crewai": {"crewai"},
}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def _subject_synonyms_for(subject: str) -> set[str]:
    s = subject.lower()
    out = {s}
    # Add stem (strip trailing 's, plural s)
    if s.endswith("'s"):
        out.add(s[:-2])
    if s.endswith("s") and len(s) > 3:
        out.add(s[:-1])
    # Add canonical groups
    for canon, group in SUBJECT_SYNONYMS.items():
        if s in group or any(s.startswith(g) or g.startswith(s) for g in group):
            out.update(group)
            out.add(canon)
    return {x for x in out if x}


def test_a_subject_match(subject: str, finding_text: str) -> bool:
    """Subject occurs in finding_text via exact or obvious-synonym match."""
    if not subject:
        return False
    haystack = _norm(finding_text)
    for cand in _subject_synonyms_for(subject):
        cand_n = _norm(cand)
        if not cand_n:
            continue
        # Word-boundary substring match against the normalized haystack.
        if re.search(rf"\b{re.escape(cand_n)}\b", haystack):
            return True
    return False


# ---------- Test B: action / property match ---------------------------------

# Conservative stopword list for content tokens used to derive action keywords.
STOPWORDS = ARTICLES_AND_PRONOUNS | {
    "via", "into", "onto", "than", "then", "while", "during", "before", "after",
    "vs", "vs.", "per", "across", "between", "among",
    "do", "does", "did", "have", "has", "had", "having",
    "can", "may", "might", "must", "should", "could", "would", "will",
    "not", "no", "yes", "only", "also", "even", "still",
    "very", "more", "most", "less", "much", "many", "some", "any", "all",
    "such", "like", "than", "thus", "however", "moreover",
    "one", "two", "three", "four", "five",
}

# Verifier explicitly allows "uses X ↔ employs X", "5-stage ↔ five-stage" —
# keep a tiny normalisation map. Numbers spelled-out get normalized to digits.
WORD_NUMBERS = {
    "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}


def _action_tokens(text: str, drop_subject: str = "") -> set[str]:
    """Extract a bag of content tokens representing the action/property.
    We drop articles, pronouns, function words, and the subject itself."""
    norm = _norm(text)
    drop_subj_n = _norm(drop_subject)
    drop_subj_tokens = set(drop_subj_n.split())
    drop_subj_synonyms = set()
    for syn in _subject_synonyms_for(drop_subject) if drop_subject else set():
        drop_subj_synonyms.update(_norm(syn).split())
    tokens = []
    for tok in norm.split():
        if tok in STOPWORDS:
            continue
        if tok in drop_subj_tokens or tok in drop_subj_synonyms:
            continue
        if len(tok) < 3 and not tok.isdigit():
            continue
        # Normalize spelled-out numbers and trailing 's plural.
        tok = WORD_NUMBERS.get(tok, tok)
        if tok.endswith("s") and len(tok) > 4:
            tok = tok[:-1]
        tokens.append(tok)
    return set(tokens)


def test_b_action_match(supported_text: str, finding_text: str, subject: str) -> tuple[bool, int]:
    """Return (passed, overlap_count). PASS if the supported_text's content
    tokens overlap the finding's content tokens by at least 2 distinct tokens
    (after subject and stopword removal). This is the spec's "paraphrase
    counts if the meaning is clearly the same" reduced to a mechanical floor.

    Threshold = 2: a single shared word is the F11 lexical-overlap trap
    (verifier failure mode). Two distinct content tokens means an action
    verb + an object/qualifier overlap, which is the minimum signal for
    semantic correspondence.
    """
    sup = _action_tokens(supported_text, drop_subject=subject)
    fnd = _action_tokens(finding_text, drop_subject=subject)
    overlap = sup & fnd
    return (len(overlap) >= 2, len(overlap))


# ---------- per-cite verdict -------------------------------------------------

@dataclass
class Violation:
    cite: str
    claim_excerpt: str
    reason: str
    line_no: int


def verify_cite(cite: Cite, sources_idx: dict[str, dict]) -> Violation | None:
    if cite.cite_id not in sources_idx:
        return Violation(
            cite=cite.cite_id,
            claim_excerpt=cite.supported_text[:80],
            reason="cited ID not in sources.jsonl",
            line_no=cite.line_no,
        )
    src = sources_idx[cite.cite_id]
    findings = src.get("findings", []) or []
    if not findings:
        return Violation(
            cite=cite.cite_id,
            claim_excerpt=cite.supported_text[:80],
            reason="source has no findings",
            line_no=cite.line_no,
        )

    subject = extract_subject(cite.supported_text)
    any_a_pass = False
    any_b_pass = False
    best_overlap = 0

    for fnd in findings:
        f_claim = fnd.get("claim", "") or ""
        f_quote = fnd.get("quote", "") or ""
        combined = f_claim + " || " + f_quote
        a = test_a_subject_match(subject, combined)
        b_pass, overlap = test_b_action_match(cite.supported_text, combined, subject)
        if a:
            any_a_pass = True
        if b_pass:
            any_b_pass = True
        best_overlap = max(best_overlap, overlap)
        if a and b_pass:
            return None  # PASS — at least one finding clears both tests

    # Determine the most specific failure reason.
    if not any_a_pass and not any_b_pass:
        reason = "no finding passes both tests"
    elif not any_a_pass:
        reason = f"Test A failed — subject '{subject}' not in source's findings"
    else:
        reason = f"Test B failed — action/property mismatch (best overlap {best_overlap})"
    return Violation(
        cite=cite.cite_id,
        claim_excerpt=cite.supported_text[:80],
        reason=reason,
        line_no=cite.line_no,
    )


# ---------- claims-mode per-cite verdict ------------------------------------

@dataclass
class ClaimsViolation:
    claim_id: str
    cite: str
    claim_excerpt: str
    reason: str


def verify_claim_cite(claim_id: str, claim_text: str, cite_id: str,
                       sources_idx: dict[str, dict]) -> ClaimsViolation | None:
    """Mode=claims companion to verify_cite(): same Test A + Test B logic, but
    the supported_text is the claim's `claim` field rather than a sentence
    extracted from prose, and the violation carries the claim_id instead of a
    line number.

    Returns None on PASS; a ClaimsViolation otherwise.
    """
    if cite_id not in sources_idx:
        return ClaimsViolation(
            claim_id=claim_id,
            cite=cite_id,
            claim_excerpt=claim_text[:80],
            reason="cited ID not in sources.jsonl",
        )
    src = sources_idx[cite_id]
    findings = src.get("findings", []) or []
    if not findings:
        return ClaimsViolation(
            claim_id=claim_id,
            cite=cite_id,
            claim_excerpt=claim_text[:80],
            reason="source has no findings",
        )

    # Claims-mode subject search: try the top K candidate subjects rather than
    # one. Claim text is wordier than dossier prose ("As of May 2026 the
    # Anthropic Computer Use API…") so the verifier-spec leeway for "obvious
    # synonym" identification of the subject translates here to "try the
    # likely-subject shortlist; PASS if any (subject, finding) pair clears
    # Tests A + B."
    candidates = extract_subject_candidates(claim_text, k=6) or [""]

    any_a_pass = False
    any_b_pass = False
    best_overlap = 0
    last_subject = candidates[0]

    for subject in candidates:
        last_subject = subject
        for fnd in findings:
            f_claim = fnd.get("claim", "") or ""
            f_quote = fnd.get("quote", "") or ""
            combined = f_claim + " || " + f_quote
            a = test_a_subject_match(subject, combined)
            b_pass, overlap = test_b_action_match(claim_text, combined, subject)
            if a:
                any_a_pass = True
            if b_pass:
                any_b_pass = True
            best_overlap = max(best_overlap, overlap)
            if a and b_pass:
                return None  # PASS — at least one finding clears both tests

    if not any_a_pass and not any_b_pass:
        reason = "no finding passes both tests"
    elif not any_a_pass:
        reason = f"Test A failed - subject '{last_subject}' not in source's findings"
    else:
        reason = f"Test B failed - action/property mismatch (best overlap {best_overlap})"
    return ClaimsViolation(
        claim_id=claim_id,
        cite=cite_id,
        claim_excerpt=claim_text[:80],
        reason=reason,
    )


# ---------- dossier-mode runner ---------------------------------------------

def run_dossier_mode(args) -> int:
    for p in (args.dossier, args.sources):
        if p is None or not p.exists():
            print(f"ERROR: missing {p}", file=sys.stderr)
            return 2

    markdown = args.dossier.read_text(encoding="utf-8")
    sources_idx = load_sources(args.sources)
    cites = extract_cites(markdown)

    # Optional sanity check: every cite ID present in claims.json should also
    # be in sources.jsonl, otherwise the brief generation already drifted.
    if args.claims and args.claims.exists():
        claims_obj = json.loads(args.claims.read_text(encoding="utf-8"))
        # claims.json may carry a top-level "claims" list, or only contradiction
        # entries with `ids` keyed as C<n> — neither is necessary for S-cite
        # validation, so we just record what we find for diagnostics.
        for entry in claims_obj.get("claims", []) or []:
            for sid in entry.get("supporting", []) or []:
                pass  # reserved for future cross-check; currently advisory

    violations: list[Violation] = []
    for c in cites:
        v = verify_cite(c, sources_idx)
        if v is not None:
            violations.append(v)

    total = len(cites)
    pass_rate = 0.0 if total == 0 else (total - len(violations)) / total

    result = {
        "mode": "dossier",
        "total_cites_checked": total,
        "unique_cite_ids": sorted({c.cite_id for c in cites}, key=lambda s: int(s[1:])),
        "violations": [
            {
                "cite": v.cite,
                "line": v.line_no,
                "claim_excerpt": v.claim_excerpt,
                "reason": v.reason,
            }
            for v in violations
        ],
        "violation_count": len(violations),
        "pass_rate": round(pass_rate, 4),
        "notes": (
            f"Validated {total} S-cite occurrences across "
            f"{len({c.cite_id for c in cites})} distinct source IDs against "
            f"{len(sources_idx)} sources. "
            f"{len(violations)} violations (mechanical Test A + Test B)."
        ),
    }

    print(json.dumps(result, indent=2))

    if not args.quiet and violations:
        sys.stderr.write(f"\n{len(violations)} cite violation(s):\n")
        for v in violations:
            sys.stderr.write(f"  L{v.line_no}  {v.cite}  {v.reason}\n    >> {v.claim_excerpt}\n")

    # Dossier mode is advisory (Phase 5.5 pre-flight wiring per SKILL.md).
    # Exit 0 always — caller decides whether violations block. The Phase 6
    # verifier is the gatekeeper; this script is the write-time advisor.
    return 0


# ---------- claims-mode runner ----------------------------------------------

def run_claims_mode(args) -> int:
    for p in (args.claims, args.sources):
        if p is None or not p.exists():
            print(f"ERROR: missing {p}", file=sys.stderr)
            return 2
    if args.dossier is not None:
        sys.stderr.write(
            f"WARN: --dossier ignored in mode=claims (got {args.dossier})\n"
        )

    sources_idx = load_sources(args.sources)
    claims_obj = json.loads(args.claims.read_text(encoding="utf-8"))
    claims_list = claims_obj.get("claims", []) or []

    violations: list[ClaimsViolation] = []
    total_pairs = 0
    unique_cite_ids: set[str] = set()

    for entry in claims_list:
        claim_id = entry.get("id", "C?")
        claim_text = entry.get("claim", "") or ""
        supporting = entry.get("supporting", []) or []
        for sid in supporting:
            total_pairs += 1
            unique_cite_ids.add(sid)
            v = verify_claim_cite(claim_id, claim_text, sid, sources_idx)
            if v is not None:
                violations.append(v)

    pass_rate = 0.0 if total_pairs == 0 else (total_pairs - len(violations)) / total_pairs

    result = {
        "mode": "claims",
        "total_claims": len(claims_list),
        "total_claim_cite_pairs_checked": total_pairs,
        "unique_cite_ids": sorted(unique_cite_ids, key=lambda s: int(s[1:]) if s[1:].isdigit() else 1_000_000),
        "violations": [
            {
                "claim_id": v.claim_id,
                "cite": v.cite,
                "claim_excerpt": v.claim_excerpt,
                "reason": v.reason,
            }
            for v in violations
        ],
        "violation_count": len(violations),
        "pass_rate": round(pass_rate, 4),
        "notes": (
            f"Validated {total_pairs} (claim, S-id) pairs across {len(claims_list)} "
            f"claims and {len(unique_cite_ids)} distinct source IDs against "
            f"{len(sources_idx)} sources. "
            f"{len(violations)} violations (mechanical Test A + Test B on claim text)."
        ),
    }

    print(json.dumps(result, indent=2))

    # Human-readable tail: one line per violation to stdout per the CLI contract.
    if violations:
        print("")
        print(f"{len(violations)} (claim, S-id) violation(s):")
        for v in violations:
            print(f"  {v.claim_id}  {v.cite}  {v.reason}")
            print(f"    >> {v.claim_excerpt}")

    return 0 if not violations else 1


# ---------- main -------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("dossier", "claims"), default=None,
                    help="Validation surface. Default: dossier (legacy). G-V5 adds claims.")
    ap.add_argument("--dossier", type=Path, required=False, default=None,
                    help="Path to dossier markdown (required for mode=dossier).")
    ap.add_argument("--sources", type=Path, required=True,
                    help="Path to sources.jsonl.")
    ap.add_argument("--claims", type=Path, required=False, default=None,
                    help="Path to claims.json (required for mode=claims; optional advisory for mode=dossier).")
    ap.add_argument("--quiet", action="store_true",
                    help="Suppress per-violation line output (machine-readable JSON only).")
    args = ap.parse_args(argv)

    # Mode resolution: explicit --mode wins; else infer from inputs.
    if args.mode is None:
        if args.dossier is not None and args.claims is None:
            args.mode = "dossier"
        elif args.claims is not None and args.dossier is None:
            # claims-only input set → assume claims mode (G-V5 convenience)
            args.mode = "claims"
        elif args.dossier is not None:
            # both supplied without --mode → preserve legacy behavior
            args.mode = "dossier"
        else:
            print("ERROR: must supply --dossier (mode=dossier) or --claims (mode=claims).",
                  file=sys.stderr)
            return 2

    if args.mode == "claims":
        if args.claims is None:
            print("ERROR: --mode claims requires --claims <path.json>.", file=sys.stderr)
            return 2
        return run_claims_mode(args)

    # mode == "dossier"
    if args.dossier is None:
        print("ERROR: --mode dossier requires --dossier <path.md>.", file=sys.stderr)
        return 2
    return run_dossier_mode(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
