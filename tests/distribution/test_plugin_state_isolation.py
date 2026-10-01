"""WIX-SEC-WS-001 (decision D17): an installed plugin tree is immutable product content.

Mutable runtime state never lives in CLAUDE_PLUGIN_ROOT. Offline (no claude CLI, no model, no
network): each plugin is copied ALONE into an install-shaped cache directory and exercised the
way Claude Code 2.1.280 drives it (hook env CLAUDE_PLUGIN_ROOT / CLAUDE_PLUGIN_DATA /
CLAUDE_PROJECT_DIR; skills and agents hand the substituted ${CLAUDE_PLUGIN_DATA} to scripts as
--plugin-data / --out). Every test hashes the install tree before and after.

  A  SessionStart hook: persists nothing into the install; telemetry only when
     WIXIE_INFERENCE_ENABLED=1, and then only in CLAUDE_PLUGIN_DATA.
  B  inference engine: WIXIE_INFERENCE_STATE > CLAUDE_PLUGIN_DATA/state > checkout; the shipped
     state/ is a read-only seed copied once; legacy residue is neither migrated nor deleted.
  C  efficacy-replay: runs/*.json + verdict.json in a fresh per-run dir under CLAUDE_PLUGIN_DATA
     (or --out), never under vendor/; no __pycache__ in the install.
  D  deep-research / cross-plugin reads: no runtime reference puts state inside the install.
  E  every script step a skill/agent runs from the plugin (converge, create, refine, test, translate,
     harden) runs with bytecode writes disabled: no __pycache__ lands in the install.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import re
import tempfile
import unittest
from pathlib import Path

_root_spec = importlib.util.spec_from_file_location(
    "wixie_test_root", Path(__file__).resolve().parents[1] / "_test_root.py")
_root_mod = importlib.util.module_from_spec(_root_spec)
_root_spec.loader.exec_module(_root_mod)
_root_mod.ensure_test_root()

REPO = Path(__file__).resolve().parents[2]
ENGINE_REL = "vendor/wixie/shared/scripts/inference-engine.py"
EFFICACY_REL = "vendor/wixie/shared/scripts/efficacy-replay.py"
GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")
BASH = str(GIT_BASH) if os.name == "nt" and GIT_BASH.is_file() else "bash"
SCRUB = ("WIXIE_INFERENCE_ENABLED", "WIXIE_INFERENCE_STATE", "WIXIE_INFERENCE_SEED", "CLAUDE_PLUGIN_DATA",
         "CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR", "CLAUDE_SUBAGENT", "CLAUDE_CODE_SESSION_ID",
         "CLAUDE_SESSION_ID", "ANTHROPIC_API_KEY", "PYTHONDONTWRITEBYTECODE")
RECORD = {"code": "F99", "category": "test", "title": "ws-001 isolation probe", "cause": "test",
          "counter": "test", "signal": "test", "tags": ["wixie", "ws001-probe"], "scope": "wixie"}


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def lines(p: Path) -> int:
    return sum(1 for ln in p.read_bytes().splitlines() if ln.strip()) if p.is_file() else 0


class Installed(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wixie-ws001-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.proj = self.tmp / "project"
        self.proj.mkdir()
        self.env = {k: v for k, v in os.environ.items() if k not in SCRUB}
        self.env["WIXIE_EFFICACY_CLAUDE_BIN"] = str(self.tmp / "no-such-claude")

    def install(self, name: str, cfg: str = "cfg") -> Path:
        dest = self.tmp / cfg / "plugins" / "cache" / "wixie" / name / "0.2.0"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(REPO / "plugins" / name, dest, ignore=shutil.ignore_patterns("__pycache__"))
        return dest

    def data(self, name: str, cfg: str = "cfg") -> Path:
        return self.tmp / cfg / "plugins" / "data" / f"{name}-wixie"

    def run_py(self, script: Path, *args, env=None, stdin=None):
        return subprocess.run([sys.executable, str(script), *args], cwd=self.proj, env=env or self.env,
                              input=stdin, capture_output=True, text=True, timeout=600)

    def engine(self, root: Path, data: Path | None, *args, stdin=None, **extra):
        env = {**self.env, **extra}
        pre = ["--plugin-data", str(data)] if data is not None else []
        return self.run_py(root / ENGINE_REL, *pre, *args, env=env, stdin=stdin)

    def assertTreeUnchanged(self, root: Path, before: dict):
        after = tree(root)
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        self.assertEqual(changed, [], f"installed plugin tree changed under {root}")


class SessionStartHook(Installed):
    """A: the SessionStart hook, run as Claude Code runs it (command text + hook env)."""

    def session(self, root: Path, data: Path, **extra):
        hooks = json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        cmd = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        cmd = cmd.replace("${CLAUDE_PLUGIN_ROOT}", root.as_posix())
        data.mkdir(parents=True, exist_ok=True)  # the CLI mkdirs the data dir before the hook runs
        env = {**self.env, "CLAUDE_PLUGIN_ROOT": root.as_posix(), "CLAUDE_PLUGIN_DATA": data.as_posix(),
               "CLAUDE_PROJECT_DIR": self.proj.as_posix(), **extra}
        r = subprocess.run([BASH, "-c", cmd], cwd=self.proj, env=env, capture_output=True, text=True, timeout=120,
                           input=json.dumps({"hook_event_name": "SessionStart", "source": "startup"}))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_gate_off_persists_nothing(self):
        root, data = self.install("inference-engine"), self.data("inference-engine")
        before = tree(root)
        for _ in range(2):
            self.session(root, data)
        self.assertTreeUnchanged(root, before)
        self.assertEqual(list(data.rglob("*")), [], "telemetry persisted while WIXIE_INFERENCE_ENABLED is unset")

    def test_gate_on_writes_only_plugin_data_across_sessions(self):
        root, data = self.install("inference-engine"), self.data("inference-engine")
        before = tree(root)
        for _ in range(3):
            self.session(root, data, WIXIE_INFERENCE_ENABLED="1")
        self.assertTreeUnchanged(root, before)
        self.assertEqual(lines(data / "telemetry" / "model-usage.ndjson"), 3)
        self.assertEqual(sorted(p.relative_to(data).as_posix() for p in data.rglob("*") if p.is_file()),
                         ["telemetry/model-usage.ndjson"])

    def test_script_itself_is_gated_and_reports_the_same_location(self):
        root, data = self.install("inference-engine"), self.data("inference-engine")
        before = tree(root)
        env = {**self.env, "CLAUDE_PLUGIN_DATA": str(data)}
        self.assertEqual(self.run_py(root / "scripts/model-freshness.py", env=env).returncode, 0)
        self.assertFalse(data.exists(), "model-freshness.py persisted with the gate off")
        r = self.run_py(root / "scripts/model-freshness.py", "--plugin-data", str(data),
                        env={**self.env, "WIXIE_INFERENCE_ENABLED": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_py(root / "bin/model-freshness-report.py", "--plugin-data", str(data), "--json")
        self.assertEqual(json.loads(r.stdout)["usage_rows"], 1, r.stdout)
        # Installed copy without any plugin data: nothing is written anywhere.
        r = self.run_py(root / "scripts/model-freshness.py", env={**self.env, "WIXIE_INFERENCE_ENABLED": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTreeUnchanged(root, before)


class InferenceEngineState(Installed):
    """B: engine state precedence, read-only seed, isolation, reinstall and legacy residue."""

    def setUp(self):
        super().setUp()
        self.root = self.install("inference-engine")
        self.pristine = tree(self.root)
        self.seed_lines = lines(self.root / "state" / "artifacts.jsonl")
        self.rec = self.tmp / "rec.json"
        self.rec.write_text(json.dumps(RECORD), encoding="utf-8")

    def emit(self, data, **extra):
        return self.engine(self.root, data, "emit", str(self.rec), WIXIE_INFERENCE_ENABLED="1", **extra)

    def test_every_subcommand_leaves_the_install_untouched(self):
        data = self.data("inference-engine")
        r = self.emit(data)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("seeded", r.stderr)
        for args in (("reconcile",), ("render-briefing", "wixie"), ("query", "F99"), ("status",)):
            r = self.engine(self.root, data, *args, WIXIE_INFERENCE_ENABLED="1")
            self.assertIn(r.returncode, (0, 1), f"{args}: {r.stderr[-400:]}")
        self.assertTreeUnchanged(self.root, self.pristine)
        st = data / "state"
        self.assertEqual(lines(st / "artifacts.jsonl"), self.seed_lines + 1)
        self.assertTrue((st / "catalog.json").is_file() and (st / "briefings" / "wixie.md").is_file())
        seed = json.loads((st / ".seed.json").read_text(encoding="utf-8"))
        self.assertTrue(seed["copied"])
        self.assertEqual(seed["files"]["artifacts.jsonl"], self.pristine["state/artifacts.jsonl"])
        status = json.loads(self.engine(self.root, data, "status").stdout)
        self.assertEqual((Path(status["state_dir"]).resolve(), status["state_source"]),
                         ((st).resolve(), "plugin-data"))

    def test_disabled_and_read_only_use_persist_nothing(self):
        data = self.data("inference-engine")
        self.assertEqual(self.engine(self.root, data, "emit", str(self.rec)).returncode, 0)  # gate off: no-op
        r = self.engine(self.root, data, "status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("unseeded", json.loads(r.stdout)["state_source"])
        self.engine(self.root, data, "query", "F07")
        self.assertFalse(data.exists(), "read-only / gate-off use persisted state")
        self.assertTreeUnchanged(self.root, self.pristine)

    def test_two_data_roots_do_not_contaminate_each_other(self):
        a, b = self.data("inference-engine", "cfgA"), self.data("inference-engine", "cfgB")
        self.assertEqual(self.emit(a).returncode, 0)
        self.assertEqual(self.emit(a).returncode, 0)
        self.assertEqual(self.engine(self.root, b, "render-briefing", "wixie").returncode, 0)
        self.assertEqual(lines(a / "state" / "artifacts.jsonl"), self.seed_lines + 2)
        self.assertEqual(lines(b / "state" / "artifacts.jsonl"), self.seed_lines)
        self.assertTreeUnchanged(self.root, self.pristine)

    def test_reinstall_does_not_define_state_through_cache_residue(self):
        data = self.data("inference-engine")
        self.assertEqual(self.emit(data).returncode, 0)
        self.root = self.install("inference-engine")          # uninstall --keep-data + reinstall
        self.assertEqual(tree(self.root), self.pristine)
        self.assertEqual(self.emit(data).returncode, 0)
        self.assertEqual(lines(data / "state" / "artifacts.jsonl"), self.seed_lines + 2)  # kept data continues
        shutil.rmtree(data)                                     # uninstall deleting data + reinstall
        self.root = self.install("inference-engine")
        self.assertEqual(self.engine(self.root, data, "render-briefing", "wixie").returncode, 0)
        self.assertEqual(lines(data / "state" / "artifacts.jsonl"), self.seed_lines)  # pristine seed again
        self.assertTreeUnchanged(self.root, self.pristine)

    def test_legacy_residue_is_neither_migrated_nor_deleted(self):
        (self.root / "state" / "model-usage.ndjson").write_text('{"legacy": 1}\n', encoding="utf-8")
        (self.root / "state" / ".lock").write_text("", encoding="utf-8")
        legacy = tree(self.root)
        data = self.data("inference-engine")
        r = self.engine(self.root, data, "render-briefing", "wixie")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("NOT seeding", r.stderr)
        self.assertEqual(r.stderr.count("NOT seeding"), 1)
        self.assertTreeUnchanged(self.root, legacy)
        self.assertFalse((data / "state" / "artifacts.jsonl").exists())
        marker = json.loads((data / "state" / ".seed.json").read_text(encoding="utf-8"))
        self.assertFalse(marker["copied"])
        self.assertIn("model-usage.ndjson", marker["residue"])
        r = self.engine(self.root, data, "render-briefing", "wixie")   # decided once, not re-announced
        self.assertNotIn("NOT seeding", r.stderr)

    def test_owner_can_start_empty(self):
        data = self.data("inference-engine")
        self.assertEqual(self.engine(self.root, data, "render-briefing", "wixie", WIXIE_INFERENCE_SEED="0").returncode, 0)
        self.assertFalse((data / "state" / "artifacts.jsonl").exists())
        self.assertTreeUnchanged(self.root, self.pristine)

    def test_precedence_env_var_equals_flag_and_explicit_override_wins(self):
        data = self.data("inference-engine")
        via_env = self.run_py(self.root / ENGINE_REL, "status", env={**self.env, "CLAUDE_PLUGIN_DATA": str(data)})
        via_flag = self.engine(self.root, data, "status")
        self.assertEqual(json.loads(via_env.stdout)["state_source"], json.loads(via_flag.stdout)["state_source"])
        override = self.tmp / "override"
        r = self.engine(self.root, data, "render-briefing", "wixie", WIXIE_INFERENCE_STATE=str(override))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((override / "briefings" / "wixie.md").is_file())
        self.assertFalse((override / "artifacts.jsonl").exists(), "an explicit override is never seeded")
        self.assertFalse(data.exists())
        self.assertTreeUnchanged(self.root, self.pristine)

    def test_installed_copy_without_plugin_data_refuses(self):
        for args in (("status",), ("reconcile",), ("render-briefing", "wixie"), ("query", "F07")):
            r = self.engine(self.root, None, *args)
            self.assertEqual(r.returncode, 2, f"{args}: {r.stdout}{r.stderr}")
            self.assertIn("refused", r.stderr)
        r = self.emit(None)
        self.assertEqual(r.returncode, 2)
        self.assertTreeUnchanged(self.root, self.pristine)

    def test_full_checkout_mode_is_unchanged(self):
        want = (REPO / "plugins" / "inference-engine" / "state").resolve()
        for script in (REPO / "shared/scripts/inference-engine.py", REPO / "plugins/inference-engine" / ENGINE_REL):
            r = self.run_py(script, "status")
            self.assertEqual(r.returncode, 0, r.stderr)
            doc = json.loads(r.stdout)
            self.assertEqual((Path(doc["state_dir"]).resolve(), doc["state_source"]), (want, "checkout"), script)


class EfficacyReplayOutputs(Installed):
    """C: measurements go to CLAUDE_PLUGIN_DATA / --out, per run and per prompt; vendor/ stays pristine."""

    def setUp(self):
        super().setUp()
        self.prompt = self.proj / "prompt.xml"
        self.prompt.write_text("<role>You are a careful engineer.</role>\n<task>Answer.</task>\n", encoding="utf-8")

    def corpus(self, root, *extra, **env):
        return self.run_py(root / EFFICACY_REL, "corpus", "deploy-bar", "--prompt", str(self.prompt), "-n", "1",
                           *extra, env={**self.env, **env})

    def test_installed_runs_write_only_plugin_data(self):
        for name in ("convergence-engine", "prompt-tester"):
            with self.subTest(plugin=name):
                root, data = self.install(name), self.data(name)
                before = tree(root)
                r1 = self.corpus(root, CLAUDE_PLUGIN_DATA=str(data))                  # hook-style env
                r2 = self.corpus(root, "--out", str(data / "efficacy"))               # skill-style --out
                self.assertEqual((r1.returncode, r2.returncode), (3, 3), r1.stderr[-400:] + r2.stderr[-400:])
                self.assertTreeUnchanged(root, before)                                # no runs/, verdict, pycache
                runs = sorted((data / "efficacy" / "corpus" / "deploy-bar").iterdir())
                self.assertEqual(len(runs), 2, "each run needs its own verdict location")
                sha = hashlib.sha256(self.prompt.read_bytes()).hexdigest()
                for run, out in zip(runs, (r1.stdout, r2.stdout)):
                    v = json.loads((run / "verdict.json").read_text(encoding="utf-8"))
                    self.assertEqual((v["prompt_sha256"], v["decision"]["verdict"]), (sha, "NO_MEASUREMENT"))
                    self.assertTrue(list((run / "runs").glob("*.json")))
                printed = {ln.split("full verdict: ", 1)[1].strip() for out in (r1.stdout, r2.stdout)
                           for ln in out.splitlines() if ln.startswith("full verdict: ")}
                self.assertEqual({str(Path(p).resolve()) for p in printed},
                                 {str((run / "verdict.json").resolve()) for run in runs})

    def test_installed_copy_without_output_location_refuses(self):
        root = self.install("prompt-tester")
        before = tree(root)
        r = self.corpus(root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("refused", r.stderr)
        self.assertTreeUnchanged(root, before)

    def test_generated_measurement_still_works_from_the_install(self):
        root, data = self.install("convergence-engine"), self.data("convergence-engine")
        before = tree(root)
        old = sys.dont_write_bytecode
        sys.dont_write_bytecode = True   # as when Claude Code runs the script (`python <script>`)
        self.addCleanup(setattr, sys, "dont_write_bytecode", old)
        spec = importlib.util.spec_from_file_location("ws001_efficacy", root / EFFICACY_REL)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        good = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": (
            "- Recommendation: I recommend option A because skipping caching is invalid.\n"
            "- You should ship behind a flag.\n- The input is empty or invalid, so there is no date to return.\n"
            "1. Risk one: hidden coupling.\n2. Risk two: race conditions.\n")}]}})

        class FakePopen:
            def __init__(self, *a, **k):
                self.returncode, self.pid = 0, 4242

            def communicate(self, timeout=None):
                return good, ""

            def kill(self):
                pass

        mod.subprocess = type("S", (), {**{k: getattr(subprocess, k) for k in dir(subprocess) if not k.startswith("__")},
                                        "Popen": FakePopen})
        v = mod.run_corpus("deploy-bar", self.prompt, n=3, model="fake-model", with_control=False,
                           out_root=data / "efficacy")
        self.assertTrue(v["treatment"]["measurement_valid"], v["treatment"])
        self.assertGreater(v["treatment"]["total"], 0)
        self.assertEqual(Path(v["run_dir"]).parent, data / "efficacy" / "corpus" / "deploy-bar")
        self.assertTrue((Path(v["run_dir"]) / "verdict.json").is_file())
        self.assertTreeUnchanged(root, before)

    def test_full_checkout_default_is_outside_vendor(self):
        want = (REPO / "state" / "efficacy-runs").resolve()
        for script in (REPO / "shared/scripts/efficacy-replay.py", REPO / "plugins/prompt-tester" / EFFICACY_REL):
            r = self.run_py(Path(__file__).resolve(), env={**self.env, "WS001_PROBE": str(script)})
            got = Path(r.stdout.strip()).resolve()
            self.assertEqual(got, want, f"{script}: {r.stderr[-400:]}")
            self.assertNotIn("vendor", got.parts)


class NoStateInsideTheInstall(Installed):
    """D: deep-research briefs / MCP config and the cross-plugin reads target plugin data."""

    def test_runtime_text_never_puts_state_under_the_plugin_root(self):
        found = []
        for p in sorted((REPO / "plugins").iterdir()):
            for f in sorted(p.rglob("*")):
                rel = f.relative_to(p)
                if not f.is_file() or rel.parts[0] in ("vendor", "state") or f.suffix not in (".md", ".json", ".py", ".sh"):
                    continue
                if "${CLAUDE_PLUGIN_ROOT}/state" in f.read_text(encoding="utf-8"):
                    found.append(f"{p.name}/{rel.as_posix()}")
        self.assertEqual(found, [])

    def test_deep_research_store_and_mcp_config_live_in_plugin_data(self):
        dr = REPO / "plugins" / "deep-research"
        for rel in ("skills/deep-research/SKILL.md", "skills/research-query/SKILL.md",
                    "skills/research-refresh/SKILL.md", "skills/research-render/SKILL.md"):
            text = (dr / rel).read_text(encoding="utf-8")
            with self.subTest(file=rel):
                self.assertIn("${CLAUDE_PLUGIN_DATA}/briefs/", text)
                self.assertNotRegex(text, r"(?<![\w}/])`?state/briefs/(<slug>|\*)")
        mcp = (dr / "agents" / "mcp-fetcher.md").read_text(encoding="utf-8")
        self.assertIn("<data_dir>/mcp-config.json", mcp)
        self.assertIn("<data_dir>/mcp-manifests/", mcp)
        self.assertIn("data_dir=${CLAUDE_PLUGIN_DATA}", (dr / "skills/deep-research/SKILL.md").read_text(encoding="utf-8"))

    def test_deep_research_scripts_do_not_write_the_install(self):
        root = self.install("deep-research")
        before = tree(root)
        r = self.run_py(root / "vendor/wixie/shared/scripts/fetcher-normalize.py", "--sq", "SQ1", stdin="[]")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTreeUnchanged(root, before)


PY_CMD = re.compile(r"(PYTHONDONTWRITEBYTECODE=1\s+)?\bpython3?((?:\s+-[A-Za-z]+)*)\s+\\?[\"']?"
                    r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9._/-]+\.py)")


def runtime_texts(plugin: Path):
    for f in sorted(plugin.rglob("*")):
        rel = f.relative_to(plugin)
        if f.is_file() and rel.parts[0] not in ("vendor", "state") and f.suffix in (".md", ".json", ".sh"):
            yield rel.as_posix(), f.read_text(encoding="utf-8")


def script_commands(plugin: Path) -> dict:
    """{script: guarded} from the plugin's own command text; guarded only if EVERY site is guarded."""
    out: dict = {}
    for _rel, text in runtime_texts(plugin):
        for m in PY_CMD.finditer(text):
            guarded = bool(m.group(1)) or any("B" in f for f in m.group(2).split())
            out[m.group(3)] = out.get(m.group(3), True) and guarded
    return out


class ScriptStepsFromInstall(Installed):
    """E: run the script steps of converge/create/refine/test/translate/harden from the install, with the
    interpreter flags the skill/agent text uses; the install tree must stay byte-identical."""

    PLUGINS = ("convergence-engine", "prompt-crafter", "prompt-refiner", "prompt-tester",
               "prompt-translate", "prompt-harden")

    def test_every_plugin_python_command_disables_bytecode(self):
        bad = []
        for p in sorted((REPO / "plugins").iterdir()):
            for rel, text in runtime_texts(p):
                for m in PY_CMD.finditer(text):
                    if not m.group(1) and not any("B" in f for f in m.group(2).split()):
                        bad.append(f"{p.name}/{rel}: {m.group(0)}")
        self.assertEqual(bad, [])

    def test_script_steps_leave_the_install_byte_identical(self):
        prompt = self.proj / "prompts" / "demo" / "prompt.xml"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("<role>You are a support triage engineer.</role>\n<task>Classify the report.</task>\n"
                          "<constraints>- Output lowercase.</constraints>\n<output_format>JSON</output_format>\n",
                          encoding="utf-8")
        (self.proj / "empty-folder").mkdir()
        args = {
            "self-eval.py": [str(prompt)],
            "deploy_bar.py": [str(prompt)],                        # read-only verdict CLI
            "token-count.py": [str(prompt), "--model", "claude-opus-4-7"],
            "convergence.py": [str(prompt), "--max", "2"],
            "report-gen.py": [str(self.proj / "empty-folder")],   # usage exit before any rendering
            "prompt_regions.py": ["check", str(prompt)],
            "efficacy-replay.py": ["corpus", "deploy-bar", "--prompt", str(prompt), "-n", "1",
                                   "--out", str(self.tmp / "data" / "efficacy")],
        }
        ran = []
        for name in self.PLUGINS:
            root = self.install(name)
            before = tree(root)
            cmds = script_commands(root)
            for rel, guarded in sorted(cmds.items()):
                script = Path(rel).name
                self.assertIn(script, args, f"{name}: no probe arguments for {rel}")
                flags = ["-B"] if guarded else []
                r = subprocess.run([sys.executable, *flags, str(root / rel), *args[script]], cwd=self.proj,
                                   env=self.env, capture_output=True, text=True, timeout=600)
                self.assertNotRegex(r.stdout + r.stderr, r"Traceback|No module named|can't open file",
                                    f"{name} {rel}: {(r.stdout + r.stderr)[-600:]}")
                ran.append(f"{name}:{script}")
            with self.subTest(plugin=name):
                self.assertTreeUnchanged(root, before)
        for must in ("convergence-engine:convergence.py", "prompt-crafter:self-eval.py", "prompt-refiner:token-count.py",
                     "prompt-tester:efficacy-replay.py", "prompt-translate:self-eval.py", "prompt-harden:prompt_regions.py"):
            self.assertIn(must, ran)


if __name__ == "__main__":
    probe = os.environ.get("WS001_PROBE")
    if probe:   # helper for test_full_checkout_default_is_outside_vendor: print the resolved output root
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("ws001_probe", probe)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        print(m.resolve_out_root()[0])
        sys.exit(0)
    unittest.main()
