#!/usr/bin/env python3
"""prompt_regions -- the explicit editability contract for Wixie prompts (WIX-CONV-001, D15).

Convergence (and output-test.py's offline and LLM fix paths) may change ONLY the bodies of
regions that the prompt file explicitly marks as editable. Everything else is immutable data.
Region boundaries come from exact marker LINES and nothing else: no Markdown/XML/fence/tag/
comment syntax is ever consulted, so malformed surrounding syntax cannot move a boundary.
Design: docs/architecture/convergence-editability.md.

Grammar (byte level; CR, LF and CRLF are the only line terminators):

    file    = [BOM] header *line                  ; BOM = EF BB BF, only at offset 0
    header  = "@wixie-editable/1 nonce=" NONCE TERM            ; physical line 1
    begin   = "@wixie-editable/1 begin " ID " " NONCE TERM
    end     = "@wixie-editable/1 end "   ID " " NONCE (TERM / end-of-file)
    NONCE   = 16 lowercase hex digits; ID = [a-z][a-z0-9_-]{0,31}, must not contain NONCE

A region body is the bytes between the end of a begin line (incl. its terminator) and the
first byte of its end line. In an annotated file, every non-marker line whose detection form
(NFKC, drop Cf/Mn/Me/default-ignorables/whitespace, NFKC, ASCII-lowercase) contains the nonce or
"wixie-editable" is a spoofed marker: the file is MALFORMED and nothing is ever written.
Recognition itself is exact bytes and never normalises (U3).

Stdlib only; linear; no recursion.

CLI:
    prompt_regions.py check FILE [--against PREV] [--translated-from SRC [--added L1-L2,...]]
    prompt_regions.py strip IN [OUT]
    prompt_regions.py strip --check MASTER SHIPPED
    prompt_regions.py annotate IN OUT --region id=Lx-Ly [...] [--exclude-nonce HEX] [--add-final-newline]
    prompt_regions.py verify ORIGINAL CANDIDATE
    prompt_regions.py commit MASTER CANDIDATE [--no-shipped]
"""
import hashlib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from typing import Optional
from enum import Enum

SCHEME = "wixie-editable/1"
SCHEME_WORD = "wixie-editable"
BOM = b"\xef\xbb\xbf"
MASTER_DIR = "editable"
TMP_TAG = ".wixie-tmp-"

_TERM_RE = re.compile(rb"\r\n|\r|\n")
_HEADER_RE = re.compile(rb"@wixie-editable/1 nonce=([0-9a-f]{16})")
_MARKER_RE = re.compile(rb"@wixie-editable/1 (begin|end) ([a-z][a-z0-9_-]{0,31}) ([0-9a-f]{16})")
_ID_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_ASCII_WS = b" \t\n\r\x0b\x0c\x1c\x1d\x1e\x1f"

# Default_Ignorable_Code_Point (DerivedCoreProperties); the stdlib has no property API for it.
_DEFAULT_IGNORABLE = (
    (0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160),
    (0x17B4, 0x17B5), (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E),
    (0x2060, 0x206F), (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)


class Status(str, Enum):
    ANNOTATED = "ANNOTATED"
    NO_REGIONS = "NO_REGIONS"
    UNANNOTATED = "UNANNOTATED"
    MALFORMED = "MALFORMED"


class RegionError(ValueError):
    """A parse / annotate / strip refusal. `code` is one of the E_* names."""

    def __init__(self, code, line=None, detail=""):
        self.code, self.line, self.detail = code, line, detail
        where = f" at line {line}" if line is not None else ""
        super().__init__(f"{code}{where}: {detail}" if detail else f"{code}{where}")


class RegionViolation(ValueError):
    """A candidate breaks the editability contract (skeleton changed, body rule broken)."""

    def __init__(self, code, region_id=None, detail=""):
        self.code, self.region_id, self.detail = code, region_id, detail
        rid = f" [{region_id}]" if region_id else ""
        super().__init__(f"{code}{rid}: {detail}" if detail else f"{code}{rid}")


class ConcurrentModification(RuntimeError):
    """The master or shipped file on disk is not what this run read (single-writer assumption)."""


@dataclass(frozen=True)
class Region:
    id: str
    start: int            # byte offset of the first body byte (in Document.raw)
    end: int              # byte offset of the end marker line (exclusive end of the body)
    eol: bytes            # the terminator new body lines get
    frozen_reason: Optional[str] = None

    @property
    def editable(self):
        return self.frozen_reason is None


@dataclass(frozen=True)
class RegionView:
    id: str
    text: str             # decoded body, line endings normalised to "\n"
    editable: bool


@dataclass(frozen=True)
class Document:
    raw: bytes
    bom: bool
    status: Status
    nonce: Optional[str] = None
    regions: tuple = ()
    error: Optional[RegionError] = None
    warnings: tuple = ()
    marker_spans: tuple = ()   # (start, end) byte spans of the header and every marker line

    @property
    def editable_regions(self):
        return tuple(r for r in self.regions if r.editable)


# ─── detection form (detect only, never accept) ──────────────────────────────────

def _is_dropped(ch):
    if ch.isspace():
        return True
    if unicodedata.category(ch) in ("Cf", "Mn", "Me"):
        return True
    cp = ord(ch)
    for lo, hi in _DEFAULT_IGNORABLE:
        if lo <= cp <= hi:
            return True
    return False


def detection_form(line: bytes) -> str:
    """NFKC, drop Cf/Mn/Me/default-ignorables/whitespace, NFKC again, ASCII-lowercase."""
    try:
        s = line.decode("utf-8")
    except UnicodeDecodeError:
        s = line.decode("utf-8", "replace")
    if s.isascii():
        return line.translate(None, _ASCII_WS).lower().decode("ascii")
    s = unicodedata.normalize("NFKC", s)
    s = "".join(ch for ch in s if not _is_dropped(ch))
    s = unicodedata.normalize("NFKC", s)
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)


def mentions_scheme(line: bytes) -> bool:
    return SCHEME_WORD in detection_form(line)


# ─── line splitting (bytes; CR / LF / CRLF only) ─────────────────────────────────

def split_lines(data: bytes):
    """Yield (start, content_end, line_end) for every physical line. Only CR, LF and CRLF
    terminate a line; VT, FF, 0x1C, NEL, U+2028/2029 are ordinary content (never splitlines)."""
    pos = 0
    n = len(data)
    for m in _TERM_RE.finditer(data):
        yield pos, m.start(), m.end()
        pos = m.end()
    if pos < n:
        yield pos, n, n


def _dominant_term(data: bytes) -> Optional[bytes]:
    counts = {}
    for m in _TERM_RE.finditer(data):
        counts[m.group()] = counts.get(m.group(), 0) + 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


# ─── parse ───────────────────────────────────────────────────────────────────────

def _malformed(raw, bom, code, line, detail="", nonce=None, warnings=()):
    return Document(raw=raw, bom=bom, status=Status.MALFORMED, nonce=nonce,
                    error=RegionError(code, line, detail), warnings=tuple(warnings))


def parse(raw: bytes) -> Document:
    """Classify `raw`. Never raises on content; problems are reported as MALFORMED."""
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError("parse() takes bytes")
    raw = bytes(raw)
    bom = raw.startswith(BOM)
    base = 3 if bom else 0
    try:
        raw[base:].decode("utf-8")
    except UnicodeDecodeError as e:
        return _malformed(raw, bom, "E_DECODE", None, f"invalid UTF-8 at byte {base + e.start}")

    lines = list(split_lines(raw[base:]))
    if not lines:
        return Document(raw=raw, bom=bom, status=Status.UNANNOTATED)
    s0, c0, e0 = lines[0]
    first = raw[base + s0:base + c0]
    hm = _HEADER_RE.fullmatch(first)
    if not hm or e0 == c0:   # the header must carry a terminator
        if detection_form(first).startswith("@" + SCHEME_WORD):
            return _malformed(raw, bom, "E_BAD_HEADER", 1,
                              "line 1 looks like a wixie-editable header but is not exact")
        warnings = []
        for i, (s, c, _e) in enumerate(lines, start=1):
            if mentions_scheme(raw[base + s:base + c]):
                warnings.append(f"marker_like_text_ignored@L{i}")
        return Document(raw=raw, bom=bom, status=Status.UNANNOTATED, warnings=tuple(warnings))

    nonce = hm.group(1).decode("ascii")
    nonce_b = nonce.encode("ascii")
    spans = [(base + s0, base + e0)]
    regions = []
    seen = set()
    open_reg = None   # (id, body_start, begin_term)
    for i, (s, c, e) in enumerate(lines[1:], start=2):
        content = raw[base + s:base + c]
        term = raw[base + c:base + e]
        mm = _MARKER_RE.fullmatch(content)
        if mm and mm.group(3) == nonce_b:
            kind = mm.group(1).decode()
            rid = mm.group(2).decode()
            if nonce in rid:
                return _malformed(raw, bom, "E_BAD_ID", i, f"id {rid!r} contains the nonce", nonce)
            spans.append((base + s, base + e))
            if kind == "begin":
                if open_reg is not None:
                    return _malformed(raw, bom, "E_NESTED", i,
                                      f"begin {rid!r} while {open_reg[0]!r} is open", nonce)
                if rid in seen:
                    return _malformed(raw, bom, "E_DUPLICATE_ID", i, f"id {rid!r}", nonce)
                if not term:
                    return _malformed(raw, bom, "E_TRUNCATED", i, "begin marker without a terminator", nonce)
                seen.add(rid)
                open_reg = (rid, base + e, term)
            else:
                if open_reg is None:
                    return _malformed(raw, bom, "E_STRAY_END", i, f"end {rid!r} with no open region", nonce)
                if rid != open_reg[0]:
                    return _malformed(raw, bom, "E_MISMATCHED_END", i,
                                      f"end {rid!r} closes {open_reg[0]!r}", nonce)
                body_start, body_end = open_reg[1], base + s
                body = raw[body_start:body_end]
                terms = set(_TERM_RE.findall(body))
                if len(terms) > 1:
                    eol, frozen = open_reg[2], "mixed-eol"
                elif terms:
                    eol, frozen = terms.pop(), None
                else:
                    eol, frozen = open_reg[2], None
                regions.append(Region(rid, body_start, body_end, eol, frozen))
                open_reg = None
            continue
        df = detection_form(content)
        if nonce_b in content.lower() or SCHEME_WORD in df or nonce in df:
            return _malformed(raw, bom, "E_SPOOFED_MARKER", i,
                              "line mentions the scheme or the nonce but is not an exact marker", nonce)
    if open_reg is not None:
        return _malformed(raw, bom, "E_UNCLOSED", None, f"region {open_reg[0]!r} is never closed", nonce)
    status = Status.ANNOTATED if regions else Status.NO_REGIONS
    return Document(raw=raw, bom=bom, status=status, nonce=nonce, regions=tuple(regions),
                    marker_spans=tuple(spans))


# ─── bodies / apply / verify ─────────────────────────────────────────────────────

def _norm(b: bytes) -> str:
    return b.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def bodies(doc: Document) -> list:
    if doc.status not in (Status.ANNOTATED, Status.NO_REGIONS):
        return []
    return [RegionView(r.id, _norm(doc.raw[r.start:r.end]), r.editable) for r in doc.regions]


def _check_body_text(doc, region, text):
    if not isinstance(text, str):
        raise RegionViolation("E_BODY_TYPE", region.id, "a body must be str")
    if "\r" in text:
        raise RegionViolation("E_BODY_CR", region.id, "bodies use \\n only")
    if text and not text.endswith("\n"):
        raise RegionViolation("E_BODY_UNTERMINATED", region.id, "a non-empty body must end with \\n")
    if doc.nonce and doc.nonce in text.lower():
        raise RegionViolation("E_BODY_NONCE", region.id, "a body may not contain the nonce")
    for line in text.split("\n"):
        enc = line.encode("utf-8")
        if mentions_scheme(enc) or (doc.nonce and doc.nonce in detection_form(enc)):
            raise RegionViolation("E_BODY_MARKER_TEXT", region.id, "a body may not contain marker text")


def apply(doc: Document, new) -> bytes:
    """Reassemble: skeleton bytes are copied slices of doc.raw; each changed body is its text
    with "\\n" mapped to the region's eol. `new` has one entry per region (None = unchanged)."""
    if doc.status not in (Status.ANNOTATED, Status.NO_REGIONS):
        raise RegionViolation("E_NOT_ANNOTATED", None, f"status {doc.status.value}")
    new = list(new)
    if len(new) != len(doc.regions):
        raise RegionViolation("E_REGION_COUNT", None, f"{len(new)} bodies for {len(doc.regions)} regions")
    out = []
    pos = 0
    for region, text in zip(doc.regions, new):
        out.append(doc.raw[pos:region.start])
        old = doc.raw[region.start:region.end]
        if text is None or text == _norm(old):
            out.append(old)
        else:
            if not region.editable:
                raise RegionViolation("E_FROZEN_REGION", region.id, region.frozen_reason or "")
            _check_body_text(doc, region, text)
            out.append(text.replace("\n", region.eol.decode("ascii")).encode("utf-8"))
        pos = region.end
    out.append(doc.raw[pos:])
    return b"".join(out)


def skeleton(doc: Document) -> tuple:
    """The immutable parts: the slices between region bodies (BOM, header, markers, data)."""
    parts, pos = [], 0
    for r in doc.regions:
        parts.append(doc.raw[pos:r.start])
        pos = r.end
    parts.append(doc.raw[pos:])
    return tuple(parts)


def verify(orig: Document, candidate: bytes) -> Document:
    """THE invariant. Re-parses `candidate` independently of apply(): same status class, BOM,
    nonce and ordered ids; byte-identical skeleton; body rules; frozen bodies unchanged.
    Returns the candidate's Document; raises RegionViolation."""
    if orig.status not in (Status.ANNOTATED, Status.NO_REGIONS):
        raise RegionViolation("E_NOT_ANNOTATED", None, f"original status {orig.status.value}")
    cand = parse(candidate)
    if cand.status is Status.MALFORMED:
        raise RegionViolation("E_CANDIDATE_MALFORMED", None, str(cand.error))
    if cand.status != orig.status:
        raise RegionViolation("E_STATUS_CHANGED", None, f"{orig.status.value} -> {cand.status.value}")
    if cand.bom != orig.bom:
        raise RegionViolation("E_BOM_CHANGED")
    if cand.nonce != orig.nonce:
        raise RegionViolation("E_NONCE_CHANGED")
    if [r.id for r in cand.regions] != [r.id for r in orig.regions]:
        raise RegionViolation("E_IDS_CHANGED", None,
                              f"{[r.id for r in orig.regions]} -> {[r.id for r in cand.regions]}")
    if skeleton(cand) != skeleton(orig):
        raise RegionViolation("E_SKELETON_CHANGED", None, "bytes outside the editable regions changed")
    for o, c in zip(orig.regions, cand.regions):
        ob, cb = orig.raw[o.start:o.end], cand.raw[c.start:c.end]
        if not o.editable:
            if ob != cb:
                raise RegionViolation("E_FROZEN_REGION", o.id, o.frozen_reason or "")
            continue
        if ob == cb:
            continue
        terms = set(_TERM_RE.findall(cb))
        if terms - {o.eol}:
            raise RegionViolation("E_BODY_EOL", o.id, "body line endings differ from the region's")
        _check_body_text(orig, o, _norm(cb))
    return cand


# ─── strip / view ────────────────────────────────────────────────────────────────

def strip(raw: bytes) -> bytes:
    """Lifecycle strip (commit, strip CLI): remove the header and marker lines with their
    terminators, keep every other byte (BOM included). Strict: ANNOTATED / NO_REGIONS input
    only, and the output may contain no scheme text. Deterministic; strip of a stripped file
    is refused (it is UNANNOTATED), which is the idempotence guard of the lifecycle."""
    doc = parse(raw)
    if doc.status is Status.MALFORMED:
        raise doc.error
    if doc.status is Status.UNANNOTATED:
        raise RegionError("E_NOT_ANNOTATED", None, "strip needs an annotated master")
    out, pos = [], 0
    for s, e in doc.marker_spans:
        out.append(doc.raw[pos:s])
        pos = e
    out.append(doc.raw[pos:])
    result = b"".join(out)
    base = 3 if result.startswith(BOM) else 0
    for i, (s, c, _e) in enumerate(split_lines(result[base:]), start=1):
        if mentions_scheme(result[base + s:base + c]):
            raise RegionError("E_SCHEME_IN_OUTPUT", i, "stripped output would contain scheme text")
    if parse(result).status is not Status.UNANNOTATED:
        raise RegionError("E_SCHEME_IN_OUTPUT", None, "stripped output is not plain")
    return result


def view(raw: bytes, normalize_newlines: bool = False) -> str:
    """Reader input (scorers, model calls). ANNOTATED/NO_REGIONS -> strip decoded;
    UNANNOTATED -> the raw bytes decoded; MALFORMED -> RegionError. The BOM is dropped."""
    doc = parse(raw)
    if doc.status is Status.MALFORMED:
        raise doc.error
    data = strip(raw) if doc.status in (Status.ANNOTATED, Status.NO_REGIONS) else raw
    if data.startswith(BOM):
        data = data[3:]
    text = data.decode("utf-8")
    if normalize_newlines:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def read_view(path, normalize_newlines: bool = False) -> str:
    with open(path, "rb") as f:
        return view(f.read(), normalize_newlines=normalize_newlines)


# ─── master / shipped identity ───────────────────────────────────────────────────

def is_master(path) -> bool:
    return os.path.basename(os.path.dirname(os.path.abspath(path))) == MASTER_DIR


def shipped_for(master_path) -> str:
    """editable/<f> -> <prompt folder>/<f>. Must differ from the input and stay inside the
    prompt folder (the directory that contains editable/)."""
    master_path = os.path.abspath(master_path)
    if not is_master(master_path):
        raise RegionError("E_NOT_MASTER", None, f"{master_path} is not under an '{MASTER_DIR}' directory")
    folder = os.path.dirname(os.path.dirname(master_path))
    shipped = os.path.join(folder, os.path.basename(master_path))
    real_folder = os.path.realpath(folder)
    real_shipped = os.path.realpath(shipped)
    if os.path.normcase(real_shipped) == os.path.normcase(os.path.realpath(master_path)):
        raise RegionError("E_SHIPPED_IS_MASTER", None, shipped)
    if os.path.normcase(os.path.dirname(real_shipped)) != os.path.normcase(real_folder):
        raise RegionError("E_SHIPPED_OUTSIDE_FOLDER", None, shipped)
    return shipped


def master_for(shipped_path) -> Optional[str]:
    shipped_path = os.path.abspath(shipped_path)
    cand = os.path.join(os.path.dirname(shipped_path), MASTER_DIR, os.path.basename(shipped_path))
    return cand if os.path.isfile(cand) else None


def prompt_folder_of(path) -> str:
    path = os.path.abspath(path)
    return os.path.dirname(os.path.dirname(path)) if is_master(path) else os.path.dirname(path)


def stale_temp_files(path) -> list:
    d = os.path.dirname(os.path.abspath(path))
    prefix = "." + os.path.basename(path) + TMP_TAG
    try:
        return sorted(os.path.join(d, n) for n in os.listdir(d) if n.startswith(prefix))
    except OSError:
        return []


# ─── commit (master + shipped, CAS restore) ──────────────────────────────────────

def _read_or_none(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _tmp_path(path):
    return os.path.join(os.path.dirname(os.path.abspath(path)),
                        "." + os.path.basename(path) + TMP_TAG + str(os.getpid()))


def _atomic_write(path, data):
    tmp = _tmp_path(path)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def cas_restore(path, written: Optional[bytes], original: Optional[bytes]) -> str:
    """Compare-then-replace (NOT atomic; single-writer assumption): restore `original` only if
    the disk still holds `written`. Returns 'restored', 'untouched' or 'concurrent'."""
    cur = _read_or_none(path)
    if cur == original:
        return "untouched"
    if cur != written:
        return "concurrent"
    if original is None:
        os.remove(path)
    else:
        _atomic_write(path, original)
    return "restored"


def commit(orig: Document, master_path, shipped_path, new_master: bytes, expected) -> dict:
    """Write the master and shipped = strip(master) as a pair. `expected` = (master bytes,
    shipped bytes or None) this run believes are on disk (advance it after each commit).
    Raises ConcurrentModification (nothing written), RegionViolation / RegionError (nothing
    written), or re-raises after CAS-restoring both files on a write/re-read failure."""
    exp_master, exp_shipped = expected
    if _read_or_none(master_path) != exp_master:
        raise ConcurrentModification(f"{master_path} changed on disk during the run")
    if shipped_path is not None and _read_or_none(shipped_path) != exp_shipped:
        raise ConcurrentModification(f"{shipped_path} changed on disk during the run")
    verify(orig, new_master)
    shipped = strip(new_master) if shipped_path is not None else None
    result = {
        "master_sha256": hashlib.sha256(new_master).hexdigest(),
        "shipped_sha256": hashlib.sha256(shipped).hexdigest() if shipped is not None else None,
        "master": new_master,
        "shipped": shipped,
        "written": False,
    }
    if new_master == exp_master and (shipped_path is None or shipped == exp_shipped):
        return result
    wrote_master = wrote_shipped = False
    try:
        if new_master != exp_master:
            _atomic_write(master_path, new_master)
            wrote_master = True
        if shipped_path is not None and shipped != exp_shipped:
            _atomic_write(shipped_path, shipped)
            wrote_shipped = True
        if _read_or_none(master_path) != new_master:
            raise RegionViolation("E_REREAD_MASTER", None, "master on disk differs from the committed bytes")
        verify(orig, _read_or_none(master_path))
        if shipped_path is not None:
            on_disk = _read_or_none(shipped_path)
            if on_disk != shipped or on_disk != strip(new_master):
                raise RegionViolation("E_REREAD_SHIPPED", None, "shipped file differs from strip(master)")
    except BaseException:
        if wrote_master:
            cas_restore(master_path, new_master, exp_master)
        if wrote_shipped:
            cas_restore(shipped_path, shipped, exp_shipped)
        raise
    result["written"] = True
    return result


# ─── annotate ────────────────────────────────────────────────────────────────────

def derive_nonce(content: bytes, exclude=()) -> str:
    lowered = content.lower()
    forms = None
    excl = {x.lower() for x in exclude}
    counter = 0
    while True:
        h = hashlib.sha256(b"wixie-editable/1\0" + content + (b"\0%d" % counter if counter else b""))
        nonce = h.hexdigest()[:16]
        counter += 1
        if nonce in excl or nonce.encode() in lowered:
            continue
        if forms is None:
            base = 3 if content.startswith(BOM) else 0
            forms = [detection_form(content[base + s:base + c]) for s, c, _e in split_lines(content[base:])]
        if any(nonce in f for f in forms):
            continue
        return nonce


def annotate(raw: bytes, ranges, *, exclude_nonces=(), add_final_newline=False, filename=None) -> bytes:
    """Insert a header and begin/end markers around explicit, human-confirmed 1-based
    inclusive line ranges [(id, first, last), ...]. The only writer of marker lines."""
    raw = bytes(raw)
    doc = parse(raw)
    if doc.status is Status.MALFORMED:
        raise doc.error
    if doc.status is not Status.UNANNOTATED:
        raise RegionError("E_ALREADY_ANNOTATED", 1, "input already carries a header")
    bom = raw.startswith(BOM)
    base = 3 if bom else 0
    content = raw[base:]
    lines = list(split_lines(content))
    for i, (s, c, _e) in enumerate(lines, start=1):
        if mentions_scheme(content[s:c]):
            raise RegionError("E_CONTENT_MENTIONS_SCHEME", i,
                              "a prompt that mentions the scheme cannot be annotated; it stays unannotated")
    ranges = [(str(r[0]), int(r[1]), int(r[2])) for r in ranges]
    if ranges and filename and filename.lower().endswith(".json"):
        raise RegionError("E_JSON_REGIONS", None, "regions are refused in .json prompts")
    seen = set()
    prev_last = 0
    for rid, first, last in sorted(ranges, key=lambda r: r[1]):
        if not _ID_RE.match(rid):
            raise RegionError("E_BAD_ID", None, f"bad id {rid!r}")
        if rid in seen:
            raise RegionError("E_DUPLICATE_ID", None, rid)
        seen.add(rid)
        if not (1 <= first <= last <= len(lines)):
            raise RegionError("E_BAD_RANGE", None, f"{rid}=L{first}-L{last} outside 1..{len(lines)}")
        if first <= prev_last:
            raise RegionError("E_OVERLAP", None, f"{rid} overlaps the previous range")
        prev_last = last
    dominant = _dominant_term(content) or b"\n"
    appended = b""
    if lines and lines[-1][1] == lines[-1][2]:          # last line has no terminator
        if any(last == len(lines) for _r, _f, last in ranges):
            if not add_final_newline:
                raise RegionError("E_RANGE_UNTERMINATED", len(lines),
                                  "the range ends on a final line without a newline; pass --add-final-newline")
            appended = dominant
            content = content + appended
            lines = list(split_lines(content))
    excluded = list(exclude_nonces)
    while True:
        nonce = derive_nonce(content, excluded)
        if not any(nonce in rid for rid, _f, _l in ranges):
            break
        excluded.append(nonce)
    nb = nonce.encode("ascii")

    def term_of(idx):   # 1-based line
        s, c, e = lines[idx - 1]
        return content[c:e] or dominant

    header_term = (term_of(1) if lines and lines[0][1] != lines[0][2] else None) or dominant
    begins = {first: rid for rid, first, _l in ranges}
    ends = {last: rid for rid, _f, last in ranges}
    out = [raw[:base], b"@wixie-editable/1 nonce=" + nb + header_term]
    for i, (s, c, e) in enumerate(lines, start=1):
        if i in begins:
            out.append(b"@wixie-editable/1 begin " + begins[i].encode() + b" " + nb + term_of(i))
        out.append(content[s:e])
        if i in ends:
            out.append(b"@wixie-editable/1 end " + ends[i].encode() + b" " + nb + term_of(i))
    result = b"".join(out)
    check = parse(result)
    if check.status not in (Status.ANNOTATED, Status.NO_REGIONS):
        raise RegionError("E_ANNOTATE_SELFCHECK", None, str(check.error or check.status.value))
    if strip(result) != raw[:base] + content:
        raise RegionError("E_ANNOTATE_SELFCHECK", None, "strip(result) != input")
    return result


# ─── region line map (for check --translated-from --added) ───────────────────────

def region_stripped_lines(doc: Document) -> dict:
    """{id: (first, last)} in the stripped file's 1-based line numbering (empty body: (n, n-1))."""
    base = 3 if doc.bom else 0
    out, stripped_no, cur = {}, 0, None
    marker_starts = {s for s, _e in doc.marker_spans}
    starts = {r.start: r.id for r in doc.regions}
    ends = {r.end: r.id for r in doc.regions}
    first_line = {}
    for s, c, e in split_lines(doc.raw[base:]):
        abs_s = base + s
        if abs_s in ends:
            rid = ends[abs_s]
            out[rid] = (first_line[rid], stripped_no)
        if abs_s in marker_starts:
            if base + e in starts:
                first_line[starts[base + e]] = stripped_no + 1
            continue
        stripped_no += 1
    return out


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _describe(doc: Document) -> dict:
    return {
        "scheme": SCHEME,
        "status": doc.status.value,
        "nonce": doc.nonce,
        "regions": [{"id": r.id, "bytes": r.end - r.start, "editable": r.editable,
                     "frozen_reason": r.frozen_reason} for r in doc.regions],
        "error": None if doc.error is None else {"code": doc.error.code, "line": doc.error.line,
                                                  "detail": doc.error.detail},
        "warnings": list(doc.warnings),
    }


def _parse_ranges(specs):
    out = []
    for spec in specs:
        m = re.fullmatch(r"([^=]+)=L?(\d+)-L?(\d+)", spec)
        if not m:
            raise RegionError("E_BAD_RANGE", None, f"bad --region {spec!r} (want id=Lx-Ly)")
        out.append((m.group(1), int(m.group(2)), int(m.group(3))))
    return out


def _cli(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, args = argv[0], argv[1:]

    def opt(name, multi=False):
        vals = []
        while name in args:
            i = args.index(name)
            if i + 1 >= len(args):
                raise RegionError("E_USAGE", None, f"{name} needs a value")
            vals.append(args[i + 1])
            del args[i:i + 2]
        return vals if multi else (vals[-1] if vals else None)

    def flag(name):
        if name in args:
            args.remove(name)
            return True
        return False

    try:
        if cmd == "check":
            against = opt("--against")
            src = opt("--translated-from")
            added = opt("--added")
            if len(args) != 1:
                raise RegionError("E_USAGE", None, "check FILE")
            doc = parse(_read(args[0]))
            report = _describe(doc)
            ok = doc.status in (Status.ANNOTATED, Status.NO_REGIONS)
            problems = []
            if ok and args[0].lower().endswith(".json") and doc.regions:
                problems.append("E_JSON_REGIONS: regions are refused in .json prompts")
            if ok and doc.status is not Status.MALFORMED:
                try:
                    strip(doc.raw)
                except RegionError as e:
                    problems.append(str(e))
            if against:
                prev = parse(_read(against))
                prev_sizes = {r.id: r.end - r.start for r in prev.regions}
                report["added_ids"] = [r.id for r in doc.regions if r.id not in prev_sizes]
                report["grown"] = {r.id: (r.end - r.start) - prev_sizes[r.id] for r in doc.regions
                                   if r.id in prev_sizes and (r.end - r.start) > prev_sizes[r.id]}
            if src:
                sdoc = parse(_read(src))
                src_ids = {r.id for r in sdoc.regions}
                extra = [r.id for r in doc.regions if r.id not in src_ids]
                if extra:
                    problems.append(f"E_TRANSLATED_NEW_IDS: {extra}")
                if sdoc.nonce and doc.nonce == sdoc.nonce:
                    problems.append("E_TRANSLATED_NONCE_REUSED")
                if added and ok:
                    spans = region_stripped_lines(doc)
                    for part in added.split(","):
                        m = re.fullmatch(r"L?(\d+)-L?(\d+)", part.strip())
                        if not m:
                            raise RegionError("E_USAGE", None, f"bad --added {part!r}")
                        a, b = int(m.group(1)), int(m.group(2))
                        for rid, (f, l) in spans.items():
                            if f <= l and not (l < a or b < f):
                                problems.append(f"E_REGION_OVERLAPS_ADDED: {rid} overlaps L{a}-L{b}")
            report["problems"] = problems
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if ok and not problems else 1
        if cmd == "strip":
            if flag("--check"):
                if len(args) != 2:
                    raise RegionError("E_USAGE", None, "strip --check MASTER SHIPPED")
                want = strip(_read(args[0]))
                have = _read(args[1]) if os.path.isfile(args[1]) else None
                if have != want:
                    print(f"MISMATCH: {args[1]} != strip({args[0]})", file=sys.stderr)
                    return 1
                print("OK")
                return 0
            if len(args) not in (1, 2):
                raise RegionError("E_USAGE", None, "strip IN [OUT]")
            out = strip(_read(args[0]))
            if len(args) == 2:
                _atomic_write(args[1], out)
            else:
                sys.stdout.buffer.write(out)
            return 0
        if cmd == "annotate":
            regions = _parse_ranges(opt("--region", multi=True))
            excl = opt("--exclude-nonce", multi=True)
            afn = flag("--add-final-newline")
            if len(args) != 2:
                raise RegionError("E_USAGE", None, "annotate IN OUT --region id=Lx-Ly ...")
            if os.path.exists(args[1]) and os.path.samefile(args[0], args[1]):
                raise RegionError("E_USAGE", None, "OUT must differ from IN")
            result = annotate(_read(args[0]), regions, exclude_nonces=excl, add_final_newline=afn,
                              filename=args[1])
            os.makedirs(os.path.dirname(os.path.abspath(args[1])), exist_ok=True)
            _atomic_write(args[1], result)
            print(json.dumps(_describe(parse(result)), indent=2, sort_keys=True))
            return 0
        if cmd == "verify":
            if len(args) != 2:
                raise RegionError("E_USAGE", None, "verify ORIGINAL CANDIDATE")
            orig = parse(_read(args[0]))
            verify(orig, _read(args[1]))
            print("OK")
            return 0
        if cmd == "commit":
            no_shipped = flag("--no-shipped")
            if len(args) != 2:
                raise RegionError("E_USAGE", None, "commit MASTER CANDIDATE [--no-shipped]")
            master, cand_path = args
            orig_raw = _read(master)
            orig = parse(orig_raw)
            shipped = None
            exp_shipped = None
            if not no_shipped:
                shipped = shipped_for(master)
                exp_shipped = _read_or_none(shipped)
                if exp_shipped != strip(orig_raw):
                    raise RegionError("E_PAIR_MISMATCH", None, f"{shipped} != strip({master})")
            res = commit(orig, master, shipped, _read(cand_path), (orig_raw, exp_shipped))
            print(json.dumps({k: v for k, v in res.items() if k not in ("master", "shipped")},
                             sort_keys=True))
            return 0
    except (RegionError, RegionViolation, ConcurrentModification, OSError) as e:
        print(f"prompt_regions {cmd}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1 if isinstance(e, (RegionViolation, ConcurrentModification)) else 2
    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
