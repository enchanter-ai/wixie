"""OD-1-RELEASE-IDENTITY: every plugin whose installed artifact changed since the published
baseline (GitHub main 10eb827) advertises a newer version, so `claude plugin update` replaces
an existing install instead of reporting "already at the latest version" (N1).

Offline and CLI-free. BASELINE is the plugin.json version of each marketplace plugin at 10eb827.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MARKETPLACE = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
BASELINE = {
    "full": "3.0.0", "prompt-crafter": "0.1.0", "prompt-refiner": "0.1.0", "convergence-engine": "0.1.0",
    "prompt-tester": "0.1.0", "prompt-harden": "0.1.0", "prompt-translate": "0.1.0",
    "inference-engine": "0.1.0", "deep-research": "0.1.0",
}
SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def version(entry: dict) -> str:
    return json.loads((REPO / entry["source"] / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]


def key(v: str) -> tuple:
    m = SEMVER.fullmatch(v)
    if not m:
        raise AssertionError(f"not a plain SemVer version: {v!r}")
    return tuple(int(x) for x in m.groups())


class ReleaseIdentity(unittest.TestCase):
    def test_every_plugin_is_newer_than_the_published_baseline(self):
        self.assertEqual(set(BASELINE), {e["name"] for e in MARKETPLACE["plugins"]})
        for entry in MARKETPLACE["plugins"]:
            with self.subTest(plugin=entry["name"]):
                self.assertGreater(key(version(entry)), key(BASELINE[entry["name"]]))

    def test_marketplace_entries_do_not_pin_a_conflicting_version(self):
        for entry in MARKETPLACE["plugins"]:
            if "version" in entry:
                with self.subTest(plugin=entry["name"]):
                    self.assertEqual(entry["version"], version(entry))

    def test_inference_engine_roadmap_names_its_current_version(self):
        text = (REPO / "plugins" / "inference-engine" / "README.md").read_text(encoding="utf-8")
        current = re.findall(r"`(\d+\.\d+\.\d+)` \(current\)", text)
        self.assertEqual(current, [version({"source": "./plugins/inference-engine"})])
        self.assertNotRegex(text, r"`%s` = U4" % re.escape(current[0]))


if __name__ == "__main__":
    unittest.main()
