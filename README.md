# Flux

Open-source Claude Code plugin that engineers prompts — not templates.

**Every technique accounted for. Every model adapted. Every prompt converged.**

> Wrote a vague one-liner about stock analysis.
> Flux ran 4 iterations autonomously. Fixed clarity, added fallbacks,
> restructured for Claude Opus XML. Scored 9.3/10. Delivered a
> production-ready prompt I'd have spent an hour writing manually.

## The Problem

Most prompt tools give you a template. Paste your task, get a wall of text, hope it works. But models aren't the same:

- **Chain-of-Thought** boosts GPT and cripples o3
- **XML tags** sharpen Claude and confuse Gemini
- **Few-shot examples** are mandatory for Gemini, wasted tokens for o-series

The prompting techniques that make one model sing make another one choke.

## What Flux Does

Give it a vague idea or an underperforming prompt. A network of specialized agents takes over:

```
You: "I need a prompt for Claude Opus to analyze stocks"

  ┌─────────────────────────────────────────────────────────────┐
  │  ORCHESTRATOR (Opus)                                        │
  │  Scans context → asks questions → selects techniques        │
  │  → generates prompt → delegates to agent network            │
  └──────────┬──────────────────────────────────┬───────────────┘
             │                                  │
             ▼                                  ▼
  ┌──────────────────────┐           ┌──────────────────────┐
  │  OPTIMIZER (Sonnet)  │           │  REVIEWER (Haiku)    │
  │                      │           │                      │
  │  Convergence Engine  │──────────▶│  9 validation checks │
  │  Up to 100 iterations│  when     │  Score freshness     │
  │  Hypothesis-driven   │  done     │  Format alignment    │
  │  Binary assertions   │           │  Registry cross-ref  │
  │  Auto-revert on      │           │  Domain coherence    │
  │  regression          │           │  APPROVED / FAIL     │
  └──────────────────────┘           └──────────────────────┘

  Result: 9.3/10. DEPLOY. 1 iteration. Zero manual fixes.
  Saved: prompt.xml + metadata.json + tests.json + report.pdf
```

No permission prompts. No manual iteration. You describe the task, the agent network delivers a production-ready prompt with a PDF audit report.

## The Convergence Engine

Other tools score your prompt and wish you luck. Flux fixes it.

The engine runs up to **100 autonomous iterations**. Each cycle:
1. **Scores** the prompt on 5 axes + 8 binary assertions
2. **Forms a hypothesis** about which fix will improve the weakest axis
3. **Applies the fix** — removes hedge words, adds missing components, restructures format
4. **Re-scores** and checks for regression
5. **Auto-reverts** if the fix made things worse
6. **Logs learnings** to `learnings.md` for persistence across sessions

```
FLUX CONVERGENCE ENGINE
Target: DEPLOY (overall >= 9.0, all axes >= 7.0)

Iteration 1:  4.4/10 — hypothesis: fix Completeness
              failed assertions: has_role, has_task, has_format, has_constraints (7/8)
Iteration 2:  8.3/10 — hypothesis: fix Model Fit
              REVERTED — regression detected, kept previous version
Iteration 3:  8.3/10 — PLATEAU

FINAL: 8.3/10 | ASSERTIONS: 7/8 pass | VERDICT: BEST EFFORT
```

**For text prompts:** Fully autonomous. Up to 100 iterations. Zero user input.

**For image prompts:** Collaborative loop. You generate the image externally, rate it 1-10, tell Flux what's wrong. It adjusts, you try again. No iteration limit.

## The Agent Network

Three tiers. Each agent uses the optimal model for its role.

| Role | Model | What it does | Cost |
|------|-------|-------------|------|
| **Orchestrator** | Opus | Designs the prompt. Understands intent, selects techniques, makes judgment calls. | Highest quality |
| **Optimizer** | Sonnet | Runs convergence.py. Executes fixes, manages artifacts. Doesn't need heavy reasoning. | Balanced |
| **Reviewer** | Haiku | Validates files, checks JSON, compares scores. Simple pass/fail checks. Fastest. | Cheapest |

The orchestrator delegates convergence to the optimizer (background), then the reviewer validates the result. If the reviewer finds issues, the optimizer re-runs. This loop continues until APPROVED or 3 review cycles.

### Plugin-Specific Review Checks

| Plugin | Reviewer Checks | Total |
|--------|----------------|-------|
| **prompt-crafter** | Standard (5) + technique rationale, version=1, no stale placeholders, domain coherence | 9 checks |
| **prompt-refiner** | Standard (5) + before/after scores, score improvement, version>1, refined timestamp, mode=refine | 10 checks |
| **convergence-engine** | File completeness, metadata consistency, score freshness, format alignment, test coverage, learnings | 6 checks |

## Model Fit Check

Pick the wrong model? Flux catches it before wasting your time.

```
⚠️ Model Fit Warning

You selected Gemini for a coding task.
Gemini requires few-shot examples and temperature 1.0 — suboptimal for
deterministic code generation.

Recommended alternatives:
1. Claude Opus 4.6 — extended thinking, strongest multi-file code gen
2. GPT-4.1 — literal instruction following, sandwich method

Continue with Gemini anyway? Or switch?
```

## The Full Lifecycle

```
  Create          Optimize         Test           Harden          Translate
  /enchant    →   /converge    →   /test-prompt → /harden     →  /translate-prompt
  ┌─────────┐    ┌───────────┐    ┌───────────┐  ┌───────────┐  ┌──────────────┐
  │ Crafter │───▶│Convergence│───▶│  Tester   │─▶│ Hardener  │─▶│  Translator  │
  │  (Opus) │    │ (Sonnet)  │    │ (Sonnet)  │  │ (Sonnet)  │  │  (Sonnet)    │
  └─────────┘    └───────────┘    └───────────┘  └───────────┘  └──────────────┘
       │              │                │               │               │
       ▼              ▼                ▼               ▼               ▼
   prompt.xml    9.3/10 DEPLOY    5/5 PASS       10/12 RESIST    prompt-gpt.md
   + metadata    + learnings.md   + results.json + audit.json    + comparison
```

Refine anytime with `/refine`. Every step is autonomous.

## Install

```
/plugin marketplace add enchanted-plugins/flux
/plugin install prompt-crafter@flux
```

Full suite:
```
/plugin install prompt-crafter@flux
/plugin install prompt-refiner@flux
/plugin install convergence-engine@flux
/plugin install prompt-tester@flux
/plugin install prompt-harden@flux
/plugin install prompt-translate@flux
```

Or manually:
```bash
bash <(curl -s https://raw.githubusercontent.com/enchanted-plugins/flux/main/install.sh)
```

## 6 Plugins, 7 Agents, 64 Models

| Plugin | Command | What | Agent |
|--------|---------|------|-------|
| prompt-crafter | `/enchant` | Creates new prompts with full pipeline | reviewer (Haiku) |
| prompt-refiner | `/refine` | Improves existing prompts, preserves intent | reviewer (Haiku) |
| convergence-engine | `/converge` | 100-iteration autonomous optimizer | optimizer (Sonnet) + reviewer (Haiku) |
| prompt-tester | `/test-prompt` | Executes tests.json assertions, pass/fail | executor (Sonnet) |
| prompt-harden | `/harden` | 12 adversarial attack patterns, defense suggestions | red-team (Sonnet) |
| prompt-translate | `/translate-prompt` | Converts between 64 models, preserves intent | adapter (Sonnet) |

### Supported Models

| Family | Models | Format |
|---|---|---|
| Claude | Opus 4.6, Sonnet 4.6, Haiku 4.5 | XML tags |
| GPT | 4.1, 4o, 5, Image 1/1.5 | Markdown |
| o-series | o1, o3, o4-mini | Minimal (no CoT) |
| Gemini | 2.5 Pro/Flash, 3 | XML or Markdown |
| DeepSeek | R1 (reasoning), V3 | Markdown |
| Grok | 2, 3 | Markdown |
| Qwen | 2.5, 2.5-Coder, QwQ | Markdown |
| Llama | 4, 3 | Special tokens |
| Mistral | Large, Codestral | Markdown |
| Cohere | Command R+ | Markdown |
| Image Gen | DALL-E 3, GPT Image 1.5, Midjourney v6-v8, Niji 7, SD 3.5, FLUX.1/2, Ideogram 2-3, Imagen 3-4, Recraft V4, Reve Image, Firefly 5, Nano Banana, Seedream 4.5/5, Luma Photon, HunyuanImage 3, Kling Image 03, Wan 2.7 | Descriptors / Natural language |
| Video Gen | Runway Gen-3, Seedance 2.0 | Natural language |
| Audio | ElevenLabs, Suno v4 | Natural language |

## What You Get Per Prompt

```
prompts/stocks-analysis/
├── prompt.xml          Production-ready prompt
├── metadata.json       Model, tokens, cost, scores, config
├── tests.json          3-5 regression test cases
├── report.pdf          Dark-themed single-page PDF audit report
└── learnings.md        Convergence hypothesis/outcome log
```

The **PDF audit report** includes: quality score bars, binary assertion results, technique pills (applied/avoided), model profile from registry, prompt statistics (words, lines, sections), audit findings with CRITICAL/WARNING severity, cost estimate per call + monthly projection, and an honest verdict (DEPLOY / REVIEW / IMPROVE / REWORK / DO NOT DEPLOY) with specific next steps.

## vs Everything Else

| | Flux | Promptfoo | AutoResearch | PromptLayer | Manual |
|---|---|---|---|---|---|
| Create prompts | 16 techniques, 64 models | - | - | - | trial and error |
| Optimize prompts | 100 autonomous iterations | - | unbounded | - | - |
| Test prompts | pass/fail assertions | YAML eval suite | hypothesis | basic metrics | - |
| Harden prompts | 12 attack patterns | red-team module | - | - | - |
| Translate prompts | 64 models, auto-adapted | - | - | - | manual rewrite |
| Multi-agent | Opus + Sonnet + Haiku | - | single agent | - | - |
| Binary assertions | 8 checks + auto-revert | custom assertions | hypothesis | - | - |
| PDF audit report | dark theme, single page | - | - | dashboard | - |
| Model fit check | warns + suggests | - | - | - | - |
| Cost estimate | per-call + monthly | post-hoc | - | post-hoc | - |
| Dependencies | Python stdlib only | Node.js | Python | SaaS | - |
| Price | Free (MIT) | Free / Pro | Free | $$$ | Free |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## License

MIT
