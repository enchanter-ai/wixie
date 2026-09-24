#!/usr/bin/env bash
# Regression tests for WIX-EVAL-003: output-test must send each role (target, evaluator,
# fixer) the provider model the registry declares for it, persist requested / resolved /
# provider-observed identity separately, fail explicitly on unknown / unavailable /
# non-Anthropic models, record declared fallbacks, keep provider errors as failures with
# unknown (not zero) usage, price by the resolved identity, and only send sampling
# parameters a model accepts.
#
# Provider-neutral: a synthetic temporary registry with made-up model ids and a fake client.
# No network, no key, no real model id or lifecycle date is encoded here.
set -euo pipefail
REPO_ROOT="${1:-.}"

PYTHONIOENCODING=utf-8 python - "$REPO_ROOT" <<'PY'
import contextlib, importlib.util, io, json, os, pathlib, sys, tempfile

root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("output_test", root / "shared" / "scripts" / "output-test.py")
ot = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(ot)

failures = []
def check(name, cond, detail=""):
    if not cond:
        failures.append(f"{name}: {detail}")

def api(model_id, availability="available", sampling="adjustable", price=None, **extra):
    a = {"model_id": model_id, "availability": availability, "sampling": sampling,
         "pricing_usd_per_mtok": None if price is None else {"input": price[0], "output": price[1]},
         "source": "synthetic test registry"}
    a.update(extra)
    return a

def entry(**kw):
    e = {"family": "Synthetic", "display_name": "x", "context_window": 1000, "format": "xml"}
    e.update(kw)
    return e

REGISTRY = {"last_updated": "2000-01-01", "model_count": 10, "models": {
    "zz-alpha": entry(provider="anthropic", api=api("zz-alpha-wire-1", price=(2.0, 8.0))),
    "zz-beta": entry(provider="anthropic", api=api("zz-beta-wire", sampling="default_only", price=(10.0, 40.0))),
    "zz-noprice": entry(provider="anthropic", api=api("zz-np-wire")),
    "zz-gone": entry(provider="anthropic", api=api("zz-gone-wire", availability="unavailable")),
    "zz-gone-fb": entry(provider="anthropic", api=api("zz-gone-fb-wire", availability="unavailable",
                                                      price=(1.0, 1.0), fallback="zz-beta")),
    "zz-gone-fb-bad": entry(provider="anthropic", api=api("x", availability="unavailable", fallback="zz-gone")),
    "zz-limited": entry(provider="anthropic", api=api("zz-lim-wire", availability="restricted", price=(1.0, 1.0))),
    "zz-foreign": entry(provider="otherco", api=api("zz-foreign-wire", price=(1.0, 1.0))),
    "zz-bare": entry(),
    "zz-noapi": entry(provider="anthropic"),
    "zz-undeclared": entry(provider="anthropic", api={"model_id": "zz-und-wire", "availability": "available"}),
}}

tmp = pathlib.Path(tempfile.mkdtemp(prefix="wix-eval003-"))
reg_path = tmp / "registry.json"
reg_path.write_text(json.dumps(REGISTRY), encoding="utf-8")
ot.REGISTRY_PATH = str(reg_path)
# Force Phase 4 onto the LLM evaluator + fixer path (the offline regex fixer is out of scope here).
ot.try_offline_fix = lambda p, s, d: (p, False, None)

SECRET = "sk-test-NOT-A-REAL-KEY-7f3a9c"
os.environ["ANTHROPIC_API_KEY"] = SECRET
for k in (ot.EVALUATOR_ENV, ot.FIXER_ENV):
    os.environ.pop(k, None)

PROMPT = ("You are a greeter.\n<task>Say hello to the user politely.</task>\n"
          "<success_criteria>1. The output says hello.</success_criteria>\n")
MISSING = object()

class Usage:
    def __init__(self, i, o): self.input_tokens, self.output_tokens = i, o
class Block:
    def __init__(self, t): self.text = t
class Resp:
    def __init__(self, text, observed=MISSING, usage=(10, 20)):
        self.content = [Block(text)]
        if observed is not MISSING:
            self.model = observed
        self.usage = None if usage is None else Usage(*usage)
        self.stop_reason = "end_turn"

class ProviderError(Exception):
    def __init__(self, msg, status_code):
        super().__init__(msg)
        self.status_code = status_code

def role_of(kw):
    text = kw["messages"][0]["content"]
    if text.startswith("You are evaluating"):
        return "evaluator"
    if text.startswith("You are a prompt engineer"):
        return "fixer"
    return "target"

EVAL_FAIL = '```json\n{"criteria": [{"id": 1, "verdict": "FAIL", "reason": "no hello", "fix": "x"}], ' \
            '"overall": "FAIL", "weakest_area": "1", "top_fix": "say hello", "output_quality_score": 3}\n```'
FIX_OK = '```json\n{"target": "Say hello to the user politely.", ' \
         '"replacement": "Say hello to the user politely and warmly.", "reason": "warmer"}\n```'

class FakeClient:
    """Records every request. behaviours: role -> Resp | Exception | callable(kw)."""
    def __init__(self, **behaviours):
        self.behaviours = {"target": Resp("hi there"), "evaluator": Resp(EVAL_FAIL),
                           "fixer": Resp(FIX_OK)}
        self.behaviours.update(behaviours)
        self.sent = []
        self.messages = self
    def create(self, **kw):
        role = role_of(kw)
        self.sent.append((role, kw))
        b = self.behaviours[role]
        if isinstance(b, Exception):
            raise b
        return b

def make_folder(target_model=None, temperature=0.3):
    d = pathlib.Path(tempfile.mkdtemp(prefix="case-", dir=tmp))
    (d / "prompt.md").write_text(PROMPT, encoding="utf-8")
    meta = {"config": {"max_tokens": 64, "temperature": temperature}}
    if target_model:
        meta["target_model"] = target_model
    (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "tests.json").write_text(json.dumps(
        [{"name": "sentinel", "expected_contains": ["ZZ-UNLIKELY-SENTINEL"]}]), encoding="utf-8")
    return d

def run_case(target, client, **kw):
    folder = make_folder(target)
    kw.setdefault("evaluator_model", "zz-alpha")  # the shipped default is not in this registry
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        ot.run(str(folder), max_iterations=kw.pop("max_iterations", 2), skip_preflight=True,
               client=client, **kw)
    raw = (folder / "output-test-results.json").read_text(encoding="utf-8")
    return json.loads(raw), raw, out.getvalue() + err.getvalue()

def all_calls(res):
    return [c for it in res["iterations_detail"] for c in it.get("calls", [])]

# ── 1. known mapping + identity for generation, evaluator and fixer ──────────
c = FakeClient(target=Resp("hi there", observed="zz-alpha-wire-1-snapshot"),
               evaluator=Resp(EVAL_FAIL),                       # response carries no model
               fixer=Resp(FIX_OK, observed="zz-np-wire"))
res, raw, _ = run_case("zz-alpha", c, evaluator_model="zz-beta", fixer_model="zz-noprice")
sent = [(r, kw["model"]) for r, kw in c.sent]
check("1 outbound models", sent[:3] == [("target", "zz-alpha-wire-1"), ("evaluator", "zz-beta-wire"),
                                        ("fixer", "zz-np-wire")], sent)
mi = res["model_identity"]
check("1 target requested/resolved", (mi["target"]["requested"], mi["target"]["resolved"]) ==
      ("zz-alpha", "zz-alpha-wire-1"), mi["target"])
check("1 target observed", mi["target"]["observed"] == ["zz-alpha-wire-1-snapshot"], mi["target"])
check("1 evaluator observed unknown, not copied", mi["evaluator"]["observed"] == [] and
      mi["evaluator"]["observed_unknown_calls"] == 1, mi["evaluator"])
check("1 evaluator source", mi["evaluator"]["requested_source"] == "cli:--evaluator-model", mi["evaluator"])
check("1 fixer identity", (mi["fixer"]["requested"], mi["fixer"]["resolved"], mi["fixer"]["observed"]) ==
      ("zz-noprice", "zz-np-wire", ["zz-np-wire"]), mi["fixer"])
calls = all_calls(res)
check("1 per-call roles", [x["role"] for x in calls][:3] == ["target", "evaluator", "fixer"], calls)
ev = calls[1]
check("1 per-call observed None when absent", ev["observed"] is None and ev["requested"] == "zz-beta"
      and ev["resolved"] == "zz-beta-wire", ev)
check("1 fix applied", res["iterations_detail"][0]["fix"]["applied"] is True, res["iterations_detail"][0].get("fix"))
# sampling capability
gen_kw, ev_kw, fx_kw = c.sent[0][1], c.sent[1][1], c.sent[2][1]
check("10 adjustable target gets metadata temperature", gen_kw.get("temperature") == 0.3, gen_kw)
check("10 default_only evaluator gets no temperature", "temperature" not in ev_kw, ev_kw)
check("10 omission recorded", ev["sampling"]["omitted"] == {"temperature": 0.0}
      and ev["sampling"]["policy"] == "default_only", ev["sampling"])
check("10 adjustable fixer gets 0.0", fx_kw.get("temperature") == 0.0, fx_kw)
# cost by resolved identity; unknown price stays unknown
check("9 target cost from zz-alpha price", abs(calls[0]["cost_usd"] - (10 * 2.0 + 20 * 8.0) / 1e6) < 1e-12, calls[0])
check("9 evaluator cost from zz-beta price", abs(calls[1]["cost_usd"] - (10 * 10.0 + 20 * 40.0) / 1e6) < 1e-12, calls[1])
check("9 unpriced fixer cost UNKNOWN", calls[2]["cost_usd"] is None and
      calls[2]["cost_provenance"].startswith("UNKNOWN"), calls[2])
check("9 total cost not a partial sum", res["total_cost_usd"] is None and res["cost_status"] == "partial"
      and res["cost_unknown_calls"] >= 1, {k: res[k] for k in ("total_cost_usd", "cost_status", "cost_unknown_calls")})

# identity mismatch flag: per call and per role
gen1, ev1, fx1 = calls[0], calls[1], calls[2]
check("3 mismatch flagged when observed != resolved", gen1.get("identity_mismatch") is True, gen1)
check("3 mismatch None when provider did not report", "identity_mismatch" in ev1 and ev1["identity_mismatch"] is None, ev1)
check("3 mismatch False when observed == resolved", fx1.get("identity_mismatch") is False, fx1)
check("3 role mismatch count", mi["target"].get("identity_mismatch_calls") == 2
      and mi["fixer"].get("identity_mismatch_calls") == 0, (mi["target"], mi["fixer"]))
# unknown cost is never persisted as 0: buckets and iterations
cb = {k: v if isinstance(v, dict) else {"cost_usd": v} for k, v in res["cost_breakdown"].items()}
gen_known = 2 * (10 * 2.0 + 20 * 8.0) / 1e6
eval_known = (10 * 10.0 + 20 * 40.0) / 1e6
check("9 generate bucket complete", abs((cb["generate"]["cost_usd"] or 0) - gen_known) < 1e-12
      and cb["generate"].get("unknown_calls") == 0, cb["generate"])
check("9 fix bucket UNKNOWN, partial sum labelled", cb["fix"]["cost_usd"] is None
      and abs(cb["fix"].get("known_cost_usd", -1) - eval_known) < 1e-12 and cb["fix"].get("unknown_calls") == 1, cb["fix"])
check("9 no-call buckets are a real zero", cb["preflight"] == {"cost_usd": 0.0, "known_cost_usd": 0.0,
      "unknown_calls": 0}, cb["preflight"])
it1, it2 = res["iterations_detail"][0], res["iterations_detail"][1]
check("9 iteration with unpriced call is UNKNOWN", it1["cost_usd"] is None and it1.get("cost_unknown_calls") == 1
      and abs(it1.get("known_cost_usd", -1) - (gen_known / 2 + eval_known)) < 1e-12 and it1["cost_complete"] is False, it1)
check("9 fully priced iteration has a cost", abs((it2["cost_usd"] or 0) - gen_known / 2) < 1e-12
      and it2["cost_complete"] is True, it2)

# ── 2-4. unknown, unavailable, non-Anthropic targets: explicit failure, zero calls ──
for target, needle in [("zz-missing", "not in models-registry"), ("zz-gone", "unavailable"),
                       ("zz-limited", "restricted"),
                       ("zz-foreign", "otherco"), ("zz-bare", "undeclared"), ("zz-noapi", "no api block"),
                       ("zz-gone-fb-bad", "do not chain")]:
    c = FakeClient()
    res, _, _ = run_case(target, c)
    check(f"2 {target} no call", c.sent == [], c.sent)
    check(f"2 {target} verdict", res["final_verdict"] == "MODEL_RESOLUTION_FAILED", res["final_verdict"])
    check(f"2 {target} error persisted", needle in res["model_resolution_errors"].get("target", ""),
          res["model_resolution_errors"])
    check(f"2 {target} requested persisted", res["model_identity"]["target"]["requested"] == target and
          res["model_identity"]["target"]["resolved"] is None, res["model_identity"]["target"])

# ── 5. provider says not-found: failure kept, no substitution, no zero usage ─────
c = FakeClient(target=ProviderError(f"model not found (key {SECRET})", 404))
res, raw, _ = run_case("zz-alpha", c)
check("5 exactly one call, same model", [kw["model"] for _, kw in c.sent] == ["zz-alpha-wire-1"], c.sent)
check("5 verdict", res["final_verdict"] == "API_ERROR", res["final_verdict"])
g = all_calls(res)[0]
check("5 failure provenance", g["ok"] is False and g["usage"] is None and g["cost_usd"] is None
      and g["error"]["status_code"] == 404 and g["observed"] is None, g)
check("5 provider_failures", len(res["provider_failures"]) == 1, res["provider_failures"])
check("5 total cost unknown", res["total_cost_usd"] is None, res["total_cost_usd"])
check("5 generate bucket UNKNOWN not 0", isinstance(res["cost_breakdown"]["generate"], dict)
      and res["cost_breakdown"]["generate"]["cost_usd"] is None
      and res["cost_breakdown"]["generate"]["unknown_calls"] == 1, res["cost_breakdown"]["generate"])
check("5 failed iteration cost UNKNOWN not 0", res["iterations_detail"][0]["cost_usd"] is None,
      res["iterations_detail"][0])
check("5 failed call has no mismatch verdict", "identity_mismatch" in g and g["identity_mismatch"] is None, g)
check("5 credential never persisted", SECRET not in raw, "secret found in results")

# ── 6. declared fallback vs none ─────────────────────────────────────────────
c = FakeClient(target=Resp("hi", observed="zz-beta-wire"))
res, _, _ = run_case("zz-gone-fb", c, max_iterations=1)
check("6 fallback sends declared target", [kw["model"] for _, kw in c.sent] == ["zz-beta-wire"], c.sent)
fe = res["fallback_events"]
check("6 fallback event recorded", len(fe) == 1 and fe[0]["from_registry_id"] == "zz-gone-fb"
      and fe[0]["from_model_id"] == "zz-gone-fb-wire" and fe[0]["to_registry_id"] == "zz-beta"
      and fe[0]["to_model_id"] == "zz-beta-wire", fe)
g = all_calls(res)[0]
check("6 call carries fallback", g["fallback"] is not None and g["requested"] == "zz-gone-fb"
      and g["resolved"] == "zz-beta-wire", g)
check("6 priced as resolved entry", abs(g["cost_usd"] - (10 * 10.0 + 20 * 40.0) / 1e6) < 1e-12, g)
check("6 fallback entry's sampling applies", "temperature" not in c.sent[0][1], c.sent[0][1])
c = FakeClient()
res, _, _ = run_case("zz-gone", c)
check("6 no fallback declared -> no call", c.sent == [] and res["fallback_events"] == [], res["fallback_events"])

# ── 7. overrides go through resolution ───────────────────────────────────────
for env, val, bad_roles in [(ot.EVALUATOR_ENV, "zz-missing", {"evaluator", "fixer"}),
                            (ot.FIXER_ENV, "zz-foreign", {"fixer"}),
                            (ot.EVALUATOR_ENV, "zz-gone", {"evaluator", "fixer"})]:
    os.environ[env] = val
    try:
        c = FakeClient()
        # CLI beats env, so leave the evaluator CLI value unset when the evaluator env is under test.
        res, _, _ = run_case("zz-alpha", c, **({"evaluator_model": None} if env == ot.EVALUATOR_ENV else {}))
    finally:
        os.environ.pop(env, None)
    check(f"7 {env}={val} no call", c.sent == [], c.sent)
    check(f"7 {env}={val} roles failed", set(res["model_resolution_errors"]) == bad_roles,
          res["model_resolution_errors"])
c = FakeClient()
res, _, _ = run_case("zz-alpha", c, fixer_model="zz-bare")
check("7 cli fixer override cannot bypass", c.sent == [] and "fixer" in res["model_resolution_errors"],
      res["model_resolution_errors"])
os.environ[ot.EVALUATOR_ENV] = "zz-beta"
try:
    ident, errs = ot.resolve_run_models({"target_model": "zz-alpha"})
finally:
    os.environ.pop(ot.EVALUATOR_ENV, None)
check("7 valid env override resolved + recorded", not errs and ident["evaluator"]["resolved"] == "zz-beta-wire"
      and ident["evaluator"]["requested_source"] == f"env:{ot.EVALUATOR_ENV}"
      and ident["fixer"]["resolved"] == "zz-beta-wire"
      and ident["fixer"]["requested_source"].startswith("inherited:evaluator"), ident)

# ── 8. evaluator provider error is a recorded failure, not a score ───────────
c = FakeClient(evaluator=ProviderError("upstream overloaded", 529))
res, _, _ = run_case("zz-alpha", c, evaluator_model="zz-alpha")
roles = [r for r, _ in c.sent]
check("8 no fixer call after evaluator failure", "fixer" not in roles, roles)
it0 = res["iterations_detail"][0]
check("8 fix_info records evaluation failure", it0["fix"].get("evaluation_failed") is True
      and it0["fix"]["error"]["status_code"] == 529 and it0["fix"]["applied"] is False, it0["fix"])
ev = [x for x in it0["calls"] if x["role"] == "evaluator"][0]
check("8 evaluator usage unknown not zero", ev["ok"] is False and ev["usage"] is None and ev["cost_usd"] is None, ev)
check("8 no pseudo quality score", "output_quality_score" not in json.dumps(it0["fix"]), it0["fix"])
check("8 no zero-usage records anywhere", all(x["usage"] != {"input_tokens": 0, "output_tokens": 0}
                                              for x in all_calls(res)), all_calls(res))

# fixer provider error
c = FakeClient(fixer=ProviderError("bad request", 400))
res, _, _ = run_case("zz-alpha", c, evaluator_model="zz-alpha", max_iterations=2)
fx = res["iterations_detail"][0]["fix"]
check("8 fixer failure recorded", fx.get("fix_failed") is True and fx["error"]["status_code"] == 400, fx)

# unparseable evaluator reply: no score invented
c = FakeClient(evaluator=Resp("not json at all"))
res, _, _ = run_case("zz-alpha", c, evaluator_model="zz-alpha")
le = res["iterations_detail"][0]["fix"].get("llm_evaluation", {})
check("8 unparseable -> score None", le.get("overall") == "UNPARSEABLE" and le.get("output_quality_score") is None, le)

# provider response without usage: usage and cost UNKNOWN, not 0
c = FakeClient(target=Resp("hi", usage=None))
res, _, _ = run_case("zz-alpha", c, max_iterations=1)
g = all_calls(res)[0]
check("8 missing usage stays unknown", g["usage"] is None and g["cost_usd"] is None
      and "usage not reported" in g["cost_provenance"], g)

# ── 10b. undeclared sampling capability: nothing non-default sent ────────────
c = FakeClient()
res, _, _ = run_case("zz-undeclared", c, max_iterations=1)
check("10 undeclared sampling not sent", "temperature" not in c.sent[0][1]
      and all_calls(res)[0]["sampling"]["policy"] == "undeclared", c.sent[0][1])

# ── 11. dry-run records identity without calling, even when unresolvable ─────
folder = make_folder("zz-missing")
with contextlib.redirect_stdout(io.StringIO()):
    ot.run(str(folder), dry_run=True, skip_preflight=True, client=FakeClient())
r = json.loads((folder / "output-test-results.json").read_text(encoding="utf-8"))
check("11 dry-run records resolution error", r["final_verdict"] == "DRY_RUN" and "target" in r["model_resolution_errors"], r)

# ── 12. shipped registry: defaults resolve; a provider-less entry is rejected ──
ot.REGISTRY_PATH = str(root / "shared" / "models-registry.json")
real = ot.load_registry()
for role, (req, _src) in ot.select_requested_models({}, env={}).items():
    try:
        rec = ot.resolve_model(req, role)
        check(f"12 default {role} sendable", rec["provider"] == "anthropic" and rec["resolved"], rec)
    except ot.ModelResolutionError as e:
        check(f"12 default {role} sendable", False, str(e))
bare = next((k for k, v in real.items() if "provider" not in v), None)
if bare:
    try:
        ot.resolve_model(bare, "target")
        check("12 provider-less real entry rejected", False, bare)
    except ot.ModelResolutionError:
        pass
for k, v in real.items():
    if v.get("provider") == "anthropic":
        a = v.get("api") or {}
        check(f"12 {k} api declares availability", a.get("availability") in ("available", "unavailable", "restricted"), a)
check("12 no hard-coded id map", not hasattr(ot, "MODEL_MAP") and not hasattr(ot, "COST_PER_1K"), "")

if failures:
    print("FAIL test-model-identity-resolution")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("PASS test-model-identity-resolution")
PY
