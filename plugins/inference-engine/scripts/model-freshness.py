#!/usr/bin/env python3
"""Model-freshness telemetry — F-006 closure.

Reads wixie/shared/models-registry.json and emits one NDJSON row per session
to state/model-usage.ndjson. Fired by SessionStart hook (advisory).

Each row records:
  - session uuid
  - timestamp (ISO 8601, UTC)
  - models_in_registry — full list of model IDs
  - models_with_known_sunset — models that declare a sunset_date
  - models_past_sunset — models whose sunset_date has elapsed (the alert set)
  - registry_last_updated — copied from registry root
  - stale_threshold_days — registry-staleness threshold (default 90)
  - registry_age_days — days since last_updated; >= threshold flags the registry itself

Stdlib only. Atomic NDJSON append.

The companion daily aggregator (`bin/model-freshness-report.py`) reads the
NDJSON, summarizes the most recent session, and flags entries whose
`sunset_date` is in the past relative to today.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
WIXIE_ROOT = PLUGIN_ROOT.parent.parent
DEFAULT_REGISTRY = WIXIE_ROOT / "shared" / "models-registry.json"
STATE_DIR = PLUGIN_ROOT / "state"
USAGE_LOG = STATE_DIR / "model-usage.ndjson"

DEFAULT_STALE_THRESHOLD_DAYS = 90


def parse_iso_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        # Accept either YYYY-MM-DD or full ISO timestamp.
        return dt.date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"registry not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def classify(registry: dict[str, Any], today: dt.date, threshold_days: int) -> dict[str, Any]:
    models = registry.get("models", {}) or {}
    last_updated = parse_iso_date(registry.get("last_updated"))

    in_registry: list[str] = sorted(models.keys())
    with_sunset: list[dict[str, str]] = []
    past_sunset: list[dict[str, str]] = []

    for name, spec in models.items():
        if not isinstance(spec, dict):
            continue
        sunset = parse_iso_date(spec.get("sunset_date"))
        if sunset is None:
            continue
        with_sunset.append({"model": name, "sunset_date": sunset.isoformat()})
        if sunset <= today:
            past_sunset.append({"model": name, "sunset_date": sunset.isoformat()})

    registry_age_days: int | None
    if last_updated is None:
        registry_age_days = None
    else:
        registry_age_days = (today - last_updated).days

    return {
        "models_in_registry": in_registry,
        "models_with_known_sunset": with_sunset,
        "models_past_sunset": past_sunset,
        "registry_last_updated": registry.get("last_updated"),
        "registry_age_days": registry_age_days,
        "stale_threshold_days": threshold_days,
        "registry_stale": (registry_age_days is not None and registry_age_days >= threshold_days),
    }


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, separators=(",", ":")) + "\n"
    # Open with O_APPEND — POSIX append for small lines is atomic enough for
    # advisory telemetry (single-writer assumption per session).
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def emit_event(
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    stale_threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS,
    session_id: str | None = None,
    output_path: Path = USAGE_LOG,
    dry_run: bool = False,
    today: dt.date | None = None,
) -> dict[str, Any]:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    registry = load_registry(registry_path)
    body = classify(registry, today, stale_threshold_days)
    event = {
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": session_id or os.environ.get("CLAUDE_SESSION_ID") or str(uuid.uuid4()),
        **body,
    }
    if not dry_run:
        append_event(output_path, event)
    return event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wixie model-freshness telemetry (F-006).")
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="Path to models-registry.json.",
    )
    parser.add_argument(
        "--stale-threshold-days",
        type=int,
        default=DEFAULT_STALE_THRESHOLD_DAYS,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=USAGE_LOG,
        help="NDJSON output path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the event but do not append to NDJSON.",
    )
    parser.add_argument(
        "--print",
        dest="print_event",
        action="store_true",
        help="Print the emitted event to stdout (default off — hooks should be quiet).",
    )
    args = parser.parse_args(argv)

    try:
        event = emit_event(
            registry_path=args.registry,
            stale_threshold_days=args.stale_threshold_days,
            output_path=args.output,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001 — fail-open advisory hook
        # Hooks must not block the session — write the failure to stderr only.
        print(f"[model-freshness] error: {exc!r}", file=sys.stderr)
        return 0

    if args.print_event:
        print(json.dumps(event, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
