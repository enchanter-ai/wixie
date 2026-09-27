#!/usr/bin/env bash
# Test: WIX-SEC-REPORT-VERDICT-001 report-gen presents only the canonical DEPLOY bar
# (shared/scripts/deploy_bar.py, shared with convergence.py): 7/8 SAT, a failed sigma, an axis
# in [5,7), metadata claiming deploy, or missing evidence never render DEPLOY; the HTML verdict,
# badge and machine-readable status agree; vendored copies behave identically. Offline; no
# model, no browser (HTML fallback).
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/distribution/test_report_verdict.py"
