"""WIX-DIST-003: the declared install graph covers every cross-plugin runtime reference.

An install of `<p>@wixie` brings in `<p>` plus the transitive closure of the
`dependencies` in its plugin.json (marketplace plugin names; the form the pinned CLI
2.1.280 resolves, as `full` already uses). A skill that invokes another plugin's
skill, or reads another plugin's directory, only works from an install when that
other plugin is in the closure. Offline and CLI-free (never invokes `claude`).

Cross-plugin references are found in shipped runtime files (skills, agents, hooks,
plugin scripts; not vendor/, state/ or README.md):
  - an instruction to invoke a skill (or engine) by name that another plugin ships;
  - a `${CLAUDE_PLUGIN_ROOT}/..` path naming another marketplace plugin's directory.
Each reference must be covered by the referencing plugin's dependency closure, or be
listed in OPTIONAL with the fallback sentence its skill text states verbatim.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MARKETPLACE = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
SOURCES = {e["name"]: (REPO / e["source"]).resolve() for e in MARKETPLACE["plugins"]}

INVOKE = re.compile(r"\b[Ii]nvoke (?:the )?`?/?([a-z][a-z0-9-]*)`? (?:skill|engine)\b")
PLUGIN_PATH = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/(?:\.\./)+(?:plugins/)?([a-z][a-z0-9-]*)/")
# (referencing plugin, referenced plugin) -> fallback the referencing skill states when absent.
OPTIONAL = {
    ("convergence-engine", "inference-engine"): "The briefing is advisory, never blocking; if missing or stale, proceed honestly",
}


def manifest(name: str) -> dict:
    return json.loads((SOURCES[name] / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))


def closure(name: str) -> set:
    seen, todo = set(), [name]
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo.extend(manifest(n).get("dependencies", []))
    return seen


def skill_owners() -> dict:
    owners = {}
    for name, root in SOURCES.items():
        for s in root.glob("skills/*/SKILL.md"):
            m = re.search(r"^name:\s*(\S+)", s.read_text(encoding="utf-8"), re.M)
            if m:
                owners[m.group(1)] = name
    return owners


def runtime_files(root: Path):
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root)
        if (f.is_file() and rel.parts[0] not in ("vendor", "state") and f.name != "README.md"
                and f.suffix in (".md", ".json", ".py", ".sh")):
            yield f, rel.as_posix()


def cross_plugin_refs():
    """(referencing plugin, referenced plugin, file, text) for every cross-plugin reference."""
    owners = skill_owners()
    for name, root in SOURCES.items():
        for f, rel in runtime_files(root):
            text = f.read_text(encoding="utf-8")
            for m in INVOKE.finditer(text):
                target = owners.get(m.group(1))
                if target and target != name:
                    yield name, target, rel, text
            for m in PLUGIN_PATH.finditer(text):
                target = m.group(1)
                if target in SOURCES and target != name:
                    yield name, target, rel, text


class DeclaredInstallGraph(unittest.TestCase):
    def test_dependencies_are_marketplace_plugins(self):
        for name in SOURCES:
            for dep in manifest(name).get("dependencies", []):
                with self.subTest(plugin=name, dependency=dep):
                    self.assertIn(dep, SOURCES)

    def test_detector_finds_the_known_references(self):
        found = {(a, b) for a, b, _, _ in cross_plugin_refs()}
        self.assertIn(("prompt-crafter", "deep-research"), found)
        self.assertIn(("convergence-engine", "inference-engine"), found)

    def test_every_cross_plugin_reference_is_installed_or_optional(self):
        for src, dst, rel, text in cross_plugin_refs():
            with self.subTest(plugin=src, file=rel, needs=dst):
                fallback = OPTIONAL.get((src, dst))
                if fallback is not None:
                    self.assertIn(fallback, text, "declared optional, but the skill no longer states its fallback")
                    continue
                self.assertIn(dst, closure(src), f"`plugin install {src}@wixie` does not install {dst}; "
                              f"declare it in plugins/{src}/.claude-plugin/plugin.json dependencies")

    def test_full_installs_every_member_closure(self):
        full = closure("full")
        for member in manifest("full")["dependencies"]:
            with self.subTest(member=member):
                self.assertLessEqual(closure(member), full)
        self.assertIn("deep-research", manifest("full")["dependencies"],
                      "/create (prompt-crafter) requires deep-research; full lists it explicitly")


if __name__ == "__main__":
    unittest.main()
