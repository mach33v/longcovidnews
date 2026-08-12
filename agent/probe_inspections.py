#!/usr/bin/env python3
"""TEMPORARY probe (round 7): can Vercel's egress reach the inspections portal?

Deploys a throwaway PREVIEW deployment (never production) containing one
function that calls the portal's searchInspections API, then hits it and prints
what came back. This is the deciding test for running the digest on Vercel cron.
"""

import json
import os
import time
import urllib.error
import urllib.request

TEAM_ID = "team_mxgswg0H6H5qIXHzQ2rW3LRE"
TOKEN = os.environ.get("VERCEL_TOKEN", "")

PROBE_FN = r"""
export default async function handler(req, res) {
  const out = { ip: null, tests: [] };

  try {
    const who = await fetch('https://api.ipify.org?format=json');
    out.ip = await who.json();
  } catch (e) { out.ip = String(e); }

  // 1. plain GET of the jurisdiction landing page
  try {
    const r = await fetch('https://inspections.myhealthdepartment.com/va-henrico', {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
      },
    });
    const body = await r.text();
    out.tests.push({ name: 'GET landing', status: r.status, len: body.length, snippet: body.slice(0, 200) });
  } catch (e) { out.tests.push({ name: 'GET landing', error: String(e) }); }

  // 2. the real data call the front-end makes
  try {
    const r = await fetch('https://inspections.myhealthdepartment.com/?page=ajax', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Referer': 'https://inspections.myhealthdepartment.com/va-henrico',
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: JSON.stringify({
        task: 'searchInspections',
        data: {
          path: 'va-henrico',
          programName: '',
          filters: { date: '2026-08-01 to 2026-08-12' },
          start: 0,
          count: 5,
          searchQueryOverride: null,
          searchStr: '',
          lat: 0,
          lng: 0,
          sort: {},
        },
      }),
    });
    const body = await r.text();
    out.tests.push({ name: 'POST ajax', status: r.status, len: body.length, snippet: body.slice(0, 800) });
  } catch (e) { out.tests.push({ name: 'POST ajax', error: String(e) }); }

  res.status(200).json(out);
}
"""


def api(path, data=None, method="GET"):
    url = f"https://api.vercel.com{path}{'&' if '?' in path else '?'}teamId={TEAM_ID}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:600]


def main():
    if not TOKEN:
        print("no VERCEL_TOKEN available to this job")
        return

    print("Creating PREVIEW deployment (target omitted — production is untouched)...")
    status, dep = api("/v13/deployments?skipAutoDetectionConfirmation=1", {
        "name": "inspections-egress-probe",
        "files": [
            {"file": "api/probe.js", "data": PROBE_FN},
            {"file": "index.html", "data": "<html><body>probe</body></html>"},
        ],
        "projectSettings": {"framework": None},
    }, method="POST")
    print("create status:", status)
    if status >= 400:
        print(dep)
        return

    dep_id = dep["id"]
    url = dep.get("url")
    print("deployment:", dep_id, url)

    for _ in range(40):
        time.sleep(5)
        s, d = api(f"/v13/deployments/{dep_id}")
        state = d.get("readyState") if isinstance(d, dict) else None
        print("  state:", state)
        if state in ("READY", "ERROR", "CANCELED"):
            break

    if state != "READY":
        print("deployment did not become ready")
        return

    probe_url = f"https://{url}/api/probe"
    print("\nGET", probe_url)
    req = urllib.request.Request(probe_url, headers={"User-Agent": "probe"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            print("status:", r.status)
            print(r.read().decode("utf-8", "replace")[:4000])
    except urllib.error.HTTPError as e:
        print("HTTP", e.code)
        body = e.read().decode("utf-8", "replace")
        print(body[:1200])
        if e.code == 401:
            print("\n>>> preview deployment is behind Vercel Authentication; "
                  "cannot test egress this way")
    except Exception as e:
        print("error:", e)

    print("\nDeleting probe deployment...")
    print(api(f"/v13/deployments/{dep_id}", method="DELETE"))


if __name__ == "__main__":
    main()
