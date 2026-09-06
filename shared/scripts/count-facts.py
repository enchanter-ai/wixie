#!/usr/bin/env python3
"""count-facts.py — derive documented counts from the source of truth and
either CHECK (fail on drift) or INJECT (rewrite them to match). Stdlib only.

Why: counts like the model count are hand-copied into the README badge/anchor/
heading/prose, CLAUDE.md, CONTRIBUTING, CITATION, marketplace.json, docs/, and
the mermaid diagrams. Every registry change silently re-breaks all of them
(the number drifted 64 -> 274 -> 447). This makes the registry the single
source and lets CI fail loudly on drift.

Usage:
    python shared/scripts/count-facts.py check     # CI: exit 1 on any drift
    python shared/scripts/count-facts.py inject     # rewrite all counts to match source

inject also propagates the model count into the adjacent sibling repos'
org-profile READMEs (../<repo>/docs/org-profile-README.md) when they are checked
out next to wixie — so one command fixes the whole org after a registry bump.
Absent siblings are skipped, so this stays a no-op in wixie's own CI.

CHANGELOG.md is intentionally NOT scanned — its "64-model registry" / "64 to
274" lines are historical release records, not current-count claims.
"""
import sys, os, re, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # shared/scripts -> repo root


def model_count():
    with open(os.path.join(ROOT, "shared", "models-registry.json"), encoding="utf-8") as fh:
        return int(json.load(fh)["model_count"])


# count name -> {value: callable-> int, patterns: [regex w/ ONE numeric group], files: [rel paths]}
COUNTS = {
    "models": {
        "value": model_count,
        "patterns": [
            r"Models-(\d+)",                          # shields.io badge slug
            r"\b(\d+)\s+(?:target\s+)?[Mm]odels\b",   # "274 models" / "274 target models" / "274 Models"
            r"\b(\d+)-model\b",                        # "274-model registry"
            r"agents-(\d+)-models",                    # README TOC anchor
        ],
        "files": [
            "README.md", "CLAUDE.md", "CONTRIBUTING.md", "CITATION.cff",
            ".claude-plugin/marketplace.json",
            "docs/faq.md", "docs/glossary.md", "docs/org-profile-README.md",
            "docs/science/README.md", "docs/architecture/index.html",
            "docs/architecture/enchanter-core-inventory.md",
            "docs/assets/lifecycle.mmd", "docs/assets/lifecycle.svg",
            "docs/assets/pipeline.mmd", "docs/assets/pipeline.svg",
            "plugins/prompt-crafter/README.md", "plugins/prompt-translate/README.md",
            "plugins/full/README.md",
        ],
    },
}

# Sibling org-profile READMEs live in adjacent repos (../<repo>, the standard
# enchanter-ai layout) and hard-code the model count in their Wixie blurb.
# `inject` rewrites them in place so a registry bump propagates org-wide in one
# command; absent siblings are skipped, so this stays a no-op in wixie's own CI.
ORG_SIBLINGS = ["crow", "djinn", "emu", "hydra", "lich", "pech", "sylph"]


def _swap(m, expected):
    """Return match text with its numeric group (group 1) replaced by expected."""
    s, e = m.start(1) - m.start(0), m.end(1) - m.start(0)
    g0 = m.group(0)
    return g0[:s] + str(expected) + g0[e:]


def _process(path, rel, patterns, expected, name, mode, drift, changed):
    """Scan one file: record drift (check) or rewrite its counts in place (inject)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    orig = text
    for pat in patterns:
        rx = re.compile(pat)
        if mode == "check":
            for m in rx.finditer(text):
                if m.group(1) != str(expected):
                    drift.append((rel, name, m.group(1), expected, m.group(0)))
        else:  # inject
            text = rx.sub(lambda m: _swap(m, expected), text)
    if mode == "inject" and text != orig:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        changed.append(rel)


def run(mode):
    drift, changed = [], []
    for name, cfg in COUNTS.items():
        expected = cfg["value"]()
        for rel in cfg["files"]:
            _process(os.path.join(ROOT, rel), rel, cfg["patterns"], expected, name, mode, drift, changed)
    # adjacent sibling org-profiles are an inject-only propagation target — the
    # push-at-bump model. wixie's own `check` never gates on another repo's docs;
    # each sibling owns its CI. (see ORG_SIBLINGS)
    if mode == "inject":
        mcfg = COUNTS["models"]
        m_expected = mcfg["value"]()
        for sib in ORG_SIBLINGS:
            _process(os.path.join(ROOT, os.pardir, sib, "docs", "org-profile-README.md"),
                     f"../{sib}/docs/org-profile-README.md", mcfg["patterns"], m_expected,
                     "models", mode, drift, changed)
    return drift, changed


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode not in ("check", "inject"):
        print("usage: count-facts.py [check|inject]", file=sys.stderr)
        sys.exit(2)
    drift, changed = run(mode)
    if mode == "inject":
        print(f"count-facts: injected — {len(changed)} file(s) updated: {', '.join(changed) or '(none)'}")
        # re-verify
        drift, _ = run("check")
    if drift:
        for rel, name, got, exp, ctx in drift:
            print(f"DRIFT {rel}: {name} says {got}, source={exp}   ({ctx!r})", file=sys.stderr)
        print(f"count-facts: FAIL — {len(drift)} drifted occurrence(s). Run: python shared/scripts/count-facts.py inject", file=sys.stderr)
        sys.exit(1)
    print(f"count-facts: OK — all counts match source (models={model_count()}).")
    sys.exit(0)


if __name__ == "__main__":
    main()
