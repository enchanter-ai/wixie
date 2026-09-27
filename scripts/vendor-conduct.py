#!/usr/bin/env python3
"""vendor-conduct.py - materialize each plugin's runtime dependency closure INTO the plugin.

WIX-DIST-001 / D13 (shared conduct) and WIX-DIST-002 / D14 (runtime closure). A
marketplace install (`/plugin install <p>@wixie`) copies only `plugins/<p>/`;
nothing from the repo root (CLAUDE.md, .vis-cache/, shared/, scripts/) reaches
the installed plugin. So every file a plugin's skills, agents, hooks and
scripts need at runtime must live INSIDE the plugin:

    authoritative sources
      vis   : the pinned vis commit (.vis-lock, lock_version 2), read with
              `git cat-file blob <tag_commit>:<path>` like scripts/bootstrap.sh
      wixie : this repository's shared/ tree (working tree; each entry records
              the git blob id of the bytes it was generated from)
      -> transitive dependency closure (this script)
      -> plugins/<p>/vendor/<source>/<source path>  (committed; a git-sourced
         marketplace install has no build step)
      -> installed plugin, referenced as ${CLAUDE_PLUGIN_ROOT}/vendor/<...>

The closure is computed, never listed by hand:
  roots   every `${CLAUDE_PLUGIN_ROOT}/vendor/(vis|wixie)/<path>` in a plugin file
          (skills, agents, hooks, the plugin's own scripts; a quoted
          "vendor/(vis|wixie)/<path>" literal in a plugin-owned script counts too),
          plus ARG_DEPS (a script whose data file is named on its command line).
  edges   Python: sibling modules it imports and file-name string literals that
          resolve next to it or one level up (e.g. SCRIPT_DIR/../models-registry.json,
          SCRIPT_DIR/self-eval.py). Markdown: relative links `](target)`.
          Followed transitively.
A plugin that relies on part of the repo-level contract references one `## `
section of CLAUDE.md as ${CLAUDE_PLUGIN_ROOT}/vendor/wixie/claude-md.<slug>.md
(slug of the heading, e.g. claude-md.deploy-bar.md): that section, byte for byte,
is the vendored file (never the whole CLAUDE.md); links in it resolve from the
repo root, which vendor/wixie/ mirrors.
The vendored tree mirrors the source layout (vendor/wixie/shared/scripts/x.py,
vendor/wixie/shared/models-registry.json, ...) so a script's own
repo-relative lookups (SCRIPT_DIR/.., parents[2]) resolve inside the plugin
without editing the script.

A relative Markdown link inside a vendored file that has no target in its own
pinned source (absent upstream, or pointing outside the pinned package tree)
cannot be rewritten without breaking byte identity; it is recorded under
`unresolved_upstream_links` in the manifest instead of being silently dropped.

Each plugin gets vendor/VENDORED.json: for every file its destination, source,
source path, source revision (vis tag commit / wixie git blob id), sha256, sha1
and consumers (the plugin or vendored files that reference it).

Modes:
    python scripts/vendor-conduct.py                     regenerate (needs the vis sibling)
    python scripts/vendor-conduct.py --check             drift check against the pinned vis
                                                         commit and this repo (needs vis)
    python scripts/vendor-conduct.py --check --offline   drift check without vis: vendored
                                                         bytes vs VENDORED.json, vis bytes vs
                                                         .vis-lock sha1, wixie bytes vs repo
Options:
    --vis-dir <dir>   vis checkout (default: <repo>/../vis, like bootstrap.sh)
    --repo <dir>      Wixie repo root (default: this script's parent's parent)

--check fails on: a missing dependency (referenced/derived file not vendored, or
its source does not exist), an unexpected dependency (a vendor/ file outside the
closure), hash drift (vendored bytes differ from the pinned/authoritative source
or from VENDORED.json), an external unresolved path (a shipped runtime reference
that resolves outside the plugin: ${CLAUDE_PLUGIN_ROOT}/.., a cwd-relative
wixie/ path, the repo-root .vis-cache/, or a ${CLAUDE_PLUGIN_ROOT}/<path> that
does not exist in the plugin), and a duplicate conflicting destination (two
sources mapped to one destination, case-insensitively, or a manifest listing a
destination twice). Exit codes: 0 ok, 1 drift / unresolved input, 2 usage error.
Stdlib only. Never fetches, never writes to the vis checkout.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCHEMA = "wixie/vendored-closure/v2"
VENDOR_DIRNAME = "vendor"
MANIFEST_NAME = "VENDORED.json"
LOCK_SCHEMA_VERSION = "2"
WIXIE_SOURCE_ROOTS = ("shared/",)
# One `## <Heading>` section of the repo CLAUDE.md, delivered as its own file
# (vendor/wixie/claude-md.<slug>.md): the applicable contract, never the whole file.
CLAUDE_SECTION_RE = re.compile(r"^claude-md\.([a-z0-9-]+)\.md$")

_PATH = rb"[A-Za-z0-9._/-]*[A-Za-z0-9_-]\.[A-Za-z0-9]+"
# Canonical root reference: ${CLAUDE_PLUGIN_ROOT}/vendor/<source>/<path>, or the
# same "vendor/<source>/<path>" as a quoted literal in a plugin-owned script.
REF_RE = re.compile(
    rb"(?:\$\{CLAUDE_PLUGIN_ROOT\}/|(?<=[\"']))vendor/"
    rb"(vis/packages/[a-z][a-z0-9_-]*/" + _PATH + rb"|wixie/shared/" + _PATH + rb"|wixie/claude-md\.[a-z0-9-]+\.md)"
)
# A script whose data file is chosen by a command-line argument in the consumer.
ARG_DEPS = [
    (re.compile(rb"vendor/wixie/shared/scripts/efficacy-replay\.py\s+corpus\s+([A-Za-z0-9_-]+)"),
     "shared/eval-corpus/{0}/corpus.json"),
]
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
# Runtime path tokens that resolve outside an installed plugin.
ESCAPE_RE = re.compile(rb"\$\{CLAUDE_PLUGIN_(?:ROOT|DATA)\}/\.\.(?:/[^\s)`\"'\]|,;]*)?")
# WIX-SEC-WS-001 (D17): the installed plugin tree is immutable product content. Mutable runtime
# state lives in ${CLAUDE_PLUGIN_DATA}; a runtime reference to ${CLAUDE_PLUGIN_ROOT}/state is drift.
PLUGIN_STATE_RE = re.compile(rb"\$\{CLAUDE_PLUGIN_ROOT\}/state(?:/[^\s)`\"'\]|,;]*)?")
CWD_WIXIE_RE = re.compile(rb"(?<![A-Za-z0-9_./-])wixie/(?:shared|plugins)/[^\s)`\"'\]|,;]*")
PLUGIN_PATH_RE = re.compile(rb"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s)`\"'\]|,;*]*)")
# Declared cross-plugin OPTIONAL state reads: another plugin's mutable runtime
# state (not an asset of this plugin, so not vendorable). Each consumer treats a
# missing file as a normal branch. An entry that no longer occurs is itself drift.
# WIX-SEC-WS-001: installed, that state is in the other plugin's data dir (a sibling
# of ${CLAUDE_PLUGIN_DATA}, named <plugin>-<marketplace> by Claude Code); in a repo
# checkout the converge read also falls back to the repository state.
CROSS_PLUGIN_OPTIONAL = {
    ("convergence-engine", "skills/converge/SKILL.md"): (
        "${CLAUDE_PLUGIN_DATA}/../inference-engine-wixie/state/briefings/wixie.md",
        "${CLAUDE_PLUGIN_ROOT}/../inference-engine/state/briefings/wixie.md",
    ),
    ("prompt-crafter", "skills/prompt-creator/SKILL.md"): (
        "${CLAUDE_PLUGIN_DATA}/../deep-research-wixie/briefs/<slug>/claims.json",
    ),
}
MD_LINK_RE = re.compile(rb"\]\(([^)\s#]+)(?:#[^)\s]*)?\)")
FILE_SUFFIXES = (".py", ".json", ".jsonl", ".md", ".txt", ".yaml", ".yml", ".html", ".css", ".js", ".sh", ".csv")
# Plugin subtrees that are not scanned for references: the generated vendor
# tree itself, and state/ (runtime data logs such as artifacts.jsonl, which
# quote historical file names as data, not as references).
SKIP_TOP = {VENDOR_DIRNAME, "state"}
# Plugin READMEs are repository documentation (not a Claude Code plugin component);
# their relative links target the repo checkout and are not runtime references.
DOC_ONLY = {"README.md"}


class Drift(Exception):
    pass


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def git_blob_id(b: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


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


# --- sources --------------------------------------------------------------------

class GitBlobs:
    """`git cat-file --batch` reader: one process for every blob read from the vis checkout."""

    def __init__(self, repo: Path):
        self.repo, self.proc = repo, None

    def get(self, commit: str, path: str) -> bytes | None:
        if self.proc is None:
            self.proc = subprocess.Popen(["git", "-C", str(self.repo), "cat-file", "--batch"],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.proc.stdin.write(f"{commit}:{path}".encode("utf-8") + b"\n")
        self.proc.stdin.flush()
        head = self.proc.stdout.readline().split()
        if len(head) != 3:  # "<name> missing" / "ambiguous"
            return None
        size = int(head[2])
        data = self.proc.stdout.read(size)
        self.proc.stdout.read(1)  # trailing LF
        return data if head[1] == b"blob" else None

    def close(self):
        if self.proc is not None:
            self.proc.stdin.close()
            self.proc.stdout.close()
            self.proc.wait()
            self.proc = None


def resolve_tag(vis: Path, tag: str) -> str:
    r = subprocess.run(["git", "-C", str(vis), "rev-parse", "--verify", "--quiet",
                        f"refs/tags/{tag}^{{commit}}"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise Drift(f"vis tag {tag} not found in {vis} (this script never fetches)")
    return r.stdout.strip()


_LISTDIR: dict = {}


def _exact_file(root: Path, rel: str) -> bool:
    """True if rel names a regular file under root with exactly this spelling (case too)."""
    cur = root
    for part in rel.split("/"):
        if cur not in _LISTDIR:
            try:
                _LISTDIR[cur] = set(os.listdir(cur))
            except OSError:
                _LISTDIR[cur] = set()
        if part not in _LISTDIR[cur]:
            return False
        cur = cur / part
    return cur.is_file()


def _slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def claude_sections(repo: Path) -> dict[str, tuple[str, bytes]]:
    """{slug: (heading line, exact bytes)} for every `## ` section of the repo CLAUDE.md.

    A section runs from its `## ` heading line up to the next `## ` heading or EOF,
    byte for byte (no normalization), so it is re-derivable and hash-checkable.
    """
    f = repo / "CLAUDE.md"
    if not f.is_file():
        return {}
    lines = f.read_bytes().splitlines(keepends=True)
    out: dict = {}
    cur = None
    for line in lines:
        if line.startswith(b"## "):
            head = line.decode("utf-8").rstrip("\r\n")
            cur = _slug(head[3:])
            if cur in out:
                raise Drift(f"CLAUDE.md: two sections slug to {cur!r}")
            out[cur] = (head, [line])
        elif cur is not None:
            out[cur][1].append(line)
    return {k: (h, b"".join(ls)) for k, (h, ls) in out.items()}


def claude_section(repo: Path, slug: str) -> bytes | None:
    got = claude_sections(repo).get(slug)
    return got[1] if got else None


def _norm(path: str) -> str | None:
    n = posixpath.normpath(path)
    return None if n.startswith("../") or n == ".." or n.startswith("/") else n


class Sources:
    """Authoritative bytes for ("vis", packages/...) and ("wixie", shared/...) keys.

    vis: the pinned commit (full mode) or, offline, the vendored copies whose sha1
    matches the .vis-lock anchor (the only offline evidence for vis bytes).
    """

    def __init__(self, repo: Path, lock: dict, vis: Path | None, pool: dict[str, bytes] | None):
        self.repo, self.lock, self.vis, self.pool = repo, lock, vis, pool
        self.blobs = GitBlobs(vis) if vis is not None else None
        self.cache: dict = {}
        self.edges: dict = {}

    def pin(self, path: str):
        parts = path.split("/")
        return self.lock["packages"].get(parts[1]) if len(parts) > 2 and parts[0] == "packages" else None

    def get(self, key: tuple[str, str]) -> bytes | None:
        if key in self.cache:
            return self.cache[key]
        source, path = key
        data = None
        if source == "vis":
            pin = self.pin(path)
            if pin is not None:
                data = self.blobs.get(pin["tag_commit"], path) if self.blobs is not None else self.pool.get(path)
        elif any(path.startswith(r) for r in WIXIE_SOURCE_ROOTS) and _exact_file(self.repo, path):
            data = (self.repo / path).read_bytes()
        elif CLAUDE_SECTION_RE.match(path):
            data = claude_section(self.repo, CLAUDE_SECTION_RE.match(path).group(1))
        self.cache[key] = data
        return data


# --- reference discovery --------------------------------------------------------

def plugin_dirs(repo: Path) -> list[Path]:
    return sorted(p for p in (repo / "plugins").iterdir()
                  if (p / ".claude-plugin" / "plugin.json").is_file())


def scanned_files(plugin: Path):
    for f in sorted(plugin.rglob("*")):
        if not f.is_file() or "__pycache__" in f.parts:
            continue
        rel = f.relative_to(plugin)
        if rel.parts[0] in SKIP_TOP:
            continue
        yield f


def _line(data: bytes, pos: int) -> int:
    return data.count(b"\n", 0, pos) + 1


def discover(plugin: Path) -> tuple[dict, list[str]]:
    """Return ({(source, path): {consumer, ...}}, problems) for one plugin's own files."""
    roots: dict = {}
    problems: list[str] = []
    name = plugin.name
    exempt_seen: set = set()
    for f in scanned_files(plugin):
        data = f.read_bytes()
        if b"\0" in data:
            continue
        relf = f.relative_to(plugin).as_posix()
        where = f"plugins/{name}/{relf}"
        for m in REF_RE.finditer(data):
            src, _, path = m.group(1).decode().partition("/")
            if _norm(path) != path:
                problems.append(f"{where}:{_line(data, m.start())}: non-normalized vendor reference {m.group(0).decode()}")
                continue
            roots.setdefault((src, path), set()).add(relf)
        for rx, tmpl in ARG_DEPS:
            for m in rx.finditer(data):
                roots.setdefault(("wixie", tmpl.format(m.group(1).decode())), set()).add(relf)
        blanked = REF_RE.sub(b"", data)
        seen_lines: set[int] = set()
        for rx, why in STALE_RES:
            for m in rx.finditer(blanked):
                line = _line(blanked, m.start())
                if line not in seen_lines:
                    seen_lines.add(line)
                    problems.append(f"{where}:{line}: {why}")
        if relf in DOC_ONLY:
            continue
        # External unresolved paths: anything that leaves the installed plugin.
        exempt = CROSS_PLUGIN_OPTIONAL.get((name, relf), ())
        for m in ESCAPE_RE.finditer(data):
            tok = m.group(0).decode()
            if tok in exempt:
                exempt_seen.add((name, relf, tok))
                continue
            problems.append(f"{where}:{_line(data, m.start())}: external unresolved path {tok} "
                            "(${CLAUDE_PLUGIN_ROOT}/.. or ${CLAUDE_PLUGIN_DATA}/.. leaves the plugin)")
        for m in PLUGIN_STATE_RE.finditer(data):
            problems.append(f"{where}:{_line(data, m.start())}: mutable state inside the installed plugin "
                            f"{m.group(0).decode()} (the plugin tree is read-only; use ${{CLAUDE_PLUGIN_DATA}})")
        for m in CWD_WIXIE_RE.finditer(data):
            problems.append(f"{where}:{_line(data, m.start())}: external unresolved path {m.group(0).decode()} "
                            "(cwd-relative path into a Wixie checkout)")
        for m in PLUGIN_PATH_RE.finditer(data):
            rest = m.group(1).decode().rstrip(".:")
            if not rest or rest.startswith(("..", VENDOR_DIRNAME + "/", "state/")) or "<" in rest:
                continue
            if not (plugin / rest).exists():
                problems.append(f"{where}:{_line(data, m.start())}: external unresolved path "
                                f"${{CLAUDE_PLUGIN_ROOT}}/{rest} (does not exist in the plugin)")
    for (pname, relf), toks in CROSS_PLUGIN_OPTIONAL.items():
        for tok in toks:
            if pname == name and (pname, relf, tok) not in exempt_seen:
                problems.append(f"plugins/{name}/{relf}: declared cross-plugin optional path {tok} no longer "
                                "occurs (stale CROSS_PLUGIN_OPTIONAL entry)")
    return roots, problems


# --- transitive edges -------------------------------------------------------------

def _py_edges(path: str, content: bytes, src: Sources) -> list[str]:
    try:
        tree = ast.parse(content.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as e:
        raise Drift(f"wixie:{path}: cannot parse for dependencies: {e}")
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value
            if (0 < len(s) < 200 and s.endswith(FILE_SUFFIXES) and not re.search(r"[\s*?<>{}\\]", s)
                    and not s.startswith(("/", "."))):
                names.add(s)
        elif isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] + ".py" for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0] + ".py")
    d = posixpath.dirname(path)
    out = []
    for s in sorted(names):
        for base in (d, posixpath.dirname(d)):
            cand = _norm(posixpath.join(base, s))
            if cand and cand != path and src.get(("wixie", cand)) is not None:
                out.append(cand)
                break
    return out


def _md_edges(source: str, path: str, content: bytes, src: Sources):
    edges, unresolved = [], []
    d = posixpath.dirname(path)
    for m in MD_LINK_RE.finditer(content):
        link = m.group(1).decode("utf-8", "replace")
        if re.match(r"^[a-z][a-z0-9+.-]*:", link) or link.startswith("/") or link.endswith("/"):
            continue
        cand = _norm(posixpath.join(d, link))
        reason = "outside the pinned source tree"
        if cand is not None and source == "vis" and cand.startswith("packages/") and src.pin(cand) is not None:
            reason = None if src.get(("vis", cand)) is not None else "absent at the pinned vis commit"
        elif cand is not None and source == "wixie" and any(cand.startswith(r) for r in WIXIE_SOURCE_ROOTS):
            reason = None if src.get(("wixie", cand)) is not None else "absent in this repository"
        if reason is None:
            edges.append(cand)
        else:
            unresolved.append({"from": f"{VENDOR_DIRNAME}/{source}/{path}", "link": link, "reason": reason})
    return edges, unresolved


def closure(roots: dict, src: Sources):
    """BFS over roots -> ({key: set(consumers)}, unresolved links, problems)."""
    consumers: dict = {}
    unresolved: list = []
    problems: list[str] = []
    queue = []
    for key, cons in sorted(roots.items()):
        consumers.setdefault(key, set()).update(cons)
        queue.append(key)
    done: set = set()
    while queue:
        key = queue.pop(0)
        if key in done:
            continue
        done.add(key)
        source, path = key
        data = src.get(key)
        if data is None:
            why = ("vis package not pinned in .vis-lock" if source == "vis" and src.pin(path) is None
                   else "does not exist at pinned commit" if source == "vis"
                   else "does not exist in this repo (wixie sources: " + ", ".join(WIXIE_SOURCE_ROOTS) + ")")
            problems.append(f"missing dependency {source}:{path} ({why}); consumers: {sorted(consumers[key])}")
            continue
        me = f"{VENDOR_DIRNAME}/{source}/{path}"
        targets: list = []
        if path.endswith(".py") and source == "wixie":
            if key not in src.edges:
                src.edges[key] = _py_edges(path, data, src)
            targets = [("wixie", t) for t in src.edges[key]]
        elif path.endswith(".md"):
            if key not in src.edges:
                src.edges[key] = _md_edges(source, path, data, src)
            e, u = src.edges[key]
            targets = [(source, t) for t in e]
            for x in u:
                if source == "wixie":
                    # Wixie owns this file: a dangling link is fixable here, so it is drift.
                    problems.append(f"missing dependency: {x['from']} links {x['link']} ({x['reason']})")
                elif x not in unresolved:
                    unresolved.append(x)
        for t in targets:
            consumers.setdefault(t, set()).add(me)
            if t not in done:
                queue.append(t)
    return consumers, unresolved, problems


# --- expected content -----------------------------------------------------------

def expected_for(consumers: dict, src: Sources) -> tuple[dict, list[str]]:
    out: dict = {}
    problems: list[str] = []
    folded: dict = {}
    for key in sorted(consumers):
        source, path = key
        data = src.get(key)
        if data is None:
            continue
        rel = f"{source}/{path}"
        if rel.casefold() in folded:
            problems.append(f"duplicate conflicting destination vendor/{rel} vs vendor/{folded[rel.casefold()]} "
                            "(one path on a case-insensitive install)")
            continue
        folded[rel.casefold()] = rel
        entry = {"path": rel, "destination": f"{VENDOR_DIRNAME}/{rel}", "source": source, "source_path": path,
                 "sha256": sha256(data), "sha1": sha1(data), "consumers": sorted(consumers[key])}
        if source == "vis":
            pin = src.pin(path)
            entry.update({"package": path.split("/")[1], "version": pin["version"], "tag": pin["tag"],
                          "tag_commit": pin["tag_commit"], "source_revision": pin["tag_commit"]})
        else:
            m = CLAUDE_SECTION_RE.match(path)
            if m:
                whole = (src.repo / "CLAUDE.md").read_bytes()
                entry.update({"source_path": "CLAUDE.md", "source_section": claude_sections(src.repo)[m.group(1)][0],
                              "source_revision": "git-blob:" + git_blob_id(whole)})
            else:
                entry["source_revision"] = "git-blob:" + git_blob_id(data)
        out[rel] = {"entry": entry, "bytes": data}
    return out, problems


def manifest_bytes(entries: list[dict], unresolved: list[dict]) -> bytes:
    doc = {
        "schema": SCHEMA,
        "generated_by": "scripts/vendor-conduct.py",
        "do_not_edit": "generated; regenerate with `python scripts/vendor-conduct.py`, verify with --check",
        "files": entries,
        "unresolved_upstream_links": sorted(unresolved, key=lambda u: (u["from"], u["link"])),
    }
    return (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")


def on_disk(repo: Path, vdir: Path) -> set[str]:
    """Files that would ship: tracked + untracked-not-ignored in a git work tree, else all files."""
    if not vdir.is_dir():
        return set()
    base = vdir.relative_to(repo).as_posix() + "/"
    if (repo / ".git").exists():
        r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others",
                            "--exclude-standard", "--", base], capture_output=True)
        if r.returncode == 0:
            return {p[len(base):] for p in r.stdout.decode("utf-8").split("\0")
                    if p.startswith(base) and (repo / p).is_file()}
    return {f.relative_to(vdir).as_posix() for f in vdir.rglob("*")
            if f.is_file() and "__pycache__" not in f.relative_to(vdir).parts}


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


def offline_pool(repo: Path, lock: dict) -> dict[str, bytes]:
    """Offline vis evidence: vendored vis copies whose sha1 matches the .vis-lock anchor."""
    pool: dict[str, bytes] = {}
    for f in sorted(repo.glob(f"plugins/*/{VENDOR_DIRNAME}/vis/**/*")):
        if not f.is_file():
            continue
        path = f.as_posix().split(f"/{VENDOR_DIRNAME}/vis/", 1)[1]
        b = f.read_bytes()
        if lock["conduct_sha1"].get(path) == sha1(b):
            pool.setdefault(path, b)
    return pool


def check_offline(name: str, lock: dict, exp: dict, mbytes: bytes, manifest: dict | None) -> list[str]:
    problems: list[str] = []
    if manifest is None or manifest.get("schema") != SCHEMA:
        return [f"{name}: {MANIFEST_NAME} missing or wrong schema"]
    m_entries: dict = {}
    folded: set = set()
    for me in manifest.get("files", []):
        key = str(me.get("path"))
        if key.casefold() in folded:
            problems.append(f"{name}: {MANIFEST_NAME} lists destination vendor/{key} more than once "
                            "(duplicate conflicting destination)")
        folded.add(key.casefold())
        m_entries[key] = me
    if set(m_entries) != set(exp):
        problems.append(f"{name}: {MANIFEST_NAME} entry set {sorted(m_entries)} != referenced set {sorted(exp)}")
    if manifest.get("unresolved_upstream_links") != json.loads(mbytes)["unresolved_upstream_links"]:
        problems.append(f"{name}: {MANIFEST_NAME} unresolved_upstream_links differ from the recomputed set")
    return problems + [p for rel, e in exp.items() for p in _offline_entry(name, lock, rel, e, m_entries.get(rel))]


def _offline_entry(name, lock, rel, e, me):
    if me is None:
        return []
    f = e["file"]
    if not f.is_file():
        return []
    problems = []
    b = f.read_bytes()
    if sha256(b) != me.get("sha256") or sha1(b) != me.get("sha1"):
        problems.append(f"{name}: vendor/{rel} does not match its {MANIFEST_NAME} hash")
    for k in ("destination", "source", "source_path", "source_section", "package", "version", "tag", "tag_commit",
              "consumers"):
        if e["entry"].get(k) != me.get(k):
            problems.append(f"{name}: {MANIFEST_NAME} {rel} field {k}={me.get(k)!r}, expected {e['entry'].get(k)!r}")
    if e["entry"]["source"] == "vis":
        locked = lock["conduct_sha1"].get(e["entry"]["source_path"])
        if locked is None:
            problems.append(f"{name}: {rel} is not covered by .vis-lock conduct_files; run the full --check against vis")
        elif locked != sha1(b):
            problems.append(f"{name}: vendor/{rel} sha1 {sha1(b)} != .vis-lock sha1 {locked}")
    elif b != e["bytes"]:
        problems.append(f"{name}: vendor/{rel} is not byte-identical to {e['entry']['source_path']}")
    if me.get("source_revision") != e["entry"]["source_revision"]:
        why = "pin moved; regenerate" if e["entry"]["source"] == "vis" else "source changed; regenerate"
        problems.append(f"{name}: {MANIFEST_NAME} {rel} source_revision {me.get('source_revision')!r} "
                        f"!= {e['entry']['source_revision']!r} ({why})")
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
    src = Sources(repo, lock, vis, None if vis is not None else offline_pool(repo, lock))
    try:
        return _run(repo, vis, mode, lock, src, problems)
    finally:
        if src.blobs is not None:
            src.blobs.close()


def _run(repo: Path, vis: Path | None, mode: str, lock: dict, src: Sources, problems: list[str]) -> int:
    total = 0
    plans: list = []
    for plugin in plugin_dirs(repo):
        name = plugin.name
        vdir = plugin / VENDOR_DIRNAME
        roots, found = discover(plugin)
        problems += found
        consumers, unresolved, cproblems = closure(roots, src)
        problems += [f"{name}: {p}" for p in cproblems]
        exp, eproblems = expected_for(consumers, src)
        problems += [f"{name}: {p}" for p in eproblems]
        for rel, e in exp.items():
            e["file"] = vdir / rel
        total += len(exp)
        mbytes = manifest_bytes([e["entry"] for e in exp.values()], unresolved)

        if mode == "write":
            plans.append((name, vdir, exp, mbytes))
            continue

        # --- check (full or offline) ---
        have = on_disk(repo, vdir)
        want = set(exp) | ({MANIFEST_NAME} if exp else set())
        for extra in sorted(have - want):
            problems.append(f"{name}: extra file in vendor/: {extra} (not referenced by the plugin: unexpected dependency)")
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
        if vis is None:
            problems += check_offline(name, lock, exp, mbytes, manifest)
            continue
        # Full check: every vendored byte is re-derived from its authoritative source.
        for rel, e in exp.items():
            if e["file"].is_file() and e["file"].read_bytes() != e["bytes"]:
                problems.append(f"{name}: vendor/{rel} is not byte-identical to "
                                f"{e['entry'].get('tag_commit', 'repo')}:{e['entry']['source_path']}")
        if mpath.is_file() and mpath.read_bytes() != mbytes:
            problems.append(f"{name}: {MANIFEST_NAME} differs from the regenerated manifest")
    if problems:
        raise Drift("\n".join(problems) + ("\nnothing was written" if mode == "write" else ""))
    if mode == "write":
        # Only after every plugin resolved cleanly: replace each vendor/ tree.
        for name, vdir, exp, mbytes in plans:
            if vdir.exists():
                shutil.rmtree(vdir)
            if not exp:
                continue
            for rel, e in exp.items():
                e["file"].parent.mkdir(parents=True, exist_ok=True)
                e["file"].write_bytes(e["bytes"])
            (vdir / MANIFEST_NAME).write_bytes(mbytes)
            print(f"{name}: vendored {len(exp)} file(s)")
        print(f"vendored {total} file(s) (vis from the pin in .vis-lock, wixie from this repo)")
    else:
        how = "offline: manifest + .vis-lock + repo" if vis is None else "byte-identical to the pinned vis commit and this repo"
        print(f"vendored closure OK ({how}): {total} file(s)")
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
