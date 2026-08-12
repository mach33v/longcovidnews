#!/usr/bin/env python3
"""TEMPORARY discovery probe for the VDH inspections portal (round 2).

Round 1: every request to inspections.myhealthdepartment.com returned a bare
nginx 403. Figure out whether that's headers, TLS fingerprint, or IP — and try
a headless browser as the fallback.
"""

import json
import subprocess
import sys

URL = "https://inspections.myhealthdepartment.com/va-henrico"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="126", "Not;A=Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}


def run(cmd, label):
    print(f"\n### {label}\n$ {' '.join(cmd[:6])} ...")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        out = (p.stdout or "")[:2500]
        err = (p.stderr or "")[:800]
        print(out)
        if err:
            print("stderr:", err)
    except Exception as e:
        print("failed:", e)


def main():
    print("=" * 70)
    print("A. curl variants — what makes the 403 go away?")
    print("=" * 70)

    hdr_args = []
    for k, v in BROWSER_HEADERS.items():
        hdr_args += ["-H", f"{k}: {v}"]

    fmt = "\\nSTATUS=%{http_code} SIZE=%{size_download} HTTP=%{http_version} IP=%{remote_ip}\\n"

    run(["curl", "-sS", "-o", "/dev/null", "-D", "-", "-w", fmt, "-m", "40", URL],
        "curl bare (default UA)")
    run(["curl", "-sS", "-o", "/dev/null", "-D", "-", "-w", fmt, "-m", "40",
         "-A", BROWSER_HEADERS["User-Agent"], URL],
        "curl + browser UA only")
    run(["curl", "-sS", "-o", "/tmp/full.html", "-D", "-", "-w", fmt, "-m", "40",
         "--compressed", "--http2"] + hdr_args + [URL],
        "curl + full browser header set + http2")
    run(["bash", "-c", "head -c 1500 /tmp/full.html 2>/dev/null || echo '(no body)'"],
        "body of full-header attempt")

    print("\n" + "=" * 70)
    print("B. who is answering? dns + tls + redirects")
    print("=" * 70)
    run(["bash", "-c", "getent hosts inspections.myhealthdepartment.com || true"], "dns")
    run(["bash", "-c",
         "curl -sS -o /dev/null -D - -m 40 -L 'https://inspections.myhealthdepartment.com/' "
         "-A '" + BROWSER_HEADERS["User-Agent"] + "' | head -40"],
        "root path headers")
    run(["bash", "-c", "curl -sSI -m 40 https://www.myhealthdepartment.com/ | head -20"],
        "marketing site (different host?)")

    print("\n" + "=" * 70)
    print("C. headless chromium via playwright")
    print("=" * 70)
    script = r"""
import json, re
from playwright.sync_api import sync_playwright

URL = "https://inspections.myhealthdepartment.com/va-henrico"
calls = []
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 2000})
    page = ctx.new_page()
    page.on("request", lambda r: calls.append((r.method, r.url, r.resource_type)))
    resp = page.goto(URL, wait_until="networkidle", timeout=60000)
    print("STATUS:", resp.status if resp else None)
    print("TITLE:", page.title())
    html = page.content()
    print("HTML LEN:", len(html))
    print("---- xhr/fetch requests ----")
    for m, u, t in calls:
        if t in ("xhr", "fetch") or "/api" in u or ".json" in u:
            print(f"  {m} [{t}] {u}")
    print("---- visible text (first 2500 chars) ----")
    print(page.inner_text("body")[:2500])
    print("---- links ----")
    hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.getAttribute('href'))")
    seen = []
    for h in hrefs:
        if h and h not in seen:
            seen.append(h)
    for h in seen[:60]:
        print("  ", h)
    b.close()
"""
    with open("/tmp/pw.py", "w") as f:
        f.write(script)
    run([sys.executable, "/tmp/pw.py"], "playwright chromium")


if __name__ == "__main__":
    main()
