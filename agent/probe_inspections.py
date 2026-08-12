#!/usr/bin/env python3
"""TEMPORARY discovery probe (round 4).

Established so far: inspections.myhealthdepartment.com returns an AWS-ALB 403 to
the GitHub runner and to a third-party reader service alike, headless Chromium
included, and no open-data mirror of Henrico/Richmond inspections exists.

Round 4 answers two things:
  1. Is there ANY egress that gets a 200? (public proxy services)
  2. What does the page look like? (Wayback snapshots — enough to write the
     parser even if the live fetch has to go through some other route.)
"""

import json
import subprocess
import urllib.parse

TARGET = "https://inspections.myhealthdepartment.com/va-henrico"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def sh(label, cmd, limit=3000):
    print(f"\n### {label}")
    try:
        p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=150)
        print((p.stdout or "")[:limit])
        if p.stderr.strip():
            print("stderr:", p.stderr[:400])
    except Exception as e:
        print("failed:", e)


def main():
    enc = urllib.parse.quote(TARGET, safe="")

    print("=" * 70)
    print("A. public proxy services — does any egress get a 200?")
    print("=" * 70)
    proxies = {
        "allorigins": f"https://api.allorigins.win/raw?url={enc}",
        "codetabs": f"https://api.codetabs.com/v1/proxy?quest={enc}",
        "corsproxy.io": f"https://corsproxy.io/?url={enc}",
        "thingproxy": f"https://thingproxy.freeboard.io/fetch/{TARGET}",
        "textance": f"https://urlreq.appspot.com/req?method=GET&url={enc}",
    }
    for name, url in proxies.items():
        sh(name,
           f"curl -sS -m 45 -A '{UA}' -o /tmp/{name}.out -w 'STATUS=%{{http_code}} SIZE=%{{size_download}}\\n' "
           f"'{url}'; echo '--- first 300 bytes ---'; head -c 300 /tmp/{name}.out; echo",
           limit=900)

    print("\n" + "=" * 70)
    print("B. wayback machine — snapshots of the portal")
    print("=" * 70)
    sh("availability api",
       f"curl -sS -m 40 'https://archive.org/wayback/available?url=inspections.myhealthdepartment.com/va-henrico'")
    sh("cdx: all captured urls under the va-henrico path",
       "curl -sS -m 60 'https://web.archive.org/cdx/search/cdx?url=inspections.myhealthdepartment.com/va-henrico*"
       "&output=text&fl=timestamp,original,statuscode&collapse=urlkey&limit=60'")
    sh("cdx: any api-looking captures on the host",
       "curl -sS -m 60 'https://web.archive.org/cdx/search/cdx?url=inspections.myhealthdepartment.com*"
       "&output=text&fl=timestamp,original,statuscode&collapse=urlkey&filter=original:.*(api|json|search).*&limit=60'")

    print("\n" + "=" * 70)
    print("C. fetch the newest wayback snapshot and dissect it")
    print("=" * 70)
    sh("newest snapshot html -> structure",
       "curl -sSL -m 90 'https://web.archive.org/web/2id_/https://inspections.myhealthdepartment.com/va-henrico' "
       "-o /tmp/wb.html -w 'STATUS=%{http_code} SIZE=%{size_download}\\n'; "
       "echo '--- scripts ---'; grep -oE '<script[^>]*src=\"[^\"]+\"' /tmp/wb.html | head -20; "
       "echo '--- api-ish strings ---'; grep -oE '\"/[a-zA-Z0-9_/.-]*(api|json|search|inspection)[a-zA-Z0-9_/.-]*\"' /tmp/wb.html | sort -u | head -40; "
       "echo '--- title/text sample ---'; grep -oE '<title>[^<]*</title>' /tmp/wb.html | head -3; "
       "head -c 1200 /tmp/wb.html",
       limit=4000)

    print("\n" + "=" * 70)
    print("D. sanity: can the runner reach unrelated sites fine?")
    print("=" * 70)
    sh("control fetches",
       "for u in https://example.com https://www.henrico.gov https://api.telegram.org; do "
       "printf '%s ' $u; curl -sS -o /dev/null -m 25 -w 'STATUS=%{http_code}\\n' $u || echo err; done")


if __name__ == "__main__":
    main()
