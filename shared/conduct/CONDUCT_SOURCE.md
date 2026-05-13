# Conduct module source

The canonical home of these conduct modules is `enchanter-ai/vis/conduct/`.

This local copy MUST match the canonical version exactly. The
`conduct-abi.yml` GitHub Actions workflow enforces this on every push and
PR — drift fails the build.

To update a conduct module:
1. Open a PR against `enchanter-ai/vis`.
2. After merge, run `bash vis/scripts/conduct-sync.sh <repo>` (operator script — see vis/scripts/) to propagate.
3. The local conduct-abi.yml will go green once propagated.

This is the F-026 (single-source) + F-008 (ABI test) contract.
