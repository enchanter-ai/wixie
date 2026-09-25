#!/usr/bin/env python3
"""vendor-conduct.py - materialize the pinned shared conduct INTO each plugin.

WIX-DIST-001 / D13. A marketplace install (`/plugin install <p>@wixie`) copies
only `plugins/<p>/`; nothing from the repo root (CLAUDE.md, .vis-cache/,
.vis-lock, scripts/bootstrap.sh, shared/) reaches the installed plugin. So
every shared-conduct file a plugin references must live INSIDE the plugin:

    pinned vis package (.vis-lock, lock_version 2)
      -> deterministic materialization (this script: `git cat-file blob
         <tag_commit>:<path>`, the same pin + read-from-commit approach
         scripts/bootstrap.sh uses for the full-checkout .vis-cache/)
      -> plugins/<p>/vendor/ (committed, so a git-sourced marketplace
         install carries it)
      -> installed plugin-local shared conduct, referenced as
         ${CLAUDE_PLUGIN_ROOT}/vendor/<...>

vis stays the source of truth: nothing under plugins/*/vendor/ is edited by
hand. This script owns those directories completely (it deletes anything it
did not generate) and --check fails on any drift.

Reference syntax (the only one plugin files may use for shared conduct):

    ${CLAUDE_PLUGIN_ROOT}/vendor/vis/packages/<pkg>/<path>.md
        vis conduct, pinned by .vis-lock (byte-identical to the pinned commit)
    ${CLAUDE_PLUGIN_ROOT}/vendor/wixie/shared/conduct/<name>.md
        Wixie's own shared conduct (byte-identical to shared/conduct/<name>.md
        in this repo)

Claude Code substitutes ${CLAUDE_PLUGIN_ROOT} with the installed plugin root
in plugin skill content and plugin agent bodies, so the path the model sees is
the absolute installed location. A file-relative `@../../../.vis-cache/...`
form is refused: it is calibrated for the full-checkout depth and points
outside the installed plugin.

Modes:
    python scripts/vendor-conduct.py                     regenerate (needs the vis sibling)
    python scripts/vendor-conduct.py --check             drift check against the pinned vis
                                                         commit (needs the vis sibling)
    python scripts/vendor-conduct.py --check --offline   drift check without vis: vendored
                                                         bytes vs VENDORED.json, VENDORED.json
                                                         vs .vis-lock (pins + sha1)
Options:
    --vis-dir <dir>   vis checkout (default: <repo>/../vis, like bootstrap.sh)
    --repo <dir>      Wixie repo root (default: this script's parent's parent)

Exit codes: 0 ok, 1 drift / unresolved input, 2 usage error.
Stdlib only. Never fetches, never writes to the vis checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCHEMA = "wixie/vendored-conduct/v1"
VENDOR_DIRNAME = "vendor"
MANIFEST_NAME = "VENDORED.json"
LOCK_SCHEMA_VERSION = "2"

# Canonical reference: ${CLAUDE_PLUGIN_ROOT}/vendor/<rel>
REF_RE = re.compile(
    rb"\$\{CLAUDE_PLUGIN_ROOT\}/vendor/"
    rb"((?:vis/packages/[a-z][a-z0-9_-]*/[A-Za-z0-9._/-]+|wixie/shared/conduct/[A-Za-z0-9._-]+)\.md)"
)
# Anything that names shared conduct but is NOT the canonical form. Checked
# after the canonical references are blanked out of the text.
STALE_RES = [
    (re.compile(rb"\.vis-cache/[A-Za-z0-9._/-]+\.md"),
     "reference into the repo-root .vis-cache/ (not shipped with an installed plugin)"),
    (re.compile(rb"packages/[a-z][a-z0-9_-]*/conduct/[A-Za-z0-9._*-]+\.md"),
     "vis conduct path outside ${CLAUDE_PLUGIN_ROOT}/vendor/vis/"),
    (re.compile(rb"shared/(?:vis/)?conduct/[A-Za-z0-9._*-]+\.md"),
     "shared/conduct path outside ${CLAUDE_PLUGIN_ROOT}/vendor/wixie/"),
]
# Plugin subtrees that are not scanned for references: the generated vendor
# tree itself, and state/ (runtime data logs such as artifacts.jsonl, which
# quote historical file names as data, not as references).
SKIP_TOP = {VENDOR_DIRNAME, "state"}


class Drift(Exception):
    pass


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


# --- .vis-lock / .vis-versions ------------------------------------------------

def parse_lock(path: Path) -> dict:
    """Parse the lock_version 2 layout written by scripts/bootstrap.sh."""
    if not path.is_file():
        raise Drift(f"missing {path} - run ./scripts/bootstrap.sh first")
    top: dict = {}
    pkgs: dict = {}
    conduct: dict = {}
    state, cur_pkg, cur_path = "top", None, None
    for n, raw in enumerate(path.read_bytes().decode("utf-8").splitlines(), 1):
        line = raw.rstrip("\r")
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s?(.*)$", line)
        if m:
            key, val = m.groups()
            if key in top:
                raise Drift(f".vis-lock: duplicate top-level key {key} (line {n})")
            top[key] = val
            state = {"packages": "packages", "conduct_files": "conduct"}.get(key, "top")
            continue
        if state in ("packages", "pkg"):
            m = re.match(r"^  ([a-z][a-zA-Z0-9_]*):\s*$", line)
            if m:
                cur_pkg = m.group(1)
                if cur_pkg in pkgs:
                    raise Drift(f".vis-lock: duplicate package block {cur_pkg} (line {n})")
                pkgs[cur_pkg] = {}
                state = "pkg"
                continue
            m = re.match(r"^    (version|tag|tag_commit):\s?(.*)$", line)
            if m and state == "pkg":
                pkgs[cur_pkg][m.group(1)] = m.group(2)
                continue
        if state == "conduct":
            m = re.match(r"^  - path:\s?(.*)$", line)
            if m:
                cur_path = m.group(1)
                conduct[cur_path] = None
                continue
            m = re.match(r"^    sha1:\s?(.*)$", line)
            if m and cur_path is not None:
                conduct[cur_path] = m.group(1)
                continue
        raise Drift(f".vis-lock: unparsed line {n}: {line!r}")
    if top.get("lock_version") != LOCK_SCHEMA_VERSION:
        raise Drift(f".vis-lock: lock_version {top.get('lock_version')!r}, expected {LOCK_SCHEMA_VERSION}")
    if top.get("mode") != "pinned":
        raise Drift(f".vis-lock: mode {top.get('mode')!r}; vendoring only ever uses a pinned lock")
    for p, f in pkgs.items():
        if set(f) != {"version", "tag", "tag_commit"} or not re.fullmatch(r"[0-9a-f]{40}", f["tag_commit"]):
            raise Drift(f".vis-lock: package {p} block incomplete or malformed: {f}")
    return {"packages": pkgs, "conduct_sha1": conduct}


def parse_versions(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r'^([a-z]+):\s*"?[~^]?([0-9][^"\s]*)"?\s*$', line)
        if m:
            out[m.group(1)] = "v" + m.group(2)
    return out


# --- reference discovery ------------------------------------------------------

def plugin_dirs(repo: Path) -> list[Path]:
    return sorted(p for p in (repo / "plugins").iterdir()
                  if (p / ".claude-plugin" / "plugin.json").is_file())


def scanned_files(plugin: Path):
    for f in sorted(plugin.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(plugin)
        if rel.parts[0] in SKIP_TOP:
            continue
        yield f


def discover(plugin: Path) -> tuple[set[str], list[str]]:
    """Return (canonical vendor-relative refs, stale-reference problems)."""
    refs: set[str] = set()
    stale: list[str] = []
    for f in scanned_files(plugin):
        data = f.read_bytes()
        if b"\0" in data:
            continue
        for m in REF_RE.finditer(data):
            refs.add(m.group(1).decode())
        blanked = REF_RE.sub(b"", data)
        seen_lines: set[int] = set()
        for rx, why in STALE_RES:
            for m in rx.finditer(blanked):
                line = blanked.count(b"\n", 0, m.start()) + 1
                if line not in seen_lines:
                    seen_lines.add(line)
                    stale.append(f"{f.relative_to(plugin.parent.parent).as_posix()}:{line}: {why}")
    return refs, stale


# --- expected content -----------------------------------------------------------

def git_blob(vis: Path, commit: str, path: str) -> bytes:
    r = subprocess.run(["git", "-C", str(vis), "cat-file", "blob", f"{commit}:{path}"],
                       capture_output=True)
    if r.returncode != 0:
        raise Drift(f"{path} does not exist at pinned commit {commit}")
    return r.stdout


def resolve_tag(vis: Path, tag: str) -> str:
    r = subprocess.run(["git", "-C", str(vis), "rev-parse", "--verify", "--quiet",
                        f"refs/tags/{tag}^{{commit}}"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise Drift(f"vis tag {tag} not found in {vis} (this script never fetches)")
    return r.stdout.strip()


def expected_for(repo: Path, lock: dict, refs: set[str], vis: Path | None) -> dict[str, dict]:
    """Map vendor-relative path -> {"entry": manifest entry, "bytes": content or None}.

    With vis=None (offline) the vis content is not available; entries carry
    the pin fields only and "bytes" is None.
    """
    out: dict[str, dict] = {}
    for rel in sorted(refs):
        if rel.startswith("vis/"):
            src = rel[len("vis/"):]
            pkg = src.split("/")[1]
            pin = lock["packages"].get(pkg)
            if pin is None:
                raise Drift(f"reference to vis package '{pkg}' ({rel}) not pinned in .vis-lock")
            entry = {"path": rel, "source": "vis", "source_path": src, "package": pkg,
                     "version": pin["version"], "tag": pin["tag"], "tag_commit": pin["tag_commit"]}
            content = git_blob(vis, pin["tag_commit"], src) if vis is not None else None
        else:
            src = rel[len("wixie/"):]
            f = repo / src
            if not f.is_file():
                raise Drift(f"reference {rel}: {src} does not exist in this repo")
            entry = {"path": rel, "source": "wixie", "source_path": src}
            content = f.read_bytes()
        if content is not None:
            entry["sha256"] = sha256(content)
            entry["sha1"] = sha1(content)
        out[rel] = {"entry": entry, "bytes": content}
    return out


def manifest_bytes(entries: list[dict]) -> bytes:
    doc = {
        "schema": SCHEMA,
        "generated_by": "scripts/vendor-conduct.py",
        "do_not_edit": "generated; regenerate with `python scripts/vendor-conduct.py`, verify with --check",
        "files": entries,
    }
    return (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")


def on_disk(vdir: Path) -> set[str]:
    if not vdir.is_dir():
        return set()
    return {f.relative_to(vdir).as_posix() for f in vdir.rglob("*") if f.is_file()}


# --- modes ----------------------------------------------------------------------

def check_pins(repo: Path, lock: dict, vis: Path) -> list[str]:
    problems = []
    declared = parse_versions(repo / ".vis-versions")
    for pkg, pin in sorted(lock["packages"].items()):
        if declared.get(pkg) != pin["version"]:
            problems.append(f".vis-lock package {pkg} version {pin['version']} != .vis-versions {declared.get(pkg)}")
        try:
            actual = resolve_tag(vis, pin["tag"])
        except Drift as e:
            problems.append(str(e))
            continue
        if actual != pin["tag_commit"]:
            problems.append(f"tag {pin['tag']} resolves to {actual}, .vis-lock pins {pin['tag_commit']} (moved tag?)")
    return problems


def run(repo: Path, vis: Path | None, mode: str) -> int:
    lock = parse_lock(repo / ".vis-lock")
    problems: list[str] = []
    if vis is not None:
        if not (vis / ".git").exists():
            raise Drift(f"vis checkout not found at {vis} (use --vis-dir, or --check --offline)")
        problems += check_pins(repo, lock, vis)
        if problems:
            raise Drift("\n".join(problems))
    total = 0
    plans: list = []
    for plugin in plugin_dirs(repo):
        name = plugin.name
        vdir = plugin / VENDOR_DIRNAME
        refs, stale = discover(plugin)
        problems += stale
        exp = expected_for(repo, lock, refs, vis)
        total += len(exp)

        if mode == "write":
            plans.append((name, vdir, exp))
            continue

        # --- check (full or offline) ---
        have = on_disk(vdir)
        want = set(exp) | ({MANIFEST_NAME} if exp else set())
        for extra in sorted(have - want):
            problems.append(f"{name}: extra file in vendor/: {extra} (not referenced by the plugin)")
        for miss in sorted(want - have):
            problems.append(f"{name}: missing vendored file: vendor/{miss}")
        if not exp:
            continue
        mpath = vdir / MANIFEST_NAME
        try:
            manifest = json.loads(mpath.read_bytes().decode("utf-8")) if mpath.is_file() else None
        except ValueError as e:
            problems.append(f"{name}: {MANIFEST_NAME} unparseable: {e}")
            manifest = None
        if vis is not None:
            # Full check: every vendored byte is re-derived from the pinned commit.
            for rel, e in exp.items():
                f = vdir / rel
                if f.is_file() and f.read_bytes() != e["bytes"]:
                    problems.append(f"{name}: vendor/{rel} is not byte-identical to {e['entry'].get('tag_commit', 'repo')}:{e['entry']['source_path']}")
            if mpath.is_file() and mpath.read_bytes() != manifest_bytes([e["entry"] for e in exp.values()]):
                problems.append(f"{name}: {MANIFEST_NAME} differs from the regenerated manifest")
            continue
        # Offline check: manifest <-> files <-> .vis-lock, no vis access.
        if manifest is None or manifest.get("schema") != SCHEMA:
            problems.append(f"{name}: {MANIFEST_NAME} missing or wrong schema")
            continue
        m_entries = {e.get("path"): e for e in manifest.get("files", [])}
        if set(m_entries) != set(exp):
            problems.append(f"{name}: {MANIFEST_NAME} entry set {sorted(m_entries)} != referenced set {sorted(exp)}")
        for rel, e in exp.items():
            me = m_entries.get(rel)
            f = vdir / rel
            if me is None or not f.is_file():
                continue
            b = f.read_bytes()
            if sha256(b) != me.get("sha256") or sha1(b) != me.get("sha1"):
                problems.append(f"{name}: vendor/{rel} does not match its {MANIFEST_NAME} hash")
            for k in ("source", "source_path", "package", "version", "tag", "tag_commit"):
                if e["entry"].get(k) != me.get(k):
                    problems.append(f"{name}: {MANIFEST_NAME} {rel} field {k}={me.get(k)!r}, expected {e['entry'].get(k)!r}")
            if e["entry"]["source"] == "vis":
                locked = lock["conduct_sha1"].get(e["entry"]["source_path"])
                if locked is None:
                    problems.append(f"{name}: {rel} is not covered by .vis-lock conduct_files; run the full --check against vis")
                elif locked != sha1(b):
                    problems.append(f"{name}: vendor/{rel} sha1 {sha1(b)} != .vis-lock sha1 {locked}")
            elif e["bytes"] is not None and b != e["bytes"]:
                problems.append(f"{name}: vendor/{rel} is not byte-identical to {e['entry']['source_path']}")
    if problems:
        raise Drift("\n".join(problems) + ("\nnothing was written" if mode == "write" else ""))
    if mode == "write":
        # Only after every plugin resolved cleanly: replace each vendor/ tree.
        for name, vdir, exp in plans:
            if vdir.exists():
                shutil.rmtree(vdir)
            if not exp:
                continue
            for rel, e in exp.items():
                dest = vdir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(e["bytes"])
            (vdir / MANIFEST_NAME).write_bytes(manifest_bytes([e["entry"] for e in exp.values()]))
            print(f"{name}: vendored {len(exp)} conduct file(s)")
        print(f"vendored {total} conduct file(s) from the pin in .vis-lock")
    else:
        print(f"vendored conduct OK ({'offline: manifest + .vis-lock' if vis is None else 'byte-identical to the pinned vis commit'}): {total} file(s)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--vis-dir")
    ap.add_argument("--repo")
    a = ap.parse_args(argv)
    if a.offline and not a.check:
        ap.error("--offline is only valid with --check")
    if a.offline and a.vis_dir:
        ap.error("--offline does not read vis; drop --vis-dir")
    repo = Path(a.repo).resolve() if a.repo else Path(__file__).resolve().parent.parent
    vis = None if a.offline else (Path(a.vis_dir).resolve() if a.vis_dir else repo.parent / "vis")
    try:
        return run(repo, vis, "check" if a.check else "write")
    except Drift as e:
        print(f"vendor-conduct: FAILED\n{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
