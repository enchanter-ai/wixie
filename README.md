# Flux

The first prompt engineering platform that learns from itself.

**6 plugins. 7 agents. 64 models. One command.**

> "Build me a B2B ticket routing system like Zendesk."
>
> Flux researched Zendesk, Freshdesk, Intercom, and Crisp. Selected 3 techniques
> for Claude Opus. Generated 10KB of production-ready prompt. Ran the Convergence
> Engine — 2 iterations, hypothesis-driven, auto-fixed Failure Resilience from 5 to 10.
> Scored 9.4/10. DEPLOY. All 8 assertions pass. Dark-themed PDF audit report delivered.
>
> Time: under 2 minutes. Manual effort: zero.

## How It Works

Flux doesn't generate prompts. It **engineers** them — then stress-tests, hardens, and translates them across 64 models.

The core innovation is the **Convergence Engine** (סטיית תקן strategy): like gradient descent for prompts, each iteration measures the deviation from perfection, forms a hypothesis about which fix will reduce it, applies the fix, checks for regression, and auto-reverts if things got worse. It learns from every iteration and persists those learnings across sessions.

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
  │  Convergence Engine  │──────────▶│  Validation checks   │
  │  Up to 100 iterations│  when     │  Score freshness     │
  │  Hypothesis-driven   │  done     │  Format alignment    │
  │  Binary assertions   │           │  Registry cross-ref  │
  │  Auto-revert on      │           │  Domain coherence    │
  │  regression          │           │  APPROVED / FAIL     │
  └──────────────────────┘           └──────────────────────┘
```

No permission prompts. No manual iteration. You describe what you need, the agent network delivers.

## What Makes Flux Different

### It supports every model you actually use

**64 models** across text, code, image, video, and audio. Not just the big 3.

Text LLMs: Claude (Opus/Sonnet/Haiku), GPT (4.1/4o/5), o-series (o1/o3/o4-mini), Gemini (2.5/3), DeepSeek (R1/V3), Grok, Qwen, Llama, Mistral, Cohere, Jamba, Amazon Nova, Phi, Yi, Codestral, Perplexity.

**Image generation**: DALL-E 3, GPT Image 1.5, Midjourney v6/v7/v8, Niji 7, Stable Diffusion 3.5, FLUX.1/2 (Pro/Flex/Max/Kontext/Schnell), Ideogram 2/3, Imagen 3/4, Recraft V4, Reve Image, Adobe Firefly 5, Nano Banana (Pro/2), Seedream 4.5/5, Luma Photon, HunyuanImage 3, Kling Image 03, Wan 2.7.

**Video**: Runway Gen-3, Seedance 2.0. **Audio**: ElevenLabs, Suno v4.

Every model has a registry entry with context window, preferred format, reasoning type, CoT approach, few-shot requirements, and key constraints. The engine adapts automatically — XML for Claude, Markdown with sandwich method for GPT, stripped-down minimal for o-series, always-few-shot for Gemini.

### It learns from itself

The Convergence Engine doesn't just loop — it **learns**. Each iteration:

1. **Scores** on 5 axes + 8 binary assertions
2. **Forms a hypothesis**: "Fixing Failure Resilience (5/10) will improve overall"
3. **Applies the fix** and re-scores
4. **Auto-reverts** if the score dropped (no regression allowed)
5. **Logs the outcome** to `learnings.md` — what worked, what didn't, why

```
FLUX CONVERGENCE ENGINE
Target: DEPLOY (overall >= 9.0, all axes >= 7.0)

Iteration 1:  8.4/10 — hypothesis: fix Failure Resilience
              applied → improved (8.4 → 9.4)
Iteration 2:  9.4/10 — DEPLOY (8/8 assertions pass)

VERDICT: DEPLOY
```

Next time you refine that prompt, the engine reads `learnings.md` and avoids repeating failed strategies. It gets smarter with every use.

### It works with image prompts too

For text prompts: fully autonomous, up to 100 iterations, zero user input.

For **image generation prompts** (DALL-E, Midjourney, Stable Diffusion, Flux, Nano Banana, and 20+ more): collaborative loop. You generate the image on your platform, rate it 1-10, tell the agent what's wrong. It adjusts the prompt based on your visual feedback — colors, composition, style, missing elements. No iteration limit. After 5+ rounds, it summarizes patterns and suggests trying a different model if issues persist.

### It catches model mismatches before you waste time

Pick Claude for image generation? GPT for a task that needs reasoning-native? Gemini without examples?

Flux cross-references your model choice against the task domain and warns you with better alternatives — before generating a single token.

### It hardens your prompts against attacks

12 adversarial attack patterns: direct injection, role override, data extraction, encoding bypass, multi-turn escalation, payload splitting, indirect injection, output manipulation, refusal bypass, language switching, token smuggling, context manipulation.

Reports VULNERABLE or RESISTANT per attack. Suggests specific defenses. Auto-applies them if you want.

### It translates prompts between any two models

Wrote the perfect Claude prompt. Now the team needs GPT-4.1. One command: `/translate-prompt --to gpt-4.1`. XML becomes Markdown. "Think thoroughly" becomes "Think step by step." Sandwich method added. Few-shot adjusted. Intent preserved. Score comparison delivered.

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
   prompt.xml    9.4/10 DEPLOY    7/7 PASS       10/12 RESIST    prompt-gpt.md
   + metadata    + learnings.md   + results.json + audit.json    + comparison
```

Refine anytime with `/refine`. Every step is autonomous.

## Install

One command. All 6 plugins.

```
/plugin marketplace add enchanted-plugins/flux
```

That's it. Browse `/plugin` → Discover to install any plugin.

Or via shell:
```bash
bash <(curl -s https://raw.githubusercontent.com/enchanted-plugins/flux/main/install.sh)
```

## 6 Plugins, 7 Agents, 64 Models

| Plugin | Command | What | Agent |
|--------|---------|------|-------|
| prompt-crafter | `/enchant` | Creates production-ready prompts | reviewer (Haiku) |
| prompt-refiner | `/refine` | Improves existing prompts | reviewer (Haiku) |
| convergence-engine | `/converge` | 100-iteration autonomous optimizer | optimizer (Sonnet) + reviewer (Haiku) |
| prompt-tester | `/test-prompt` | Runs test assertions, pass/fail | executor (Sonnet) |
| prompt-harden | `/harden` | 12 attack patterns, defense suggestions | red-team (Sonnet) |
| prompt-translate | `/translate-prompt` | Converts between 64 models | adapter (Sonnet) |

## What You Get Per Prompt

```
prompts/b2b-ticket-router/
├── prompt.xml          Production-ready prompt
├── metadata.json       Model, tokens, cost, scores, config
├── tests.json          7 regression test cases
├── report.pdf          Dark-themed single-page PDF audit report
└── learnings.md        Convergence hypothesis/outcome log
```

The **PDF audit report** includes: quality score bars, 8 binary assertion results, technique pills, model profile from the 64-model registry, prompt statistics, audit findings (CRITICAL/WARNING), cost estimate, and an honest verdict with next steps.

## vs Everything Else

| | Flux | Promptfoo | AutoResearch | PromptLayer | Manual |
|---|---|---|---|---|---|
| Create prompts | 16 techniques, 64 models | - | - | - | trial and error |
| Optimize (convergence) | 100 iterations, self-learning | - | unbounded | - | - |
| Test prompts | pass/fail assertions | YAML eval suite | hypothesis | basic metrics | - |
| Harden prompts | 12 attack patterns | red-team module | - | - | - |
| Translate prompts | 64 models, auto-adapted | - | - | - | manual rewrite |
| Image LLM support | 27 image models + collab loop | - | - | - | - |
| Video/Audio support | Runway, Seedance, ElevenLabs, Suno | - | - | - | - |
| Multi-agent pipeline | Opus + Sonnet + Haiku | - | single agent | - | - |
| Self-learning | learnings.md persistence | - | learnings.md | - | - |
| Auto-revert | yes (regression protection) | - | git-based | - | - |
| PDF audit report | dark theme, single page | - | - | dashboard | - |
| Dependencies | Python stdlib only | Node.js | Python | SaaS | - |
| Price | Free (MIT) | Free / Pro | Free | $$$ | Free |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## License

MIT
