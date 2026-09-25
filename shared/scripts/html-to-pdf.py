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

Stdlib only. No pip installs.
"""
import sys, os, subprocess, shutil, platform, tempfile, json, time


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

    WIXIE_TEST_PDF_BROWSERS, if set, is a JSON array of [name, path, type] triples that
    REPLACES real discovery entirely. This module's own tests use it to exercise browser
    selection, fallback ordering, profile isolation and cleanup deterministically against
    stub scripts, without depending on a real installed browser or touching PATH/registry
    state. It is never read outside a test invocation in normal use.
    """
    override = os.environ.get("WIXIE_TEST_PDF_BROWSERS")
    if override:
        try:
            # os.path.abspath also normalizes separators, so a test may supply forward-slash
            # paths on Windows and still get an executable CreateProcess can actually resolve.
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


def _rmtree_with_retries(path, attempts=10, delay=0.5):
    """Remove a directory tree, retrying briefly on failure. A just-exited Chromium-family
    browser can still hold a handle open on a file inside its own profile directory for a
    short moment after subprocess.run() has already returned (observed live on this host: a
    real, isolated Edge profile directory failed to delete for several seconds with no process
    left referencing it -- a transient race, not a permanent lock; a single-attempt
    ignore_errors=True cleanup measurably leaked these on this host across repeated real runs).
    Bounded (worst case ~4.5s here, against subprocess.run's own 30s allowance) and best-effort:
    after the last attempt this still gives up silently, exactly as the single-attempt cleanup
    it replaces did, so a persistent failure here can never turn into a hang or a crash -- it
    only leaves the temp profile directory in place for the OS's own temp cleanup to reclaim."""
    for i in range(attempts):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.isdir(path):
            return
        if i < attempts - 1:
            time.sleep(delay)


def convert_one(html_path, pdf_path, browser_name, browser_path, browser_type, timeout=30):
    """Attempt a single browser conversion. Returns (ok, detail). detail is empty on
    success, or a short, documented reason on failure (bounded to 200 chars of the last
    line of stderr/stdout — WIX-PDF-001's finding specifically flagged that subprocess
    output was previously captured and then discarded entirely on every path)."""
    abs_html = os.path.abspath(html_path)
    abs_pdf = os.path.abspath(pdf_path)
    file_url = "file:///" + abs_html.replace("\\", "/")

    profile_dir = None
    try:
        if browser_type == "chromium":
            # WIX-PDF-001: a fresh, private, per-invocation profile forces a genuinely new
            # browser process instead of letting the launch hand off to (and silently rely
            # on) an already-running instance of the same browser.
            profile_dir = tempfile.mkdtemp(prefix="wixie-pdf-profile-")
            cmd = [browser_path] + CHROMIUM_ARGS + [
                f"--user-data-dir={profile_dir}",
                f"--print-to-pdf={abs_pdf}",
                file_url,
            ]
        elif browser_type == "firefox":
            profile_dir = tempfile.mkdtemp(prefix="wixie-pdf-profile-")
            cmd = [
                browser_path, "--headless", "-no-remote", "-new-instance",
                "-profile", profile_dir, f"--print-to-file={abs_pdf}", file_url,
            ]
        elif browser_type == "wkhtmltopdf":
            cmd = [browser_path, "--quiet", "--page-size", "A4", "--no-outline", abs_html, abs_pdf]
        else:
            return False, f"unknown browser type '{browser_type}'"

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, f"timed out after {timeout}s"
        except (FileNotFoundError, OSError) as exc:
            return False, f"failed to launch: {exc}"

        def _tail(res):
            lines = (res.stderr or res.stdout or "").strip().splitlines()
            return f": {lines[-1][:200]}" if lines else ""

        if not os.path.isfile(abs_pdf) or os.path.getsize(abs_pdf) == 0:
            reason = f"exit {result.returncode}" if result.returncode != 0 else "reported success but wrote nothing"
            return False, f"{reason}{_tail(result)}"

        with open(abs_pdf, "rb") as fh:
            header_ok = fh.read(5) == b"%PDF-"
        # The remove() must happen after the file handle above is closed -- Windows refuses to
        # delete a file that still has an open handle, which used to make this cleanup silently
        # no-op (the OSError was swallowed) and leave the bogus file sitting at abs_pdf.
        if not header_ok:
            try:
                os.remove(abs_pdf)
            except OSError:
                pass
            return False, f"produced a non-PDF file (missing %PDF- header){_tail(result)}"

        return True, ""
    finally:
        if profile_dir:
            _rmtree_with_retries(profile_dir)


def convert_with_fallback(html_path, pdf_path, candidates, timeout=30):
    """Try each candidate browser in order; stop at the first validated PDF. Returns
    (ok, used_name, attempts) where attempts is a list of "name: reason" strings for every
    browser that was tried and failed (WIX-PDF-001: a failing browser must not prevent
    trying the next available converter)."""
    attempts = []
    for name, path, btype in candidates:
        ok, detail = convert_one(html_path, pdf_path, name, path, btype, timeout=timeout)
        if ok:
            return True, name, attempts
        attempts.append(f"{name}: {detail}" if detail else name)
    return False, None, attempts


def main():
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
