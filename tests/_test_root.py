"""Python side of the Wixie test temp-root contract (WIX-TEST-ENV-001).

Mirror of tests/lib/test-root.sh; read that file for the full contract. In short:
WIXIE_TEST_ROOT is the one private directory all test scratch derives from. Unset, it defaults
to <repo>/.test-root/standalone (gitignored). Set, it must be absolute and outside the shared
temp dirs (/tmp, /var/tmp, the real Windows %TEMP%), or ensure_test_root() raises. There is no
fallback to a global temp dir: after the call, TMPDIR/TMP/TEMP and tempfile.tempdir all point to
<root>/tmp and tempfile.gettempdir() is checked to resolve inside the root; GIT_CONFIG_GLOBAL
points to <root>/gitconfig, which holds only a throwaway test identity.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class TestRootError(RuntimeError):
    pass


def _shared_temp_dirs() -> list[Path]:
    dirs = [Path(p) for p in ("/tmp", "/var/tmp", "/usr/tmp", "/dev/shm")]
    for var, sub in (("LOCALAPPDATA", "Temp"), ("SYSTEMROOT", "Temp")):
        if os.environ.get(var):
            dirs.append(Path(os.environ[var]) / sub)
    return dirs


def _inside(child: Path, parent: Path) -> bool:
    c, p = os.path.normcase(str(child)), os.path.normcase(str(parent))
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def ensure_test_root() -> Path:
    raw = os.environ.get("WIXIE_TEST_ROOT") or str(REPO / ".test-root" / "standalone")
    root = Path(raw)
    if not root.is_absolute():
        raise TestRootError(f"WIXIE_TEST_ROOT must be an absolute path, got {raw!r}")
    root = Path(os.path.abspath(root))
    for shared in _shared_temp_dirs():
        if _inside(root, Path(os.path.abspath(shared))):
            raise TestRootError(f"WIXIE_TEST_ROOT {raw!r} is inside the shared temp dir {shared}")
    tmp = root / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    os.environ["WIXIE_TEST_ROOT"] = str(root)
    for var in ("TMPDIR", "TMP", "TEMP"):
        os.environ[var] = str(tmp)
    tempfile.tempdir = str(tmp)
    gitconfig = root / "gitconfig"
    if not gitconfig.exists():
        # Throwaway identity for fixture repos inside the root (same content as tests/lib/test-root.sh).
        gitconfig.write_text("[user]\n\tname = wixie-test\n\temail = wixie-test@example.invalid\n",
                             encoding="utf-8", newline="\n")
    os.environ["GIT_CONFIG_GLOBAL"] = str(gitconfig)
    if not _inside(Path(os.path.abspath(tempfile.gettempdir())), root):
        raise TestRootError(f"tempfile.gettempdir() {tempfile.gettempdir()} is outside {root}")
    return root
