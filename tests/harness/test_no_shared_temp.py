"""Static guard for the private test temp-root contract (WIX-TEST-ENV-001).

Offline, reads files only. Fails if a test file (tests/**/*.sh, tests/**/*.py) reintroduces a
path outside WIXIE_TEST_ROOT: a literal /tmp or /var/tmp path, a bare mktemp (only
tests/lib/test-root.sh and tests/run-all.sh may call mktemp, always with a template inside the
root), a TMPDIR/TMP/TEMP reassignment to a repo or absolute path, a user-home config path, or a
scratch-creating test that does not load the root helper. Comment lines, and lines carrying a
`wixie-temp-ok: <reason>` marker (e.g. a read-only listing of shared /tmp), are ignored.

Repo under test: WIXIE_STATIC_REPO if set (used to show the guard fails on an older tree),
else this checkout.
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

REPO = Path(os.environ.get("WIXIE_STATIC_REPO") or Path(__file__).resolve().parents[2])
HELPERS = {"tests/lib/test-root.sh", "tests/_test_root.py", "tests/harness/test_no_shared_temp.py"}
MKTEMP_ALLOWED = {"tests/lib/test-root.sh", "tests/run-all.sh"}

RULES = [
    ("literal shared temp path",
     re.compile(r"""(^|[\s"'=(<>:,\[])(/var)?/tmp([/"'\s)\]]|$)""")),
    ("user-home config path",
     re.compile(r"""~/\.|\$\{?HOME\b|%USERPROFILE%|\$env:USERPROFILE|\bUSERPROFILE\b|expanduser\(|Path\.home\(|\.gitconfig\b|XDG_CONFIG_HOME|AppData[/\\]Local[/\\]Temp""")),
    ("temp var reassigned outside the root",
     re.compile(r"""(^|[\s;])(export\s+)?(TMPDIR|TMP|TEMP)=["']?(/|\$\{?REPO_ROOT)""")),
]
MKTEMP = re.compile(r"\bmktemp\b")
SH_SCRATCH = re.compile(
    r"wixie_mktemp_d|tempfile|mkdtemp|TemporaryDirectory|html-to-pdf\.py|report-gen\.py|"
    r"efficacy-replay\.py|inference-stress\.py|convergence\.py|scripts/bootstrap\.(sh|ps1)")
SH_SOURCES_HELPER = re.compile(r"""^\s*(source|\.)\s+.*lib/test-root\.sh""", re.M)
PY_TEMPFILE = re.compile(r"^\s*(import tempfile|from tempfile import)|\btempfile\.", re.M)
PY_ENSURES = re.compile(r"ensure_test_root|^\s*(from tests\.inference_engine )?import _support|_support as S", re.M)


def test_files() -> list[Path]:
    root = REPO / "tests"
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in (".sh", ".py")
                  and "fixtures" not in p.relative_to(root).parts and "__pycache__" not in p.parts)


def code_lines(text: str):
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#") or "wixie-temp-ok:" in line:
            continue
        yield n, line


def violations() -> list[str]:
    out = []
    for path in test_files():
        rel = path.relative_to(REPO).as_posix()
        if rel in HELPERS:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, line in code_lines(text):
            for name, rx in RULES:
                if rx.search(line):
                    out.append(f"{rel}:{n}: {name}: {line.strip()[:120]}")
            if MKTEMP.search(line) and rel not in MKTEMP_ALLOWED:
                out.append(f"{rel}:{n}: bare mktemp (use wixie_mktemp_d): {line.strip()[:120]}")
        code = "\n".join(line for _, line in code_lines(text))
        if path.suffix == ".sh" and path.name.startswith("test-") and SH_SCRATCH.search(code) \
                and not SH_SOURCES_HELPER.search(text):
            out.append(f"{rel}: creates scratch but does not source tests/lib/test-root.sh")
        if path.suffix == ".py" and PY_TEMPFILE.search(code) and not PY_ENSURES.search(text):
            out.append(f"{rel}: uses tempfile but never calls ensure_test_root (tests/_test_root.py)")
    return out


class NoSharedTemp(unittest.TestCase):
    def test_helpers_exist(self):
        for rel in ("tests/lib/test-root.sh", "tests/_test_root.py"):
            self.assertTrue((REPO / rel).is_file(), f"missing {rel}")

    def test_no_shared_temp_paths(self):
        found = violations()
        self.assertEqual(found, [], "shared temp/home paths in tests:\n" + "\n".join(found))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
