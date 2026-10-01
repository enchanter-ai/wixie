#!/usr/bin/env python3
"""
Regression tests for shared/scripts/procsafe.py (incident 2026-10-01, cross-session Claude kill).

Deterministic part: a synthetic process table reproduces the incident's exact topology — this
driver's wrapper and worker, five VSCode-hosted Claude sessions under one extension host (one of
them the session that launched this driver), and another session's driver tree. Process-table
reads and kill calls are mocked, so the tests prove which PIDs WOULD be selected without touching
any real process.

Live part (Windows only): a harmless `cmd /c python sleep` wrapper is timed out through
procsafe.run while an unrelated decoy keeps running; the decoy and every genuine claude.exe on the
machine must survive.

Usage: python test_procsafe.py [REPO_ROOT]   (exit 0 = pass)
Authorship: Enchanter Labs.
"""
import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "shared" / "scripts"))
import procsafe  # noqa: E402

ME = os.getpid()
EXT_HOST, SESSION, SESSION_BASH = 64436, 4712, 20340
VSCODE_SESSIONS = [57292, SESSION, 26244, 2116, 17504]
WRAPPER, CHILD, CHILD_BASH = 14268, 42284, 61000
OTHER_DRIVER, OTHER_WRAPPER, OTHER_CHILD = 36580, 2012, 11928
HOST_CMD = ("c:\\users\\x\\.vscode\\extensions\\anthropic.claude-code-2.1.283\\resources\\native-binary\\claude.exe "
            "--output-format stream-json --verbose --input-format stream-json")
WORKER_CMD = "c:\\users\\x\\appdata\\roaming\\npm\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe -p --model opus"


def P(ppid, nm, created, cmd=""):
    return {"ppid": ppid, "name": nm, "created": created, "cmd": cmd or nm}


def incident_table():
    t = {EXT_HOST: P(1000, "Code.exe", "2026-10-01T05:00:00Z", "code.exe --type=extensionHost")}
    for i, pid in enumerate(VSCODE_SESSIONS):
        t[pid] = P(EXT_HOST, "claude.exe", f"2026-10-01T06:0{i}:00Z", HOST_CMD)
    t[SESSION_BASH] = P(SESSION, "bash.exe", "2026-10-01T08:00:00Z")
    t[ME] = P(SESSION_BASH, "python.exe", "2026-10-01T08:30:00Z", "python driver.py")
    t[WRAPPER] = P(ME, "cmd.exe", "2026-10-01T08:31:00Z", "cmd.exe /c claude.CMD -p --model opus")
    t[CHILD] = P(WRAPPER, "claude.exe", "2026-10-01T08:31:01Z", WORKER_CMD)
    t[CHILD_BASH] = P(CHILD, "bash.exe", "2026-10-01T08:35:00Z")
    t[OTHER_DRIVER] = P(20168, "python.exe", "2026-10-01T07:00:00Z", "python tools/run_wixie_lifecycle.py F")
    t[OTHER_WRAPPER] = P(OTHER_DRIVER, "cmd.exe", "2026-10-01T07:01:00Z", "cmd.exe /c claude.cmd -p")
    t[OTHER_CHILD] = P(OTHER_WRAPPER, "claude.exe", "2026-10-01T07:01:01Z", WORKER_CMD)
    return t


UNRELATED = set(VSCODE_SESSIONS) | {EXT_HOST, SESSION_BASH, ME, OTHER_DRIVER, OTHER_WRAPPER, OTHER_CHILD}


class FakePopen:
    def __init__(self, pid, alive=True):
        self.pid, self._alive, self.returncode = pid, alive, None

    def poll(self):
        return None if self._alive else 0

    def kill(self):
        self._alive = False


class Harness:
    """Mocked process table + kill recorder. `effective` kills remove PIDs from the table."""

    def __init__(self, table, effective=True):
        self.table, self.effective, self.kills = table, effective, []

    def snapshot(self):
        return {k: dict(v) for k, v in self.table.items()}

    def kill(self, pid, tree):
        self.kills.append((pid, tree))
        if self.effective:
            doomed = {pid} | (procsafe.raw_tree(pid, self.table) if tree else set())
            for d in doomed:
                self.table.pop(d, None)
        return 0, ""

    def __enter__(self):
        self._p = [mock.patch.object(procsafe, "snapshot", self.snapshot),
                   mock.patch.object(procsafe, "_kill_pid", self.kill),
                   mock.patch.object(procsafe.time, "sleep", lambda s: None),
                   mock.patch.object(procsafe, "IS_WINDOWS", True)]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()


def worker_for(table, wrapper=WRAPPER, alive=True):
    w = procsafe.Worker(popen=FakePopen(wrapper, alive), label="t", state_file=None, is_wrapper=True)
    snap = {k: dict(v) for k, v in table.items()}
    w.refresh_tree(snap)
    return w


class Deterministic(unittest.TestCase):
    def assert_untouched(self, h):
        hit = {pid for pid, _ in h.kills} & UNRELATED
        self.assertEqual(hit, set(), f"unrelated process selected for termination: {hit}")
        for pid in VSCODE_SESSIONS:
            self.assertIn(pid, h.table, f"VSCode Claude session {pid} did not survive")

    def test_records_wrapper_and_real_child(self):
        w = worker_for(incident_table())
        self.assertEqual(w.WRAPPER_PID, WRAPPER)
        self.assertEqual(w.REAL_CHILD_PID, CHILD)
        self.assertEqual(set(w.tree), {WRAPPER, CHILD, CHILD_BASH})

    def test_vscode_sessions_never_selected_on_timeout(self):
        t = incident_table()
        w = worker_for(t)
        with Harness(t) as h:
            rec = procsafe.terminate_own_tree(w, "timeout")
        self.assertEqual(rec["result"], procsafe.OK)
        self.assertEqual(h.kills, [(WRAPPER, True)], "expected exactly one /T kill on the owned wrapper")
        for pid in (WRAPPER, CHILD, CHILD_BASH):
            self.assertNotIn(pid, h.table)
        self.assert_untouched(h)

    def test_orphaned_child_after_wrapper_exit(self):
        t = incident_table()
        w = worker_for(t)
        del t[WRAPPER]  # wrapper exited; the real claude.exe keeps its dangling ParentProcessId
        w.popen._alive = False
        with Harness(t) as h:
            rec = procsafe.terminate_own_tree(w, "orphan")
        self.assertEqual(rec["result"], procsafe.OK)
        self.assertEqual(h.kills, [(CHILD, True)])
        self.assert_untouched(h)

    def test_recycled_child_pid_is_not_ours(self):
        t = incident_table()
        w = worker_for(t)
        del t[WRAPPER]
        w.popen._alive = False
        del t[CHILD_BASH]
        t[CHILD] = P(EXT_HOST, "claude.exe", "2026-10-01T09:00:00Z", HOST_CMD)  # PID now a new VSCode session
        VS = CHILD
        with Harness(t) as h:
            rec = procsafe.terminate_own_tree(w, "reuse")
        self.assertEqual(h.kills, [])
        self.assertEqual(rec["result"], procsafe.ALREADY_GONE)
        self.assertIn(VS, h.table)

    def test_stale_parent_link_disables_tree_kill(self):
        t = incident_table()
        # an old VSCode session whose dead parent's PID happens to equal our live wrapper PID
        t[57000] = P(WRAPPER, "claude.exe", "2026-10-01T04:00:00Z", HOST_CMD)
        w = worker_for(t)
        self.assertNotIn(57000, w.tree)
        with Harness(t) as h:
            rec = procsafe.terminate_own_tree(w, "stale")
        self.assertEqual(rec["result"], procsafe.OK)
        self.assertTrue(all(not tree for _, tree in h.kills), "/T must not be used when it would cross a stale link")
        self.assertEqual({p for p, _ in h.kills}, {WRAPPER, CHILD, CHILD_BASH})
        self.assertIn(57000, h.table)
        self.assert_untouched(h)

    def test_kill_failure_returns_failed_without_widening(self):
        t = incident_table()
        w = worker_for(t)
        with Harness(t, effective=False) as h:
            rec = procsafe.terminate_own_tree(w, "stuck")
        self.assertEqual(rec["result"], procsafe.FAILED)
        self.assertEqual({p for p, _ in h.kills}, {WRAPPER}, "a failed kill must not be retried on a wider set")
        self.assert_untouched(h)

    def test_session_ancestor_is_never_a_target(self):
        t = incident_table()
        w = worker_for(t)
        w.tree[SESSION] = dict(t[SESSION])  # corrupted record claims the launching session
        w.tree[ME] = dict(t[ME])
        with Harness(t) as h:
            rec = procsafe.terminate_own_tree(w, "corrupt")
        refused = {r["pid"] for r in rec["steps"][0]["VERIFY_OWNERSHIP"]["refused"]}
        self.assertTrue({SESSION, ME} <= refused)
        self.assert_untouched(h)

    def test_issued_command_shape(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.object(procsafe, "IS_WINDOWS", True), mock.patch.object(procsafe.subprocess, "run", fake_run):
            procsafe._kill_pid(1234, tree=True)
            procsafe._kill_pid(5678, tree=False)
        self.assertEqual(calls, [["taskkill", "/F", "/T", "/PID", "1234"], ["taskkill", "/F", "/PID", "5678"]])

    def test_no_name_based_kill_in_shared_runners(self):
        im = "[/-]" + "IM" + r"\b"
        forbidden = re.compile("|".join([im, r"\bp" + r"kill\b", r"\bkill" + r"all\b", "Stop-" + r"Process\s+-(Name|ProcessName)",
                                         r"wmic\s+" + "process", "process" + "_iter", r"\bsp" + r"ps\b", "Image" + "Name"]), re.I)
        for rel in ["shared/scripts/procsafe.py", "shared/scripts/efficacy-replay.py", "shared/scripts/dispatch-via-cli.py"]:
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIsNone(forbidden.search(text), f"name-based kill pattern in {rel}")
        for rel in ["shared/scripts/efficacy-replay.py", "shared/scripts/dispatch-via-cli.py"]:
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn("procsafe.run(", text, f"{rel} must launch claude through procsafe")
            self.assertNotRegex(text, r"subprocess\.run\(\s*base_cmd|subprocess\.run\(\s*cmd,", f"{rel} still uses raw subprocess.run")


@unittest.skipUnless(os.name == "nt", "live wrapper test is Windows-specific")
class LiveWindows(unittest.TestCase):
    def test_timeout_kills_wrapper_and_child_only(self):
        def claude_pids():
            return {p for p, i in procsafe.snapshot().items() if i["name"].lower() == "claude.exe"}

        genuine_before = claude_pids()
        issued_before = len(procsafe.ISSUED_COMMANDS)
        sleeper = [sys.executable, "-c", "import time; time.sleep(120)"]
        nowin = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        decoy = subprocess.Popen(sleeper, creationflags=nowin)
        try:
            cmd = [os.environ.get("ComSpec", "cmd.exe"), "/c", *sleeper]
            t0 = time.time()
            with self.assertRaises(procsafe.WorkerTimeout) as ctx:
                procsafe.run(cmd, timeout=4, capture_output=True, text=True, is_wrapper=True, creationflags=nowin)
            rec = ctx.exception.termination
            self.assertEqual(rec["result"], procsafe.OK, rec)
            owned = rec["steps"][0]["VERIFY_OWNERSHIP"]["owned_live"]
            self.assertGreaterEqual(len(owned), 2, "wrapper and real child must both be owned")
            self.assertNotIn(decoy.pid, owned)
            after = procsafe.snapshot()
            for pid in owned:
                self.assertNotIn(pid, after, f"owned pid {pid} survived")
            self.assertIsNone(decoy.poll(), "unrelated decoy was terminated")
            # Other sessions' claude.exe may exit on their own during the test, so assert on what WE issued:
            # every kill targeted an owned PID, and none targeted a genuine Claude process.
            targeted = {int(c[-1]) for c in procsafe.ISSUED_COMMANDS[issued_before:]}
            self.assertTrue(targeted, "no kill was issued")
            self.assertLessEqual(targeted, set(owned), f"kill issued outside the owned tree: {targeted - set(owned)}")
            self.assertEqual(targeted & genuine_before, set(), "a genuine claude.exe was targeted")
            for c in procsafe.ISSUED_COMMANDS[issued_before:]:
                self.assertEqual(c[0], "taskkill")
                self.assertIn("/PID", c)
            self.assertLess(time.time() - t0, 90)
        finally:
            decoy.kill()  # by our own handle (exact PID), never by name
            decoy.wait(timeout=10)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], "-v"])
