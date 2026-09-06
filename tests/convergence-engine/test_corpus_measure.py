#!/usr/bin/env python3
"""
Offline test for efficacy-replay.py `corpus` mode — the measured DEPLOY bar.

MOCKS THE MODEL CALL: monkeypatches the module's `subprocess.run` so NO real
`claude -p` invocation, NO tokens, and NO network are required. This exercises the
full real path otherwise: parse_stream_json -> classify_corpus -> wilson_ci ->
accept_predicate -> exit-code decision. Runs hermetically against a temp corpus dir
so the repo's shared/eval-corpus/ is never written to.

Usage: python test_corpus_measure.py <REPO_ROOT>   (exit 0 = pass)
"""
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


def load_module(repo_root: Path):
    path = repo_root / "shared" / "scripts" / "efficacy-replay.py"
    spec = importlib.util.spec_from_file_location("efficacy_replay", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def stream_json_for(text: str) -> str:
    """Emit a single-line assistant event as `claude -p --output-format stream-json` would."""
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})


GOOD_RESPONSE = (
    "- Recommendation: I recommend option A because skipping caching is invalid.\n"
    "- You should ship behind a flag.\n"
    "- The input is empty or invalid, so there is no date to return.\n"
    "1. Risk one: hidden coupling.\n"
    "2. Risk two: race conditions.\n"
)

BAD_RESPONSE = "As an AI, it depends. I'm not sure. The date is 2024-01-01."


def fake_run_factory(response_text: str):
    def fake_run(cmd, *args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=stream_json_for(response_text), stderr="")
    return fake_run


def make_temp_corpus(tmp: Path) -> Path:
    """Copy the deploy-bar case shape into a temp corpus so the real dir stays clean."""
    cdir = tmp / "deploy-bar"
    cdir.mkdir(parents=True)
    corpus = {
        "name": "deploy-bar",
        "control_system": "You are a helpful assistant.",
        "accept": {"rate_floor": 0.75},
        "cases": [
            {"id": "structure", "input": "Compare approaches and recommend one.",
             "expect_patterns": ["(^|\\n)\\s*(-|\\d+[.)])", "(recommend|should)"],
             "reject_patterns": ["\\bas an AI\\b"]},
            {"id": "decisive", "input": "Flag or wait?",
             "expect_patterns": ["\\b(flag|wait|ship)\\b"],
             "reject_patterns": ["\\bI'?m not sure\\b"]},
            {"id": "edge", "input": "Parse '' into a date.",
             "expect_patterns": ["(empty|invalid)"],
             "reject_patterns": ["\\b2\\d{3}-\\d{2}-\\d{2}\\b"]},
        ],
    }
    (cdir / "corpus.json").write_text(json.dumps(corpus), encoding="utf-8")
    return cdir


def run_with_response(mod, tmp: Path, prompt_path: Path, response: str, with_control: bool):
    mod.subprocess.run = fake_run_factory(response)
    # n high enough that a 100%-pass arm's Wilson lower bound clears the 0.75 floor
    # (few trials => wide CI => honest REJECT even at rate 1.0).
    return mod.run_corpus("deploy-bar", prompt_path, n=10, model="fake-model", with_control=with_control)


def main() -> int:
    repo_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(".").resolve()
    mod = load_module(repo_root)

    # --- unit: wilson_ci sanity ---
    lo, hi = mod.wilson_ci(10, 10)
    assert 0.0 <= lo <= hi <= 1.0 and lo > 0.6, f"wilson_ci(10,10) lower bound too low: {lo}"
    assert mod.wilson_ci(0, 0) == (0.0, 0.0)

    # --- unit: classify_corpus ---
    good_trace = [{"role": "assistant", "content": [{"type": "text", "text": "- I recommend flag."}]}]
    case = {"expect_patterns": ["recommend"], "reject_patterns": ["as an AI"]}
    assert mod.classify_corpus(good_trace, case)["score"] == "PASS"
    bad_trace = [{"role": "assistant", "content": [{"type": "text", "text": "As an AI I can't."}]}]
    assert mod.classify_corpus(bad_trace, case)["score"] == "FAIL"

    # --- unit: accept_predicate ---
    strong = {"ci_95_low": 0.8, "ci_95_high": 0.95}
    weak = {"ci_95_low": 0.2, "ci_95_high": 0.5}
    assert mod.accept_predicate(strong, None, 0.75)["verdict"] == "ACCEPT"
    assert mod.accept_predicate(weak, None, 0.75)["verdict"] == "REJECT"
    # measured lift: strong treatment over weak control accepts; over strong control rejects
    assert mod.accept_predicate(strong, weak, 0.75)["verdict"] == "ACCEPT"
    assert mod.accept_predicate(strong, strong, 0.75)["verdict"] == "REJECT"

    # --- integration (mocked model): ACCEPT path ---
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        mod.CORPUS_ROOT = tmp
        make_temp_corpus(tmp)
        prompt = tmp / "prompt.xml"
        prompt.write_text("<role>disciplined engineer</role>", encoding="utf-8")

        v_good = run_with_response(mod, tmp, prompt, GOOD_RESPONSE, with_control=False)
        assert v_good["treatment"]["rate"] == 1.0, f"expected rate 1.0, got {v_good['treatment']['rate']}"
        assert v_good["decision"]["verdict"] == "ACCEPT", v_good["decision"]

        v_bad = run_with_response(mod, tmp, prompt, BAD_RESPONSE, with_control=False)
        assert v_bad["treatment"]["rate"] == 0.0, f"expected rate 0.0, got {v_bad['treatment']['rate']}"
        assert v_bad["decision"]["verdict"] == "REJECT", v_bad["decision"]

    # --- the real shipped corpus parses and every regex compiles ---
    real = json.loads((repo_root / "shared" / "eval-corpus" / "deploy-bar" / "corpus.json").read_text(encoding="utf-8"))
    assert real["cases"], "real corpus has no cases"
    for c in real["cases"]:
        assert "id" in c and "input" in c, f"malformed case: {c}"
        for p in c.get("expect_patterns", []) + c.get("reject_patterns", []):
            re.compile(p)

    print("test_corpus_measure: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
