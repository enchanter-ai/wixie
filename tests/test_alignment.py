"""Alignment tests for this repo — cross-cutting brand contracts.

Verifies plugin.json shape, marketplace.json completeness, hook subagent guard,
and conduct module count consistency. Repo-aware via REPO_ROOT below.
"""
from __future__ import annotations
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_PLUGIN_KEYS = {"name", "version", "description"}

# Subagent-guard variants accepted in the first 20 lines of a hook script.
_GUARD_PATTERNS = [
    'if [[ -n "$CLAUDE_SUBAGENT" ]]; then',
    'if [[ -n "${CLAUDE_SUBAGENT:-}" ]]; then',
]


def _plugin_dirs() -> list[Path]:
    """Return subdirectories of <repo_root>/plugins/ that exist on disk."""
    plugins_root = REPO_ROOT / "plugins"
    if not plugins_root.is_dir():
        return []
    return [p for p in plugins_root.iterdir() if p.is_dir()]


def _marketplace_names() -> set[str]:
    """Return the plugin names listed in <repo_root>/.claude-plugin/marketplace.json."""
    mp = REPO_ROOT / ".claude-plugin" / "marketplace.json"
    if not mp.exists():
        return set()
    data = json.loads(mp.read_text(encoding="utf-8"))
    return {p["name"] for p in data.get("plugins", [])}


class TestPluginJsonShape(unittest.TestCase):
    """Every plugin.json parses and carries required keys; marketplace.json is in sync."""

    def test_every_plugin_json_parses_and_has_required_keys(self):
        plugin_dirs = _plugin_dirs()
        if not plugin_dirs:
            self.skipTest("No plugin directories found — nothing to assert.")
        for plugin_dir in plugin_dirs:
            with self.subTest(plugin=plugin_dir.name):
                path = plugin_dir / ".claude-plugin" / "plugin.json"
                self.assertTrue(path.exists(), f"{path} is missing")
                data = json.loads(path.read_text(encoding="utf-8"))
                missing = REQUIRED_PLUGIN_KEYS - data.keys()
                self.assertFalse(
                    missing,
                    f"{plugin_dir.name}: plugin.json missing keys {missing}",
                )
                for key in REQUIRED_PLUGIN_KEYS:
                    self.assertTrue(
                        str(data[key]).strip(),
                        f"{plugin_dir.name}: key '{key}' is empty",
                    )

    def test_marketplace_json_lists_every_disk_plugin(self):
        """Every plugin dir found on disk must appear in marketplace.json."""
        plugin_dirs = _plugin_dirs()
        if not plugin_dirs:
            self.skipTest("No plugin directories found — nothing to assert.")
        mp = REPO_ROOT / ".claude-plugin" / "marketplace.json"
        self.assertTrue(mp.exists(), "marketplace.json is missing")
        disk_names = {p.name for p in plugin_dirs}
        listed_names = _marketplace_names()
        unlisted = disk_names - listed_names
        self.assertFalse(
            unlisted,
            f"Plugins on disk but missing from marketplace.json: {unlisted}",
        )

    def test_marketplace_json_has_no_phantom_plugins(self):
        """marketplace.json must not list plugins that don't exist on disk."""
        plugin_dirs = _plugin_dirs()
        disk_names = {p.name for p in plugin_dirs}
        listed_names = _marketplace_names()
        if not listed_names:
            self.skipTest("marketplace.json absent or empty — nothing to assert.")
        phantom = listed_names - disk_names
        self.assertFalse(
            phantom,
            f"marketplace.json lists plugins not found on disk: {phantom}",
        )


class TestHookSubagentGuard(unittest.TestCase):
    """Every hook .sh file must contain the subagent-loop guard within its first 20 lines."""

    def test_every_hook_has_subagent_guard(self):
        hooks = list((REPO_ROOT / "plugins").rglob("hooks/*/*.sh")) if (REPO_ROOT / "plugins").is_dir() else []
        if not hooks:
            # No hook scripts is a valid state for repos without hooks (e.g. wixie).
            return
        for path in hooks:
            with self.subTest(hook=str(path.relative_to(REPO_ROOT))):
                lines = path.read_text(encoding="utf-8").splitlines()
                # Examine only the first 20 non-empty, non-shebang lines.
                head = [
                    ln.strip()
                    for ln in lines[:20]
                    if ln.strip() and not ln.strip().startswith("#!")
                ]
                found = any(
                    any(guard in ln for guard in _GUARD_PATTERNS)
                    for ln in head
                )
                self.assertTrue(
                    found,
                    f"{path.name}: subagent guard not found in first 20 lines. "
                    f"Expected one of: {_GUARD_PATTERNS}",
                )


class TestConductModuleCount(unittest.TestCase):
    """Conduct module count on disk should match any N-module claim in CLAUDE.md / README.md."""

    def _count_conduct_modules(self) -> int:
        # Vendored foundations conduct modules (canonical source).
        foundations_dir = REPO_ROOT / "shared" / "foundations" / "conduct"
        foundations_count = len(list(foundations_dir.glob("*.md"))) if foundations_dir.is_dir() else 0
        # Wixie-specific conduct modules (inference-substrate.md lives here).
        local_dir = REPO_ROOT / "shared" / "conduct"
        local_count = len(list(local_dir.glob("*.md"))) if local_dir.is_dir() else 0
        return foundations_count + local_count

    def _check_doc_count(self, doc_path: Path, actual: int) -> None:
        """Soft check: if a numeric module count claim exists in doc, it must match actual."""
        if not doc_path.exists():
            return
        text = doc_path.read_text(encoding="utf-8")
        # Match patterns like "10 modules", "10-module", "Agent Conduct (10 Modules)"
        matches = re.findall(r"\b(\d+)[\s-]?[Mm]odule", text)
        if not matches:
            return  # No count claim — nothing to assert.
        for m in matches:
            with self.subTest(doc=doc_path.name, claimed=m):
                self.assertEqual(
                    int(m),
                    actual,
                    f"{doc_path.name} claims {m} conduct modules but {actual} .md files found "
                    f"in shared/foundations/conduct/ + shared/conduct/",
                )

    def test_conduct_module_count_matches_claude_md(self):
        actual = self._count_conduct_modules()
        self._check_doc_count(REPO_ROOT / "CLAUDE.md", actual)

    def test_conduct_module_count_matches_readme(self):
        actual = self._count_conduct_modules()
        self._check_doc_count(REPO_ROOT / "README.md", actual)


if __name__ == "__main__":
    unittest.main()
