#!/usr/bin/env python3
"""Wixie HTML-to-PDF — converts HTML reports to PDF using browser headless print.

Usage:
    python html-to-pdf.py <html-file-or-prompt-folder>
    python html-to-pdf.py <prompt-folder> --keep-html

Tries every available browser in preference order: Edge > Chrome > Brave > Chromium >
Firefox > wkhtmltopdf. A browser that fails (crashes, times out, hands off to an
already-running instance and produces nothing) does not stop the attempt — the next
available converter is tried (WIX-PDF-001).

WIX-PDF-001 root cause: a headless Chromium-family browser launched WITHOUT an isolated
--user-data-dir can hand its print job off to an already-running instance of the same
browser instead of executing it in this subprocess. When that happens, subprocess.run()
below returns (often with exit 0) before any PDF has actually been written, and
convert() used to report that as success on nothing more than "the process exited". Every
invocation here launches with a fresh, private, per-run profile directory so it always
runs as a genuinely new instance — this is true whether the user's regular browser window
is open, closed, or has several instances already running; a fresh --user-data-dir behaves
like a fresh instance either way, which is also how "browser closed" is exercised in this
module's own tests, since there is no separate code path for "no other instance is running".

Exit codes:
    0  a validated PDF was written (non-empty, %PDF- header) via some available browser.
    1  no browser is available, or every available browser was tried and failed. A
       documented reason is printed for each attempted browser; the caller (report-gen.py)
       is expected to fall back to an HTML report in this case.
    2  usage error.

Timeouts (WIX-PDF-001 fix round 1): PER_BROWSER_TIMEOUT_S bounds a single browser attempt;
OVERALL_TIMEOUT_S bounds the whole fallback chain across every candidate browser tried by this
process. PER_BROWSER_TIMEOUT_S is deliberately much smaller than OVERALL_TIMEOUT_S so a hung
first browser still leaves room to try the rest: with 12s/attempt and a 45s overall budget, at
least 3 browsers always get a full attempt before the chain gives up. report-gen.py's own
subprocess timeout on *this whole script* must stay larger than OVERALL_TIMEOUT_S (documented
there too) -- otherwise report-gen kills this process at the exact moment it would otherwise
still be trying the next converter, which is exactly the defect this fixes.

Stdlib only. No pip installs.
"""
import sys, os, subprocess, shutil, platform, tempfile, json, time, types

PER_BROWSER_TIMEOUT_S = 12
OVERALL_TIMEOUT_S = 45

# WIX-PDF-001 fix round 1: a leaked wixie-pdf-profile-* directory that a prior run's own
# bounded cleanup retry couldn't finish removing (observed live: a transient Windows
# handle-release race that can outlast even a several-second retry window under heavy real-
# browser load) is swept up here as a backstop. 600s is comfortably longer than any single
# invocation's own lifetime (OVERALL_TIMEOUT_S plus cleanup, well under two minutes), so a
# directory this old can only be abandoned, never one still in use by a concurrently-running
# invocation.
STALE_PROFILE_MAX_AGE_S = 600


BROWSERS = {
    "win32": [
        ("Edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ("Edge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        ("Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        ("Chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ("Brave", r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ],
    "darwin": [
        ("Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ("Edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ("Brave", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    ],
    "linux": [
        ("Chrome", "/usr/bin/google-chrome"),
        ("Chrome", "/usr/bin/google-chrome-stable"),
        ("Chromium", "/usr/bin/chromium-browser"),
        ("Chromium", "/usr/bin/chromium"),
        ("Edge", "/usr/bin/microsoft-edge"),
    ],
}

CHROMIUM_ARGS = [
    "--headless", "--disable-gpu", "--no-sandbox",
    "--run-all-compositor-stages-before-draw",
    "--disable-extensions", "--no-pdf-header-footer",
    "--no-first-run", "--no-default-browser-check",
]

FIREFOX_PATHS = [
    r"C:\Program Files\Mozilla Firefox\firefox.exe",
    r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    "/usr/bin/firefox",
    "/Applications/Firefox.app/Contents/MacOS/firefox",
]


def _platform_key():
    return "win32" if sys.platform == "win32" else ("darwin" if sys.platform == "darwin" else "linux")


def find_browsers():
    """Return every available candidate browser, in preference order, as (name, path,
    type) triples. WIX-PDF-001: a failing browser must never prevent trying the next
    available converter, so callers iterate this whole list rather than stopping at the
    first match (the previous find_browser(), singular, returned only one).

    WIXIE_TEST_PDF_BROWSERS, if set AND WIXIE_TEST_MODE=1 is ALSO set, is a JSON array of
    [name, path, type] triples that REPLACES real discovery entirely. This module's own
    tests use it to exercise browser selection, fallback ordering, profile isolation and
    cleanup deterministically against stub scripts, without depending on a real installed
    browser or touching PATH/registry state.

    WIX-PDF-001 fix round 1: WIXIE_TEST_PDF_BROWSERS alone is deliberately NOT enough --
    requiring the second, unambiguous WIXIE_TEST_MODE=1 flag means a single stray or
    attacker-influenced environment variable can never silently redirect browser discovery
    to an arbitrary path in a normal (non-test) invocation; both variables must be set
    together, which only a deliberate test invocation does. Neither variable is ever read
    or set outside this module's own tests.
    """
    if os.environ.get("WIXIE_TEST_MODE") == "1":
        override = os.environ.get("WIXIE_TEST_PDF_BROWSERS")
        if override:
            try:
                # os.path.abspath also normalizes separators, so a test may supply
                # forward-slash paths on Windows and still get an executable CreateProcess
                # can actually resolve.
                return [(name, os.path.abspath(path), btype) for name, path, btype in json.loads(override)]
            except (ValueError, TypeError):
                return []

    plat = _platform_key()
    candidates = []
    seen_paths = set()

    for name, path in BROWSERS.get(plat, []):
        if os.path.isfile(path) and path not in seen_paths:
            candidates.append((name, path, "chromium"))
            seen_paths.add(path)

    # Also check PATH for any Chromium-based browser not already found by absolute path.
    for cmd in ["msedge", "google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "brave-browser"]:
        found = shutil.which(cmd)
        if found and found not in seen_paths:
            candidates.append((cmd, found, "chromium"))
            seen_paths.add(found)

    # Firefox fallback.
    firefox_path = None
    for path in FIREFOX_PATHS:
        if os.path.isfile(path):
            firefox_path = path
            break
    if not firefox_path:
        firefox_path = shutil.which("firefox")
    if firefox_path and firefox_path not in seen_paths:
        candidates.append(("Firefox", firefox_path, "firefox"))
        seen_paths.add(firefox_path)

    # wkhtmltopdf fallback (not a browser; no single-instance handoff concern, no profile).
    wk = shutil.which("wkhtmltopdf")
    if wk and wk not in seen_paths:
        candidates.append(("wkhtmltopdf", wk, "wkhtmltopdf"))

    return candidates


def _rmtree_with_retries(path, attempts=20, delay=0.75):
    """Remove a directory tree, retrying briefly on failure. A just-exited Chromium-family
    browser can still hold a handle open on a file inside its own profile directory for a
    short moment after its process tree has already been terminated (observed live on this
    host, both with real Edge and with a synthetic lingering-handle test process: a directory
    can fail to delete for several seconds -- sometimes close to 10s under load -- even with
    the holding process already confirmed dead; a transient kernel-level handle-release race,
    not a permanent lock). A single-attempt ignore_errors=True cleanup measurably leaked these
    on this host across repeated real runs, and even this bounded retry will not always win
    that race under heavy load -- see _sweep_stale_profile_dirs() for the backstop that
    catches whatever this retry still misses. Bounded (worst case ~15s here, comfortably inside
    OVERALL_TIMEOUT_S when only one or two candidates need it) and best-effort: after the last
    attempt this still gives up silently, exactly as the single-attempt cleanup it replaces
    did, so a persistent failure here can never turn into a hang or a crash."""
    for i in range(attempts):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.isdir(path):
            return
        if i < attempts - 1:
            time.sleep(delay)


def _sweep_stale_profile_dirs():
    """Best-effort cleanup of wixie-pdf-profile-* directories a PRIOR run's own
    _rmtree_with_retries() failed to remove in time (WIX-PDF-001 fix round 1: 5/5 real runs on
    this host left a 7-9MB profile directory behind past 60s under heavy real-browser load,
    even though every one of them deleted cleanly moments later once the OS finished releasing
    whatever handle was still open). Runs once at the start of every invocation of this script.

    Safety: only ever touches a directory (a) directly inside the OS temp directory (never a
    subdirectory, never resolved through a symlink target outside it), (b) whose basename
    matches the exact 'wixie-pdf-profile-' prefix this module itself uses for nothing else,
    and (c) whose mtime is older than STALE_PROFILE_MAX_AGE_S -- comfortably longer than any
    single invocation's own lifetime, so a directory this old cannot belong to a
    concurrently-running invocation. Never raises; a failure here is silently skipped and left
    for the next sweep or the OS's own temp-directory cleanup."""
    try:
        tmp = os.path.abspath(tempfile.gettempdir())
        now = time.time()
        for name in os.listdir(tmp):
            if not name.startswith("wixie-pdf-profile-"):
                continue
            path = os.path.join(tmp, name)
            try:
                if not os.path.isdir(path) or os.path.islink(path):
                    continue
                if os.path.dirname(os.path.abspath(path)) != tmp:
                    continue
                if now - os.path.getmtime(path) < STALE_PROFILE_MAX_AGE_S:
                    continue
                shutil.rmtree(path, ignore_errors=True)
            except OSError:
                continue
    except OSError:
        pass


def _terminate_process_tree(pid):
    """Best-effort termination of a process and every descendant it spawned, cross-platform.
    WIX-PDF-001 fix round 1: subprocess.run(timeout=...)'s own timeout handling only kills the
    *direct* child -- a browser that spawns renderer/GPU/helper processes (or, in this
    module's own tests, a .bat that shells out to a further process) can leave those
    descendants running past the timeout, which is exactly how a real run's profile directory
    was observed to leak (the browser itself was gone, but something in its tree still held a
    file open inside its own --user-data-dir). Called both on a timeout AND after a normal
    exit, unconditionally, before any profile-directory cleanup is attempted."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        else:
            import signal
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
    except Exception:
        pass


def _run_bounded(cmd, timeout):
    """subprocess.run(timeout=...) equivalent that also kills the whole process tree (not
    just the direct child) on timeout, on both Windows and POSIX. Returns a
    types.SimpleNamespace(returncode, stdout, stderr); returncode is None if the process was
    killed for timing out. start_new_session=True on POSIX puts the child in its own process
    group so os.killpg can reach every descendant even if the direct child has already exited
    (e.g. a shell wrapper that already returned while a grandchild it spawned is still
    running) -- Windows' `taskkill /T` does the equivalent by PPID regardless of process
    groups."""
    popen_kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return types.SimpleNamespace(returncode=proc.returncode, stdout=stdout, stderr=stderr), False
    except subprocess.TimeoutExpired:
        _terminate_process_tree(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except Exception:
            stdout, stderr = "", ""
        return types.SimpleNamespace(returncode=None, stdout=stdout, stderr=stderr), True
    finally:
        # WIX-PDF-001 fix round 1: terminate the whole tree unconditionally, even on a normal
        # (non-timeout) exit -- a browser can leave a lingering helper/renderer process running
        # after its own main process exits, and that lingering process is exactly what was
        # observed holding a file open inside the profile directory this function's caller is
        # about to try to delete. taskkill/killpg against an already-exited pid is a harmless
        # no-op if nothing in its tree is still alive.
        _terminate_process_tree(proc.pid)


def convert_one(html_path, pdf_path, browser_name, browser_path, browser_type, timeout=PER_BROWSER_TIMEOUT_S):
    """Attempt a single browser conversion. Returns (ok, detail). detail is empty on
    success, or a short, documented reason on failure (bounded to 200 chars of the last
    line of stderr/stdout — WIX-PDF-001's finding specifically flagged that subprocess
    output was previously captured and then discarded entirely on every path).

    WIX-PDF-001 fix round 1 (stale-PDF false success): the browser is always pointed at a
    FRESH, uniquely-named temp file -- never directly at the final pdf_path. A pre-existing
    file at pdf_path (a stale report.pdf from a previous run) can therefore never be mistaken
    for this run's output: the temp file either exists (this run produced something) or it
    doesn't (it didn't), independent of whatever was already sitting at pdf_path. The temp
    file is moved into pdf_path via os.replace() only after it has been validated -- an
    unverified or absent conversion never touches pdf_path at all."""
    abs_html = os.path.abspath(html_path)
    dest_pdf = os.path.abspath(pdf_path)
    file_url = "file:///" + abs_html.replace("\\", "/")

    profile_dir = None
    work_fd, work_path = tempfile.mkstemp(prefix="wixie-pdf-out-", suffix=".pdf")
    os.close(work_fd)
    try:
        if browser_type == "chromium":
            # WIX-PDF-001: a fresh, private, per-invocation profile forces a genuinely new
            # browser process instead of letting the launch hand off to (and silently rely
            # on) an already-running instance of the same browser.
            profile_dir = tempfile.mkdtemp(prefix="wixie-pdf-profile-")
            cmd = [browser_path] + CHROMIUM_ARGS + [
                f"--user-data-dir={profile_dir}",
                f"--print-to-pdf={work_path}",
                file_url,
            ]
        elif browser_type == "firefox":
            profile_dir = tempfile.mkdtemp(prefix="wixie-pdf-profile-")
            cmd = [
                browser_path, "--headless", "-no-remote", "-new-instance",
                "-profile", profile_dir, f"--print-to-file={work_path}", file_url,
            ]
        elif browser_type == "wkhtmltopdf":
            cmd = [browser_path, "--quiet", "--page-size", "A4", "--no-outline", abs_html, work_path]
        else:
            return False, f"unknown browser type '{browser_type}'"

        try:
            result, timed_out = _run_bounded(cmd, timeout)
        except (FileNotFoundError, OSError) as exc:
            return False, f"failed to launch: {exc}"

        if timed_out:
            return False, f"timed out after {timeout}s (process tree terminated)"

        def _tail(res):
            lines = (res.stderr or res.stdout or "").strip().splitlines()
            return f": {lines[-1][:200]}" if lines else ""

        if not os.path.isfile(work_path) or os.path.getsize(work_path) == 0:
            reason = f"exit {result.returncode}" if result.returncode != 0 else "reported success but wrote nothing"
            return False, f"{reason}{_tail(result)}"

        with open(work_path, "rb") as fh:
            header_ok = fh.read(5) == b"%PDF-"
        if not header_ok:
            return False, f"produced a non-PDF file (missing %PDF- header){_tail(result)}"

        # Verified: this run's own temp output exists, is non-empty, and starts with a PDF
        # header. Only now does anything touch pdf_path -- os.replace is atomic on both
        # Windows and POSIX, so a reader can never observe a half-written destination file.
        os.replace(work_path, dest_pdf)
        work_path = None
        return True, ""
    finally:
        # The temp output file must be removed on every non-success path (it holds either
        # nothing, a partial write, or a rejected non-PDF -- never something to keep).
        if work_path and os.path.isfile(work_path):
            try:
                os.remove(work_path)
            except OSError:
                pass
        if profile_dir:
            _rmtree_with_retries(profile_dir)


def convert_with_fallback(html_path, pdf_path, candidates, overall_timeout=OVERALL_TIMEOUT_S,
                           per_browser_timeout=PER_BROWSER_TIMEOUT_S):
    """Try each candidate browser in order; stop at the first validated PDF. Returns
    (ok, used_name, attempts) where attempts is a list of "name: reason" strings for every
    browser that was tried and failed (WIX-PDF-001: a failing browser must not prevent
    trying the next available converter).

    WIX-PDF-001 fix round 1 (hung converter blocks fallback): each attempt is bounded by
    min(per_browser_timeout, time remaining in the overall budget), never more. A hung first
    browser therefore costs at most per_browser_timeout, not the whole overall_timeout, which
    is exactly what leaves room to actually try the next converter -- the previous behavior
    (report-gen's outer timeout equal to a single browser's timeout) meant a hung browser
    consumed the ENTIRE budget and the process was killed from outside before a second
    candidate was ever attempted."""
    attempts = []
    deadline = time.time() + overall_timeout
    for name, path, btype in candidates:
        remaining = deadline - time.time()
        if remaining <= 0:
            attempts.append(f"{name}: not attempted (overall {overall_timeout}s budget exhausted)")
            continue
        ok, detail = convert_one(html_path, pdf_path, name, path, btype,
                                  timeout=min(per_browser_timeout, remaining))
        if ok:
            return True, name, attempts
        attempts.append(f"{name}: {detail}" if detail else name)
    return False, None, attempts


def main():
    # WIX-PDF-001 fix round 1: sweep any stale wixie-pdf-profile-* directory a prior
    # invocation's own bounded cleanup retry didn't finish removing, before doing anything
    # else. See _sweep_stale_profile_dirs()'s docstring for the safety bounds.
    _sweep_stale_profile_dirs()

    keep_html = "--keep-html" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not args:
        print("Usage: python html-to-pdf.py <html-file-or-prompt-folder> [--keep-html]", file=sys.stderr)
        sys.exit(2)

    target = args[0]
    if os.path.isdir(target):
        html_path = os.path.join(target, "report.html")
        pdf_path = os.path.join(target, "report.pdf")
    else:
        html_path = target
        pdf_path = os.path.splitext(target)[0] + ".pdf"

    if not os.path.isfile(html_path):
        print(f"Error: {html_path} not found", file=sys.stderr)
        sys.exit(2)

    candidates = find_browsers()
    if not candidates:
        print("Warning: No browser found for PDF generation.", file=sys.stderr)
        print("Install Edge, Chrome, Firefox, or wkhtmltopdf.", file=sys.stderr)
        print(f"HTML report available at: {html_path}", file=sys.stderr)
        sys.exit(1)

    ok, used, attempts = convert_with_fallback(html_path, pdf_path, candidates)
    # Earlier failures are reported regardless of the final outcome -- WIX-PDF-001 specifically
    # flagged that subprocess output was captured and then silently discarded; a browser that
    # failed before a later one succeeded is still worth knowing about (e.g. the user's normally
    # preferred browser is broken even though a fallback covered for it this time).
    for a in attempts:
        print(f"  tried and failed: {a}", file=sys.stderr)
    if ok:
        print(f"PDF saved: {pdf_path} (via {used})")
        if not keep_html:
            os.remove(html_path)
    else:
        print(f"Error: all {len(candidates)} available browser(s) failed to generate PDF.", file=sys.stderr)
        print(f"HTML report available at: {html_path}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
