#!/usr/bin/env python3
"""
label_commits.py — free ground-truth labeling of git commits by change durability.

For a target git repo, walk `git log` and label each commit's change:

  y=0 (bad / did-not-stick):
     * the commit was reverted  (message ^Revert, or a later commit whose body
       says "This reverts commit <sha>"), OR
     * the lines it introduced were mostly deleted/rewritten inside the maturity
       window  (line-survival ratio < SURVIVAL_THRESHOLD).

  y=1 (good / durable):
     * its introduced lines survive to the window horizon
       (survival ratio >= SURVIVAL_THRESHOLD).

Commits too recent to have matured (age < window_days) are EXCLUDED — they have
not had a fair chance to be reverted/rewritten.

Ground truth is FREE: it comes entirely from git history, no human labels.

Line survival is measured with `git blame` at a fixed per-commit horizon ref
(the newest commit whose date <= commit_date + window_days). A line the commit
added counts as "surviving" iff blame at the horizon still attributes it to that
commit (i.e. no later commit in the window overwrote it).

Stdlib only. Output: JSONL, one record per labeled commit.

Usage:
  python label_commits.py --repo <path> [--window-days 60] [--survival 0.5]
                          [--out dataset.jsonl] [--repo-name wixie]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from bisect import bisect_right
from pathlib import Path

# ── change_type classification (mirrors crow's change-tracker taxonomy) ──
TEST_RE = re.compile(r"(^|/)(test|tests|spec|__tests__)(/|_)|[._](test|spec)\.", re.I)
CONFIG_EXTS = {".env", ".ini", ".cfg", ".conf", ".json", ".yaml", ".yml", ".toml"}
CODE_EXTS = {".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".sh", ".rb",
             ".java", ".c", ".h", ".cpp", ".cc", ".mjs", ".cjs"}
DOC_EXTS = {".md", ".txt", ".rst", ".mmd"}
# files that are noise for a survival signal (generated / vendored / binary-ish)
SKIP_RE = re.compile(r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|\.min\.|"
                     r"\.(png|jpg|jpeg|gif|svg|pdf|ico|woff2?|ttf|zip|lock)$)", re.I)


def classify_path(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if name.startswith(".env") or ext in CONFIG_EXTS:
        # tests take priority over config for e.g. jest.config in __tests__
        if TEST_RE.search(path):
            return "test_change"
        return "config_change"
    if TEST_RE.search(path):
        return "test_change"
    if ext in CODE_EXTS:
        return "source_code"
    if ext in DOC_EXTS:
        return "docs"
    return "other"


def git(repo: str, *args: str) -> str:
    r = subprocess.run(["git", "-C", repo, *args],
                       capture_output=True, text=True, errors="replace")
    return r.stdout


def load_commits(repo: str) -> list[dict]:
    """Linear list of non-merge commits, oldest first, with ts + subject."""
    out = git(repo, "log", "--no-merges", "--reverse",
              "--pretty=format:%H%x09%ct%x09%s")
    commits = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        sha, ct, subj = parts
        commits.append({"sha": sha, "ts": int(ct), "subject": subj})
    return commits


def reverted_shas(repo: str, commits: list[dict]) -> set[str]:
    """SHAs known-reverted: parse 'This reverts commit <sha>' from all bodies,
    plus map ^Revert "<subject>" messages back to the reverted subject."""
    reverted: set[str] = set()
    full = git(repo, "log", "--no-merges", "--pretty=format:%H%x1e%B%x1f")
    subj_to_sha = {c["subject"]: c["sha"] for c in commits}
    for rec in full.split("\x1f"):
        rec = rec.strip()
        if not rec or "\x1e" not in rec:
            continue
        _sha, body = rec.split("\x1e", 1)
        for m in re.finditer(r"This reverts commit ([0-9a-f]{7,40})", body):
            short = m.group(1)
            for c in commits:
                if c["sha"].startswith(short):
                    reverted.add(c["sha"])
        m = re.match(r'\s*Revert "(.+?)"', body)
        if m and m.group(1) in subj_to_sha:
            reverted.add(subj_to_sha[m.group(1)])
    return reverted


def commit_files(repo: str, sha: str) -> list[dict]:
    """Per-file additions/deletions from numstat (binary files reported as -)."""
    out = git(repo, "show", "--numstat", "--format=", sha)
    files = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        add, dele, path = parts
        if add == "-" or dele == "-":
            continue  # binary
        files.append({"path": path, "add": int(add), "del": int(dele)})
    return files


def horizon_survival(repo: str, sha: str, files: list[dict],
                     horizon_sha: str) -> tuple[int, int, dict]:
    """Fraction of lines this commit added that still exist at horizon_sha.
    Returns (surviving_lines, total_added_lines, per_file_detail)."""
    total_added = 0
    surviving = 0
    detail = {}
    for f in files:
        path, add = f["path"], f["add"]
        if add == 0 or SKIP_RE.search(path):
            continue
        cls = classify_path(path)
        if cls in ("docs", "other"):
            # survival still measured, but these are noisy; keep for completeness
            pass
        total_added += add
        # blame the file at the horizon; count lines still attributed to sha
        r = subprocess.run(
            ["git", "-C", repo, "blame", "--line-porcelain", horizon_sha,
             "--", path],
            capture_output=True, text=True, errors="replace")
        alive = 0
        if r.returncode == 0 and r.stdout:
            for bl in r.stdout.splitlines():
                # porcelain header: "<40-sha> <orig> <final> [<num>]"
                if len(bl) >= 40 and bl[:40] == sha:
                    alive += 1
        alive = min(alive, add)  # blame can't attribute more than were added
        surviving += alive
        detail[path] = {"added": add, "alive": alive}
    return surviving, total_added, detail


def build_horizon_index(commits: list[dict]):
    """Sorted timestamps for O(log n) horizon lookup."""
    ordered = sorted(commits, key=lambda c: c["ts"])
    ts = [c["ts"] for c in ordered]
    return ordered, ts


def find_horizon(ordered, ts_list, commit_ts: int, window_secs: int) -> dict | None:
    """Newest commit with ts <= commit_ts + window."""
    target = commit_ts + window_secs
    idx = bisect_right(ts_list, target) - 1
    if idx < 0:
        return None
    return ordered[idx]


def label_repo(repo: str, repo_name: str, window_days: int,
               survival_threshold: float) -> list[dict]:
    window_secs = window_days * 86400
    commits = load_commits(repo)
    if not commits:
        return []
    head_ts = max(c["ts"] for c in commits)
    reverted = reverted_shas(repo, commits)
    ordered, ts_list = build_horizon_index(commits)

    records = []
    for c in commits:
        sha, cts = c["sha"], c["ts"]
        matured = (head_ts - cts) >= window_secs
        if not matured:
            continue  # too recent to have had a fair window
        files = commit_files(repo, sha)
        if not files:
            continue
        additions = sum(f["add"] for f in files)
        deletions = sum(f["del"] for f in files)
        # primary change type = most common non-other class by file count
        counts: dict[str, int] = {}
        for f in files:
            counts[classify_path(f["path"])] = counts.get(classify_path(f["path"]), 0) + 1
        primary = max(counts, key=lambda k: counts[k]) if counts else "other"

        horizon = find_horizon(ordered, ts_list, cts, window_secs)
        horizon_sha = horizon["sha"] if horizon else sha

        is_revert_msg = bool(re.match(r"\s*Revert\b", c["subject"], re.I))
        was_reverted = sha in reverted

        surviving, total_added, detail = horizon_survival(repo, sha, files, horizon_sha)
        survival_ratio = (surviving / total_added) if total_added > 0 else None

        # ── label ──
        if was_reverted:
            label, reason = 0, "reverted"
        elif survival_ratio is None:
            # pure-deletion / non-code-only commit: no introduced lines to track
            continue
        elif survival_ratio < survival_threshold:
            label, reason = 0, "rewritten"
        else:
            label, reason = 1, "durable"

        records.append({
            "repo": repo_name,
            "commit": sha[:12],
            "subject": c["subject"][:120],
            "ts": cts,
            "age_days": round((head_ts - cts) / 86400, 1),
            "files": [f["path"] for f in files],
            "n_files": len(files),
            "additions": additions,
            "deletions": deletions,
            "change_type": primary,
            "is_revert_commit": is_revert_msg,
            "was_reverted": was_reverted,
            "horizon_commit": horizon_sha[:12],
            "surviving_lines": surviving,
            "tracked_added_lines": total_added,
            "survival_ratio": round(survival_ratio, 4) if survival_ratio is not None else None,
            "label": label,
            "label_reason": reason,
        })
    return records


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--repo-name", default=None)
    ap.add_argument("--window-days", type=int, default=60)
    ap.add_argument("--survival", type=float, default=0.5)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    repo = str(Path(args.repo).resolve())
    name = args.repo_name or Path(repo).name
    recs = label_repo(repo, name, args.window_days, args.survival)

    out = "\n".join(json.dumps(r) for r in recs)
    if args.out:
        Path(args.out).write_text(out + ("\n" if recs else ""), encoding="utf-8")
    else:
        print(out)

    n = len(recs)
    bad = sum(1 for r in recs if r["label"] == 0)
    sys.stderr.write(
        f"[label] {name}: n={n} durable={n-bad} bad={bad} "
        f"(window={args.window_days}d survival>={args.survival})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
