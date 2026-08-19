#!/usr/bin/env python3
"""
score.py — compute candidate change-quality signals per commit.

Two families of predictors, each a per-commit boolean flag that we later test
against the durability label:

(a) CROW CONTENT DETECTORS  — ported from crow's trust-scorer
    (plugins/trust-scorer/hooks/post-tool-use/score-change.sh). Crow runs these
    over a file's current head-500 content; here we adapt them to run over the
    ADDED lines of the commit's diff (the content the commit introduced), which
    is the natural per-commit analog. Detectors:
        gutted_test, trivial_assertions, weak_crypto,
        wildcard_cors, exposed_secrets, debug_enabled, very_short_file
    Derived rollups:
        crow_critical  = gutted_test | exposed_secrets
        crow_high      = weak_crypto | wildcard_cors
        crow_flag_any  = any detector fired

(b) STRUCTURAL FEATURES  — cheap size/shape signals:
        big_diff       = additions+deletions > BIG_DIFF
        many_files     = n_files > MANY_FILES
        is_test_change / is_config_change / is_source_code

Each commit record gets a "signals" dict of booleans. Stdlib only.

Usage:
  python score.py --repo <path> --in dataset.jsonl --out scored.jsonl
  (repo needed to re-read each commit's diff for the content detectors)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from label_commits import classify_path, SKIP_RE

BIG_DIFF = 150      # additions+deletions threshold
MANY_FILES = 5      # files-touched threshold
VERY_SHORT = 5      # lines


# ── crow detector regexes (transcribed from score-change.sh) ──
TRIVIAL_RE = re.compile(r"expect\(true\)|expect\(1\)\.toBe\(1\)|assert\(true\)|\.toBe\(true\)\s*$", re.I)
REAL_ASSERT_RE = re.compile(r"expect\(|assert[A-Z(]|\.toThrow|\.toEqual|\.toMatch|\.toContain|\.toBe\(", re.I)
WEAK_CRYPTO_RE = re.compile(r'"HS256"|\'HS256\'|algorithms.*HS256|md5\(|MD5\(|eval\(')
WILDCARD_CORS_RE = re.compile(r'CORS.*=.*\*|cors.*:.*\*|"origin".*:.*"\*"', re.I)
SECRETS_RE = re.compile(r'sk_live|sk-live|PRIVATE.KEY|secret_key|api.key.*=.*[A-Za-z0-9]{20}', re.I)
DEBUG_RE = re.compile(r'"debug".*:.*true|DEBUG.*=.*true|debug.*=.*1', re.I)
COMMENT_STRIP_RE = re.compile(r'(//.*$)|(#.*$)', re.M)


def git(repo: str, *args: str) -> str:
    r = subprocess.run(["git", "-C", repo, *args],
                       capture_output=True, text=True, errors="replace")
    return r.stdout


def added_lines_by_file(repo: str, sha: str) -> dict[str, list[str]]:
    """Map file path -> list of lines the commit ADDED (diff '+' lines)."""
    out = git(repo, "show", sha, "--unified=0", "--format=", "--no-color")
    result: dict[str, list[str]] = {}
    cur = None
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
            result.setdefault(cur, [])
        elif line.startswith("+++ "):
            cur = None
        elif line.startswith("+") and not line.startswith("+++") and cur is not None:
            result[cur].append(line[1:])
    return result


def run_detectors(added: dict[str, list[str]]) -> dict[str, bool]:
    flags = {k: False for k in (
        "gutted_test", "trivial_assertions", "weak_crypto",
        "wildcard_cors", "exposed_secrets", "debug_enabled", "very_short_file")}
    for path, lines in added.items():
        if SKIP_RE.search(path):
            continue
        cls = classify_path(path)
        blob = "\n".join(lines)

        if cls == "test_change":
            trivial = len(TRIVIAL_RE.findall(blob))
            real = len(REAL_ASSERT_RE.findall(blob)) - trivial
            real = max(real, 0)
            if trivial > 0 and real == 0:
                flags["gutted_test"] = True
            elif trivial > 0:
                flags["trivial_assertions"] = True

        if cls == "source_code":
            code_only = COMMENT_STRIP_RE.sub("", blob)
            if WEAK_CRYPTO_RE.search(code_only):
                flags["weak_crypto"] = True
            if 0 < len(lines) < VERY_SHORT:
                flags["very_short_file"] = True

        if cls == "config_change":
            if WILDCARD_CORS_RE.search(blob):
                flags["wildcard_cors"] = True
            if SECRETS_RE.search(blob):
                flags["exposed_secrets"] = True
            if DEBUG_RE.search(blob):
                flags["debug_enabled"] = True
    return flags


def score_record(repo: str, rec: dict) -> dict:
    sha = rec["commit"]
    added = added_lines_by_file(repo, sha)
    det = run_detectors(added)

    churn = rec["additions"] + rec["deletions"]
    structural = {
        "big_diff": churn > BIG_DIFF,
        "many_files": rec["n_files"] > MANY_FILES,
        "is_test_change": rec["change_type"] == "test_change",
        "is_config_change": rec["change_type"] == "config_change",
        "is_source_code": rec["change_type"] == "source_code",
    }
    signals = dict(det)
    signals["crow_critical"] = det["gutted_test"] or det["exposed_secrets"]
    signals["crow_high"] = det["weak_crypto"] or det["wildcard_cors"]
    signals["crow_flag_any"] = any(det.values())
    signals.update(structural)

    rec = dict(rec)
    rec["signals"] = signals
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    repo = str(Path(args.repo).resolve())
    recs = [json.loads(l) for l in Path(args.inp).read_text(encoding="utf-8").splitlines() if l.strip()]
    scored = [score_record(repo, r) for r in recs]

    out = "\n".join(json.dumps(r) for r in scored)
    if args.out:
        Path(args.out).write_text(out + ("\n" if scored else ""), encoding="utf-8")
    else:
        print(out)
    sys.stderr.write(f"[score] scored {len(scored)} commits from {repo}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
