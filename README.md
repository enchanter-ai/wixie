# Flux
Open-source Claude Code plugin for prompt engineering that actually adapts to your model.

**Every technique accounted for.**

> Pasted the same prompt into Claude and GPT.
> Claude nailed it. GPT hallucinated the schema.
> Same prompt. Different models. That's the problem Flux solves.

## The Problem

Most prompt tools give you a template. Paste your task, get a wall of text, hope it works. But models aren't the same:

- **Chain-of-Thought** boosts GPT and cripples o3
- **XML tags** sharpen Claude and confuse Gemini
- **Few-shot examples** are mandatory for Gemini, wasted tokens for o-series

The prompting techniques that make one model sing make another one choke.

## What Flux Does

Give it a vague idea or an underperforming prompt. It reads your intent, selects from 16 prompting techniques, adapts the format to your target model, and explains every decision it made.

You get back:
1. **An enchanted prompt** — restructured for your target model
2. **An Enchantment Report** — which techniques, which avoided (and why), quality score
3. **Self-evaluation** — 5-axis scoring (Clarity, Completeness, Efficiency, Model Fit, Failure Resilience)

## Install

Start with prompt-crafter. It's the one you'll use most.

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

## 2 Plugins, 16 Techniques, 39 Models

| Plugin | What |
|--------|------|
| prompt-crafter | Creates new prompts — technique selection + model fitting + scoring |
| prompt-refiner | Improves existing prompts — diagnoses weaknesses, preserves intent |

| Model Family | Format | Key Adaptation |
|---|---|---|
| Claude 4.6 (Opus/Sonnet/Haiku) | XML tags | "Think thoroughly", no aggressive language |
| GPT-4.1 / 4o / 5 | Markdown | Sandwich method, explicit CoT |
| o-series (o1/o3/o4-mini) | Minimal | No CoT (built-in), developer messages |
| Gemini 2.5 / 3 | XML or Markdown | Always few-shot, temperature 1.0 |
| DeepSeek R1 / V3 | Markdown | R1: reasoning-native (no CoT), V3: explicit CoT |
| Grok 2 / 3 | Markdown | Less restrictive content policies |
| Qwen 2.5 / QwQ | Markdown | QwQ: reasoning-native, Qwen: strong multilingual |
| Llama 4 / 3 | Special tokens | Explicit CoT, clear delimiters |
| Mistral / Codestral | Markdown | Codestral: code-specialized, 80+ languages |
| Cohere Command R+ | Markdown | Strong RAG, native citations |
| Image Gen (DALL-E 3, MJ, SD, Flux) | Descriptors | Model-specific syntax, negative prompts |
| Video Gen (Runway Gen-3) | Natural language | Text/image-to-video |
| Audio (ElevenLabs, Suno) | Natural language | TTS/voice cloning, text-to-music |

## vs Everything Else

| | Flux | Generic Templates | Manual Prompting |
|---|---|---|---|
| Model-specific formatting | automatic | - | manual |
| Technique selection | 16 techniques, auto-routed | - | trial and error |
| Anti-pattern detection | warns you | - | - |
| Quality scoring | 5-axis heuristic | - | gut feeling |
| Explained reasoning | Enchantment Report | - | - |
| Dependencies | Python stdlib | varies | - |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## License

MIT
