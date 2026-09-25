#!/usr/bin/env bash
# Test: WIX-CONV-001 -- convergence.py's fixers may edit only "editable prose" (top-level
# prose and prose inside allow-listed XML instruction sections, never inside an inline
# bracket/quote/backtick span); fenced/indented code, tables, blockquotes, bracket (JSON)
# blocks, non-allow-listed XML elements, <example>/<examples> blocks and tag tokens stay
# content-equal. The accept/revert gate and every exit path (DEPLOY, plateau,
# max-iterations, crash) enforce a structural fingerprint; output-test.py's
# try_offline_fix shares the gate; line endings / BOM are preserved; deep nesting and
# large inputs stay fast. See test_structural_protection.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/convergence-engine/test_structural_protection.py" "$REPO_ROOT" >/dev/null
