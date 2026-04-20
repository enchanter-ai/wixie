# Support

Short version: **pick the right channel, and you'll get an answer faster.**

## Where to go

| You have a… | Go to |
|-------------|-------|
| Security vulnerability | [Private security advisory](https://github.com/enchanted-plugins/flux/security/advisories/new) — **never** a public issue. See [SECURITY.md](SECURITY.md). |
| Reproducible bug | [Bug report issue](https://github.com/enchanted-plugins/flux/issues/new?template=bug_report.md). Include repro steps, versions, exact error. |
| Concrete feature proposal | [Feature request issue](https://github.com/enchanted-plugins/flux/issues/new?template=feature_request.md). Half-formed ideas → Discussions first. |
| Usage question | [Discussions → Q&A](https://github.com/enchanted-plugins/flux/discussions/categories/q-a) |
| Show-and-tell, idea, or discussion | [Discussions → Ideas / Show & Tell](https://github.com/enchanted-plugins/flux/discussions) |
| Wanted something that already exists | Read the docs list below first. |

## Before filing

1. **Search first.** Existing issues + Discussions. Duplicates get closed without comment.
2. **Read the docs.** Most questions are answered in one of these:
   - [README.md](README.md) — overview, install, what the plugin does
   - [docs/getting-started.md](docs/getting-started.md) — 5-minute first run
   - [docs/installation.md](docs/installation.md) — all install paths
   - [docs/troubleshooting.md](docs/troubleshooting.md) — common failures + fixes
   - [docs/architecture/](docs/architecture/) — diagrams of what runs when
   - [docs/science/README.md](docs/science/README.md) — the algorithms, derived
3. **Narrow the bug.** "It sometimes fails" is not reproducible. Minimize the failing case.
4. **Check the ecosystem.** This plugin is one of several in [`enchanted-plugins`](https://github.com/enchanted-plugins/flux/blob/main/docs/ecosystem.md). Your question may belong in a sibling repo.

## Response expectations

This is a community-maintained project. We answer when we can, usually within a few days.

- **Security reports**: acknowledged within 72 hours (see [SECURITY.md](SECURITY.md)).
- **Bug reports**: triaged roughly weekly. High-signal reports (clear repro, exact versions) move fastest.
- **Feature requests**: considered at roadmap review time, not on demand.
- **Questions in Discussions**: community-first — maintainers chime in when the question is about internals.

## What we can't help with

- Questions about Claude Code itself → [anthropics/claude-code](https://github.com/anthropics/claude-code).
- Prompt-engineering help for your specific app → this is not a consulting service. Flux is the enchanted-plugins product for that.
- "Please review my pull request faster" → opening a second issue about it doesn't help.

Thanks for using an @enchanted-plugins product.
