# Changelog

All notable changes to `flux` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Tier-1 governance docs: `SECURITY.md`, `SUPPORT.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`.
- `.github/` scaffold: issue templates, PR template, CODEOWNERS, dependabot config.
- Tier-2 docs: `docs/getting-started.md`, `docs/installation.md`, `docs/troubleshooting.md`, `docs/glossary.md`, `docs/adr/README.md`.

## [3.0.0] — multi-agent pipeline, 64-model registry

The current shipped release. See [README.md](README.md) for the complete feature surface.

### Highlights
- 6 plugins spanning the prompt lifecycle: `prompt-crafter`, `prompt-refiner`, `convergence-engine`, `prompt-tester`, `prompt-harden`, `prompt-translate`.
- 7 managed agents across three tiers (Opus orchestrator, Sonnet executor, Haiku validator).
- 64-model registry with per-family format defaults (XML for Claude, Markdown-sandwich for GPT, stripped minimal for o-series, always-few-shot for Gemini).
- 6 named engines (E1 Gauss Convergence through E6 Gauss Accumulation) — formal derivations in [docs/science/README.md](docs/science/README.md).
- 5 scoring axes + 8 binary SAT assertions — DEPLOY / HOLD / FAIL verdict.
- 12-attack adversarial harden suite covering OWASP LLM Top 10.
- Self-learning across sessions via `learnings.md` (E6).
- Dark-themed single-page PDF audit report per prompt.

[Unreleased]: https://github.com/enchanted-plugins/flux/compare/v3.0.0...HEAD
[3.0.0]: https://github.com/enchanted-plugins/flux/releases/tag/v3.0.0
