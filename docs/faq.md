# Frequently asked questions

Quick answers to questions that don't yet have their own doc. For anything deeper, follow the links — the full answer usually lives in a neighboring file.

## What's the difference between Wixie and the other siblings?

Wixie answers *"what did I say?"* — it engineers the prompt you send to a model. Sibling plugins answer different questions in the same session: Emu tracks token spend, Crow watches change trust, Hydra scans for security surface, Sylph coordinates git workflow. All are independent installs; none require the others. See [docs/ecosystem.md](ecosystem.md) for the full map.

## Do I need the other siblings to use Wixie?

No. Wixie is self-contained — install `full@wixie` and every command works standalone. The siblings compose if you install them, but nothing in Wixie depends on another repo being present.

## How do I report a bug vs. ask a question vs. disclose a security issue?

- **Security vulnerability** — private advisory, never a public issue. See [SECURITY.md](../SECURITY.md).
- **Reproducible bug** — a bug report issue with repro steps + exact versions.
- **Usage question or half-formed idea** — [Discussions](https://github.com/enchanter-ai/wixie/discussions).

The [SUPPORT.md](../SUPPORT.md) page has the exact links for each.

## Is Wixie an official Anthropic product?

No. Wixie is an independent open-source plugin for [Claude Code](https://github.com/anthropics/claude-code) (Anthropic's CLI). It's published by [enchanter-ai](https://github.com/enchanter-ai) under the MIT license and is not affiliated with, endorsed by, or supported by Anthropic.

## Can I use Wixie with models outside the 274-model registry?

Partially. The convergence engine and SAT assertions work on any prompt text, but format adaptation (XML for Claude, Markdown-sandwich for GPT, minimal for o-series, always-few-shot for Gemini) relies on the registry entry. If your target model is not listed in `shared/models-registry.json`, Wixie will stop and ask rather than guess — see the "ESCALATE on unknown target model" rule in [CLAUDE.md](../CLAUDE.md). Adding a new registry entry is a normal contribution path; the schema lives alongside the existing entries.

## Why does `/converge` sometimes end in HOLD instead of DEPLOY?

HOLD means the convergence run hit a plateau — σ is still too high, an axis is still under 7.0, or an assertion is still failing, and the engine ran out of hypotheses that wouldn't cause a regression. Read `learnings.md` in the prompt folder; it records every hypothesis tried and why it was reverted. The fix is usually to adjust the source brief (more context, clearer constraints) rather than retry verbatim.
