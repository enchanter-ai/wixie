#!/usr/bin/env python3
"""
rebrand.py — renames old plugin names to new modded-MC entity names across a repo.

Old -> New:
    Emu  -> Emu       (F)
    Wixie   -> Wixie     (W)
    Crow -> Crow     (R)
    Hydra -> Hydra     (H)
    Sylph -> Sylph     (S)
    Lich -> Lich      (L)
    Pech   -> Pech      (P)

Default mode is dry-run. Path-looking matches (bracketed by / or \\) are skipped
unless --include-paths is passed, so the user can rename folders separately.

Usage:
    python rebrand.py --root <path>                # dry-run, prints diffs
    python rebrand.py --root <path> --apply        # write changes in place
    python rebrand.py --root <path> --include-paths --apply   # also rewrite paths
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
from pathlib import Path

MAPPING = {
    "emu": "emu",
    "faes": "emu",
    "wixie": "wixie",
    "wixiees": "wixies",
    "crow": "crow",
    "ravens": "ravens",
    "hydra": "hydra",
    "hydras": "hydras",
    "sylph": "sylph",
    "sylphs": "sylphs",
    "lich": "lich",
    "liches": "liches",
    "pech": "pech",
    "pechs": "pechs",
}

TEXT_EXTS = {
    ".md", ".txt", ".rst",
    ".py", ".sh", ".bash", ".zsh", ".ps1",
    ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".html", ".css", ".scss", ".sass",
    ".cff", ".xml", ".svg",
}

NAMELESS_TEXT = {
    "README", "LICENSE", "CHANGELOG", "CONTRIBUTING", "CODE_OF_CONDUCT",
    "SECURITY", "SUPPORT", "AUTHORS", "NOTICE",
    "Dockerfile", "Makefile",
}

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", "dist", "build",
    ".venv", "venv", ".mypy_cache", ".pytest_cache",
    ".next", ".nuxt", ".cache", "coverage",
}

SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock",
    "poetry.lock", "Cargo.lock", "Gemfile.lock",
    "rebrand.py",  # don't rename the rename script
}


def preserve_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper() and source[1:].islower():
        return replacement.capitalize()
    if source.islower():
        return replacement.lower()
    return replacement.lower()


def build_regex() -> re.Pattern:
    keys = sorted(MAPPING.keys(), key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b", re.IGNORECASE)


PATTERN = build_regex()


def is_path_context(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    return before in "/\\" or after in "/\\"


def replace_in_text(text: str, include_paths: bool) -> tuple[str, int]:
    count = 0

    def sub(m: re.Match) -> str:
        nonlocal count
        if not include_paths and is_path_context(text, m.start(), m.end()):
            return m.group(0)
        original = m.group(0)
        replacement = MAPPING[original.lower()]
        count += 1
        return preserve_case(original, replacement)

    new_text = PATTERN.sub(sub, text)
    return new_text, count


def is_text_file(path: Path) -> bool:
    if path.name in SKIP_FILES:
        return False
    if path.suffix.lower() in TEXT_EXTS:
        return True
    if path.stem in NAMELESS_TEXT or path.name in NAMELESS_TEXT:
        return True
    return False


def walk_repo(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if is_text_file(path):
                yield path


def process_file(path: Path, include_paths: bool, apply: bool) -> tuple[int, str]:
    try:
        original = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError, OSError):
        return 0, ""
    new_text, count = replace_in_text(original, include_paths=include_paths)
    if count == 0:
        return 0, ""
    if apply:
        path.write_text(new_text, encoding="utf-8")
    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=str(path),
        tofile=str(path),
        n=1,
    ))
    return count, diff


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebrand old plugin names across a repo.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run).")
    parser.add_argument("--include-paths", action="store_true", help="Rewrite path-context refs too.")
    parser.add_argument("--max-diff-files", type=int, default=30)
    parser.add_argument("--quiet", action="store_true", help="Suppress per-file diffs.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    total_files = 0
    total_replacements = 0
    diffs_shown = 0
    show_diff = not args.quiet

    for path in walk_repo(root):
        count, diff = process_file(path, include_paths=args.include_paths, apply=args.apply)
        if count > 0:
            total_files += 1
            total_replacements += count
            if show_diff and diffs_shown < args.max_diff_files:
                sys.stdout.write(diff)
                diffs_shown += 1

    mode = "APPLIED" if args.apply else "DRY-RUN"
    paths_flag = " +paths" if args.include_paths else ""
    sys.stderr.write(f"\n[{mode}{paths_flag}] {total_files} files, {total_replacements} replacements\n")
    if show_diff and total_files > diffs_shown:
        sys.stderr.write(f"(showed {diffs_shown} diffs; {total_files - diffs_shown} more — bump --max-diff-files)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
