"""WIX-DIST-002: an installed plugin must carry the runtime dependency closure of what it advertises.

An install copies only plugins/<p>/. These tests check, without the claude CLI and
without model calls, that:
  - no shipped runtime reference in a skill, agent, hook or plugin script leaves the
    plugin (except the two declared cross-plugin optional state reads);
  - every script a skill/agent runs, and everything those scripts load, is vendored;
  - the vendored scripts actually run from a plugin copied alone (install layout);
  - the repo-level contract reaches plugins only as exact CLAUDE.md sections;
  - scripts/vendor-conduct.py --check fails on every drift class (mutation cases,
    against a synthetic vis release built by the WIX-DIST-001 fixture).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Private temp root (WIX-TEST-ENV-001, tests/_test_root.py): scratch never lands in shared temp.
_root_spec = importlib.util.spec_from_file_location(
    "wixie_test_root", Path(__file__).resolve().parents[1] / "_test_root.py")
_root_mod = importlib.util.module_from_spec(_root_spec)
_root_spec.loader.exec_module(_root_mod)
_root_mod.ensure_test_root()

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_plugin_distribution as _dist  # noqa: E402  (module import: do not re-collect its TestCases)

PLUGINS, REPO, git, run = _dist.PLUGINS, _dist.REPO, _dist.git, _dist.run

ESCAPE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/\.\.[^\s)`\"'\]|,;]*")
CWD_WIXIE = re.compile(r"(?<![A-Za-z0-9_./-])wixie/(?:shared|plugins)/")
PY_RUN = re.compile(r"python3?\s+\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9._/-]+\.py)")
VENDOR_REF = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/vendor/([A-Za-z0-9._/-]+\.[A-Za-z0-9]+)")
DECLARED_OPTIONAL = {
    ("convergence-engine", "skills/converge/SKILL.md"): "${CLAUDE_PLUGIN_ROOT}/../inference-engine/state/briefings/wixie.md",
    ("prompt-crafter", "skills/prompt-creator/SKILL.md"): "${CLAUDE_PLUGIN_ROOT}/../../plugins/deep-research/state/briefs/<slug>/claims.json",
}


def runtime_files(p: Path):
    for f in sorted(p.rglob("*")):
        rel = f.relative_to(p)
        if not f.is_file() or rel.parts[0] in ("vendor", "state") or f.name == "README.md" or "__pycache__" in rel.parts:
            continue
        if f.suffix in (".md", ".json", ".py", ".sh"):
            yield f, rel.as_posix()


class RuntimeClosureInRepo(unittest.TestCase):
    def test_no_runtime_reference_leaves_the_plugin(self):
        for p in PLUGINS:
            for f, rel in runtime_files(p):
                text = f.read_text(encoding="utf-8")
                with self.subTest(file=f"{p.name}/{rel}"):
                    escapes = [m.group(0) for m in ESCAPE.finditer(text)]
                    allowed = DECLARED_OPTIONAL.get((p.name, rel))
                    self.assertEqual([e for e in escapes if e != allowed], [], "path leaves the installed plugin")
                    self.assertIsNone(CWD_WIXIE.search(text), "cwd-relative path into a Wixie checkout")
                    for m in VENDOR_REF.finditer(text):
                        self.assertTrue((p / "vendor" / m.group(1)).is_file(), m.group(0))

    def test_every_script_a_skill_or_agent_runs_ships_in_the_plugin(self):
        seen = 0
        for p in PLUGINS:
            for f, rel in runtime_files(p):
                for m in PY_RUN.finditer(f.read_text(encoding="utf-8")):
                    seen += 1
                    with self.subTest(file=f"{p.name}/{rel}", script=m.group(1)):
                        self.assertTrue((p / m.group(1)).is_file())
        self.assertGreater(seen, 30)

    def test_transitive_dependencies_are_vendored(self):
        v = REPO / "plugins" / "convergence-engine" / "vendor" / "wixie" / "shared"
        for rel in ("scripts/convergence.py", "scripts/self-eval.py",       # convergence.py loads self-eval.py
                    "scripts/report-gen.py", "scripts/html-to-pdf.py",       # report-gen.py runs html-to-pdf.py
                    "scripts/token-count.py", "models-registry.json",        # SCRIPT_DIR/../models-registry.json
                    "eval-corpus/deploy-bar/corpus.json"):                   # efficacy-replay.py corpus deploy-bar
            self.assertTrue((v / rel).is_file(), rel)
        self.assertTrue((REPO / "plugins/prompt-tester/vendor/wixie/shared/eval-corpus/deploy-bar/corpus.json").is_file())
        self.assertTrue((REPO / "plugins/inference-engine/vendor/wixie/shared/models-registry.json").is_file())

    def test_manifest_records_provenance_and_consumers(self):
        for m in sorted(REPO.glob("plugins/*/vendor/VENDORED.json")):
            doc = json.loads(m.read_text(encoding="utf-8"))
            self.assertEqual(doc["schema"], "wixie/vendored-closure/v2")
            for e in doc["files"]:
                with self.subTest(manifest=m.parent.parent.name, file=e.get("path")):
                    for k in ("destination", "source", "source_path", "source_revision", "sha256", "sha1"):
                        self.assertTrue(e.get(k), k)
                    self.assertEqual(e["destination"], "vendor/" + e["path"])
                    self.assertTrue(e["consumers"])

    def test_contract_is_delivered_as_exact_claude_md_sections(self):
        claude = (REPO / "CLAUDE.md").read_bytes()
        found = 0
        for f in sorted(REPO.glob("plugins/*/vendor/wixie/claude-md.*.md")):
            found += 1
            b = f.read_bytes()
            self.assertTrue(b.startswith(b"## "), f)
            self.assertIn(b, claude, f"{f} is not a byte-exact CLAUDE.md section")
        self.assertGreater(found, 0)
        self.assertEqual(list(REPO.glob("plugins/*/**/CLAUDE.md")), [], "never ship CLAUDE.md wholesale")


class InstallLayoutRuntime(unittest.TestCase):
    """Copy a plugin ALONE (like an installed cache/<mkt>/<plugin>/<version>) and run its scripts there."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wixie-dist2-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.proj = self.tmp / "project"
        (self.proj / "prompts" / "demo").mkdir(parents=True)
        (self.proj / "prompts" / "demo" / "prompt.xml").write_text(
            "<role>You are a support triage engineer.</role>\n<task>Classify the bug report into one category.</task>\n"
            "<constraints>- Output lowercase.</constraints>\n<output_format>JSON</output_format>\n", encoding="utf-8")
        self.env = {**os.environ, "WIXIE_EFFICACY_CLAUDE_BIN": str(self.tmp / "no-such-claude")}
        self.env.pop("WIXIE_INFERENCE_STATE", None)

    def install(self, name):
        dest = self.tmp / "cache" / "wixie" / name / "0.1.0"
        shutil.copytree(REPO / "plugins" / name, dest, ignore=shutil.ignore_patterns("__pycache__"))
        return dest

    def py(self, root, script, *args):
        return subprocess.run([sys.executable, str(root / "vendor/wixie/shared/scripts" / script), *args],
                              cwd=self.proj, env=self.env, capture_output=True, text=True, timeout=300)

    def assert_ran(self, r, ok=(0, 1)):
        blob = r.stdout + r.stderr
        self.assertNotRegex(blob, r"can't open file|No such file|registry not found|not in registry|No module named", blob[-800:])
        self.assertIn(r.returncode, ok, blob[-800:])

    def test_convergence_engine_scripts_run_from_install_layout(self):
        root = self.install("convergence-engine")
        prompt = str(self.proj / "prompts/demo/prompt.xml")
        self.assert_ran(self.py(root, "self-eval.py", prompt))
        r = self.py(root, "token-count.py", prompt, "--model", "claude-opus-4-7")
        self.assert_ran(r, ok=(0,))
        self.assertIn("claude-opus-4-7", r.stdout)
        self.assert_ran(self.py(root, "convergence.py", prompt, "--max", "3"))
        # WIX-SEC-WS-001: Claude Code gives the plugin a data dir; measurements are written there.
        self.env["CLAUDE_PLUGIN_DATA"] = str(self.tmp / "data" / "convergence-engine-wixie")
        r = self.py(root, "efficacy-replay.py", "corpus", "deploy-bar", "--prompt", prompt, "-n", "1")
        self.assertNotIn("no corpus at", r.stderr)
        self.assertEqual(r.returncode, 3, r.stderr[-600:])  # NO_MEASUREMENT: the CLI override does not exist

    def test_inference_engine_runs_from_install_layout_with_plugin_data(self):
        # C6: replaces test_inference_engine_uses_its_own_state_when_installed, which pinned the
        # WIX-DIST-002 choice <plugin>/state. Decision D17 (2026-09-27, WIX-SEC-WS-001) supersedes it:
        # the installed tree is immutable product content; runtime state lives in CLAUDE_PLUGIN_DATA.
        root = self.install("inference-engine")
        data = self.tmp / "data" / "inference-engine-wixie"
        r = self.py(root, "inference-engine.py", "--plugin-data", str(data), "render-briefing", "wixie")
        self.assert_ran(r, ok=(0,))
        r = self.py(root, "inference-engine.py", "--plugin-data", str(data), "status")
        self.assert_ran(r, ok=(0,))
        self.assertEqual(Path(json.loads(r.stdout)["state_dir"]).resolve(), (data / "state").resolve())
        r = subprocess.run([sys.executable, str(root / "scripts/model-freshness.py"), "--print", "--dry-run"],
                           cwd=self.proj, env=self.env, capture_output=True, text=True, timeout=120)
        self.assert_ran(r, ok=(0,))
        self.assertIn("models_in_registry", r.stdout)


def _fixture(cls):
    """Reuse the WIX-DIST-001 synthetic-vis fixture (repo copy + tagged vis) for mutation cases."""
    for name in ("setUp", "check", "assert_both_fail"):
        setattr(cls, name, getattr(_dist.DriftDetection, name))
    return cls


@_fixture
class ClosureDrift(unittest.TestCase):
    def write(self, rel, text, mode="a"):
        f = self.repo / rel
        with open(f, mode, encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def test_path_escaping_the_plugin(self):
        self.write("plugins/prompt-harden/agents/red-team.md",
                   "\nRun python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/self-eval.py x\n")
        self.assert_both_fail("external unresolved path ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/self-eval.py")

    def test_cwd_relative_checkout_path(self):
        self.write("plugins/prompt-harden/agents/red-team.md", "\npython wixie/shared/scripts/self-eval.py x\n")
        self.assert_both_fail("cwd-relative path into a Wixie checkout")

    def test_plugin_path_that_does_not_exist(self):
        self.write("plugins/prompt-harden/agents/red-team.md", "\npython ${CLAUDE_PLUGIN_ROOT}/scripts/nope.py\n")
        self.assert_both_fail("does not exist in the plugin")

    def test_missing_transitive_dependency(self):
        (self.repo / "plugins/convergence-engine/vendor/wixie/shared/scripts/html-to-pdf.py").unlink()
        self.assert_both_fail("missing vendored file: vendor/wixie/shared/scripts/html-to-pdf.py")

    def test_reference_to_a_source_that_does_not_exist(self):
        self.write("plugins/prompt-harden/agents/red-team.md",
                   "\npython ${CLAUDE_PLUGIN_ROOT}/vendor/wixie/shared/scripts/nope.py\n")
        self.assert_both_fail("missing dependency wixie:shared/scripts/nope.py")

    def test_unexpected_dependency(self):
        extra = self.repo / "plugins/prompt-harden/vendor/wixie/shared/scripts/extra.py"
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("print(1)\n")
        self.assert_both_fail("extra file in vendor/: wixie/shared/scripts/extra.py")

    def test_hash_drift_in_vendored_script(self):
        f = self.repo / "plugins/prompt-translate/vendor/wixie/shared/scripts/self-eval.py"
        f.write_bytes(f.read_bytes() + b"# tampered\n")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not byte-identical", r.stderr)
        r = self.check(offline=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not match its VENDORED.json hash", r.stderr)

    def test_source_changed_without_regenerating_is_stale(self):
        self.write("shared/scripts/self-eval.py", "\n# new rule\n")
        self.assert_both_fail("self-eval.py")
        self.assertIn("source changed; regenerate", self.check(offline=True).stderr)
        self.assertEqual(run(self.vis_args).returncode, 0)
        self.assertEqual(self.check().returncode, 0)

    def test_new_import_grows_the_closure_one_command(self):
        # e.g. a new helper module shared/scripts/new_helper.py imported by convergence.py
        (self.repo / "shared/scripts/new_helper.py").write_text("HELPER = 1\n", encoding="utf-8", newline="\n")
        src = self.repo / "shared/scripts/convergence.py"
        src.write_bytes(src.read_bytes().replace(b"import sys, os, re", b"import new_helper\nimport sys, os, re", 1))
        self.assert_both_fail("missing vendored file: vendor/wixie/shared/scripts/new_helper.py")
        self.assertEqual(run(self.vis_args).returncode, 0)
        self.assertEqual(self.check().returncode, 0)
        self.assertEqual(self.check(offline=True).returncode, 0)
        for p in ("convergence-engine", "prompt-crafter", "prompt-refiner"):
            self.assertTrue((self.repo / f"plugins/{p}/vendor/wixie/shared/scripts/new_helper.py").is_file(), p)

    def test_duplicate_destination_in_manifest(self):
        m = self.repo / "plugins/prompt-translate/vendor/VENDORED.json"
        doc = json.loads(m.read_text(encoding="utf-8"))
        dup = dict(doc["files"][0])
        dup["sha256"] = "0" * 64
        doc["files"].append(dup)
        m.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        r = self.check(offline=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("duplicate conflicting destination", r.stderr)
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("differs from the regenerated manifest", r.stderr)

    def test_duplicate_destination_case_insensitive(self):
        # Two pinned sources that collide on a case-insensitive install (Windows/macOS).
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=self.vis, input=b"variant\n",
                              capture_output=True, check=True).stdout.decode().strip()
        git(self.vis, "update-index", "--add", "--cacheinfo", f"100644,{blob},packages/core/conduct/Tier-Sizing.md")
        git(self.vis, "commit", "-q", "-m", "case variant")
        new = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.vis, capture_output=True, text=True).stdout.strip()
        lock = (self.repo / ".vis-lock").read_text(encoding="utf-8")
        for tag in re.findall(r"tag: (\S+)", lock):
            git(self.vis, "tag", "-f", "-a", "-m", tag, tag, new)
        (self.repo / ".vis-lock").write_text(lock.replace(self.sha, new), encoding="utf-8", newline="\n")
        self.write("plugins/prompt-tester/agents/executor.md",
                   "\nAlso `@${CLAUDE_PLUGIN_ROOT}/vendor/vis/packages/core/conduct/Tier-Sizing.md`.\n")
        r = run(self.vis_args)
        self.assertEqual(r.returncode, 1)
        self.assertIn("duplicate conflicting destination", r.stderr)
        self.assertIn("nothing was written", r.stderr)

    def test_stale_cross_plugin_exemption(self):
        f = self.repo / "plugins/convergence-engine/skills/converge/SKILL.md"
        f.write_text(f.read_text(encoding="utf-8").replace(
            "${CLAUDE_PLUGIN_ROOT}/../inference-engine/state/briefings/wixie.md", "state/briefings/wixie.md"),
            encoding="utf-8", newline="\n")
        self.assert_both_fail("stale CROSS_PLUGIN_OPTIONAL entry")

    def test_contract_section_drift(self):
        f = self.repo / "CLAUDE.md"
        f.write_bytes(f.read_bytes().replace(b"| DEPLOY | ", b"| DEPLOY (edited) | ", 1))
        self.assert_both_fail("claude-md.deploy-bar.md")
        self.assertEqual(run(self.vis_args).returncode, 0)
        self.assertEqual(self.check().returncode, 0)


if __name__ == "__main__":
    unittest.main()
