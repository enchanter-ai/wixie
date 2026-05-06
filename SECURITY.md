# Security Policy

## Reporting a vulnerability

**Do not open a public issue for security reports.** Use GitHub's private vulnerability reporting instead:

- **Primary channel:** [Open a private security advisory](https://github.com/enchanter-ai/wixie/security/advisories/new) on this repository.
- **Maintainer:** @klaiderman.

We treat reports confidentially. We will acknowledge receipt within 72 hours and share a remediation timeline within 7 days. Coordinated disclosure is strongly preferred — please do not disclose publicly until a fix has shipped or we have agreed on a disclosure date together.

## What to include

A good report has:

- A clear, reproducible proof-of-concept.
- The exact plugin / sub-plugin / command or hook involved.
- The version you observed the issue in (`/plugin list` output).
- Impact assessment: what can an attacker do, and under what preconditions.
- Suggested remediation, if you have one.

Minimal reports ("there's a bug") get triaged last. Be specific.

## Supported versions

The security fix window tracks the latest minor release on the latest major. Older majors receive fixes for critical issues only, at maintainer discretion.

| Version | Supported |
|---------|-----------|
| latest major | ✅ full support |
| previous major | 🟡 critical fixes only |
| older | ❌ not supported |

## Scope

In scope:

- Prompt-injection paths that cause the plugin to execute unintended actions.
- Credential / secret exposure in logs, artifacts, or hook output.
- Command-injection surfaces in hooks or helper scripts.
- Bypass of the shared [hooks contract](shared/foundations/conduct/hooks.md) — any hook that decides instead of advises.
- Supply-chain concerns in the renderer toolchain (`docs/assets/package.json`).

Out of scope:

- Vulnerabilities in Claude Code itself — report those at [anthropics/claude-code](https://github.com/anthropics/claude-code/issues).
- Vulnerabilities in external services (GitHub, marketplaces) — report to those vendors.
- Denial of service from obviously adversarial input that the plugin's documented contract does not promise to handle.

## Safe harbor

Good-faith security research that adheres to this policy is welcomed. We will not pursue legal action against researchers who:

- Make a reasonable effort to avoid privacy violations, data destruction, or service degradation.
- Report the vulnerability through the private channel above.
- Give us a reasonable window to remediate before public disclosure.

## Related documents

- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — community behavior
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution workflow
- [SUPPORT.md](SUPPORT.md) — where to ask non-security questions
