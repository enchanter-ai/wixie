#!/usr/bin/env python3
"""
run.py — orchestrate the crow-on-git free-ground-truth experiment.

  label  -> score -> confusion -> written verdict

Pools commits across one or more target repos, labels each by durability
(git line-survival / revert), scores crow's content detectors + structural
features, then reports per-signal precision/recall/F1 with Wilson 95% CIs and
an HONEST verdict.

Usage:
  python run.py --repos <path1> <path2> ... [--window-days 60] [--survival 0.5]
                [--out-dir output]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import label_commits
import score
import confusion

# signal display order: crow detectors first, then rollups, then structural
SIGNAL_ORDER = [
    "gutted_test", "trivial_assertions", "weak_crypto", "wildcard_cors",
    "exposed_secrets", "debug_enabled", "very_short_file",
    "crow_critical", "crow_high", "crow_flag_any",
    "big_diff", "many_files", "is_test_change", "is_config_change",
    "is_source_code",
]


def verdict(stats: dict, rows: list[dict]) -> str:
    """Honest, calibrated verdict. Does NOT inflate."""
    n = stats["n"]
    bad = stats["bad"]
    lines = ["=" * 78, "VERDICT", "=" * 78]

    # 1. Is n enough to conclude anything?
    lines.append(f"Dataset power: n={n}, bad={bad} "
                 f"(reverted={stats['bad_reverted']}, rewritten={stats['bad_rewritten']}).")
    if stats["bad_reverted"] == 0:
        lines.append("- The EXPLICIT-REVERT ground-truth channel is EMPTY: no commit in the")
        lines.append("  target history was reverted. All 'bad' labels come from the")
        lines.append("  line-survival (rewrite/churn) channel only.")
    if bad < 10 or (n - bad) < 10:
        lines.append(f"- Class sizes are small (bad={bad}, durable={n-bad}). Wilson CIs on")
        lines.append("  precision/recall will be wide; treat point estimates as indicative,")
        lines.append("  not conclusive.")

    # 2. Which signals separate? A signal is 'informative' if it fired at all AND
    #    its precision CI lower bound clears the base rate (better than guessing).
    base = stats["base_rate_bad"]
    lines.append("")
    lines.append(f"Base rate P(bad)={base*100:.1f}%. A signal beats chance only if its")
    lines.append("precision CI lower-bound exceeds the base rate.")
    informative, fired_but_weak, never_fired = [], [], []
    for c in rows:
        if c["fired"] == 0:
            never_fired.append(c["signal"])
            continue
        pci = c["precision_ci"]
        if pci and pci[0] > base and c["tp"] > 0:
            informative.append((c["signal"], c["precision"], pci, c["recall"], c["f1"]))
        else:
            fired_but_weak.append(c["signal"])

    lines.append("")
    if informative:
        lines.append("SIGNALS THAT SEPARATE (precision CI lower-bound > base rate):")
        for s, p, pci, r, f1 in informative:
            lines.append(f"  * {s}: precision={p*100:.0f}% CI95=[{pci[0]*100:.0f},{pci[1]*100:.0f}] "
                         f"recall={('%.0f%%' % (r*100)) if r is not None else 'n/a'} "
                         f"F1={('%.2f' % f1) if f1 is not None else 'n/a'}")
    else:
        lines.append("SIGNALS THAT SEPARATE: NONE. No signal's precision CI lower-bound")
        lines.append("clears the base rate — no candidate predictor is demonstrably better")
        lines.append("than guessing at this n.")
    if fired_but_weak:
        lines.append(f"Fired but NOT demonstrably better than chance: {', '.join(fired_but_weak)}")
    if never_fired:
        lines.append(f"Never fired on this corpus (zero signal): {', '.join(never_fired)}")

    # 3. crow-B recommendation
    lines.append("")
    lines.append("-" * 78)
    lines.append("CROW-B RECOMMENDATION (re-found crow on git survival?):")
    crow_dets = [c for c in rows if c["signal"] in (
        "gutted_test", "weak_crypto", "wildcard_cors", "exposed_secrets",
        "debug_enabled", "trivial_assertions", "very_short_file",
        "crow_critical", "crow_high", "crow_flag_any")]
    crow_fired = sum(c["fired"] for c in crow_dets)
    crow_informative = [s for (s, *_ ) in informative if s in {c["signal"] for c in crow_dets}]
    if crow_fired == 0:
        lines.append("  crow's content detectors fired on ~0 commits in this corpus. The")
        lines.append("  detectors are tuned for adversarial security regressions (leaked")
        lines.append("  secrets, gutted tests, weak crypto) that simply don't occur in this")
        lines.append("  benign self-authored history. => This corpus CANNOT validate crow-B.")
    elif crow_informative:
        lines.append(f"  crow detectors {crow_informative} show separation — WEAK support for")
        lines.append("  crow-B, but confirm on a larger/noisier corpus before building.")
    else:
        lines.append("  crow detectors fired but did not separate durable from bad.")
        lines.append("  => NOT YET justified to build the git-survival trust model.")
    lines.append("")
    lines.append("  Bottom line: the org has the measurement machinery (this harness runs)")
    lines.append("  but THIN GROUND TRUTH — near-zero reverts and few security regressions")
    lines.append("  in clean self-authored repos. Free git ground truth exists, but this")
    lines.append("  particular corpus is the wrong population to prove a change-quality")
    lines.append("  detector. Validate crow-B on a large multi-contributor OSS repo with")
    lines.append("  real reverts before committing to the re-founding.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", nargs="+", required=True)
    ap.add_argument("--window-days", type=int, default=60)
    ap.add_argument("--survival", type=float, default=0.5)
    ap.add_argument("--out-dir", default="output")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_recs: list[dict] = []
    for repo in args.repos:
        rp = str(Path(repo).resolve())
        name = Path(rp).name
        labeled = label_commits.label_repo(rp, name, args.window_days, args.survival)
        scored = [score.score_record(rp, r) for r in labeled]
        all_recs.extend(scored)
        print(f"[run] {name}: {len(scored)} matured commits labeled+scored")

    # persist labeled+scored dataset
    ds_path = out_dir / "dataset.jsonl"
    ds_path.write_text("\n".join(json.dumps(r) for r in all_recs) +
                       ("\n" if all_recs else ""), encoding="utf-8")

    signals = [s for s in SIGNAL_ORDER
               if any(s in r.get("signals", {}) for r in all_recs)]
    report, stats, rows = confusion.format_report(all_recs, signals)
    verdict_txt = verdict(stats, rows)

    full = "\n".join([
        "crow-on-git — free-ground-truth change-durability experiment",
        f"window_days={args.window_days}  survival_threshold={args.survival}  "
        f"repos={[Path(r).name for r in args.repos]}",
        "",
        report,
        "",
        verdict_txt,
        "",
    ])
    print("\n" + full)
    (out_dir / "verdict.txt").write_text(full, encoding="utf-8")
    (out_dir / "confusion.json").write_text(
        json.dumps({"stats": stats, "signals": rows}, indent=2), encoding="utf-8")
    print(f"\n[run] wrote {ds_path}, {out_dir/'verdict.txt'}, {out_dir/'confusion.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
