"""WIX-DIST-001: an installed plugin must carry its pinned shared conduct.

Offline and CLI-free (never invokes `claude`): checks the manifest shape the
pinned Claude Code CLI accepts, and that scripts/vendor-conduct.py keeps every
plugin's plugin-local conduct (plugins/<p>/vendor/) identical to the pin and
fails on every kind of drift. The full byte-identity check against the real
vis release runs in CI (.github/workflows/vis-verify.yml) where the vis
sibling is checked out; here it runs against a synthetic vis fixture, and
against a real ../vis sibling only when one is present.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "vendor-conduct.py"
PLUGINS = sorted(p for p in (REPO / "plugins").iterdir() if (p / ".claude-plugin" / "plugin.json").is_file())


def run(args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True)


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=t@t.local", "-c", "user.name=t", "-c", "core.autocrlf=false",
                    *args], cwd=cwd, check=True, capture_output=True)


class ManifestShape(unittest.TestCase):
    """plugin.json in the form the pinned CLI (2.1.280) validates and loads.

    Probed with `claude plugin validate` / `install` / `details` in an isolated
    config: `"agents": "./agents/"` (directory string, with or without slash,
    or as an array) is rejected ("agents: Invalid input"); an explicit file
    list validates but `details` then reports Agents (0); omitting the field
    auto-discovers agents/*.md. So: no `agents` key, agents live in agents/.
    """

    def test_no_agents_field(self):
        for p in PLUGINS:
            with self.subTest(plugin=p.name):
                data = json.loads((p / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
                self.assertNotIn("agents", data, "declare no `agents`; the CLI auto-discovers agents/*.md")
                self.assertNotIn("display_name", data, "unknown field; the CLI field is displayName")

    def test_skills_paths_exist(self):
        for p in PLUGINS:
            data = json.loads((p / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
            for s in data.get("skills", []):
                with self.subTest(plugin=p.name, skill=s):
                    self.assertTrue((p / s / "SKILL.md").is_file())

    def test_full_dependencies_are_marketplace_plugins(self):
        mp = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        names = {e["name"] for e in mp["plugins"]}
        full = json.loads((REPO / "plugins" / "full" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertTrue(full["dependencies"])
        self.assertLessEqual(set(full["dependencies"]), names)


class VendoredConductInRepo(unittest.TestCase):
    def test_offline_check_passes(self):
        r = run(["--check", "--offline"], cwd=REPO)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_every_vis_reference_is_plugin_local(self):
        # The independent half: every conduct reference in shipped plugin files
        # is ${CLAUDE_PLUGIN_ROOT}/vendor/<rel> and <rel> exists inside the plugin.
        ref = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/vendor/([A-Za-z0-9._/-]+\.md)")
        seen = 0
        for p in PLUGINS:
            for f in p.rglob("*.md"):
                rel = f.relative_to(p).parts
                if rel[0] in ("vendor", "state"):
                    continue
                text = f.read_text(encoding="utf-8")
                self.assertNotRegex(text, r"\.vis-cache/[A-Za-z0-9._/-]+\.md", f"{f}: repo-root .vis-cache reference")
                for m in ref.finditer(text):
                    seen += 1
                    self.assertTrue((p / "vendor" / m.group(1)).is_file(), f"{f}: {m.group(0)} not vendored")
        self.assertGreater(seen, 0)

    @unittest.skipUnless((REPO.parent / "vis" / ".git").exists(), "no ../vis sibling (CI vis-verify runs this)")
    def test_full_check_against_vis_sibling(self):
        r = run(["--check"], cwd=REPO)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class DriftDetection(unittest.TestCase):
    """A copy of the repo + a synthetic vis release; every drift must fail."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wixie-dist-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "wixie"
        self.vis = self.tmp / "vis"
        self.repo.mkdir()
        for name in (".vis-lock", ".vis-versions"):
            shutil.copy2(REPO / name, self.repo / name)
        shutil.copytree(REPO / "scripts", self.repo / "scripts")
        shutil.copytree(REPO / "shared" / "conduct", self.repo / "shared" / "conduct")
        shutil.copytree(REPO / "plugins", self.repo / "plugins",
                        ignore=shutil.ignore_patterns("state", "__pycache__"))
        # Fixture vis: the referenced vis files (content from the vendored copies)
        # committed and tagged per package, then the copied lock repointed at it.
        self.vis.mkdir()
        git(self.vis, "init", "-q", "-b", "main")
        for f in self.repo.glob("plugins/*/vendor/vis/**/*.md"):
            src = f.as_posix().split("/vendor/vis/", 1)[1]
            dest = self.vis / src
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(f.read_bytes())
        git(self.vis, "add", "-A")
        git(self.vis, "commit", "-q", "-m", "fixture")
        self.sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.vis, capture_output=True,
                                  text=True, check=True).stdout.strip()
        lock = (self.repo / ".vis-lock").read_text(encoding="utf-8")
        for tag in re.findall(r"tag: (\S+)", lock):
            git(self.vis, "tag", "-a", "-m", tag, tag, self.sha)
        (self.repo / ".vis-lock").write_text(re.sub(r"tag_commit: [0-9a-f]{40}", f"tag_commit: {self.sha}", lock),
                                             encoding="utf-8", newline="\n")
        self.args = ["--repo", str(self.repo)]
        self.vis_args = self.args + ["--vis-dir", str(self.vis)]
        r = run(self.vis_args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def check(self, *, offline=False):
        return run(self.args + ["--check", "--offline"] if offline else self.vis_args + ["--check"])

    def assert_both_fail(self, needle):
        for offline in (False, True):
            r = self.check(offline=offline)
            self.assertEqual(r.returncode, 1, f"offline={offline}: {r.stdout}{r.stderr}")
            self.assertIn(needle, r.stderr, f"offline={offline}")

    def vendored(self, rel="plugins/prompt-tester/vendor/vis/packages/core/conduct/tier-sizing.md"):
        return self.repo / rel

    def test_clean_passes_and_regeneration_is_deterministic(self):
        self.assertEqual(self.check().returncode, 0)
        self.assertEqual(self.check(offline=True).returncode, 0)
        before = {p: p.read_bytes() for p in self.repo.glob("plugins/*/vendor/**/*") if p.is_file()}
        self.assertEqual(run(self.vis_args).returncode, 0)
        after = {p: p.read_bytes() for p in self.repo.glob("plugins/*/vendor/**/*") if p.is_file()}
        self.assertEqual(before, after)

    def test_modified_byte(self):
        f = self.vendored()
        f.write_bytes(f.read_bytes() + b" ")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not byte-identical", r.stderr)
        r = self.check(offline=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not match its VENDORED.json hash", r.stderr)

    def test_crlf_conversion_is_drift(self):
        f = self.vendored()
        f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(self.check().returncode, 1)
        self.assertEqual(self.check(offline=True).returncode, 1)

    def test_file_and_manifest_forged_together(self):
        # Offline: the .vis-lock sha1 anchor still catches it.
        f = self.vendored()
        f.write_bytes(b"forged\n")
        m = self.repo / "plugins/prompt-tester/vendor/VENDORED.json"
        doc = json.loads(m.read_text(encoding="utf-8"))
        for e in doc["files"]:
            if e["path"].endswith("tier-sizing.md"):
                e["sha256"] = hashlib.sha256(b"forged\n").hexdigest()
                e["sha1"] = hashlib.sha1(b"forged\n").hexdigest()
        m.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        self.assert_both_fail("tier-sizing.md")
        self.assertIn(".vis-lock sha1", self.check(offline=True).stderr)

    def test_missing_file(self):
        self.vendored().unlink()
        self.assert_both_fail("missing vendored file")

    def test_extra_file(self):
        (self.repo / "plugins/prompt-tester/vendor/vis/packages/core/conduct/extra.md").write_text("x\n")
        self.assert_both_fail("extra file in vendor/")

    def test_unreferenced_vendor_dir(self):
        d = self.repo / "plugins/prompt-harden/vendor"
        d.mkdir()
        (d / "VENDORED.json").write_text("{}\n")
        self.assert_both_fail("extra file in vendor/")

    def test_new_reference_not_vendored(self):
        f = self.repo / "plugins/prompt-harden/agents/new.md"
        f.write_text("Governed by `@${CLAUDE_PLUGIN_ROOT}/vendor/vis/packages/core/conduct/tier-sizing.md`.\n")
        self.assert_both_fail("missing vendored file")

    def test_stale_full_checkout_reference(self):
        f = self.repo / "plugins/prompt-harden/agents/old.md"
        f.write_text("Governed by `@../../../.vis-cache/vis/packages/core/conduct/tier-sizing.md`.\n")
        self.assert_both_fail(".vis-cache")
        f.write_text("Governed by `../vis/packages/core/conduct/tier-sizing.md`.\n")
        self.assert_both_fail("outside ${CLAUDE_PLUGIN_ROOT}/vendor/vis/")
        f.write_text("See `shared/conduct/inference-substrate.md`.\n")
        self.assert_both_fail("outside ${CLAUDE_PLUGIN_ROOT}/vendor/wixie/")

    def test_regeneration_refuses_stale_reference_and_writes_nothing(self):
        before = self.vendored().read_bytes()
        self.vendored().write_bytes(b"to be restored only by a clean regenerate\n")
        (self.repo / "plugins/prompt-harden/agents/old.md").write_text("@../../../.vis-cache/vis/packages/core/conduct/x.md\n")
        r = run(self.vis_args)
        self.assertEqual(r.returncode, 1)
        self.assertIn("nothing was written", r.stderr)
        self.assertNotEqual(self.vendored().read_bytes(), before)

    def test_wixie_local_conduct_drift(self):
        src = self.repo / "shared/conduct/inference-substrate.md"
        src.write_bytes(src.read_bytes() + b"\nnew rule\n")
        self.assert_both_fail("inference-substrate.md")

    def test_moved_tag(self):
        (self.vis / "packages/core/conduct/tier-sizing.md").write_text("changed upstream\n")
        git(self.vis, "commit", "-q", "-am", "retag")
        lock = (self.repo / ".vis-lock").read_text(encoding="utf-8")
        tag = re.search(r"tag: (enchanter-core--\S+)", lock).group(1)
        git(self.vis, "tag", "-f", "-a", "-m", "moved", tag, "HEAD")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("moved tag", r.stderr)

    def test_lock_repinned_without_regenerating(self):
        (self.vis / "packages/core/conduct/tier-sizing.md").write_text("new release content\n")
        git(self.vis, "commit", "-q", "-am", "next")
        new = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.vis, capture_output=True, text=True).stdout.strip()
        lock = (self.repo / ".vis-lock").read_text(encoding="utf-8")
        for tag in re.findall(r"tag: (\S+)", lock):
            git(self.vis, "tag", "-f", "-a", "-m", tag, tag, new)
        (self.repo / ".vis-lock").write_text(lock.replace(self.sha, new), encoding="utf-8", newline="\n")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not byte-identical", r.stderr)
        self.assertEqual(self.check(offline=True).returncode, 1)
        self.assertEqual(run(self.vis_args).returncode, 0)
        self.assertEqual(self.check().returncode, 0)

    def test_missing_vis_is_a_failure_not_a_skip(self):
        r = run(self.args + ["--check", "--vis-dir", str(self.tmp / "nowhere")])
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
