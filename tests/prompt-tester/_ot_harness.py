"""Offline harness for output-test.py tests (no model, no network, no key, no claude CLI).

Two ways to drive output-test.py:
  * in process: load_ot(tree) + StubClient, calling ot.run(...) directly;
  * as the real CLI: run_cli(tree, folder, scenario, args), which puts a fake `anthropic`
    module first on PYTHONPATH so the real __main__ path (and its exit code) runs.

`script_tree(minimal=True)` copies output-test.py, prompt_regions.py and models-registry.json
into a private directory under WIXIE_TEST_ROOT. The optional heuristic sub-engines
(output-eval, output-schema, output-sim, self-eval, self-check-inject, convergence) are absent
there, so the only score axis is the tests.json assertion rate and verdicts are exact.
`script_tree(minimal=False)` is the repository's shared/scripts itself (all engines).
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent


def setup(repo):
    """Private temp root (WIX-TEST-ENV-001), no model binary, no key. Returns the root Path."""
    spec = importlib.util.spec_from_file_location("wixie_test_root", Path(repo) / "tests" / "_test_root.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    root = mod.ensure_test_root()
    os.environ["WIXIE_EFFICACY_CLAUDE_BIN"] = "/nonexistent/claude"
    for k in ("ANTHROPIC_API_KEY", "WIXIE_EVALUATOR_MODEL", "WIXIE_FIXER_MODEL"):
        os.environ.pop(k, None)
    return root


def scratch(root, prefix):
    return Path(tempfile.mkdtemp(prefix=prefix, dir=Path(root) / "tmp"))


def script_tree(repo, root, minimal=True):
    repo = Path(repo)
    if not minimal:
        return repo
    dest = scratch(root, "ot-tree-")
    (dest / "shared" / "scripts").mkdir(parents=True)
    for name in ("output-test.py", "prompt_regions.py"):
        shutil.copy2(repo / "shared" / "scripts" / name, dest / "shared" / "scripts" / name)
    shutil.copy2(repo / "shared" / "models-registry.json", dest / "shared" / "models-registry.json")
    return dest


def load_ot(tree, name="output_test_uut"):
    path = Path(tree) / "shared" / "scripts" / "output-test.py"
    sys.modules.pop("prompt_regions", None)      # bind the tree's own prompt_regions
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(mod)
    mod.try_offline_fix = lambda p, s, d, **kw: (p, False, None)   # LLM path only
    return mod


def role_of(user_text):
    if user_text.startswith("You are evaluating the output"):
        return "evaluator"
    if user_text.startswith("You are a prompt engineer fixing"):
        return "fixer"
    return "target"


class StubClient:
    """Scripted replies per role. An item is a text, (text, usage) or an Exception to raise.
    usage=(in, out) builds a usage object; None means the provider reported no usage."""

    def __init__(self, target=(), evaluator=(), fixer=(), usage=(100, 200)):
        self.q = {"target": list(target), "evaluator": list(evaluator), "fixer": list(fixer)}
        self.usage = usage
        self.log = []
        self.requests = []
        self.messages = self

    def create(self, **kw):
        role = role_of(kw["messages"][0]["content"])
        self.log.append(role)
        self.requests.append((role, kw))
        item = self.q[role].pop(0)
        if isinstance(item, BaseException):
            raise item
        text, usage = item if isinstance(item, tuple) else (item, self.usage)
        u = None if usage is None else SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1])
        return SimpleNamespace(content=[SimpleNamespace(text=text)], model=kw["model"], usage=u,
                               stop_reason="end_turn")


PROMPT = """<role>You are a release-notes writer for the Acme CLI.</role>
<task>Write release notes for version 2.4.0 covering the three changes in context.</task>
<context>1. added --json to acme status; 2. fixed a crash in acme sync; 3. removed acme legacy.</context>
<output_format>## Summary, ## Changes, ## Upgrade notes</output_format>
<constraints>Name every command. Under 300 words.</constraints>
<success_criteria>
1. Mentions the --json flag.
2. Mentions the acme sync crash fix.
3. Mentions removal of acme legacy.
</success_criteria>
"""

TESTS = [
    {"name": "json-flag", "expected_contains": ["--json"]},
    {"name": "sync-fix", "expected_contains": ["acme sync"]},
    {"name": "legacy-removed", "expected_contains": ["acme legacy"], "tags": ["edge-case"]},
]

# 3/3 assertions -> 10.0 PASS; 2/3 -> 6.7 MARGINAL (minimal tree: assertions are the only axis).
GOOD_OUTPUT = ("## Summary\nAcme CLI 2.4.0.\n## Changes\n- acme status gains --json.\n"
               "- acme sync no longer crashes.\n## Upgrade notes\nacme legacy was removed.\n")
MARGINAL_OUTPUT = ("## Summary\nAcme CLI 2.4.0.\n## Changes\n- acme status gains --json.\n"
                   "- acme sync no longer crashes.\n## Upgrade notes\nNothing else changed.\n")


def fence(obj):
    return "```json\n" + json.dumps(obj) + "\n```"


EVAL_FAIL = fence({"criteria": [{"id": 3, "verdict": "FAIL", "reason": "legacy removal missing",
                                 "fix": "require it"}],
                   "overall": "FAIL", "weakest_area": "3", "top_fix": "require it",
                   "output_quality_score": 5})
FIX_OK = fence({"target": "zzz-not-in-prompt", "replacement": "q", "reason": "r"})


def make_folder(root, name, prompt=PROMPT, tests=TESTS, meta=None):
    d = scratch(root, name + "-")
    (d / "prompt.xml").write_text(prompt, encoding="utf-8", newline="\n")
    (d / "metadata.json").write_text(json.dumps(meta or {"target_model": "claude-opus-4-6"}),
                                     encoding="utf-8")
    (d / "tests.json").write_text(json.dumps(tests), encoding="utf-8")
    return d


def run_in_process(ot, folder, client, **kw):
    """Returns (return value, exception or None, stdout+stderr)."""
    kw.setdefault("skip_preflight", True)
    out = io.StringIO()
    exc = None
    res = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            res = ot.run(str(folder), client=client, **kw)
        except BaseException as e:   # noqa: BLE001 - the test inspects what escapes run()
            exc = e
    return res, exc, out.getvalue()


def results(folder):
    p = Path(folder) / "output-test-results.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


FAKE_ANTHROPIC = '''\
import json, os
from types import SimpleNamespace as NS

def _role(t):
    if t.startswith("You are evaluating the output"):
        return "evaluator"
    if t.startswith("You are a prompt engineer fixing"):
        return "fixer"
    return "target"

class _Messages:
    def __init__(self):
        with open(os.environ["WIXIE_OT_FAKE_SCENARIO"], encoding="utf-8") as f:
            self.s = json.load(f)
        self.q = {k: list(self.s.get(k, [])) for k in ("target", "evaluator", "fixer")}
    def create(self, **kw):
        role = _role(kw["messages"][0]["content"])
        with open(os.environ["WIXIE_OT_FAKE_SCENARIO"] + ".log", "a", encoding="utf-8") as f:
            f.write(role + "\\n")
        u = self.s.get("usage", [100, 200])
        return NS(content=[NS(text=self.q[role].pop(0))], model=kw["model"], stop_reason="end_turn",
                  usage=None if u is None else NS(input_tokens=u[0], output_tokens=u[1]))

class Anthropic:
    def __init__(self, api_key=None):
        self.messages = _Messages()
'''


def run_cli(root, tree, folder, scenario, args=()):
    """Run the real CLI with a fake `anthropic` module. Returns (exit code, output, roles called)."""
    fake = scratch(root, "fake-sdk-")
    (fake / "anthropic").mkdir()
    (fake / "anthropic" / "__init__.py").write_text(FAKE_ANTHROPIC, encoding="utf-8")
    scen = fake / "scenario.json"
    scen.write_text(json.dumps(scenario), encoding="utf-8")
    env = dict(os.environ)
    env.update({"PYTHONPATH": str(fake), "WIXIE_OT_FAKE_SCENARIO": str(scen),
                "ANTHROPIC_API_KEY": "stub-not-a-real-key-000", "PYTHONIOENCODING": "utf-8"})
    p = subprocess.run([sys.executable, str(Path(tree) / "shared" / "scripts" / "output-test.py"),
                        str(folder), "--skip-preflight"] + list(args),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, timeout=300)
    log = Path(str(scen) + ".log")
    roles = log.read_text(encoding="utf-8").split() if log.is_file() else []
    return p.returncode, p.stdout + p.stderr, roles
