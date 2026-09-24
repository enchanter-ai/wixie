#!/usr/bin/env python3
"""Wixie Inference Engine — evidence accumulation over an artifact stream.

Stdlib only. No external runtime deps.

Subcommands:
    emit <record.json|->            Append an artifact record to state/artifacts.jsonl
    reconcile                       Fingerprint artifacts (U1), run Wald SPRT (U2), update Beta-Binomial (U3), apply EMA decay (U5). Atomic catalog write.
    render-briefing <plugin>        Render state/briefings/<plugin>.md from catalog
    query <term>                    Search catalog by code, tag, or pattern_id. JSON to stdout.
    backfill <source.jsonl>         Replay an external JSONL (e.g. precedent.jsonl) through emit
    status                          Print catalog summary + last reconcile timestamp

Algorithms (all stdlib):
    U1 Pattern fingerprint          SHA-1 of (code, sorted(tags)) — deterministic id per semantic pattern
    U2 Wald SPRT                    log-likelihood ratio over recurrences; elevate at +2.89, retire at -2.25
    U3 Beta-Binomial posterior      alpha/beta per pattern; mean + 95% CI via beta quantile
    U5 EMA decay                    weight *= exp(-lambda * days_since_last_seen); lambda = ln(2)/30
    U6 Reservoir sampling           bounded retention of raw artifacts per pattern (K=50 Vitter)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


# Windows default console is cp1252 — reconfigure to UTF-8 so non-ASCII glyphs
# (em-dashes, arrows, CI brackets) in output don't crash the subcommand.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ─── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = SCRIPT_DIR.parent.parent / "plugins" / "inference-engine"
# Tests + sandboxes override via WIXIE_INFERENCE_STATE to avoid polluting
# production state at plugins/inference-engine/state/.
STATE_DIR = Path(os.environ.get("WIXIE_INFERENCE_STATE") or (PLUGIN_DIR / "state"))
BRIEFINGS_DIR = STATE_DIR / "briefings"
CATALOG_PATH = STATE_DIR / "catalog.json"


def env_enabled() -> bool:
    """Opt-in gate — default off during rollout per ship_scope."""
    return os.environ.get("WIXIE_INFERENCE_ENABLED", "0") == "1"


def artifacts_path(ts: datetime | None = None) -> Path:
    # One master append-only log. Rotation deferred until volume warrants it
    # (see discipline.md — three similar lines beats a premature abstraction).
    return STATE_DIR / "artifacts.jsonl"


def append_jsonl_locked(path: Path, line: str) -> None:
    """Append one JSON line, locked + flushed. Cross-platform.

    Closes F-015: parallel races and partial-line writes on artifacts.jsonl
    that biased the SPRT walk. Per spec section G.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not line.endswith("\n"):
        line += "\n"
    with path.open("a", encoding="utf-8") as f:
        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            finally:
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        else:
            import fcntl
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


# ─── Event identity (WIX-RUN-002) ─────────────────────────────────────────────
#
# One stored line = one logical event. Its identity is a SHA-256 over the stored record's
# identity basis: every field except the engine metadata keys below, with the event's source
# coordinates (session_id, ts/date, source_session, event_id, source_ordinal) part of the basis.
# The same logical event therefore has the same identity however many times it is imported,
# while the same payload in a different session, at a different supplied time, or with a
# different event_id is a different event.
#
# Every value the engine stamps is either deterministic from the source record (backfill) or
# a recorded fact of the event (emit's session and generated event_id), so re-hashing a stored
# line always reproduces its identity. The one non-reproducible stamp, a ts filled from the
# engine's clock, is flagged with _ts_clock and left out of the basis.
#
# This is NOT pattern dedup: fingerprint() below is the many-to-one pattern key that reconcile
# accumulates over. Identity only stops the same event from being counted twice.

META_KEYS = ("_identity", "_session_source", "_ts_clock")
UNKNOWN_SESSION = "unknown"


def with_ordinal(record: dict, ordinal: int) -> dict:
    """The ordinal-th repeat (0-based) of an identical record within one source file is its own
    event. Ordinal 0 leaves the record unchanged, so a record that occurs once is unaffected."""
    if not ordinal:
        return record
    out = dict(record)
    prev = out.get("source_ordinal")
    out["source_ordinal"] = ordinal if prev is None else f"{prev}.{ordinal}"
    return out


def identity_basis(record: dict) -> dict:
    basis = {k: v for k, v in record.items() if k not in META_KEYS}
    if record.get("_ts_clock") is True:
        basis.pop("ts", None)
    return basis


def canonical(record: dict) -> str:
    return json.dumps(identity_basis(record), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def event_identity(record: dict) -> str:
    return hashlib.sha256(canonical(record).encode("utf-8")).hexdigest()[:32]


def resolve_session(record: dict, *, use_env: bool) -> tuple[str, str]:
    """Source-session precedence, first match wins:

        record session_id > record source_session > $CLAUDE_CODE_SESSION_ID
        > $CLAUDE_SESSION_ID > "unknown"

    The environment is consulted only for emit (the event is happening in this session).
    backfill never consults it: the importing session is not where the event happened.
    Returns (session, provenance); the provenance is stored as _session_source.
    """
    for key in ("session_id", "source_session"):
        val = record.get(key)
        if isinstance(val, str) and val.strip():
            return val, f"record:{key}"
    if use_env:
        for var in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID"):
            val = os.environ.get(var, "").strip()
            if val:
                return val, f"env:{var}"
    return UNKNOWN_SESSION, "unknown"


def stamp_session(record: dict, *, use_env: bool) -> None:
    session, source = resolve_session(record, use_env=use_env)
    if not (isinstance(record.get("session_id"), str) and record["session_id"].strip()):
        record["session_id"] = session
    record.setdefault("_session_source", source)


# ─── U1: Pattern fingerprint ──────────────────────────────────────────────────


def fingerprint(record: dict) -> str:
    """SHA-1 of (code, sorted(tags)). Deterministic across sessions."""
    code = record.get("code", "")
    tags = sorted(record.get("tags") or [])
    key = f"{code}|{'|'.join(tags)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# ─── U2: Wald Sequential Probability Ratio Test ───────────────────────────────

# Hypothesis test:
#   H0: pattern is noise         (p0 = 0.05 per independent observation)
#   H1: pattern is real recurrence (p1 = 0.30 per independent observation)
# Thresholds (Wald, alpha=0.05, beta=0.10):
#   A = ln((1-beta)/alpha) = ln(0.90/0.05) ≈ 2.890
#   B = ln(beta/(1-alpha)) = ln(0.10/0.95) ≈ -2.251

P0 = 0.05
P1 = 0.30
LLR_ELEVATE = math.log((1 - 0.10) / 0.05)
LLR_RETIRE = math.log(0.10 / (1 - 0.05))
LLR_POS = math.log(P1 / P0)            # +obs increment
LLR_NEG = math.log((1 - P1) / (1 - P0))  # -obs (non-recurrence) — usually unused


def sprt_update(prior_llr: float, positive_observations: int) -> float:
    """Add positive_observations to the running LLR. Capped at [-10, +10] to prevent overflow."""
    new_llr = prior_llr + positive_observations * LLR_POS
    return max(-10.0, min(10.0, new_llr))


def sprt_verdict(llr: float) -> str:
    if llr >= LLR_ELEVATE:
        return "elevated"
    if llr <= LLR_RETIRE:
        return "retired"
    return "noise"


# ─── U3: Beta-Binomial posterior ──────────────────────────────────────────────


def beta_update(alpha: float, beta: float, successes: int, failures: int) -> tuple[float, float]:
    return alpha + successes, beta + failures


def beta_mean(alpha: float, beta: float) -> float:
    return alpha / (alpha + beta)


def _beta_quantile(alpha: float, beta: float, q: float, iters: int = 60) -> float:
    """Bisection over the regularized incomplete beta via series. Stdlib-only.

    For small alpha/beta (common here), a coarse bisection is enough for a
    95% CI that matches our honest-numbers contract — we don't need 6 decimals.
    """
    lo, hi = 0.0, 1.0
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        # Regularized incomplete beta via math.lgamma + simple Simpson integration.
        # Enough for CI reporting; not hot-path.
        cdf = _incomplete_beta(alpha, beta, mid)
        if cdf < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _incomplete_beta(a: float, b: float, x: float, steps: int = 256) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    # I_x(a,b) via Simpson's rule on the integrand t^(a-1) * (1-t)^(b-1) / B(a,b).
    log_betaB = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    h = x / steps

    def f(t: float) -> float:
        if t <= 0 or t >= 1:
            return 0.0
        return math.exp((a - 1) * math.log(t) + (b - 1) * math.log(1 - t) - log_betaB)

    s = f(0.0) + f(x)
    for i in range(1, steps):
        s += (4 if i % 2 else 2) * f(i * h)
    return max(0.0, min(1.0, s * h / 3.0))


def beta_ci(alpha: float, beta: float, level: float = 0.95) -> tuple[float, float]:
    tail = (1 - level) / 2
    return (_beta_quantile(alpha, beta, tail), _beta_quantile(alpha, beta, 1 - tail))


# ─── U5: EMA decay ────────────────────────────────────────────────────────────

# lambda = ln(2) / half_life_days. half_life=30 days = a pattern unseen for 30 days
# weighs half what it did when last seen.
HALF_LIFE_DAYS = 30.0
LAMBDA = math.log(2.0) / HALF_LIFE_DAYS


def ema_weight(days_since_last_seen: float, base: float = 1.0) -> float:
    return base * math.exp(-LAMBDA * max(0.0, days_since_last_seen))


# ─── U6: Reservoir sampling (Vitter Algorithm R) ──────────────────────────────


def reservoir_add(reservoir: list, item, k: int, rng: random.Random) -> list:
    if len(reservoir) < k:
        reservoir.append(item)
    else:
        idx = rng.randint(0, len(reservoir))
        if idx < k:
            reservoir[idx] = item
    return reservoir


# ─── IO helpers ───────────────────────────────────────────────────────────────


def atomic_write_text(path: Path, text: str) -> None:
    """Write to a uniquely named sibling temp file, fsync, then rename over the target.

    A crash at any point leaves either the previous file or the new one, never a torn file:
    the temp name is unique per call (mkstemp), the data is durable before the rename, and a
    failed write removes its own temp file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    tmp: Path | None = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass


def atomic_write_json(path: Path, data) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


# ─── Derived catalog: validation, quarantine, recovery (WIX-RUN-004) ──────────
#
# catalog.json is derived state: reconcile rebuilds all of it from the artifact log and reads
# the previous copy only to keep the first-crossing stamps (elevated_at / retired_at). A
# catalog that cannot be read or does not have the catalog shape is CORRUPT:
#
#   reconcile                      moves it to catalog.json.corrupt-<UTC stamp> (never deletes
#                                  it), rebuilds from the log, carries over stamps from any
#                                  entries that were still well-formed, records last_recovery
#                                  in the new catalog, and exits 0 (or 3, see WIX-RUN-003).
#   status / query / render-briefing  refuse with exit 74 and point at reconcile; they never
#                                  guess from damaged state.
#
# A missing catalog is not corrupt: it is the normal state before the first reconcile, and
# also what an interrupted recovery leaves behind (quarantined, not yet rewritten).

EXIT_OK = 0
EXIT_FAILED = 1           # query found nothing, or an operational failure (message on stderr)
EXIT_USAGE = 2            # bad arguments or an invalid input record
EXIT_CORRUPT_STATE = 74   # catalog.json is corrupt; run reconcile to quarantine and rebuild

EMPTY_CATALOG = {"version": 1, "last_reconciled": None, "patterns": {}}

_NUM = (int, float)
PATTERN_FIELD_TYPES = {
    "pattern_id": str, "code": str, "title": str, "category": str, "verdict": str,
    "signal": str, "counter": str, "first_seen": str, "last_seen": str,
    "elevated_at": str, "retired_at": str,
    "tags": list, "sessions_seen": list, "posterior_ci95": list,
    "observations": _NUM, "llr": _NUM, "weight": _NUM, "posterior_mean": _NUM,
    "days_since_last_seen": _NUM, "alpha": _NUM, "beta": _NUM,
}


class CorruptCatalog(RuntimeError):
    """catalog.json exists but cannot be used. Distinct from a missing catalog."""

    def __init__(self, reason: str, salvage: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.salvage = salvage  # parsed data whose well-formed entries can still be used


def pattern_problem(pid, pat) -> str | None:
    if not isinstance(pat, dict):
        return f"pattern {pid!r} is {type(pat).__name__}, not an object"
    for field, typ in PATTERN_FIELD_TYPES.items():
        if field in pat and not isinstance(pat[field], typ):
            return f"pattern {pid!r} field {field!r} has type {type(pat[field]).__name__}"
    if "tags" in pat and not all(isinstance(t, str) for t in pat["tags"]):
        return f"pattern {pid!r} has a non-string tag"
    return None


def load_catalog() -> dict:
    """Read and validate the derived catalog. Raises CorruptCatalog with the reason."""
    try:
        raw = CATALOG_PATH.read_bytes()
    except FileNotFoundError:
        return json.loads(json.dumps(EMPTY_CATALOG))
    except OSError as exc:
        raise CorruptCatalog(f"cannot be read ({type(exc).__name__}: {exc})") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise CorruptCatalog(f"is not valid UTF-8 (byte {exc.start})") from exc
    except (ValueError, RecursionError) as exc:
        raise CorruptCatalog(f"is not valid JSON ({type(exc).__name__}: {exc})") from exc
    if not isinstance(data, dict):
        raise CorruptCatalog(f"top level is {type(data).__name__}, not an object")
    patterns = data.get("patterns")
    if not isinstance(patterns, dict):
        raise CorruptCatalog("has no 'patterns' object")
    for pid, pat in patterns.items():
        problem = pattern_problem(pid, pat)
        if problem:
            raise CorruptCatalog(problem, salvage=data)
    return data


def quarantine_catalog() -> Path:
    """Move catalog.json aside, keeping its bytes for inspection. Returns the new path."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = CATALOG_PATH.with_name(f"{CATALOG_PATH.name}.corrupt-{stamp}")
    n = 1
    while dest.exists():
        dest = CATALOG_PATH.with_name(f"{CATALOG_PATH.name}.corrupt-{stamp}-{n}")
        n += 1
    os.replace(CATALOG_PATH, dest)
    return dest


def load_catalog_for_rebuild() -> tuple[dict, dict | None]:
    """reconcile's read: a corrupt catalog is quarantined instead of aborting the rebuild.

    Returns (prior_patterns, recovery) where recovery is None when the catalog was usable.
    """
    try:
        return load_catalog().get("patterns", {}), None
    except CorruptCatalog as exc:
        dest = quarantine_catalog()
        prior: dict = {}
        if exc.salvage is not None:
            for pid, pat in exc.salvage["patterns"].items():
                if pattern_problem(pid, pat) is None:
                    prior[pid] = pat
        recovery = {"at": iso_now(), "reason": exc.reason, "quarantined_as": dest.name,
                    "stamps_carried_from": len(prior)}
        sys.stderr.write(
            f"[inference-engine] catalog.json is corrupt ({exc.reason}); moved to {dest.name} "
            f"and rebuilding from the artifact log ({len(prior)} well-formed prior entries kept "
            "for their first-crossing stamps)\n")
        return prior, recovery


def load_catalog_or_exit() -> dict | int:
    """Read-only commands: a corrupt catalog is reported as exit 74, never guessed around."""
    try:
        return load_catalog()
    except CorruptCatalog as exc:
        sys.stderr.write(
            f"[inference-engine] {CATALOG_PATH} {exc.reason}. It is derived state: run "
            "`inference-engine.py reconcile` to quarantine it and rebuild from the artifact "
            "log.\n")
        return EXIT_CORRUPT_STATE


class LogScan:
    """Result of reading the artifact stream: unique events in stream order plus accounting."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.identities: set[str] = set()
        self.duplicates: list[dict] = []   # {file, line, identity}: a repeat of a counted event


def log_paths() -> list[Path]:
    # Master log (current convention)
    master = STATE_DIR / "artifacts.jsonl"
    paths = [master] if master.exists() else []
    # Legacy date-rotated files, if any linger from before the rotation was retired.
    paths.extend(sorted(STATE_DIR.glob("artifacts-*.jsonl")))
    return paths


def scan_log() -> LogScan:
    """Load every artifact from state/artifacts.jsonl plus any legacy artifacts-*.jsonl files.

    Each line is identified by event_identity() over the stored record; the n-th repeat of an
    identical line within one file gets ordinal n (see with_ordinal), exactly as backfill assigns
    it, so a legacy log keeps every line it always counted. A line whose identity was already
    read (a copy of the log dropped next to it, for example) is the same event and is counted
    once.
    """
    scan = LogScan()
    for p in log_paths():
        repeats: dict[str, int] = {}
        with p.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = canonical(rec)
                ordinal = repeats.get(key, 0)
                repeats[key] = ordinal + 1
                eid = event_identity(with_ordinal(rec, ordinal))
                if eid in scan.identities:
                    scan.duplicates.append({"file": p.name, "line": lineno, "identity": eid})
                    continue
                scan.identities.add(eid)
                scan.events.append(rec)
    return scan


def iter_artifacts() -> list[dict]:
    return scan_log().events


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None
    # Coerce to UTC-aware — date-only strings and some ISO forms land tz-naive.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Subcommand: emit ─────────────────────────────────────────────────────────


def cmd_emit(args: list[str]) -> int:
    if not env_enabled():
        sys.stderr.write("[inference-engine] WIXIE_INFERENCE_ENABLED!=1 — emit skipped\n")
        return 0

    if not args:
        sys.stderr.write("usage: inference-engine.py emit <record.json|->\n")
        return 2
    src = args[0]
    raw = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")
    try:
        record = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"[inference-engine] invalid JSON: {e}\n")
        return 2

    # WIX-RUN-002. emit records an event happening now. Each call is a new event unless the
    # caller supplies an event_id: the engine then mints one, so two genuine occurrences of the
    # same payload in one session stay two events. A caller that may retry (a hook re-run after
    # an ambiguous failure) supplies its own event_id; the retry then has the same identity and
    # is recorded once.
    stamp_session(record, use_env=True)
    record.setdefault("plugin", os.environ.get("ENCHANTED_ATTRIBUTION_PLUGIN", "unknown"))
    supplied_id = "event_id" in record
    if not supplied_id:
        record["event_id"] = uuid.uuid4().hex
    if "ts" not in record:
        record["ts"] = iso_now()
        record["_ts_clock"] = True
    eid = event_identity(record)
    record["_identity"] = eid

    if supplied_id and eid in scan_log().identities:
        print(f"duplicate {record.get('code', '?')} (event {eid[:12]}) already recorded; nothing added")
        return 0
    path = artifacts_path(parse_ts(record["ts"]) or datetime.now(timezone.utc))
    append_jsonl_locked(path, json.dumps(record, ensure_ascii=False))
    print(f"emitted {record.get('code', '?')} -> {path.name} (event {eid[:12]})")
    return 0


# ─── Subcommand: backfill ─────────────────────────────────────────────────────


def cmd_backfill(args: list[str]) -> int:
    if not args:
        sys.stderr.write("usage: inference-engine.py backfill <source.jsonl>\n")
        return 2
    src = Path(args[0])
    if not src.exists():
        sys.stderr.write(f"source not found: {src}\n")
        return 2
    # WIX-RUN-002. backfill re-imports events that already happened elsewhere, so every stamp
    # is a deterministic function of the source line (session from session_id/source_session,
    # ts from date, plugin from scope) and the identity carries the source's own coordinates.
    # Re-running the same import, finishing an interrupted one, or importing a copy of an
    # engine-written log adds only events not already recorded.
    seen = scan_log().identities
    repeats: dict[str, int] = {}
    count = skipped = 0
    for line in src.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        stamp_session(record, use_env=False)
        if "ts" not in record:
            if isinstance(record.get("date"), str) and record["date"].strip():
                record["ts"] = record["date"]
            else:
                record["ts"] = iso_now()
                record["_ts_clock"] = True
        record.setdefault("plugin", record.get("scope", "unknown"))
        key = canonical(record)
        ordinal = repeats.get(key, 0)
        repeats[key] = ordinal + 1
        record = with_ordinal(record, ordinal)
        eid = event_identity(record)
        if eid in seen:
            skipped += 1
            continue
        record["_identity"] = eid
        path = artifacts_path(parse_ts(record["ts"]) or datetime.now(timezone.utc))
        append_jsonl_locked(path, json.dumps(record, ensure_ascii=False))
        seen.add(eid)
        count += 1
    print(f"backfilled {count} new records from {src.name} ({skipped} already recorded)")
    return 0


# ─── Subcommand: reconcile ────────────────────────────────────────────────────


def recurrence_count(record: dict) -> int:
    """A single artifact may document multiple sub-session recurrences.

    Honest rule: one artifact = one observation, UNLESS evidence explicitly
    counts sub-session recurrences (iterations, user_rounds_of_pushback,
    occurrences). In that case, count each as an independent SPRT observation.
    """
    ev = record.get("evidence") or {}
    recurrences = 1
    for key in ("user_rounds_of_pushback", "iterations", "occurrences", "times_hit"):
        val = ev.get(key)
        if isinstance(val, int) and val > 1:
            recurrences = max(recurrences, val)
    return recurrences


def cmd_reconcile(args: list[str]) -> int:
    scan = scan_log()
    artifacts = scan.events
    if scan.duplicates:
        sys.stderr.write(
            f"[inference-engine] {len(scan.duplicates)} line(s) repeat an already-counted event "
            "and were counted once\n")
    if not artifacts:
        sys.stderr.write("[inference-engine] no artifacts to reconcile\n")
        return 0

    # Event-sourced rebuild: derive the whole pattern state from the artifact log
    # every reconcile. Preserve only the first-crossing timestamps from the
    # previous catalog so elevation/retirement history is durable.
    prior_patterns, recovery = load_catalog_for_rebuild()
    patterns: dict[str, dict] = {}
    rng = random.Random(42)  # deterministic reservoir selection across runs
    now = datetime.now(timezone.utc)

    for art in artifacts:
        pid = fingerprint(art)
        pat = patterns.get(pid)
        obs = recurrence_count(art)
        art_ts = parse_ts(art.get("ts")) or now

        if pat is None:
            pat = {
                "pattern_id": pid,
                "code": art.get("code", ""),
                "title": art.get("title", ""),
                "category": art.get("category", ""),
                "tags": art.get("tags") or [],
                "first_seen": art.get("ts") or iso_now(),
                "last_seen": art.get("ts") or iso_now(),
                "sessions_seen": [],
                "observations": 0,
                "llr": 0.0,
                "alpha": 1.0,
                "beta": 1.0,
                "reservoir": [],
                "signal": art.get("signal", ""),
                "counter": art.get("counter", ""),
            }
            patterns[pid] = pat

        sid = art.get("session_id", "unknown")
        if sid not in pat["sessions_seen"]:
            pat["sessions_seen"].append(sid)

        pat["observations"] += obs
        pat["llr"] = sprt_update(pat["llr"], obs)
        pat["alpha"], pat["beta"] = beta_update(pat["alpha"], pat["beta"], obs, 0)
        pat["last_seen"] = art.get("ts") or pat["last_seen"]
        if art.get("signal") and not pat["signal"]:
            pat["signal"] = art["signal"]
        if art.get("counter") and not pat["counter"]:
            pat["counter"] = art["counter"]

        reservoir_add(pat["reservoir"], {"ts": art.get("ts"), "session": sid, "title": art.get("title", "")}, 50, rng)

    # Compute verdict + EMA weight per pattern; restore first-crossing stamps
    for pid, pat in patterns.items():
        last = parse_ts(pat["last_seen"]) or now
        days = (now - last).total_seconds() / 86400.0
        pat["days_since_last_seen"] = round(days, 3)
        pat["weight"] = round(ema_weight(days), 4)
        pat["verdict"] = sprt_verdict(pat["llr"])
        pat["posterior_mean"] = round(beta_mean(pat["alpha"], pat["beta"]), 4)
        lo, hi = beta_ci(pat["alpha"], pat["beta"])
        pat["posterior_ci95"] = [round(lo, 4), round(hi, 4)]
        prior = prior_patterns.get(pid) or {}
        if pat["verdict"] == "elevated":
            pat["elevated_at"] = prior.get("elevated_at") or iso_now()
        if pat["verdict"] == "retired":
            pat["retired_at"] = prior.get("retired_at") or iso_now()

    new_catalog = {
        "version": 1,
        "last_reconciled": iso_now(),
        "total_artifacts": len(artifacts),
        "total_patterns": len(patterns),
        "elevated_count": sum(1 for p in patterns.values() if p["verdict"] == "elevated"),
        "retired_count": sum(1 for p in patterns.values() if p["verdict"] == "retired"),
        "patterns": patterns,
    }
    if recovery:
        new_catalog["last_recovery"] = recovery
    atomic_write_json(CATALOG_PATH, new_catalog)

    print(
        f"reconciled {len(artifacts)} artifacts -> "
        f"{new_catalog['total_patterns']} patterns "
        f"({new_catalog['elevated_count']} elevated, {new_catalog['retired_count']} retired)"
    )
    return 0


# ─── Subcommand: render-briefing ──────────────────────────────────────────────


def cmd_render_briefing(args: list[str]) -> int:
    if not args:
        sys.stderr.write("usage: inference-engine.py render-briefing <plugin>\n")
        return 2
    plugin = args[0]
    catalog = load_catalog_or_exit()
    if isinstance(catalog, int):
        return catalog
    patterns = catalog.get("patterns", {})

    # Filter: a pattern is relevant to a plugin briefing if ANY hold:
    #   1. plugin == "all"                                  — the unscoped ecosystem view
    #   2. plugin name appears in tags                      — the plugin-scoped view
    #   3. category in CROSS_CUTTING                        — meta / review patterns are
    #                                                         load-bearing for every plugin
    CROSS_CUTTING = {"meta", "review"}
    relevant = []
    for pat in patterns.values():
        if pat.get("verdict") != "elevated":
            continue
        tags = [t.lower() for t in pat.get("tags", [])]
        category = (pat.get("category") or "").lower()
        if (
            plugin.lower() == "all"
            or plugin.lower() in tags
            or category in CROSS_CUTTING
        ):
            relevant.append(pat)

    relevant.sort(key=lambda p: p.get("weight", 0), reverse=True)

    # Top-N cap for the ecosystem-wide briefing. Plugin-scoped briefings are
    # already filter-narrow, so no cap there. Full catalog always in catalog.json.
    BRIEFING_CAP = 10
    total_matching = len(relevant)
    truncated = plugin.lower() == "all" and total_matching > BRIEFING_CAP
    if truncated:
        relevant = relevant[:BRIEFING_CAP]

    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    out = BRIEFINGS_DIR / f"{plugin}.md"
    lines = [
        f"# {plugin.title()} Briefing — elevated patterns",
        "",
        f"Rendered: {iso_now()}   ·   Catalog reconciled: {catalog.get('last_reconciled', 'never')}",
        "",
        f"*This briefing is machine-generated by `wixie/shared/scripts/inference-engine.py`.*  ",
        f"*Source of truth is `wixie/plugins/inference-engine/state/catalog.json`.*",
        "",
        "---",
        "",
    ]

    if not relevant:
        lines.append(
            "_No elevated patterns yet. Run `/inference-reconcile` after at least one cross-session recurrence._"
        )
    else:
        header = f"## {len(relevant)} elevated pattern(s)"
        if truncated:
            header = f"## Top {len(relevant)} of {total_matching} elevated patterns (ranked by EMA-decayed weight)"
        lines.append(header)
        if truncated:
            lines.append("")
            lines.append(
                f"_Truncated to top {BRIEFING_CAP} by weight. Full catalog at `state/catalog.json`; "
                "use `/inference-query <code|tag|pattern_id>` to search the rest._"
            )
        lines.append("")
        for pat in relevant:
            lines += [
                f"### {pat.get('code', '?')} — {pat.get('title', 'untitled')}",
                "",
                f"- **Weight:** {pat.get('weight', 0):.3f}   "
                f"**Posterior:** {pat.get('posterior_mean', 0):.3f} (95% CI {pat.get('posterior_ci95', [0, 0])})   "
                f"**LLR:** {pat.get('llr', 0):.2f}",
                f"- **Observations:** {pat.get('observations', 0)} across {len(pat.get('sessions_seen', []))} session(s)   "
                f"**Last seen:** {pat.get('last_seen', '?')[:10]} ({pat.get('days_since_last_seen', 0):.0f}d ago)",
                f"- **Tags:** `{', '.join(pat.get('tags', []))}`",
                "",
                f"**Signal:** {pat.get('signal', '')}",
                "",
                f"**Counter:** {pat.get('counter', '')}",
                "",
                "---",
                "",
            ]

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"rendered {out}")
    return 0


# ─── Subcommand: query ────────────────────────────────────────────────────────


def cmd_query(args: list[str]) -> int:
    if not args:
        sys.stderr.write("usage: inference-engine.py query <code|tag|pattern_id>\n")
        return 2
    term = args[0].lower()
    catalog = load_catalog_or_exit()
    if isinstance(catalog, int):
        return catalog
    hits = []
    for pat in catalog.get("patterns", {}).values():
        if (
            term == pat.get("pattern_id", "").lower()
            or term == pat.get("code", "").lower()
            or term in [t.lower() for t in pat.get("tags", [])]
        ):
            hits.append(pat)
    print(json.dumps(hits, indent=2, ensure_ascii=False))
    return 0 if hits else 1


# ─── Subcommand: status ───────────────────────────────────────────────────────


def cmd_status(_args: list[str]) -> int:
    catalog = load_catalog_or_exit()
    if isinstance(catalog, int):
        return catalog
    patterns = catalog.get("patterns", {})
    verdicts = {"elevated": 0, "noise": 0, "retired": 0}
    for pat in patterns.values():
        verdicts[pat.get("verdict", "noise")] = verdicts.get(pat.get("verdict", "noise"), 0) + 1
    print(
        json.dumps(
            {
                "enabled": env_enabled(),
                "last_reconciled": catalog.get("last_reconciled"),
                "total_artifacts": catalog.get("total_artifacts", 0),
                "total_patterns": catalog.get("total_patterns", 0),
                "verdicts": verdicts,
                "state_dir": str(STATE_DIR),
            },
            indent=2,
        )
    )
    return 0


# ─── Dispatch ─────────────────────────────────────────────────────────────────


COMMANDS = {
    "emit": cmd_emit,
    "reconcile": cmd_reconcile,
    "render-briefing": cmd_render_briefing,
    "query": cmd_query,
    "backfill": cmd_backfill,
    "status": cmd_status,
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        sys.stderr.write(__doc__ or "")
        return 0 if len(argv) >= 2 else 2
    cmd = argv[1]
    if cmd not in COMMANDS:
        sys.stderr.write(f"unknown subcommand: {cmd}\n")
        sys.stderr.write(f"available: {', '.join(COMMANDS)}\n")
        return 2
    return COMMANDS[cmd](argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
