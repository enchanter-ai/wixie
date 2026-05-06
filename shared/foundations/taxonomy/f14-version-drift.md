# F14 — Version Drift

## Signature

Agent uses an API, model ID, flag, dependency version, or syntax that *used to be valid* and no longer is. Distinct from F02 fabrication (which invents things that never existed) — version drift uses real things that have moved.

Common shapes:

- Cites a model ID that has been retired (`text-davinci-003`, `claude-1`, `gpt-4-32k`).
- Uses a deprecated method (`request.body()` instead of `request.json()`).
- Imports from a package path that moved between major versions.
- Recommends a CLI flag that was renamed two releases ago.
- Cites an RFC / spec at a version that has been superseded.

## Counter

Verify against current source:

1. **Model IDs** → check the model registry / capability list of the relevant vendor.
2. **APIs** → run a docs lookup or `--help` for the current version installed.
3. **Imports** → check the package's current README or CHANGELOG.
4. **Specs / RFCs** → cite both the title and the version; verify the version is current.

When citing a fact, include a `date` field or version marker so downstream consumers can weight by freshness.

## Examples

1. Agent recommends `model: "text-davinci-003"` in 2026. That ID was retired. **Counter:** Check the model registry; pick a current ID. Use the `date` field on cited facts so downstream readers see the source's age.

2. Agent imports `from urllib2 import urlopen` in Python 3 code. That module was renamed to `urllib.request` in Python 3.0. **Counter:** Verify imports against the project's Python version.

3. Agent suggests `npm install --save foo`. The `--save` flag has been default since npm 5.0; passing it now is harmless but obsolete. The agent's training data is older than the change. **Counter:** Check current npm docs.

4. Agent quotes a section number from RFC 6750; the cited section is from RFC 6749 (the predecessor). **Counter:** Verify the RFC number along with the section.

## Adjacent codes

- **F02 fabrication** — fabrication invents things that never existed; version drift uses real things that moved. Distinguished by whether the citation *ever* matched reality.
- **F08 tool mis-invocation** — mis-invocation uses a real tool wrong; version drift uses a real tool that's been *replaced*.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Regenerate against the current registry / docs |
| 3+ in one workflow | The agent's grounding source is stale — refresh model registries and dep lockfiles before continuing |
