#!/usr/bin/env bash
# Test: WIX-SEC-BRIEF-001 render-briefing refuses non-slug plugin names (exit 2) and never
# writes outside the resolved briefings directory; legitimate slugs render.
# See test_sec_brief_path.py.
set -euo pipefail
REPO_ROOT="${1:-.}"
python "$REPO_ROOT/tests/inference_engine/test_sec_brief_path.py"
