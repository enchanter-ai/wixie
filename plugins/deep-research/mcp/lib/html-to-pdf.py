#!/usr/bin/env python3
"""Wixie HTML-to-PDF — converts HTML reports to PDF using browser headless print.

Usage:
    python html-to-pdf.py <html-file-or-prompt-folder>
    python html-to-pdf.py <prompt-folder> --keep-html

Uses any available browser in headless mode (--print-to-pdf).
Tries: Edge > Chrome > Chromium > Firefox > wkhtmltopdf.

Stdlib only. No pip installs.
"""
import sys, os, subprocess, shutil, platform


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
]


def find_browser():
    """Find an available browser. Returns (name, path, type)."""
    plat = "win32" if sys.platform == "win32" else ("darwin" if sys.platform == "darwin" else "linux")
    for name, path in BROWSERS.get(plat, []):
        if os.path.isfile(path):
            return name, path, "chromium"

    # Try PATH for any Chromium-based browser
    for cmd in ["msedge", "google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "brave-browser"]:
        found = shutil.which(cmd)
        if found:
            return cmd, found, "chromium"

    # Firefox fallback
    firefox_paths = [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        "/usr/bin/firefox",
        "/Applications/Firefox.app/Contents/MacOS/firefox",
    ]
    for path in firefox_paths:
        if os.path.isfile(path):
            return "Firefox", path, "firefox"
    found = shutil.which("firefox")
    if found:
        return "Firefox", found, "firefox"

    # wkhtmltopdf fallback
    found = shutil.which("wkhtmltopdf")
    if found:
        return "wkhtmltopdf", found, "wkhtmltopdf"

    return None, None, None


def convert(html_path, pdf_path, browser_name, browser_path, browser_type):
    """Run the conversion."""
    abs_html = os.path.abspath(html_path)
    abs_pdf = os.path.abspath(pdf_path)
    file_url = "file:///" + abs_html.replace("\\", "/")

    if browser_type == "chromium":
        cmd = [browser_path] + CHROMIUM_ARGS + [f"--print-to-pdf={abs_pdf}", file_url]
    elif browser_type == "firefox":
        cmd = [browser_path, "--headless", f"--print-to-file={abs_pdf}", file_url]
    elif browser_type == "wkhtmltopdf":
        cmd = [browser_path, "--quiet", "--page-size", "A4", "--no-outline", abs_html, abs_pdf]
    else:
        return False

    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if os.path.isfile(abs_pdf) and os.path.getsize(abs_pdf) > 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False


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

    browser_name, browser_path, browser_type = find_browser()
    if not browser_path:
        print("Warning: No browser found for PDF generation.", file=sys.stderr)
        print("Install Edge, Chrome, Firefox, or wkhtmltopdf.", file=sys.stderr)
        print(f"HTML report available at: {html_path}", file=sys.stderr)
        sys.exit(1)

    if convert(html_path, pdf_path, browser_name, browser_path, browser_type):
        print(f"PDF saved: {pdf_path} (via {browser_name})")
        if not keep_html:
            os.remove(html_path)
    else:
        print(f"Error: {browser_name} failed to generate PDF.", file=sys.stderr)
        print(f"HTML report available at: {html_path}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
