#!/usr/bin/env python3
"""
procsafe — spawn and stop headless worker processes by OWNED process tree only.

Incident 2026-10-01: a driver held the PID of the `cmd.exe /c claude.CMD` wrapper; killing that
PID orphaned the real claude.exe, and recovery escalated to an image-name kill that terminated
every Claude Code session on the machine. This module is the shared answer for every runner that
launches `claude -p` (efficacy-replay, dispatch-via-cli, mission drivers).

Hard invariants:
  * No process is ever selected by image or process name. Every kill targets an explicit PID.
  * A PID is owned iff it is this process's own Popen root, or a descendant of that root by
    ParentProcessId whose creation time is not earlier than its parent's (a recycled or stale
    ParentProcessId never counts), recorded at spawn or found live under the live root.
  * The calling process and its ancestors (the Claude session that launched the driver) are never
    targets.
  * Contract on timeout or cancel: VERIFY OWNERSHIP -> LOG TREE -> TERMINATE OWN TREE -> VERIFY
    EXITED. If anything owned survives, the result is WORKER_TERMINATION_FAILED; scope never widens.

Derived from .research/agent-toolchain-rnd/provenance/procsafe.py (D-018). Additions: creation-order
lineage, ancestor protection, stale-ParentProcessId-safe `/T`, POSIX support, stdin input and a
`subprocess.run`-shaped `run()`.

Authorship: Enchanter Labs.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field

OK = "TERMINATED_OWN_TREE"
ALREADY_GONE = "ALREADY_EXITED"
FAILED = "WORKER_TERMINATION_FAILED"
IS_WINDOWS = os.name == "nt"
ISSUED_COMMANDS: list[list[str]] = []  # every kill this module issues, for audit by tests


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- process table

def snapshot() -> dict[int, dict]:
    """pid -> {ppid, name, cmd, created}. `created` sorts chronologically within one platform."""
    if IS_WINDOWS:
        ps = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine,"
              "@{n='Created';e={$_.CreationDate.ToUniversalTime().ToString('o')}} | ConvertTo-Json -Compress")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=60).stdout
            rows = json.loads(out) if out.strip() else []
        except (OSError, subprocess.SubprocessError, ValueError):
            return {}
        if isinstance(rows, dict):
            rows = [rows]
        return {r["ProcessId"]: {"ppid": r["ParentProcessId"], "name": r.get("Name") or "",
                                 "cmd": r.get("CommandLine") or "", "created": r.get("Created") or ""}
                for r in rows}
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,etimes=,comm=,args="],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    now, snap = int(time.time()), {}
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        created = f"{now - int(parts[2]):012d}" if parts[2].isdigit() else ""
        snap[int(parts[0])] = {"ppid": int(parts[1]), "name": parts[3], "created": created,
                               "cmd": parts[4] if len(parts) > 4 else parts[3]}
    return snap


def _born_after(child: dict, parent: dict) -> bool:
    """A child cannot predate its parent; if it does, its ParentProcessId points at a recycled PID."""
    c, p = child.get("created") or "", parent.get("created") or ""
    return not c or not p or c >= p


def descendants(root: int, snap: dict[int, dict]) -> list[int]:
    """Descendants of `root` by ParentProcessId, rejecting stale links (child older than parent)."""
    if root not in snap:
        return []
    out, stack = [], [root]
    while stack:
        parent = stack.pop()
        for pid, info in snap.items():
            if info["ppid"] == parent and pid != root and pid not in out and _born_after(info, snap[parent]):
                out.append(pid)
                stack.append(pid)
    return out


def raw_tree(root: int, snap: dict[int, dict]) -> set[int]:
    """What `taskkill /T` would walk: ParentProcessId links only, no creation-time check."""
    out, stack = set(), [root]
    while stack:
        parent = stack.pop()
        for pid, info in snap.items():
            if info["ppid"] == parent and pid != root and pid not in out:
                out.add(pid)
                stack.append(pid)
    return out


def ancestors(pid: int, snap: dict[int, dict]) -> set[int]:
    """`pid` and every live ancestor of it, following valid (creation-ordered) links only."""
    out, cur = set(), pid
    while cur in snap and cur not in out:
        out.add(cur)
        parent = snap[cur]["ppid"]
        if parent not in snap or not _born_after(snap[cur], snap[parent]):
            break
        cur = parent
    return out


def resolve_real_claude(override: str | None = None) -> tuple[str, bool]:
    """Return (executable, is_wrapper). Prefer the real claude.exe so Popen.pid IS the worker.

    On Windows `shutil.which("claude")` returns the npm shim claude.CMD; launching it puts a
    cmd.exe wrapper between the driver and the worker, which is how the incident started.
    """
    if override:
        return override, override.lower().endswith((".cmd", ".bat"))
    shim = shutil.which("claude")
    if not shim:
        return "claude", False
    if IS_WINDOWS:
        real = pathlib.Path(shim).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if real.exists():
            return str(real), False
    return shim, shim.lower().endswith((".cmd", ".bat"))


GUARD_HOOK = pathlib.Path.home() / ".claude" / "hooks" / "claude_kill_guard.py"


def guard_settings_args() -> list[str]:
    """`--settings` carrying this machine's global claude-kill-guard hook, or [] when it is not installed.

    A child launched with `--setting-sources ""` (or `project`) skips user settings and therefore the
    global PreToolUse guard; `--settings` still applies, so passing this keeps the child guarded.
    It adds no context to the child; it only gates Bash/PowerShell/Monitor commands that kill Claude.
    """
    if not GUARD_HOOK.is_file():
        return []
    hook = {"type": "command", "command": f"python {GUARD_HOOK.as_posix()}", "timeout": 30}
    return ["--settings", json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash|PowerShell|Monitor", "hooks": [hook]}]}})]


# --------------------------------------------------------------------------- worker handle

@dataclass
class Worker:
    popen: subprocess.Popen
    label: str
    state_file: pathlib.Path | None
    is_wrapper: bool
    spawned_at: str = field(default_factory=_now)
    WRAPPER_PID: int | None = None
    REAL_CHILD_PID: int | None = None
    tree: dict[int, dict] = field(default_factory=dict)  # pid -> identity recorded at spawn/refresh

    def refresh_tree(self, snap: dict[int, dict] | None = None) -> None:
        snap = snapshot() if snap is None else snap
        root = self.popen.pid
        if root in snap and snap[root]["ppid"] == os.getpid():
            self.tree.setdefault(root, snap[root])
            for pid in descendants(root, snap):
                self.tree.setdefault(pid, snap[pid])
        if self.is_wrapper:
            self.WRAPPER_PID = root
            kids = [p for p, i in self.tree.items() if p != root and i["name"].lower() not in ("cmd.exe", "conhost.exe")]
            self.REAL_CHILD_PID = kids[0] if kids else self.REAL_CHILD_PID
        else:
            self.WRAPPER_PID, self.REAL_CHILD_PID = None, root
        self._write_state("RUNNING")

    def _write_state(self, status: str, extra: dict | None = None) -> None:
        if not self.state_file:
            return
        doc = {"label": self.label, "status": status, "driver_pid": os.getpid(), "spawned_at": self.spawned_at,
               "updated": _now(), "WRAPPER_PID": self.WRAPPER_PID, "REAL_CHILD_PID": self.REAL_CHILD_PID,
               "POPEN_PID": self.popen.pid, "POPEN_PID_IS": "WRAPPER" if self.is_wrapper else "REAL_CHILD",
               "process_tree": {str(p): {k: (v[:300] if isinstance(v, str) else v) for k, v in i.items()}
                                for p, i in self.tree.items()}}
        doc.update(extra or {})
        try:
            pathlib.Path(self.state_file).write_text(json.dumps(doc, indent=2), encoding="utf-8")
        except OSError:
            pass


def spawn(cmd: list[str], *, label: str, state_file: pathlib.Path | None = None, is_wrapper: bool = False,
          settle_s: float | None = None, **popen_kw) -> Worker:
    if not IS_WINDOWS:
        popen_kw.setdefault("start_new_session", True)
    p = subprocess.Popen(cmd, **popen_kw)
    w = Worker(popen=p, label=label, state_file=state_file, is_wrapper=is_wrapper)
    time.sleep(2.0 if settle_s is None and is_wrapper else (settle_s or 0))  # let a wrapper start its child
    w.refresh_tree()
    return w


# --------------------------------------------------------------------------- termination

def _kill_pid(pid: int, tree: bool) -> tuple[int, str]:
    if IS_WINDOWS:
        cmd = ["taskkill", "/F", "/T", "/PID", str(pid)] if tree else ["taskkill", "/F", "/PID", str(pid)]
        ISSUED_COMMANDS.append(cmd)
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode, (r.stdout + r.stderr).strip()[:300]
    ISSUED_COMMANDS.append(["os.kill", str(pid), "SIGKILL"])
    try:
        os.kill(pid, signal.SIGKILL)
        return 0, ""
    except OSError as exc:
        return 1, str(exc)


def owned_live(w: Worker, snap: dict[int, dict]) -> tuple[list[int], list[dict]]:
    """VERIFY OWNERSHIP. Returns (owned live PIDs, refused records)."""
    root = w.popen.pid
    if root in snap and snap[root]["ppid"] == os.getpid() and w.popen.poll() is None:
        for pid in descendants(root, snap):  # pick up live descendants spawned since the last refresh
            w.tree.setdefault(pid, snap[pid])
    protected = ancestors(os.getpid(), snap) | {os.getpid()}
    owned, refused = [], []
    for pid, info in w.tree.items():
        live = snap.get(pid)
        if not live:
            continue
        same = live.get("created") == info.get("created") and live.get("name") == info.get("name")
        root_ok = pid != root or live.get("ppid") == os.getpid()
        if pid in protected:
            refused.append({"pid": pid, "why": "calling process or its ancestor"})
        elif same and root_ok:
            owned.append(pid)
        else:
            refused.append({"pid": pid, "why": "identity changed (pid reuse) or root not a child of this process"})
    return owned, refused


def terminate_own_tree(w: Worker, reason: str, log: pathlib.Path | None = None, *, settle_s: float = 1.5) -> dict:
    """VERIFY OWNERSHIP -> LOG TREE -> TERMINATE ONLY OWN TREE -> VERIFY EXITED. Never by name."""
    rec = {"at": _now(), "label": w.label, "reason": reason, "driver_pid": os.getpid(),
           "popen_pid": w.popen.pid, "steps": []}
    snap = snapshot()
    if not snap:
        # No process table: the only process whose identity is certain is our own Popen handle.
        if w.popen.poll() is None:
            w.popen.kill()
            ISSUED_COMMANDS.append(["Popen.kill", str(w.popen.pid)])
        rec["steps"].append({"VERIFY_OWNERSHIP": "process table unavailable; killed own handle only"})
        rec["result"] = FAILED
        _finish(w, rec, log)
        return rec
    owned, refused = owned_live(w, snap)
    rec["steps"].append({"VERIFY_OWNERSHIP": {"owned_live": owned, "refused": refused}})
    rec["steps"].append({"LOG_PROCESS_TREE": {str(p): {"name": w.tree[p]["name"], "ppid": w.tree[p]["ppid"],
                                                       "cmd": w.tree[p]["cmd"][:200]} for p in owned}})
    if not owned:
        rec["result"] = ALREADY_GONE if not refused or w.popen.poll() is not None else FAILED
        _finish(w, rec, log)
        return rec
    owned_set = set(owned)
    # Roots of the owned forest: owned PIDs whose parent is not itself owned (the wrapper, or an orphan).
    roots = [p for p in owned if snap[p]["ppid"] not in owned_set]
    for root in roots:
        # `/T` follows raw ParentProcessId links; use it only when that walk stays inside the owned set.
        if IS_WINDOWS and raw_tree(root, snap) <= owned_set:
            rc, out = _kill_pid(root, tree=True)
            rec["steps"].append({"TERMINATE": {"pid": root, "tree": True, "rc": rc, "out": out}})
        else:
            subtree = [root] + [p for p in descendants(root, snap) if p in owned_set]
            for pid in reversed(subtree):  # leaves first
                rc, out = _kill_pid(pid, tree=False)
                rec["steps"].append({"TERMINATE": {"pid": pid, "tree": False, "rc": rc, "out": out}})
    survivors = owned
    for _ in range(3):
        time.sleep(settle_s)
        after = snapshot()
        survivors = [p for p in owned if p in after and after[p].get("created") == w.tree[p].get("created")]
        if not survivors:
            break
    rec["steps"].append({"VERIFY_TREE_EXITED": {"survivors": survivors}})
    rec["result"] = OK if not survivors else FAILED  # FAILED never escalates to a broader kill
    _finish(w, rec, log)
    return rec


def _finish(w: Worker, rec: dict, log: pathlib.Path | None) -> None:
    w._write_state(rec["result"], {"termination": rec})
    if log:
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass


# --------------------------------------------------------------------------- waiting

def communicate(w: Worker, timeout: float, log: pathlib.Path | None = None, input=None):
    """Wait for the worker. On timeout terminate the own tree only.

    Returns (returncode, stdout, stderr, status, termination_record_or_None).
    """
    try:
        out, err = w.popen.communicate(input=input, timeout=timeout)
        w._write_state("EXITED", {"returncode": w.popen.returncode})
        return w.popen.returncode, out, err, "EXITED", None
    except subprocess.TimeoutExpired:
        rec = terminate_own_tree(w, f"timeout after {timeout}s", log)
        try:
            out, err = w.popen.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            out, err = None, None  # an unkillable owned survivor still holds the pipes; do not hang
        note = f"\n[procsafe] TIMEOUT -> {rec['result']}"
        if isinstance(err, bytes):
            err = err + note.encode()
        else:
            err = (err or "") + note
        return w.popen.returncode, out, err, "TIMEOUT:" + rec["result"], rec


class WorkerTimeout(subprocess.TimeoutExpired):
    """subprocess.TimeoutExpired raised after the worker's own tree was terminated."""

    def __init__(self, cmd, timeout, output=None, stderr=None, termination: dict | None = None):
        super().__init__(cmd, timeout, output=output, stderr=stderr)
        self.termination = termination or {}


def run(cmd: list[str], *, timeout: float, input=None, capture_output: bool = False, label: str = "worker",
        state_file: pathlib.Path | None = None, log: pathlib.Path | None = None, is_wrapper: bool | None = None,
        **popen_kw) -> subprocess.CompletedProcess:
    """Drop-in for `subprocess.run(cmd, timeout=...)` that never orphans a wrapped worker.

    On timeout the owned tree is terminated and WorkerTimeout (a subprocess.TimeoutExpired) is raised;
    its `.termination["result"]` is TERMINATED_OWN_TREE or WORKER_TERMINATION_FAILED.
    """
    if capture_output:
        popen_kw["stdout"] = popen_kw["stderr"] = subprocess.PIPE
    if input is not None:
        popen_kw["stdin"] = subprocess.PIPE
    if is_wrapper is None:
        is_wrapper = IS_WINDOWS and str(cmd[0]).lower().endswith((".cmd", ".bat"))
    w = spawn(cmd, label=label, state_file=state_file, is_wrapper=is_wrapper, **popen_kw)
    rc, out, err, status, rec = communicate(w, timeout, log=log, input=input)
    if rec is not None:
        raise WorkerTimeout(cmd, timeout, output=out, stderr=err, termination=rec)
    return subprocess.CompletedProcess(cmd, rc, out, err)


if __name__ == "__main__":
    sys.exit("procsafe is a library; see tests/procsafe/test_procsafe.py")
