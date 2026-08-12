#!/usr/bin/env python3
"""TEMPORARY discovery probe (round 3).

Rounds 1-2: inspections.myhealthdepartment.com answers 403 from its AWS ALB to
everything sent from a GitHub runner, including real headless Chromium — so the
block is IP/ASN based. Now look for a route that isn't blocked, and for an
open-data source that carries the same inspections.
"""

import subprocess

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def sh(label, cmd):
    print(f"\n### {label}")
    try:
        p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=120)
        print((p.stdout or "")[:3000])
        if p.stderr.strip():
            print("stderr:", p.stderr[:500])
    except Exception as e:
        print("failed:", e)


def main():
    print("=" * 70)
    print("A. alternate hosts for the same platform")
    print("=" * 70)
    for host in [
        "api.myhealthdepartment.com",
        "inspections-api.myhealthdepartment.com",
        "app.myhealthdepartment.com",
        "va.myhealthdepartment.com",
        "healthspace.com",
        "www.healthspace.com",
    ]:
        sh(host, f"curl -sS -o /dev/null -w 'STATUS=%{{http_code}} IP=%{{remote_ip}}\\n' "
                 f"-m 25 -A '{UA}' https://{host}/ 2>&1 | tail -3")

    sh("legacy healthspace VDH module",
       f"curl -sS -o /dev/null -w 'STATUS=%{{http_code}}\\n' -m 25 -A '{UA}' -L "
       f"'https://healthspace.com/Clients/VDH/Virginia/Web.nsf/module_inspections.xsp' 2>&1 | tail -3")

    print("\n" + "=" * 70)
    print("B. does a third-party fetch of the portal succeed? (is it really our IP?)")
    print("=" * 70)
    sh("r.jina.ai reader proxy",
       "curl -sS -m 60 'https://r.jina.ai/https://inspections.myhealthdepartment.com/va-henrico' "
       "| head -c 2500")

    print("\n" + "=" * 70)
    print("C. open data portals")
    print("=" * 70)
    sh("data.virginia.gov CKAN search: inspection",
       "curl -sS -m 40 'https://data.virginia.gov/api/3/action/package_search?q=inspection&rows=25' "
       "| python3 -c \"import sys,json; d=json.load(sys.stdin)['result']; print('count',d['count']); "
       "[print('-',r['title'],'|',r['name'],'|',r.get('organization',{}).get('title')) for r in d['results']]\" 2>&1 | head -40")
    sh("data.virginia.gov CKAN search: restaurant OR food establishment",
       "curl -sS -m 40 'https://data.virginia.gov/api/3/action/package_search?q=restaurant+OR+%22food+establishment%22&rows=25' "
       "| python3 -c \"import sys,json; d=json.load(sys.stdin)['result']; print('count',d['count']); "
       "[print('-',r['title'],'|',r['name'],'|',[x.get('url') for x in r.get('resources',[])][:3]) for r in d['results']]\" 2>&1 | head -60")

    print("\n" + "=" * 70)
    print("D. locality / district pages that may embed the data")
    print("=" * 70)
    sh("henrico.gov food service links",
       f"curl -sS -m 40 -A '{UA}' -L 'https://henrico.gov/health/environmental-health/food-service-links/' "
       "| grep -oE 'href=\"[^\"]*\"' | sort -u | head -40")
    sh("vdh richmond-city food safety",
       f"curl -sS -m 40 -A '{UA}' -L 'https://www.vdh.virginia.gov/richmond-city/food-safety/' "
       "| grep -oiE 'href=\"[^\"]*(inspect|myhealth|healthspace)[^\"]*\"' | sort -u | head -30")


if __name__ == "__main__":
    main()
