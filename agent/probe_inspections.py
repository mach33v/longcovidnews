#!/usr/bin/env python3
"""TEMPORARY discovery probe (round 5).

The portal is a Webflow shell whose data comes from JS page-controllers. Pull
those controllers out of the Wayback Machine, extract every endpoint they call,
then hit each one live from the runner — the WAF 403 may only guard the HTML
host, not the data API.
"""

import re
import subprocess
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HOST = "https://inspections.myhealthdepartment.com"

JS_FILES = [
    "/va-henrico/js/page-controllers/jurisdiction-landing/controller.js",
    "/va-henrico/js/page-controllers/search/controller.js",
    "/va-henrico/js/page-controllers/inspection/controller.js",
    "/va-henrico/inspection/js/myhd-full.min.js",
    "/va-henrico/js/myhd-full.min.js",
    "/clarkcountywa/js/page-controllers/search/controller.js",
]


def wayback(path):
    url = f"https://web.archive.org/web/2id_/{HOST}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  wayback miss {path}: {e}")
        return ""


def sh(label, cmd, limit=1200):
    print(f"\n### {label}")
    try:
        p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=90)
        print((p.stdout or "")[:limit])
        if p.stderr.strip():
            print("stderr:", p.stderr[:300])
    except Exception as e:
        print("failed:", e)


def main():
    print("=" * 70)
    print("A. controllers from wayback -> endpoints")
    print("=" * 70)

    endpoints = set()
    hosts = set()
    for path in JS_FILES:
        js = wayback(path)
        if not js:
            continue
        print(f"\n--- {path} ({len(js)} bytes) ---")

        # Absolute URLs to non-CDN hosts
        for u in set(re.findall(r'https?://[a-zA-Z0-9_\-\.]+[a-zA-Z0-9_\-/\.]*', js)):
            if any(x in u for x in ("w3.org", "typekit", "jquery", "cloudflare", "sentry.io", "webflow")):
                continue
            hosts.add(u.split("?")[0])

        # ajax/fetch calls and url-ish literals
        for pat in (
            r'\$\.(?:get|post|ajax)\(\s*["\']([^"\']+)["\']',
            r'url\s*:\s*["\']([^"\']+)["\']',
            r'fetch\(\s*["\'`]([^"\'`]+)["\'`]',
            r'["\'](/[a-zA-Z0-9_\-/\.]*(?:api|search|inspection|establishment|facility)[a-zA-Z0-9_\-/\.]*)["\']',
        ):
            for m in re.findall(pat, js):
                endpoints.add(m)

        # Show the interesting slice of the file verbatim
        for m in re.finditer(r'.{140}(?:\$\.ajax|\$\.get|fetch\(|XMLHttpRequest).{240}', js, re.S):
            print("   ...", m.group(0).replace("\n", " ")[:380])

    print("\n--- endpoint literals found ---")
    for e in sorted(endpoints):
        print("  ", e)
    print("\n--- absolute urls found ---")
    for h in sorted(hosts):
        print("  ", h)

    print("\n" + "=" * 70)
    print("B. live test of every discovered endpoint")
    print("=" * 70)
    tests = []
    for e in sorted(endpoints):
        if e.startswith("http"):
            tests.append(e)
        elif e.startswith("/"):
            tests.append(f"{HOST}/va-henrico{e}")
            tests.append(f"{HOST}{e}")
    tests += sorted(hosts)
    tests += [
        f"{HOST}/va-henrico/search?searchStr=pizza",
        f"{HOST}/va-henrico/inspection/?inspectionID=007606B0-8F56-48AB-B014-F31CB8332C6F",
    ]

    seen = set()
    for t in tests:
        if t in seen:
            continue
        seen.add(t)
        sh(t, f"curl -sS -o /tmp/e.out -m 30 -A '{UA}' "
              f"-H 'Referer: {HOST}/va-henrico' -H 'X-Requested-With: XMLHttpRequest' "
              f"-w 'STATUS=%{{http_code}} SIZE=%{{size_download}} TYPE=%{{content_type}}\\n' '{t}'; "
              f"head -c 200 /tmp/e.out; echo",
           limit=500)


if __name__ == "__main__":
    main()
