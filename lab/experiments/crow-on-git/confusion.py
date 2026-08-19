#!/usr/bin/env python3
"""
confusion.py — confusion matrix + precision/recall/F1 (with Wilson 95% CIs)
for each candidate signal vs the durability label.

Convention: the POSITIVE class is "bad" (label == 0, did-not-stick). A signal
firing is a POSITIVE prediction ("this change is risky"). So:

    TP = signal fired  AND commit was bad (label 0)
    FP = signal fired  AND commit was durable (label 1)
    FN = signal silent AND commit was bad
    TN = signal silent AND commit was durable

    precision = TP / (TP+FP)   "of flagged changes, how many really were bad"
    recall    = TP / (TP+FN)   "of bad changes, how many did we flag"

Wilson 95% CI (copied from shared/scripts/efficacy-replay.py) is put on
precision and recall — the interval a small n really warrants.

Stdlib only.
"""
from __future__ import annotations

import json
import math
from pathlib import Path


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    # copied verbatim from shared/scripts/efficacy-replay.py
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def confusion_for_signal(records: list[dict], signal: str) -> dict:
    tp = fp = fn = tn = 0
    for r in records:
        fired = bool(r.get("signals", {}).get(signal, False))
        bad = r["label"] == 0
        if fired and bad:
            tp += 1
        elif fired and not bad:
            fp += 1
        elif not fired and bad:
            fn += 1
        else:
            tn += 1
    prec_den = tp + fp
    rec_den = tp + fn
    precision = tp / prec_den if prec_den else None
    recall = tp / rec_den if rec_den else None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = None
    return {
        "signal": signal,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "fired": tp + fp,
        "precision": precision,
        "precision_ci": wilson_ci(tp, prec_den) if prec_den else None,
        "recall": recall,
        "recall_ci": wilson_ci(tp, rec_den) if rec_den else None,
        "f1": f1,
    }


def dataset_stats(records: list[dict]) -> dict:
    n = len(records)
    bad = sum(1 for r in records if r["label"] == 0)
    durable = n - bad
    reverted = sum(1 for r in records if r.get("was_reverted"))
    rewritten = sum(1 for r in records if r.get("label_reason") == "rewritten")
    base_rate = bad / n if n else 0.0
    return {
        "n": n,
        "durable": durable,
        "bad": bad,
        "bad_reverted": reverted,
        "bad_rewritten": rewritten,
        "base_rate_bad": base_rate,
        "base_rate_bad_ci": wilson_ci(bad, n) if n else None,
        "by_repo": _by_repo(records),
    }


def _by_repo(records: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in records:
        repo = r.get("repo", "?")
        d = out.setdefault(repo, {"n": 0, "bad": 0})
        d["n"] += 1
        if r["label"] == 0:
            d["bad"] += 1
    return out


def fmt_pct(x) -> str:
    return "  n/a" if x is None else f"{x*100:5.1f}%"


def fmt_ci(ci) -> str:
    return "        " if ci is None else f"[{ci[0]*100:4.0f},{ci[1]*100:4.0f}]"


def format_report(records: list[dict], signals: list[str]) -> str:
    stats = dataset_stats(records)
    lines = []
    lines.append("=" * 78)
    lines.append("DATASET")
    lines.append("=" * 78)
    lines.append(f"  n commits (matured)     : {stats['n']}")
    lines.append(f"  durable (y=1)           : {stats['durable']}")
    lines.append(f"  bad / did-not-stick(y=0): {stats['bad']}  "
                 f"(reverted={stats['bad_reverted']} rewritten={stats['bad_rewritten']})")
    br = stats["base_rate_bad"]
    lines.append(f"  base rate P(bad)        : {br*100:.1f}%  "
                 f"Wilson95={fmt_ci(stats['base_rate_bad_ci'])}")
    lines.append("  by repo:")
    for repo, d in sorted(stats["by_repo"].items()):
        lines.append(f"     {repo:<12} n={d['n']:<4} bad={d['bad']}")
    lines.append("")
    lines.append("=" * 78)
    lines.append("SIGNALS vs durability label   (positive class = bad, y=0)")
    lines.append("=" * 78)
    header = (f"{'signal':<20} {'fired':>5} {'TP':>3} {'FP':>3} {'FN':>3} {'TN':>3} "
              f"{'prec':>7} {'prec95':>11} {'recall':>7} {'rec95':>11} {'F1':>6}")
    lines.append(header)
    lines.append("-" * len(header))
    rows = [confusion_for_signal(records, s) for s in signals]
    for c in rows:
        lines.append(
            f"{c['signal']:<20} {c['fired']:>5} {c['tp']:>3} {c['fp']:>3} "
            f"{c['fn']:>3} {c['tn']:>3} {fmt_pct(c['precision'])} "
            f"{fmt_ci(c['precision_ci'])} {fmt_pct(c['recall'])} "
            f"{fmt_ci(c['recall_ci'])} "
            f"{'  n/a' if c['f1'] is None else format(c['f1'], '6.3f')}")
    return "\n".join(lines), stats, rows


if __name__ == "__main__":
    import sys
    recs = [json.loads(l) for l in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if l.strip()]
    sigs = sorted({s for r in recs for s in r.get("signals", {})})
    report, _, _ = format_report(recs, sigs)
    print(report)
