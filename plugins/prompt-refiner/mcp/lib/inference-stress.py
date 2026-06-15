#!/usr/bin/env python3
"""Inference-engine stress test — 100 synthetic artifacts, validate SPRT in practice.

Generates a realistic recurrence distribution, backfills it into a sandbox
state dir (never production), runs reconcile, and verifies that:

  * 3 HIGH-recurrence patterns (~10 observations across 6 sessions) elevate.
  * 5 MID-recurrence patterns (~4 observations across 3 sessions) elevate.
  * 50 NOISE singletons stay below the SPRT threshold.

Exits 0 if all expectations hold, 1 otherwise. Cleans up the sandbox on exit.

Stdlib only. Uses only subprocess + tempfile + random + json + pathlib.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows stdout/stderr UTF-8 — same fix as inference-engine.py
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE = SCRIPT_DIR / "inference-engine.py"

# Distribution — totals to exactly 100 artifacts
HIGH_PATTERNS = 3      # each produces 10 observations across 6 sessions
HIGH_OBS = 10
HIGH_SESSIONS = 6

MID_PATTERNS = 5       # each produces 4 observations across 3 sessions
MID_OBS = 4
MID_SESSIONS = 3

NOISE_PATTERNS = 50    # each produces 1 observation, 1 session
NOISE_OBS = 1

TOTAL_EXPECTED = HIGH_PATTERNS * HIGH_OBS + MID_PATTERNS * MID_OBS + NOISE_PATTERNS * NOISE_OBS
assert TOTAL_EXPECTED == 100, f"distribution doesn't sum to 100, got {TOTAL_EXPECTED}"


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_artifacts(seed: int = 2026) -> list[dict]:
    """Produce exactly 100 artifact dicts with a realistic temporal spread."""
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    artifacts = []

    # HIGH: patterns that recur often across many sessions
    for i in range(HIGH_PATTERNS):
        code = f"HR{i+1:02d}"
        for j in range(HIGH_OBS):
            session = f"sess-high-{i}-{j % HIGH_SESSIONS}"
            days_back = rng.uniform(0, 30)
            ts = iso(now - timedelta(days=days_back, hours=rng.uniform(0, 24)))
            artifacts.append({
                "code": code,
                "category": "stress-test",
                "title": f"[stress] high-recurrence pattern {code}",
                "cause": f"synthetic high-recurrence artifact #{j+1} for {code}",
                "counter": "synthetic counter — ignored by stress test",
                "signal": "synthetic trigger — ignored",
                "tags": ["stress", "high-recurrence", f"pattern-{code.lower()}"],
                "ts": ts,
                "session_id": session,
                "scope": "stress-test",
                "evidence": {"occurrences": 1, "cross_session_recurrence_observed": True},
            })

    # MID: patterns that recur a few times across a few sessions
    for i in range(MID_PATTERNS):
        code = f"MR{i+1:02d}"
        for j in range(MID_OBS):
            session = f"sess-mid-{i}-{j % MID_SESSIONS}"
            days_back = rng.uniform(0, 30)
            ts = iso(now - timedelta(days=days_back, hours=rng.uniform(0, 24)))
            artifacts.append({
                "code": code,
                "category": "stress-test",
                "title": f"[stress] mid-recurrence pattern {code}",
                "cause": f"synthetic mid-recurrence artifact #{j+1} for {code}",
                "counter": "synthetic counter — ignored by stress test",
                "signal": "synthetic trigger — ignored",
                "tags": ["stress", "mid-recurrence", f"pattern-{code.lower()}"],
                "ts": ts,
                "session_id": session,
                "scope": "stress-test",
                "evidence": {"occurrences": 1, "cross_session_recurrence_observed": True},
            })

    # NOISE: one-shot patterns that should never elevate
    for i in range(NOISE_PATTERNS):
        code = f"NZ{i+1:03d}"
        days_back = rng.uniform(0, 30)
        ts = iso(now - timedelta(days=days_back, hours=rng.uniform(0, 24)))
        artifacts.append({
            "code": code,
            "category": "stress-test",
            "title": f"[stress] noise singleton {code}",
            "cause": f"synthetic one-shot artifact for {code}",
            "counter": "synthetic counter — ignored by stress test",
            "signal": "synthetic trigger — ignored",
            "tags": ["stress", "noise", f"pattern-{code.lower()}"],
            "ts": ts,
            "session_id": f"sess-noise-{i}",
            "scope": "stress-test",
            "evidence": {"occurrences": 1, "cross_session_recurrence_observed": True},
        })

    rng.shuffle(artifacts)
    return artifacts


def run_engine(sandbox: Path, argv: list[str], env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "WIXIE_INFERENCE_STATE": str(sandbox), "WIXIE_INFERENCE_ENABLED": "1"}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(ENGINE), *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def main() -> int:
    print("=" * 60)
    print("  INFERENCE-ENGINE STRESS TEST")
    print("  100 synthetic artifacts · 3 HIGH + 5 MID + 50 NOISE")
    print("=" * 60)

    if not ENGINE.exists():
        print(f"FAIL: engine not found at {ENGINE}", file=sys.stderr)
        return 2

    sandbox = Path(tempfile.mkdtemp(prefix="inference-stress-"))
    print(f"\nsandbox: {sandbox}")

    try:
        # Step 1 — generate artifacts
        artifacts = generate_artifacts()
        assert len(artifacts) == 100
        print(f"\nstep 1 — generated {len(artifacts)} artifacts")
        print(f"  HIGH patterns: HR01, HR02, HR03 (10 obs × 6 sessions each)")
        print(f"  MID patterns:  MR01–MR05 (4 obs × 3 sessions each)")
        print(f"  NOISE:         NZ001–NZ050 (1 obs × 1 session)")

        # Step 2 — write to temp JSONL
        jsonl_path = sandbox / "seed.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as f:
            for a in artifacts:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")
        size_kb = jsonl_path.stat().st_size / 1024
        print(f"\nstep 2 — wrote {jsonl_path.name} ({size_kb:.1f} KB)")

        # Step 3 — backfill
        r = run_engine(sandbox, ["backfill", str(jsonl_path)])
        if r.returncode != 0:
            print(f"FAIL backfill — stdout:\n{r.stdout}\nstderr:\n{r.stderr}", file=sys.stderr)
            return 1
        print(f"\nstep 3 — backfill: {r.stdout.strip()}")

        # Step 4 — reconcile
        r = run_engine(sandbox, ["reconcile"])
        if r.returncode != 0:
            print(f"FAIL reconcile — stderr:\n{r.stderr}", file=sys.stderr)
            return 1
        print(f"step 4 — reconcile: {r.stdout.strip()}")

        # Step 5 — reconcile again (idempotency sanity check)
        r2 = run_engine(sandbox, ["reconcile"])
        if r2.stdout.strip() != r.stdout.strip():
            print(f"FAIL idempotency — run 1: {r.stdout.strip()!r} != run 2: {r2.stdout.strip()!r}", file=sys.stderr)
            return 1
        print(f"step 5 — idempotency OK (identical reconcile output on re-run)")

        # Step 6 — read catalog + verify elevations
        catalog = json.loads((sandbox / "catalog.json").read_text(encoding="utf-8"))
        patterns = catalog["patterns"]
        elevated = {pat["code"]: pat for pat in patterns.values() if pat["verdict"] == "elevated"}
        noise_verdicts = [pat for pat in patterns.values() if pat["verdict"] == "noise"]

        print(f"\nstep 6 — verdict breakdown:")
        print(f"  elevated: {len(elevated)}")
        print(f"  noise:    {len(noise_verdicts)}")
        print(f"  retired:  {sum(1 for p in patterns.values() if p['verdict'] == 'retired')}")

        print(f"\nstep 7 — elevated patterns (code, LLR, posterior_mean, 95% CI, obs, sessions):")
        for code in sorted(elevated):
            p = elevated[code]
            sess = len(p.get("sessions_seen", []))
            print(
                f"  {code:8} LLR={p['llr']:6.2f}  mean={p['posterior_mean']:.3f}  "
                f"CI={p['posterior_ci95']}  obs={p['observations']:3}  sessions={sess}"
            )

        # Expected behavior
        expected_elevated = {f"HR{i+1:02d}" for i in range(HIGH_PATTERNS)} | {f"MR{i+1:02d}" for i in range(MID_PATTERNS)}
        actual_elevated = set(elevated.keys())
        falsely_elevated = {c for c in actual_elevated if c.startswith("NZ")}

        missing = expected_elevated - actual_elevated
        unexpected = actual_elevated - expected_elevated

        print(f"\nstep 8 — SPRT behavior check:")
        print(f"  expected elevated (HR + MR): {sorted(expected_elevated)}")
        print(f"  actual elevated:              {sorted(actual_elevated)}")
        print(f"  missing (should-elevate-but-didn't): {sorted(missing) or 'none'}")
        print(f"  unexpected (elevated noise):         {sorted(unexpected) or 'none'}")

        ok = (not missing) and (not falsely_elevated)
        print(f"\nVERDICT: {'PASS — SPRT separates signal from noise correctly' if ok else 'FAIL — see missing/unexpected above'}")
        return 0 if ok else 1

    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
        print(f"\nsandbox cleaned up")


if __name__ == "__main__":
    sys.exit(main())
