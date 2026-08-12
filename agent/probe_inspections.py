#!/usr/bin/env python3
"""TEMPORARY discovery probe (round 6).

The portal's data API is same-host: the front-end POSTs {"task": ..., "data": {...}}
to "/?page=ajax". Dump the page controllers so the exact task names and payloads
are known, and pull one archived inspection page as a parser fixture.
"""

import re
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HOST = "https://inspections.myhealthdepartment.com"


def wayback(path, timeout=120):
    url = f"https://web.archive.org/web/2id_/{HOST}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            print(f"  (attempt {attempt + 1} failed for {path}: {e})")
    return ""


def main():
    print("=" * 70)
    print("A. jurisdiction-landing controller (full)")
    print("=" * 70)
    js = wayback("/va-henrico/js/page-controllers/jurisdiction-landing/controller.js")
    print(js if js else "(unavailable)")

    print("\n" + "=" * 70)
    print("B. search controller (full)")
    print("=" * 70)
    js2 = wayback("/va-henrico/js/page-controllers/search/controller.js")
    print(js2 if js2 else "(unavailable)")

    print("\n" + "=" * 70)
    print("C. ajax plumbing inside myhd-full.min.js")
    print("=" * 70)
    big = wayback("/va-henrico/js/myhd-full.min.js")
    if big:
        print(f"(bundle {len(big)} bytes)")
        for needle in ("page=ajax", "task:", '"task"', "getInspection", "getEstablishment",
                       "searchStr", "inspectionID"):
            print(f"\n--- context for {needle!r} ---")
            for m in list(re.finditer(re.escape(needle), big))[:6]:
                s = max(0, m.start() - 300)
                print("  ...", big[s:m.end() + 300].replace("\n", " "))
    else:
        print("(bundle unavailable)")

    print("\n" + "=" * 70)
    print("D. archived inspection detail page (parser fixture)")
    print("=" * 70)
    html = wayback("/va-henrico/inspection/?inspectionID=007606B0-8F56-48AB-B014-F31CB8332C6F")
    print(f"(length {len(html)})")
    print(html[:12000] if html else "(unavailable)")


if __name__ == "__main__":
    main()
