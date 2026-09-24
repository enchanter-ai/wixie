"""Shared helpers for the inference-engine tests.

Every test runs the real engine as a subprocess against a disposable WIXIE_INFERENCE_STATE
directory (never plugins/inference-engine/state/), with the session and gate variables
cleared so the host's own CLAUDE_CODE_SESSION_ID cannot leak into an expectation.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "shared" / "scripts" / "inference-engine.py"
EMIT_SH = REPO / "shared" / "scripts" / "inference-emit.sh"

SCRUBBED_ENV = (
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_SESSION_ID",
    "ENCHANTED_ATTRIBUTION_PLUGIN",
    "WIXIE_INFERENCE_ENABLED",
    "WIXIE_INFERENCE_STATE",
    "WIXIE_INFERENCE_LOCK_TIMEOUT",
    "WIXIE_INFERENCE_EMIT_WAIT",
)


def clean_env(state: Path, **extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV}
    env["WIXIE_INFERENCE_STATE"] = str(state)
    env["WIXIE_INFERENCE_ENABLED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def run_engine(state: Path, *args: str, stdin: bytes | None = None, timeout: float = 180,
               **env_extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ENGINE), *args],
        input=stdin,
        capture_output=True,
        env=clean_env(state, **env_extra),
        timeout=timeout,
    )


def out(proc: subprocess.CompletedProcess) -> str:
    return proc.stdout.decode("utf-8", "replace")


def err(proc: subprocess.CompletedProcess) -> str:
    return proc.stderr.decode("utf-8", "replace")


def first_token(proc: subprocess.CompletedProcess) -> str:
    text = out(proc).strip()
    return text.split()[0] if text else ""


def write_jsonl(path: Path, records: list) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                    encoding="utf-8")
    return path


def write_json(path: Path, record) -> Path:
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return path


def catalog(state: Path) -> dict:
    return json.loads((state / "catalog.json").read_text(encoding="utf-8"))


def log_lines(state: Path) -> list[bytes]:
    p = state / "artifacts.jsonl"
    if not p.exists():
        return []
    return [ln for ln in p.read_bytes().split(b"\n") if ln.strip()]


SUMMARY_KEYS = ("observations", "sessions_seen", "llr", "alpha", "beta", "posterior_mean",
                "verdict")


def summary(state: Path) -> dict:
    """Evidence-bearing fields per pattern code. Time-dependent fields are excluded."""
    cat = catalog(state)
    res = {}
    for pat in cat["patterns"].values():
        res[pat["code"]] = {k: pat[k] for k in SUMMARY_KEYS}
    return {"total_artifacts": cat["total_artifacts"], "patterns": res}


class StateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wixie-inference-test-"))
        self.state = self.tmp / "state"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def new_state(self, name: str) -> Path:
        return self.tmp / name

    def ok(self, proc: subprocess.CompletedProcess, code: int = 0) -> subprocess.CompletedProcess:
        self.assertEqual(proc.returncode, code,
                         f"exit {proc.returncode}\nstdout: {out(proc)}\nstderr: {err(proc)}")
        self.assertNotIn("Traceback", err(proc))
        return proc


def main() -> None:
    unittest.main(module="__main__", verbosity=1)
