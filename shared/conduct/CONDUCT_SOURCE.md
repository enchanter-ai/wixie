# Conduct module source

The canonical home of these conduct modules is `enchanter-ai/agent-foundations/conduct/`.

This local copy MUST match the canonical version exactly. The
`conduct-abi.yml` GitHub Actions workflow enforces this on every push and
PR — drift fails the build.

To update a conduct module:
1. Open a PR against `enchanter-ai/agent-foundations`.
2. After merge, run `bash agent-foundations/scripts/conduct-sync.sh <repo>` (operator script — see agent-foundations/scripts/) to propagate.
3. The local conduct-abi.yml will go green once propagated.

This is the F-026 (single-source) + F-008 (ABI test) contract.
