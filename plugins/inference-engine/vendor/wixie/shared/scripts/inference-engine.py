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

Global option (before the subcommand): --plugin-data <dir> carries the plugin data directory
that Claude Code substitutes for ${CLAUDE_PLUGIN_DATA} in skill/agent text.

State location (WIX-SEC-WS-001; one precedence, shared/scripts/plugin_state.py):
    1. WIXIE_INFERENCE_STATE            explicit override (tests, sandboxes); used as-is, never seeded
    2. CLAUDE_PLUGIN_DATA/state         installed plugin (env var from Claude Code, or --plugin-data)
    3. <checkout>/plugins/inference-engine/state   full-checkout development mode (unchanged)
    Otherwise every subcommand refuses with exit 2: the installed plugin tree is never written.
The shipped plugin state/ is a read-only seed. On the first write to an empty plugin-data state
dir (reconcile, render-briefing, backfill, or an enabled emit) it is copied there once and the
copy is logged; status/query read the seed in place until then. WIXIE_INFERENCE_SEED=0 starts
empty instead. A shipped state/ that holds anything besides the seed files (runtime residue a
pre-WIX-SEC-WS-001 version wrote into the install) is not copied and not touched: the data dir
starts empty and a one-line notice says so. The seed decision is recorded in <state>/.seed.json.

Exit codes (contract: shared/conduct/inference-substrate.md):
    0   success, incl. documented no-ops (gate-off emit, empty reconcile) and the emit outcomes
        "duplicate" and "queued"
    1   query found nothing, or an operational failure (one-line reason on stderr)
    2   usage error, refused input record, or refused render-briefing plugin name
    3   partial: reconcile/backfill completed but rejected some input lines (listed on stderr)
    74  status/query/render-briefing: catalog.json is corrupt; run reconcile to rebuild it
    75  reconcile/backfill: state/.lock busy past WIXIE_INFERENCE_LOCK_TIMEOUT; nothing changed

Algorithms (all stdlib):
    U1 Pattern fingerprint          SHA-1 of (code, sorted(tags)) — deterministic id per semantic pattern
    U2 Wald SPRT                    log-likelihood ratio over recurrences; elevate at +2.89, retire at -2.25
    U3 Beta-Binomial posterior      alpha/beta per pattern; mean + 95% CI via beta quantile
    U5 EMA decay                    weight *= exp(-lambda * days_since_last_seen); lambda = ln(2)/30
    U6 Reservoir sampling           bounded retention of raw artifacts per pattern (K=50 Vitter)
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import math
import os
import random
import re
import shutil
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
# WIX-SEC-WS-001: never write bytecode caches next to a vendored copy in an installed plugin.
sys.dont_write_bytecode = True


def _load_plugin_state():
    import importlib.util
    spec = importlib.util.spec_from_file_location("wixie_plugin_state", SCRIPT_DIR / "plugin_state.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


plugin_state = _load_plugin_state()

# The plugin that ships this script, whose state/ is the read-only seed: the repository's
# plugins/inference-engine/ for the canonical copy, or <plugin>/ for the copy vendored at
# <plugin>/vendor/wixie/shared/scripts/ (WIX-DIST-002).
PLUGIN_DIR = SCRIPT_DIR.parent.parent / "plugins" / "inference-engine"
_INSTALLED_ROOT = SCRIPT_DIR.parents[3] if len(SCRIPT_DIR.parents) > 3 else None
if _INSTALLED_ROOT and SCRIPT_DIR.parents[2].name == "vendor" and (_INSTALLED_ROOT / ".claude-plugin" / "plugin.json").is_file():
    PLUGIN_DIR = _INSTALLED_ROOT
SEED_DIR = PLUGIN_DIR / "state"
# The files a shipped seed consists of; anything else in the shipped state/ is runtime residue.
SEED_TOP_FILES = ("artifacts.jsonl", "catalog.json")
SEED_SUBDIR_GLOBS = (("briefings", "*.md"),)
SEED_MARKER = ".seed.json"


def resolve_state(plugin_data: str | None = None) -> tuple[Path | None, str]:
    """WIXIE_INFERENCE_STATE > CLAUDE_PLUGIN_DATA/state > checkout plugins/inference-engine/state."""
    return plugin_state.resolve(
        __file__, explicit=os.environ.get("WIXIE_INFERENCE_STATE"), data_sub="state",
        checkout_rel="plugins/inference-engine/state", plugin_data=plugin_data)


def _bind_state(state_dir: Path) -> None:
    """Point every state path at `state_dir` (module globals read at call time)."""
    global STATE_DIR, BRIEFINGS_DIR, CATALOG_PATH, LOCK_PATH, PENDING_DIR
    STATE_DIR = state_dir
    BRIEFINGS_DIR = state_dir / "briefings"
    CATALOG_PATH = state_dir / "catalog.json"
    LOCK_PATH = state_dir / ".lock"
    PENDING_DIR = state_dir / "pending"


STATE_DIR, STATE_SOURCE = resolve_state()
# Unresolved (an installed copy without CLAUDE_PLUGIN_DATA): main() refuses before any use.
_bind_state(STATE_DIR if STATE_DIR is not None else Path("<unresolved-inference-state>"))


def env_enabled() -> bool:
    """Opt-in gate — default off during rollout per ship_scope."""
    return os.environ.get("WIXIE_INFERENCE_ENABLED", "0") == "1"


def artifacts_path(ts: datetime | None = None) -> Path:
    # One master append-only log. Rotation deferred until volume warrants it
    # (see discipline.md — three similar lines beats a premature abstraction).
    return STATE_DIR / "artifacts.jsonl"


class LogAppender:
    """Append JSON lines to the log, each one locked, flushed and fsynced. Cross-platform.

    Closes F-015: parallel races and partial-line writes on artifacts.jsonl
    that biased the SPRT walk. Per spec section G.

    The file is opened once per command, not once per line: on Windows every open with read
    access is scanned, which made a large backfill spend most of its time in open().
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = path.open("a+b")
        self.guard = _newline_guard(self.f)

    def append(self, line: str) -> None:
        if not line.endswith("\n"):
            line += "\n"
        data = self.guard + line.encode("utf-8")
        f = self.f
        if sys.platform == "win32":
            import msvcrt
            pos = f.seek(0, os.SEEK_END)
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            finally:
                try:
                    f.seek(pos)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        else:
            import fcntl
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        self.guard = b""

    def close(self) -> None:
        self.f.close()

    def __enter__(self) -> "LogAppender":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def append_jsonl_locked(path: Path, line: str) -> None:
    """Append one JSON line (see LogAppender)."""
    with LogAppender(path) as log:
        log.append(line)


def _newline_guard(f) -> bytes:
    """b"\n" if the file is non-empty and does not end in a newline, else b"".

    WIX-RUN-003: a torn final line (an append interrupted mid-write) must stay its own rejected
    line instead of swallowing the next record appended after it.
    """
    end = f.seek(0, os.SEEK_END)
    if end == 0:
        return b""
    f.seek(end - 1)
    last = f.read(1)
    f.seek(0, os.SEEK_END)
    return b"" if last == b"\n" else b"\n"


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


def verified_identity(record: dict) -> str | None:
    """The record's stored _identity if it recomputes exactly from the record, else None.

    A line the engine wrote carries its identity. When that identity verifies, it IS the
    event, with no per-file repeat counter: any copy, concatenation or in-place duplication of
    an engine-written log therefore adds nothing. A missing, edited or forged _identity does not
    verify and the line is identified from its content (plus repeat counter) instead.
    """
    stored = record.get("_identity")
    if isinstance(stored, str) and stored == event_identity(record):
        return stored
    return None


def line_identity(record: dict, repeats: dict[str, int]) -> str:
    """Identity of one line read from a file, updating that file's repeat counter."""
    eid = verified_identity(record)
    if eid is not None:
        return eid
    key = canonical(record)
    ordinal = repeats.get(key, 0)
    repeats[key] = ordinal + 1
    return event_identity(with_ordinal(record, ordinal))


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


@functools.lru_cache(maxsize=None)
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
        _replace_with_retry(tmp, path)
        tmp = None
        _fsync_dir(path.parent)
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass


def _fsync_dir(directory: Path) -> None:
    """Make a rename in `directory` durable. POSIX only: on Windows (NTFS) the rename is
    journaled and a directory cannot be opened for fsync. A filesystem that refuses directory
    fsync is tolerated; the data file itself was already fsynced."""
    if sys.platform == "win32":
        return
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _replace_with_retry(src: Path, dst: Path) -> None:
    """os.replace, retried briefly on Windows, where a reader holding dst open makes the
    rename fail with a sharing violation (PermissionError) for the duration of the read."""
    delay = 0.01
    deadline = time.monotonic() + 5.0
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if sys.platform != "win32" or time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.2)


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
    problem = top_level_problem(data)
    if problem:
        raise CorruptCatalog(problem, salvage=data)
    return data


# Top-level catalog fields other than "patterns": readers (status, the next reconcile) use them,
# so a wrong type is corruption, not something to crash on.
TOP_LEVEL_TYPES = {
    "version": int, "last_reconciled": (str, type(None)), "total_artifacts": int,
    "total_patterns": int, "elevated_count": int, "retired_count": int, "outcome": str,
    "accounting": dict, "rejected": list, "last_recovery": dict,
}


def top_level_problem(data: dict) -> str | None:
    for field, typ in TOP_LEVEL_TYPES.items():
        if field in data and not isinstance(data[field], typ):
            return f"top-level field {field!r} has type {type(data[field]).__name__}"
    if not all(isinstance(v, int) for v in data.get("accounting", {}).values()):
        return "top-level field 'accounting' has a non-integer value"
    if not all(isinstance(r, dict) for r in data.get("rejected", [])):
        return "top-level field 'rejected' has a non-object entry"
    return None


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


def load_catalog_for_rebuild() -> tuple[dict, dict | None, list]:
    """reconcile's read: a corrupt catalog is quarantined instead of aborting the rebuild.

    Returns (prior_patterns, recovery, prior_rejected); recovery is None when the catalog was
    usable. After a recovery prior_rejected is empty, so every rejected line reports as new.
    """
    try:
        prior = load_catalog()
        return prior.get("patterns", {}), None, prior.get("rejected", [])
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
        return prior, recovery, []


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


# ─── Record validation and rejection accounting (WIX-RUN-003) ─────────────────
#
# Every non-empty line of the artifact stream ends up in exactly one bucket: a counted event, a
# duplicate of a counted event (same identity), or a REJECTED record reported with file:line and
# a reason. Lines are split and decoded one at a time from bytes, so one undecodable or torn
# line cannot hide the lines around it.

EXIT_PARTIAL = 3          # completed, but some input records were rejected (listed on stderr)

EVIDENCE_COUNT_KEYS = ("user_rounds_of_pushback", "iterations", "occurrences", "times_hit")
MAX_RECURRENCES = 1000
# Fields reconcile copies into catalog.json: they must be strings when present.
RECORD_STR_FIELDS = ("code", "title", "category", "signal", "counter", "session_id")


def record_problem(rec) -> str | None:
    """Why this parsed record cannot be counted, or None if it can."""
    if not isinstance(rec, dict):
        return f"expected a JSON object, got {type(rec).__name__}"
    for field in RECORD_STR_FIELDS:
        if field in rec and not isinstance(rec[field], str):
            return f"field {field!r} must be a string, got {type(rec[field]).__name__}"
    for field in ("ts", "date"):
        if rec.get(field) is not None and not isinstance(rec[field], str):
            return f"field {field!r} must be a string, got {type(rec[field]).__name__}"
    tags = rec.get("tags")
    if tags is not None and not (isinstance(tags, list) and all(isinstance(t, str) for t in tags)):
        return "field 'tags' must be a list of strings"
    ev = rec.get("evidence")
    if ev is not None:
        if not isinstance(ev, dict):
            return f"field 'evidence' must be an object, got {type(ev).__name__}"
        for key in EVIDENCE_COUNT_KEYS:
            val = ev.get(key)
            if isinstance(val, int) and not isinstance(val, bool) and val > MAX_RECURRENCES:
                return f"evidence.{key}={val} exceeds {MAX_RECURRENCES}"
    if "event_id" in rec and not (isinstance(rec["event_id"], str) and rec["event_id"].strip()):
        return "field 'event_id' must be a non-empty string"
    if "_ts_clock" in rec and not isinstance(rec["_ts_clock"], bool):
        return "field '_ts_clock' must be a boolean"
    return None


def decode_record(raw: bytes) -> tuple[dict | None, str | None]:
    """bytes of one line -> (record, None) or (None, reason)."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, f"invalid UTF-8 at byte {exc.start}"
    try:
        rec = json.loads(text)
    except (ValueError, RecursionError) as exc:
        return None, f"invalid JSON ({type(exc).__name__}: {exc})"[:200]
    problem = record_problem(rec)
    return (None, problem) if problem else (rec, None)


def excerpt(raw: bytes) -> str:
    return raw[:120].decode("utf-8", "replace")


def read_jsonl(path: Path):
    """Yield (lineno, record, reason, excerpt) for every non-empty line; reason is None for a
    usable record. A final line with no trailing newline that does not parse is reported as a
    torn write."""
    segments = path.read_bytes().split(b"\n")
    last = len(segments) - 1
    for idx, raw in enumerate(segments):
        if idx == 0 and raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        raw = raw.strip()
        if not raw:
            continue
        rec, reason = decode_record(raw)
        if reason and idx == last:
            reason = f"incomplete final line (no trailing newline): {reason}"
        yield idx + 1, rec, reason, excerpt(raw)


def report_rejected(rejected: list[dict], what: str, limit: int = 20) -> None:
    if not rejected:
        return
    sys.stderr.write(f"[inference-engine] {len(rejected)} {what} rejected and NOT counted:\n")
    for r in rejected[:limit]:
        sys.stderr.write(f"  {r['file']}:{r['line']}: {r['reason']} | {r['excerpt']}\n")
    if len(rejected) > limit:
        sys.stderr.write(f"  ... and {len(rejected) - limit} more\n")


def rejection_key(r: dict) -> tuple:
    return (r.get("file"), r.get("line"), r.get("reason"), r.get("excerpt"))


def split_new_rejections(rejected: list[dict], prior: list) -> list[dict]:
    """Mark each rejected line new=True unless the previous catalog already listed it (same
    file, line, reason and excerpt: the log is append-only, so an old rejection keeps its
    place). Returns the new ones, in log order."""
    seen = {rejection_key(r) for r in prior if isinstance(r, dict)}
    for r in rejected:
        r["new"] = rejection_key(r) not in seen
    return [r for r in rejected if r["new"]]


class LogScan:
    """Result of reading the artifact stream: unique events in stream order plus accounting."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.identities: set[str] = set()
        self.duplicates: list[dict] = []   # {file, line, identity}: a repeat of a counted event
        self.rejected: list[dict] = []     # {file, line, reason, excerpt}
        self.nonempty_lines = 0


def log_paths() -> list[Path]:
    # Master log (current convention)
    master = STATE_DIR / "artifacts.jsonl"
    paths = [master] if master.exists() else []
    # Legacy date-rotated files, if any linger from before the rotation was retired.
    paths.extend(sorted(STATE_DIR.glob("artifacts-*.jsonl")))
    return paths


def scan_log() -> LogScan:
    """Load every artifact from state/artifacts.jsonl plus any legacy artifacts-*.jsonl files.

    A line carrying a verified _identity is that event (see verified_identity). Any other line
    is identified by event_identity() over the stored record; the n-th repeat of an identical
    such line within one file gets ordinal n (see with_ordinal), exactly as backfill assigns
    it, so a legacy log keeps every line it always counted. A line whose identity was already
    read (a copy of the log dropped next to it, for example) is the same event and is counted
    once. A line that cannot be counted is rejected with its location (WIX-RUN-003).
    """
    scan = LogScan()
    for p in log_paths():
        repeats: dict[str, int] = {}
        for lineno, rec, reason, text in read_jsonl(p):
            scan.nonempty_lines += 1
            if reason:
                scan.rejected.append({"file": p.name, "line": lineno, "reason": reason,
                                      "excerpt": text})
                continue
            eid = line_identity(rec, repeats)
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


# ─── State lock and pending queue (WIX-RUN-001) ───────────────────────────────
#
# Every mutation of the state directory (emit's append, backfill, reconcile's read-compute-write)
# runs under one exclusive lock on state/.lock. Acquisition is a bounded non-blocking poll:
#
#   reconcile, backfill   wait up to WIXIE_INFERENCE_LOCK_TIMEOUT seconds (default 30), then exit
#                         75 (EXIT_LOCK_BUSY) having changed nothing. Retry later.
#   emit                  waits up to WIXIE_INFERENCE_EMIT_WAIT seconds (default 1). If the lock is
#                         still busy the event is written, identity and all, to
#                         state/pending/<identity>.json (atomic rename) and emit exits 0 with the
#                         outcome token "queued". An event is never dropped.
#
# The next lock holder (emit, backfill or reconcile) folds every pending file into the log:
# append unless its identity is already recorded, fsync, then delete the file. A crash between
# the append and the delete leaves a file whose identity is already in the log, so the next
# fold only deletes it: each queued event is recorded exactly once.

EXIT_LOCK_BUSY = 75       # the state lock was not acquired within the bound; nothing changed

# LOCK_PATH (<state>/.lock) and PENDING_DIR (<state>/pending) are bound by _bind_state().


class LockBusy(RuntimeError):
    """The state lock could not be acquired. A distinct outcome, never a silent success."""


def env_seconds(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        val = float(raw)
        if val >= 0 and math.isfinite(val):
            return val
    except ValueError:
        pass
    sys.stderr.write(f"[inference-engine] ignoring {name}={raw!r}; using {default:g}s\n")
    return default


@contextlib.contextmanager
def state_lock(timeout: float, purpose: str):
    """Exclusive, bounded, cross-platform lock over the state directory (state/.lock)."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    # A symlinked or non-file .lock is refused rather than followed or truncated.
    if LOCK_PATH.is_symlink():
        raise LockBusy(f"{LOCK_PATH} is a symlink; refusing to use it")
    if LOCK_PATH.exists() and not LOCK_PATH.is_file():
        raise LockBusy(f"{LOCK_PATH} exists and is not a regular file; refusing to use it")
    try:
        f = LOCK_PATH.open("a+", encoding="utf-8")
    except OSError as exc:
        raise LockBusy(f"cannot open {LOCK_PATH} for {purpose}: {exc}") from exc
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockBusy(
                        f"could not acquire {LOCK_PATH} for {purpose} within {timeout:g}s; "
                        "another inference-engine process holds it") from None
                time.sleep(random.uniform(0.005, 0.03))
        try:
            f.seek(0)
            f.truncate()
            f.write(f"{os.getpid()} {purpose}\n")
            f.flush()
        except OSError:
            pass  # the holder note is diagnostic only
        yield
    finally:
        try:
            if sys.platform == "win32":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        f.close()


def queue_pending(record: dict) -> Path:
    """Durably record an event that could not be appended because the lock was busy."""
    dest = PENDING_DIR / f"{record['_identity']}.json"
    atomic_write_text(dest, json.dumps(record, ensure_ascii=False) + "\n")
    return dest


DEFAULT_EMIT_WAIT = 1.0
# A queue write lasts milliseconds; a pending temp file older than this was left by a killed
# writer. Completed events are *.json and are never removed except by folding them in.
STALE_PENDING_TMP_SECONDS = 600


def clean_stale_pending_tmp() -> None:
    """Remove pending/*.tmp left by a queue write that was killed before its rename. Caller
    holds the state lock, but queue writers do not take it, so only old temp files go."""
    if not PENDING_DIR.is_dir():
        return
    cutoff = time.time() - STALE_PENDING_TMP_SECONDS
    for tmp in PENDING_DIR.glob("*.tmp"):
        try:
            if tmp.stat().st_mtime < cutoff:
                tmp.unlink()
        except OSError:
            pass


def pending_files() -> list[Path]:
    if not PENDING_DIR.is_dir():
        return []
    return sorted(PENDING_DIR.glob("*.json"))


def fold_pending(log: "LogAppender", identities: set[str]) -> tuple[int, int]:
    """Fold queued events into the log. Caller holds the state lock. Returns (added, already)."""
    items = []
    for path in pending_files():
        rec, reason = decode_record(path.read_bytes().strip())
        if reason:
            bad = path.with_name(path.name + ".rejected")
            os.replace(path, bad)
            sys.stderr.write(f"[inference-engine] pending event {path.name} rejected ({reason}); "
                             f"kept as pending/{bad.name}\n")
            continue
        items.append((str(rec.get("ts") or ""), path.name, path, rec))
    added = already = 0
    for _ts, _name, path, rec in sorted(items, key=lambda t: (t[0], t[1])):
        eid = event_identity(rec)
        if eid in identities:
            already += 1
        else:
            rec["_identity"] = eid
            log.append(json.dumps(rec, ensure_ascii=False))
            identities.add(eid)
            added += 1
        path.unlink()
    clean_stale_pending_tmp()
    if added or already:
        sys.stderr.write(f"[inference-engine] folded {added} pending event(s) into the log"
                         + (f" ({already} already recorded)" if already else "") + "\n")
    return added, already


def clean_stale_temp_files() -> None:
    """Remove catalog temp files left by an interrupted write. Caller holds the state lock, and
    only lock holders write the catalog, so none of these can be in flight."""
    for tmp in STATE_DIR.glob(f"{CATALOG_PATH.name}*.tmp"):
        try:
            tmp.unlink()
        except OSError:
            pass


# ─── Subcommand: emit ─────────────────────────────────────────────────────────


def cmd_emit(args: list[str]) -> int:
    if not env_enabled():
        sys.stderr.write("[inference-engine] WIXIE_INFERENCE_ENABLED!=1 — emit skipped\n")
        return 0

    if not args:
        sys.stderr.write("usage: inference-engine.py emit <record.json|->\n")
        return 2
    src = args[0]
    # WIX-RUN-003: read bytes and decode UTF-8 explicitly (the host default may be cp1252), and
    # reject an unusable record with its source and reason instead of raising.
    try:
        raw = sys.stdin.buffer.read() if src == "-" else Path(src).read_bytes()
    except OSError as exc:
        sys.stderr.write(f"[inference-engine] cannot read {src}: {exc}\n")
        return EXIT_USAGE
    record, reason = decode_record(raw.strip().lstrip(b"\xef\xbb\xbf"))
    if reason:
        where = "stdin" if src == "-" else src
        sys.stderr.write(f"[inference-engine] rejected {where}: {reason}; nothing recorded\n")
        return EXIT_USAGE

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

    # WIX-RUN-001 emit-lock policy: bounded wait, then a durable pending record. The outcome
    # token (first word on stdout) is one of: emitted, duplicate, queued.
    code = record.get("code", "?")
    # The default is short because emit runs inside hooks, and Claude Code discards a hook that
    # outlives its timeout: this plugin's own hooks use 3-5 s. Requirement (documented): the
    # timeout of any hook that emits must exceed WIXIE_INFERENCE_EMIT_WAIT + 2 s (interpreter
    # start-up and the queue write).
    wait = env_seconds("WIXIE_INFERENCE_EMIT_WAIT", DEFAULT_EMIT_WAIT)
    try:
        with state_lock(wait, "emit"):
            path = artifacts_path()
            with LogAppender(path) as log:
                pending = pending_files()
                identities = scan_log().identities if (supplied_id or pending) else set()
                if pending:
                    fold_pending(log, identities)
                if eid in identities:
                    print(f"duplicate {code} (event {eid[:12]}) already recorded; nothing added")
                    return EXIT_OK
                log.append(json.dumps(record, ensure_ascii=False))
    except LockBusy as exc:
        try:
            dest = queue_pending(record)
        except OSError as qexc:
            sys.stderr.write(f"[inference-engine] {exc}; queueing also failed ({qexc}). "
                             "Event NOT recorded.\n")
            return EXIT_FAILED
        print(f"queued {code} -> pending/{dest.name} (event {eid[:12]}); state lock busy, "
              "folded into the log by the next emit, backfill or reconcile")
        return EXIT_OK
    print(f"emitted {code} -> {path.name} (event {eid[:12]})")
    return EXIT_OK


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
    try:
        lines = list(read_jsonl(src))
    except OSError as exc:
        sys.stderr.write(f"[inference-engine] cannot read {src}: {exc}\n")
        return EXIT_USAGE
    # WIX-RUN-001: the whole import runs under the state lock, so a concurrent import or emit
    # cannot interleave between the identity read and the appends.
    with state_lock(env_seconds("WIXIE_INFERENCE_LOCK_TIMEOUT", 30.0), f"backfill {src.name}"):
        with LogAppender(artifacts_path()) as log:
            return _backfill_locked(src, lines, log)


def _backfill_locked(src: Path, lines: list, log: "LogAppender") -> int:
    seen = scan_log().identities
    fold_pending(log, seen)
    repeats: dict[str, int] = {}
    count = skipped = 0
    rejected: list[dict] = []
    for lineno, record, reason, text in lines:
        if reason:
            rejected.append({"file": src.name, "line": lineno, "reason": reason, "excerpt": text})
            continue
        eid = verified_identity(record)
        if eid is not None:
            # A line an engine already wrote (a copy of a log): it is that event, unchanged.
            if eid in seen:
                skipped += 1
                continue
            log.append(json.dumps(record, ensure_ascii=False))
            seen.add(eid)
            count += 1
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
        log.append(json.dumps(record, ensure_ascii=False))
        seen.add(eid)
        count += 1
    print(f"backfilled {count} new records from {src.name} ({skipped} already recorded, "
          f"{len(rejected)} rejected)")
    report_rejected(rejected, f"line(s) of {src.name}")
    return EXIT_PARTIAL if rejected else EXIT_OK


# ─── Subcommand: reconcile ────────────────────────────────────────────────────


def recurrence_count(record: dict) -> int:
    """A single artifact may document multiple sub-session recurrences.

    Honest rule: one artifact = one observation, UNLESS evidence explicitly
    counts sub-session recurrences (iterations, user_rounds_of_pushback,
    occurrences). In that case, count each as an independent SPRT observation.
    """
    ev = record.get("evidence") or {}
    recurrences = 1
    for key in EVIDENCE_COUNT_KEYS:
        val = ev.get(key)
        if isinstance(val, int) and val > 1:
            recurrences = max(recurrences, val)
    return recurrences


def cmd_reconcile(args: list[str]) -> int:
    # WIX-RUN-001: read-compute-write runs under the state lock, so concurrent reconciles
    # serialize (or return 75 after the bound) instead of racing on the catalog.
    with state_lock(env_seconds("WIXIE_INFERENCE_LOCK_TIMEOUT", 30.0), "reconcile"):
        if pending_files():
            with LogAppender(artifacts_path()) as log:
                fold_pending(log, scan_log().identities)
        clean_stale_temp_files()
        clean_stale_pending_tmp()
        return _reconcile_locked()


def _reconcile_locked() -> int:
    scan = scan_log()
    artifacts = scan.events
    # Event-sourced rebuild: derive the whole pattern state from the artifact log
    # every reconcile. Preserve only the first-crossing timestamps from the
    # previous catalog so elevation/retirement history is durable.
    # Read (and if corrupt, quarantine) the prior catalog first, even when there is nothing to
    # rebuild: otherwise read-only commands would keep sending the caller here while the no-op
    # below left the damage in place (WIX-RUN-004).
    prior_patterns, recovery, prior_rejected = load_catalog_for_rebuild()
    if scan.duplicates:
        sys.stderr.write(
            f"[inference-engine] {len(scan.duplicates)} line(s) repeat an already-counted event "
            "and were counted once\n")
    # WIX-RUN-003: rejections NEW since the previous reconcile are listed first and in full (up
    # to 200), so a fresh one is never hidden behind older, already-reported ones.
    new_rejected = split_new_rejections(scan.rejected, prior_rejected)
    report_rejected(new_rejected, "NEW artifact line(s) since the last reconcile", limit=200)
    old_count = len(scan.rejected) - len(new_rejected)
    if old_count:
        sys.stderr.write(
            f"[inference-engine] {old_count} previously reported rejected line(s) are still in "
            "the log and NOT counted (listed in catalog.json 'rejected')\n")
    if not artifacts and not scan.rejected:
        # With no events the quarantine above is the whole repair; a missing catalog is the
        # normal empty state.
        sys.stderr.write("[inference-engine] no artifacts to reconcile\n")
        return 0

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
        # WIX-RUN-003: complete accounting of the stream. nonempty_lines == events +
        # duplicate_lines + rejected_lines always holds; outcome is "partial" when any line
        # was rejected (reconcile then exits 3).
        "outcome": "partial" if scan.rejected else "clean",
        "accounting": {
            "nonempty_lines": scan.nonempty_lines,
            "events": len(artifacts),
            "duplicate_lines": len(scan.duplicates),
            "rejected_lines": len(scan.rejected),
            "new_rejected_lines": len(new_rejected),
        },
        "rejected": [{k: r[k] for k in ("file", "line", "reason", "excerpt", "new")}
                     for r in scan.rejected],
    }
    if recovery:
        new_catalog["last_recovery"] = recovery
    atomic_write_json(CATALOG_PATH, new_catalog)

    print(
        f"reconciled {len(artifacts)} artifacts -> "
        f"{new_catalog['total_patterns']} patterns "
        f"({new_catalog['elevated_count']} elevated, {new_catalog['retired_count']} retired)"
        + (f" [partial: {len(scan.rejected)} rejected line(s), {len(new_rejected)} new]"
           if scan.rejected else "")
    )
    return EXIT_PARTIAL if scan.rejected else EXIT_OK


# ─── Subcommand: render-briefing ──────────────────────────────────────────────

# WIX-SEC-BRIEF-001. <plugin> becomes a filename, so it must be a plugin slug: 1-64 characters
# from [A-Za-z0-9._-], starting with a letter or digit, and not a Windows device name (CON, NUL,
# COM1, ... with or without an extension). Anything else is refused with exit 2, never rewritten
# into a different name. After resolution the target must sit directly in the resolved
# briefings directory; the file is written by atomic rename, which replaces rather than
# follows anything already at that path.
PLUGIN_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
WIN_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)


def briefing_target(plugin: str) -> Path | None:
    """The briefing path for a plugin slug, or None (with the reason on stderr) if refused."""
    if not PLUGIN_SLUG_RE.fullmatch(plugin):
        sys.stderr.write(f"[inference-engine] refusing plugin name {plugin!r}: expected a slug "
                         "matching [A-Za-z0-9][A-Za-z0-9._-]{0,63}\n")
        return None
    if plugin.split(".")[0].upper() in WIN_RESERVED_NAMES:
        sys.stderr.write(f"[inference-engine] refusing plugin name {plugin!r}: reserved device "
                         "name\n")
        return None
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    base = BRIEFINGS_DIR.resolve()
    out = base / f"{plugin}.md"
    if out.resolve().parent != base:
        sys.stderr.write(f"[inference-engine] refusing to write {out}: it resolves outside "
                         f"{base}\n")
        return None
    return out


def cmd_render_briefing(args: list[str]) -> int:
    if not args:
        sys.stderr.write("usage: inference-engine.py render-briefing <plugin>\n")
        return 2
    plugin = args[0]
    out = briefing_target(plugin)
    if out is None:
        return EXIT_USAGE
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

    atomic_write_text(out, "\n".join(lines))
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
                "last_outcome": catalog.get("outcome"),
                "rejected_lines": (catalog.get("accounting") or {}).get("rejected_lines"),
                "new_rejected_lines": (catalog.get("accounting") or {}).get("new_rejected_lines"),
                "verdicts": verdicts,
                "state_dir": str(STATE_DIR),
                "state_source": STATE_SOURCE,
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


# ─── State location + read-only seed (WIX-SEC-WS-001) ─────────────────────────


def _note(msg: str) -> None:
    sys.stderr.write(f"[inference-engine] {msg}\n")


def seed_files(seed_dir: Path) -> tuple[list[str], list[str]]:
    """(seed files, residue) under the shipped state/: residue is anything that is not a seed file."""
    wanted = set(SEED_TOP_FILES)
    seed_dirs = {d for d, _ in SEED_SUBDIR_GLOBS}
    files, residue = [], []
    for p in sorted(seed_dir.rglob("*")):
        rel = p.relative_to(seed_dir).as_posix()
        if p.is_dir():
            if rel not in seed_dirs:
                residue.append(rel + "/")
            continue
        parent = rel.rpartition("/")[0]
        if rel in wanted or any(parent == d and p.match(g) for d, g in SEED_SUBDIR_GLOBS):
            files.append(rel)
        else:
            residue.append(rel)
    return files, residue


def _is_empty_dir(d: Path) -> bool:
    return d.is_dir() and not any(d.iterdir())


def ensure_seeded(state_dir: Path, seed_dir: Path) -> None:
    """Copy the shipped read-only seed into an empty plugin-data state dir, once.

    Never writes to `seed_dir`. The decision (copied, or why not) is recorded in
    <state_dir>/.seed.json, so it is taken once per data dir; deleting the data dir re-runs it."""
    if state_dir.exists() and not _is_empty_dir(state_dir):
        return
    decision: dict = {"schema": "wixie/inference-seed/v1", "decided_at": iso_now(), "seed": str(seed_dir)}
    files: list[str] = []
    if os.environ.get("WIXIE_INFERENCE_SEED", "1").strip() == "0":
        decision.update(copied=False, reason="WIXIE_INFERENCE_SEED=0 (owner override: start empty)")
    elif not seed_dir.is_dir():
        decision.update(copied=False, reason="no shipped seed")
    else:
        files, residue = seed_files(seed_dir)
        if residue:
            decision.update(copied=False, residue=residue, reason=(
                "the shipped state/ holds runtime residue written by an earlier version into the "
                "installed plugin, so it is not a pristine seed"))
            files = []
        else:
            decision.update(copied=True, files={
                rel: hashlib.sha256((seed_dir / rel).read_bytes()).hexdigest() for rel in files})
    tmp = state_dir.parent / f".{state_dir.name}.seeding-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        tmp.mkdir(parents=True)
        for rel in files:
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes((seed_dir / rel).read_bytes())
        (tmp / SEED_MARKER).write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
        if _is_empty_dir(state_dir):
            state_dir.rmdir()
        try:
            os.rename(tmp, state_dir)
        except OSError:
            if state_dir.is_dir() and not _is_empty_dir(state_dir):
                return  # a concurrent process seeded it first
            raise
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    if decision.get("copied"):
        _note(f"seeded {state_dir} from the shipped read-only seed {seed_dir} ({len(files)} files); "
              "the seed itself is never written")
    elif decision.get("residue"):
        _note(f"NOT seeding {state_dir}: {seed_dir} contains runtime residue from an earlier version "
              f"({', '.join(decision['residue'][:5])}); it was left as-is and not migrated. The data dir "
              "starts empty; reinstall the plugin to get a pristine seed.")
    else:
        _note(f"{state_dir} starts empty: {decision['reason']}")


# Subcommands that write state. emit writes only when the gate is on (gate-off emit is a no-op).
_WRITERS = {"reconcile", "render-briefing", "backfill"}


def _configure_state(cmd: str, plugin_data: str | None) -> int | None:
    """Resolve + bind the state dir for this command. Returns an exit code to stop with, or None."""
    global STATE_SOURCE
    state_dir, source = resolve_state(plugin_data)
    STATE_SOURCE = source
    if state_dir is None:
        _note(f"{cmd}: refused: {plugin_state.UNRESOLVED_HINT}. Nothing was changed.")
        return EXIT_USAGE
    _bind_state(state_dir)
    if source != "plugin-data":
        return None
    writes = cmd in _WRITERS or (cmd == "emit" and env_enabled())
    if writes:
        ensure_seeded(state_dir, SEED_DIR)
    elif (not state_dir.exists() or _is_empty_dir(state_dir)) and SEED_DIR.is_dir():
        # Read-only use before the first write: read the shipped seed in place; persist nothing.
        _bind_state(SEED_DIR)
        STATE_SOURCE = "plugin-data (unseeded: reading the shipped seed read-only)"
    return None


def main(argv: list[str]) -> int:
    argv = list(argv)
    plugin_data = None
    if len(argv) > 1 and argv[1].startswith("--plugin-data="):
        plugin_data = argv[1].split("=", 1)[1]
        del argv[1]
    elif len(argv) > 1 and argv[1] == "--plugin-data":
        if len(argv) < 3:
            sys.stderr.write("usage: inference-engine.py [--plugin-data <dir>] <subcommand> ...\n")
            return 2
        plugin_data = argv[2]
        del argv[1:3]
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        sys.stderr.write(__doc__ or "")
        return 0 if len(argv) >= 2 else 2
    cmd = argv[1]
    if cmd not in COMMANDS:
        sys.stderr.write(f"unknown subcommand: {cmd}\n")
        sys.stderr.write(f"available: {', '.join(COMMANDS)}\n")
        return 2
    try:
        stop = _configure_state(cmd, plugin_data)
        if stop is not None:
            return stop
        return COMMANDS[cmd](argv[2:])
    except LockBusy as exc:
        sys.stderr.write(f"[inference-engine] {cmd}: {exc}. Nothing was changed; retry later.\n")
        return EXIT_LOCK_BUSY
    except OSError as exc:
        sys.stderr.write(f"[inference-engine] {cmd} failed: {type(exc).__name__}: {exc}\n")
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv))
