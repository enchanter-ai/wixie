# Flux

Open-source Claude Code plugin that engineers prompts — not templates.

**Every technique accounted for. Every model adapted. Every prompt converged.**

> Wrote a vague one-liner about stock analysis.
> Flux ran 4 iterations autonomously. Fixed clarity, added fallbacks,
> restructured for Claude Opus XML. Scored 9.1/10. Delivered a
> production-ready prompt I'd have spent an hour writing manually.

## The Problem

Most prompt tools give you a template. Paste your task, get a wall of text, hope it works. But models aren't the same:

- **Chain-of-Thought** boosts GPT and cripples o3
- **XML tags** sharpen Claude and confuse Gemini
- **Few-shot examples** are mandatory for Gemini, wasted tokens for o-series

The prompting techniques that make one model sing make another one choke.

## What Flux Does

Give it a vague idea or an underperforming prompt. It reads your intent, selects from 16 prompting techniques, adapts the format to your target model, and iterates until the prompt is production-ready.

You get back:
1. **A production-ready prompt** — not a draft, not a template
2. **A PDF audit report** — techniques applied, model warnings, quality scores, verdict
3. **Convergence guarantee** — the engine loops up to 100 times until DEPLOY or plateau

## The Convergence Engine

Other tools score your prompt and wish you luck. Flux fixes it.

```
FLUX CONVERGENCE ENGINE
Target: DEPLOY (overall >= 9.0, all axes >= 7.0)

Iteration 1:  4.4/10 — fixing: Clarity, Completeness, Resilience
Iteration 2:  8.1/10 — fixing: Model Fit
Iteration 3:  8.1/10 — PLATEAU

VERDICT: BEST EFFORT (8.1/10)
```

**For text prompts:** Fully autonomous. Up to 100 iterations. Fixes hedge words, adds missing components, removes filler, restructures for the target model, adds fallbacks. No user input needed.

**For image prompts:** Collaborative loop. You generate the image, rate it 1-10, tell Flux what's wrong. It adjusts and you try again. Repeats until you're satisfied.

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

## Install

```
/plugin marketplace add enchanted-plugins/flux
/plugin install prompt-crafter@flux
```

Full suite:
```
/plugin install prompt-crafter@flux
/plugin install prompt-refiner@flux
```

Or manually:
```bash
bash <(curl -s https://raw.githubusercontent.com/enchanted-plugins/flux/main/install.sh)
```

## 2 Plugins, 16 Techniques, 64 Models

| Plugin | What |
|--------|------|
| prompt-crafter | Creates new prompts — technique selection + model fitting + convergence |
| prompt-refiner | Improves existing prompts — diagnoses weaknesses, preserves intent |

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
| Image Gen | DALL-E 3, Midjourney v6-v8, SD 3.5, FLUX.1/2, Ideogram 2-3, Imagen 3-4, Recraft V4, Reve Image, Firefly 5, Nano Banana, Seedream, Luma Photon, HunyuanImage 3, Kling Image 03, Wan 2.7 | Descriptors / Natural language |
| Video Gen | Runway Gen-3, Seedance 2.0 | Natural language |
| Audio | ElevenLabs, Suno v4 | Natural language |

## What You Get Per Prompt

Every prompt saves as a folder:

```
prompts/stocks-analysis/
├── prompt.xml          The prompt (XML, Markdown, JSON, or TXT)
├── metadata.json       Model, tokens, cost, scores, config
├── tests.json          Regression test cases
└── report.pdf          Dark-themed single-page audit report
```

The PDF report includes: quality scores with visual bars, technique pills, model profile, prompt statistics, audit findings (critical/warning), cost estimate, and a verdict with next steps.

## vs Everything Else

| | Flux | Generic Templates | PromptLayer | Manual |
|---|---|---|---|---|
| Model-specific formatting | automatic | - | manual | manual |
| Technique selection | 16 techniques, auto-routed | - | - | trial and error |
| Anti-pattern detection | warns before you waste time | - | post-hoc | - |
| Convergence loop | 100 autonomous iterations | - | - | - |
| Quality scoring | 5-axis heuristic + PDF report | - | basic metrics | gut feeling |
| Model fit check | warns + suggests alternatives | - | - | - |
| Image prompt collaboration | forced feedback loop | - | - | - |
| Cost estimate | per-call + monthly projection | - | post-hoc | - |
| Dependencies | Python stdlib only | varies | SaaS | - |
| Price | Free (MIT) | Free-$$ | $$$ | Free |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## License

MIT
