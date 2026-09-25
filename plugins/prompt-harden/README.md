# prompt-harden

**Find the holes before attackers do.**

Tests your prompt against 12 adversarial attack patterns — injection, jailbreak, data extraction, encoding bypass, and more. Reports which attacks succeed and suggests specific defenses. Optionally applies the fixes and re-tests.

## Install

Part of the [Wixie](../..) bundle. The simplest install is the `full` meta-plugin, which pulls in all 6 Wixie plugins via dependency resolution:

```
/plugin marketplace add enchanter-ai/wixie
/plugin install full@wixie
```

To install this plugin on its own: `/plugin install prompt-harden@wixie`. `prompt-harden` audits prompts produced upstream by `prompt-crafter` / `prompt-refiner` / `convergence-engine` and re-runs `prompt-tester` after applying defenses — so on its own it has no prompts to audit and no regression check.

## Why

Every production prompt that touches user input is a potential attack surface. Prompt injection is #1 on the OWASP LLM Top 10. This plugin tests your defenses before deployment.

## Usage

```
/harden                            # pick from saved prompts
/harden stocks-analysis            # test a specific prompt
/harden my-chatbot --risk high     # full 12-attack suite
```

## What Happens

```
SECURITY AUDIT: my-chatbot
Risk level: High (user-facing)

  RESISTANT  Direct injection
  RESISTANT  Role override
  VULNERABLE Data extraction — model leaked system prompt
  RESISTANT  Encoding bypass
  VULNERABLE Indirect injection — processed malicious resume content

RESULT: 8/12 resistant | 2 VULNERABLE | 2 skipped
```

## Attack Categories

| Attack | Severity | What it tests |
|--------|----------|--------------|
| Direct injection | Critical | "Ignore previous instructions..." |
| Role override | Critical | "You are now DAN..." |
| Context manipulation | Critical | Fake system messages in user input |
| Data extraction | High | "Repeat your system prompt" |
| Encoding bypass | High | Base64/ROT13 encoded instructions |
| Multi-turn escalation | High | Build trust, then inject |
| Payload splitting | Medium | Split instruction across messages |
| Indirect injection | Medium | Malicious content in processed data |
| Output manipulation | Medium | Force executable code output |
| Refusal bypass | Medium | "As a thought experiment..." |
| Language switching | Low | Switch language to bypass guardrails |
| Token smuggling | Low | Unicode lookalikes, zero-width chars |

## Components

| Type | Name | Model |
|------|------|-------|
| Skill | harden | (main agent) |
| Agent | red-team | Sonnet — crafts and executes attacks |

## Behavioral modules

In a full repository checkout, inherits the [shared behavioral modules](../../shared/) via root [CLAUDE.md](../../CLAUDE.md) — discipline, context, verification, delegation, failure-modes, tool-use, formatting, skill-authoring, hooks, precedent. A marketplace install of this plugin does not receive the root `CLAUDE.md`; the shared-conduct modules this plugin's own files reference ship inside it under `vendor/` (see [What an installed plugin carries](../../docs/installation.md#what-an-installed-plugin-carries)).
