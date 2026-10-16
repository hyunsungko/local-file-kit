"""Make real-world style PDFs for tests by printing HTML with a headless Chromium browser (Edge or Chrome).

Browsers embed fonts with ToUnicode maps, as word processors do, so these PDFs exercise the same code paths as
Korean PDFs people receive. Returns None when no browser is installed (tests then skip).
"""
import html
import os
import shutil
import subprocess
import tempfile

CANDIDATES = [
    os.environ.get("LFK_TEST_BROWSER", ""),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
]


def browser():
    for c in CANDIDATES:
        if not c:
            continue
        path = c if os.path.isfile(c) else shutil.which(c)
        if path:
            return path
    return None


def make_pdf(paragraphs, out_path, title="sample"):
    exe = browser()
    if not exe:
        return None
    work = tempfile.mkdtemp(prefix="lfk-pdf-")
    page = os.path.join(work, "page.html")
    body = "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)
    with open(page, "w", encoding="utf-8") as f:
        f.write(f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>"
                f"<body style='font-family: sans-serif'>{body}</body>")
    cmd = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-pdf-header-footer",
           f"--user-data-dir={os.path.join(work, 'profile')}", f"--print-to-pdf={out_path}",
           "file:///" + page.replace("\\", "/").lstrip("/")]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out_path if os.path.isfile(out_path) and os.path.getsize(out_path) > 0 else None
