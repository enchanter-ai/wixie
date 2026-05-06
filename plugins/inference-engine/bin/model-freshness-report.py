#!/usr/bin/env python3
"""Daily aggregator for model-freshness telemetry — F-006 closure.

Reads state/model-usage.ndjson, summarizes the most recent N events per
session, and flags any registry entry whose sunset_date has passed today.

Stdlib only. Read-only — never mutates the NDJSON.

Output: human-readable text by default, JSON via --json. Exit code is
always 0 (advisory). The presence of past-sunset entries is signalled by
content, not by exit code.

Usage:
    model-freshness-report.py
    model-freshness-report.py --json
    model-freshness-report.py --usage path/to/model-usage.ndjson
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
DEFAULT_USAGE = PLUGIN_ROOT / "state" / "model-usage.ndjson"
WIXIE_ROOT = PLUGIN_ROOT.parent.parent
DEFAULT_REGISTRY = WIXIE_ROOT / "shared" / "models-registry.json"


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip malformed rows silently — advisory contract.
                continue
    return rows


def latest_event(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    # Rows have ISO ts; lexicographic sort works for the format we emit.
    return max(rows, key=lambda r: r.get("ts", ""))


def flag_past_sunset(registry_path: Path, today: dt.date) -> list[dict[str, str]]:
    if not registry_path.exists():
        return []
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    flagged: list[dict[str, str]] = []
    for name, spec in (registry.get("models") or {}).items():
        if not isinstance(spec, dict):
            continue
        sunset_raw = spec.get("sunset_date")
        if not sunset_raw:
            continue
        try:
            sunset = dt.date.fromisoformat(str(sunset_raw)[:10])
        except (ValueError, TypeError):
            continue
        if sunset <= today:
            flagged.append({
                "model": name,
                "sunset_date": sunset.isoformat(),
                "days_past": str((today - sunset).days),
            })
    return flagged


def render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=== Wixie model-freshness report ===")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append(f"Usage NDJSON rows: {report['usage_rows']}")

    last = report.get("latest_event")
    if last is None:
        lines.append("No telemetry events recorded yet.")
    else:
        lines.append(f"Latest session: {last.get('session')}")
        lines.append(f"  ts:                    {last.get('ts')}")
        lines.append(f"  registry last_updated: {last.get('registry_last_updated')}")
        lines.append(f"  registry age (days):   {last.get('registry_age_days')}")
        lines.append(f"  stale threshold:       {last.get('stale_threshold_days')}")
        lines.append(f"  registry stale:        {last.get('registry_stale')}")
        lines.append(f"  models in registry:    {len(last.get('models_in_registry') or [])}")
        lines.append(f"  models with sunset:    {len(last.get('models_with_known_sunset') or [])}")
        lines.append(f"  models past sunset:    {len(last.get('models_past_sunset') or [])}")

    flagged = report.get("flagged_today") or []
    if flagged:
        lines.append("")
        lines.append(f"FLAGGED — {len(flagged)} model(s) past sunset_date as of today:")
        for entry in flagged:
            lines.append(
                f"  - {entry['model']}: sunset {entry['sunset_date']} "
                f"({entry['days_past']} day(s) ago)"
            )
    else:
        lines.append("")
        lines.append("No models past sunset_date.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily model-freshness aggregator (F-006).")
    parser.add_argument("--usage", type=Path, default=DEFAULT_USAGE)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON.")
    args = parser.parse_args(argv)

    today = dt.datetime.now(dt.timezone.utc).date()
    rows = read_ndjson(args.usage)
    last = latest_event(rows)
    flagged = flag_past_sunset(args.registry, today)

    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "usage_path": str(args.usage),
        "registry_path": str(args.registry),
        "usage_rows": len(rows),
        "latest_event": last,
        "flagged_today": flagged,
    }

    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
