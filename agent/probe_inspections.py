#!/usr/bin/env python3
"""TEMPORARY discovery probe for the VDH inspections portal.

Runs in GitHub Actions (which has open network access) to reverse-engineer the
data endpoints behind inspections.myhealthdepartment.com. Deleted once the real
scraper is built.
"""

import re
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
BASE = "https://inspections.myhealthdepartment.com"


def get(url, headers=None, timeout=25):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()[:2000]
    except Exception as e:
        return None, {"error": str(e)}, b""


def show(label, url, headers=None, body_chars=0):
    status, hdrs, body = get(url, headers)
    ct = hdrs.get("Content-Type", hdrs.get("content-type", "?"))
    print(f"\n[{label}] {url}\n  status={status} type={ct} len={len(body)}")
    if hdrs.get("error"):
        print(f"  error={hdrs['error']}")
    if body_chars and body:
        print("  body>>", body[:body_chars].decode("utf-8", "replace").replace("\n", " ")[:body_chars])
    return status, hdrs, body


def main():
    print("=" * 70)
    print("STEP 1: landing pages")
    print("=" * 70)

    pages = {}
    for slug in ("va-henrico", "va-richmond", "virginia"):
        st, hd, body = show("page", f"{BASE}/{slug}")
        if body:
            pages[slug] = body.decode("utf-8", "replace")

    html = pages.get("va-henrico", "")
    if html:
        print("\n--- scripts on va-henrico ---")
        for m in re.findall(r'<script[^>]+src="([^"]+)"', html)[:40]:
            print("  ", m)
        print("\n--- api-ish strings in page html ---")
        hits = set(re.findall(r'["\'](/[a-zA-Z0-9_\-/\.]*(?:api|json|search|data)[a-zA-Z0-9_\-/\.]*)["\']', html))
        for h in sorted(hits)[:60]:
            print("  ", h)
        print("\n--- forms/inputs ---")
        for m in re.findall(r"<form[^>]*>", html)[:10]:
            print("  ", m[:300])
        for m in re.findall(r"<input[^>]*>", html)[:30]:
            print("  ", m[:200])
        print("\n--- links containing inspection/establishment ---")
        links = set(re.findall(r'href="([^"]*(?:inspection|establishment|facility|module)[^"]*)"', html, re.I))
        for l in sorted(links)[:40]:
            print("  ", l)
        print("\n--- first 3000 chars of body ---")
        body_start = html.find("<body")
        print(html[body_start:body_start + 3000])

    print("\n" + "=" * 70)
    print("STEP 2: js bundles -> api paths")
    print("=" * 70)
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
    for src in srcs[:12]:
        url = urllib.parse.urljoin(f"{BASE}/va-henrico", src)
        if "myhealthdepartment.com" not in urllib.parse.urlparse(url).netloc:
            print(f"  skip external {url}")
            continue
        st, hd, body = get(url)
        text = body.decode("utf-8", "replace")
        print(f"\n[js] {url} status={st} len={len(text)}")
        found = set(re.findall(r'["\'`](/(?:api|v1|v2)[a-zA-Z0-9_\-/\.\{\}:]*)["\'`]', text))
        found |= set(re.findall(r'["\'`](https://[a-zA-Z0-9_\-\.]*myhealthdepartment[a-zA-Z0-9_\-/\.]*)["\'`]', text))
        for f in sorted(found)[:60]:
            print("   ->", f)

    print("\n" + "=" * 70)
    print("STEP 3: candidate endpoints")
    print("=" * 70)
    candidates = [
        f"{BASE}/va-henrico?module=Food",
        f"{BASE}/virginia/Henrico?module=Food",
        f"{BASE}/va-henrico/inspections",
        f"{BASE}/va-henrico/search?q=pizza",
        f"{BASE}/api/v1/jurisdictions",
        f"{BASE}/api/jurisdictions",
        f"{BASE}/api/v1/va-henrico/inspections",
        f"{BASE}/va-henrico/api/inspections",
        f"{BASE}/va-henrico/establishments",
        f"{BASE}/va-henrico/recent",
        f"{BASE}/sitemap.xml",
        f"{BASE}/robots.txt",
    ]
    for c in candidates:
        show("try", c, headers={"Accept": "application/json, text/html"}, body_chars=400)


if __name__ == "__main__":
    sys.exit(main())
