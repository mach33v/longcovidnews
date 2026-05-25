#!/usr/bin/env python3
"""
Daily Long COVID News agent.
Fetches recent news via multiple RSS sources, writes articles using Claude.
Falls back to Claude generating articles from its own knowledge if RSS is blocked.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree

import anthropic

# Multiple RSS sources — more resilient than Google News alone
RSS_SOURCES = [
    ("https://feeds.reuters.com/reuters/healthNews", "long covid"),
    ("https://rss.medicalnewstoday.com/featurednews.xml", "long covid"),
    ("https://www.nih.gov/news-events/nih-research-matters/rss.xml", "long covid"),
    ("https://tools.cdc.gov/podcasts/feed.asp?feedid=183", "long covid"),
    ("https://jamanetwork.com/rss/site_3/67.xml", "long covid"),
    ("https://www.bmj.com/rss/current.xml", "long covid"),
]

CATEGORIES = {
    "research":  ["study","research","journal","finding","scientists","clinical","published","trial","biomarker"],
    "legal":     ["lawsuit","court","disability","claim","attorney","settlement","ruling","ssdi","compensation"],
    "policy":    ["policy","government","congress","fda","nih","cdc","funding","legislation","bill","act"],
    "treatment": ["treatment","therapy","drug","vaccine","symptom","recovery","medication","relief","exercise"],
}


def fetch_rss(url: str, keyword: str) -> list[dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; LongCovidNewsBot/1.0; +https://longcovidnews.com)",
        "Accept": "application/rss+xml, application/xml, text/xml",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            xml = r.read()
        tree = ElementTree.fromstring(xml)
        cutoff = datetime.now(timezone.utc) - timedelta(days=4)
        items = []
        for item in tree.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link", "")
            desc  = item.findtext("description", "")
            pub   = item.findtext("pubDate", "")
            full  = (title + " " + desc).lower()
            if keyword not in full:
                continue
            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub).astimezone(timezone.utc)
                if pub_dt < cutoff:
                    continue
                pub_iso = pub_dt.isoformat()
            except Exception:
                pub_iso = datetime.now(timezone.utc).isoformat()
            if title:
                items.append({"title": title, "url": link, "desc": desc[:200], "pub": pub_iso})
        return items
    except Exception as e:
        print(f"RSS error {url}: {e}", file=sys.stderr)
        return []


def make_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]


def already_covered_block(existing: list[dict], limit: int = 60) -> str:
    """Return a formatted list of recent article titles to pass to Claude as a do-not-repeat list."""
    titles = [a["title"] for a in existing[:limit]]
    if not titles:
        return ""
    lines = "\n".join(f"- {t}" for t in titles)
    return f"\nTopics already covered (do NOT repeat or substantially overlap with any of these):\n{lines}\n"


def write_articles_from_headlines(items: list[dict], existing: list[dict], client: anthropic.Anthropic) -> list[dict]:
    headlines = "\n".join(
        f"{i+1}. {x['title']} — {x['desc'][:120]}" for i, x in enumerate(items)
    )
    covered = already_covered_block(existing)
    prompt = f"""You are the editor of longcovidnews.com, a trusted daily digest covering long COVID research, law, and policy.
{covered}
Here are today's headlines:

{headlines}

Pick the 3 most newsworthy headlines that have NOT already been covered above, and write a separate 400-500 word article for each. Each article must:
- Have a clear factual headline
- Open with the key fact in the first sentence
- Explain significance for long COVID patients, researchers, or advocates
- End with a one-sentence "why this matters" takeaway

Return ONLY a JSON array with exactly 3 objects:
- "title": string
- "excerpt": string (1-2 sentence preview)
- "body": string (HTML using <p> and <h2> tags only)
- "category": one of: research, legal, policy, treatment, community
- "source_url": string (URL from the headline list, or "")

Raw JSON only, no markdown fences."""

    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = re.sub(r"^```json\s*|\s*```$", "", msg.content[0].text.strip(), flags=re.MULTILINE).strip()
    return json.loads(raw)


def write_articles_from_knowledge(existing: list[dict], client: anthropic.Anthropic) -> list[dict]:
    """Fallback: ask Claude to write about recent long COVID developments it knows about."""
    today = datetime.now(timezone.utc).strftime("%B %Y")
    covered = already_covered_block(existing)
    prompt = f"""You are the editor of longcovidnews.com. Today is {today}.
{covered}
Write 3 timely, informative articles about long COVID that have NOT already been covered above — covering recent research findings, legal/disability developments, treatment advances, or policy changes. Focus on the most clinically or socially significant developments from recent months that are distinct from prior coverage.

Each article must:
- Have a specific, factual headline (not generic — name specific studies, courts, drugs, policies)
- Open with the key fact in the first sentence
- Run 400-500 words
- Be written in plain authoritative prose
- End with a one-sentence "why this matters" takeaway

Return ONLY a JSON array with exactly 3 objects:
- "title": string
- "excerpt": string (1-2 sentence preview)
- "body": string (HTML using <p> and <h2> tags only)
- "category": one of: research, legal, policy, treatment, community
- "source_url": string (leave "" since this is knowledge-based)

Raw JSON only, no markdown fences."""

    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = re.sub(r"^```json\s*|\s*```$", "", msg.content[0].text.strip(), flags=re.MULTILINE).strip()
    return json.loads(raw)


def main():
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Load existing articles FIRST so we can pass them to Claude
    articles_path = os.path.join(os.path.dirname(__file__), "..", "articles.json")
    try:
        with open(articles_path) as f:
            existing = json.load(f)
    except Exception:
        existing = []

    print(f"Existing articles: {len(existing)}", file=sys.stderr)

    # Gather from all RSS sources
    seen, all_items = set(), []
    for url, keyword in RSS_SOURCES:
        for item in fetch_rss(url, keyword):
            key = item["title"].lower()
            if key not in seen:
                seen.add(key)
                all_items.append(item)
        time.sleep(0.5)

    print(f"Found {len(all_items)} unique headlines", file=sys.stderr)

    try:
        if len(all_items) >= 3:
            raw_articles = write_articles_from_headlines(all_items, existing, client)
        else:
            print("Not enough headlines — using Claude knowledge fallback", file=sys.stderr)
            raw_articles = write_articles_from_knowledge(existing, client)
    except Exception as e:
        print(f"Claude error: {e}", file=sys.stderr)
        return

    today = datetime.now(timezone.utc).date().isoformat()
    new_articles = []
    for a in raw_articles:
        new_articles.append({
            "slug":       make_slug(a.get("title", "")),
            "title":      a.get("title", ""),
            "excerpt":    a.get("excerpt", ""),
            "body":       a.get("body", ""),
            "category":   a.get("category", "research"),
            "date":       today,
            "source_url": a.get("source_url", ""),
        })

    existing_slugs = {a["slug"] for a in existing}
    fresh = [a for a in new_articles if a["slug"] not in existing_slugs]

    if not fresh:
        print("No new articles to publish.", file=sys.stderr)
        return

    merged = (fresh + existing)[:500]

    with open(articles_path, "w") as f:
        json.dump(merged, f, indent=2)

    print(f"Published {len(fresh)} article(s):")
    for a in fresh:
        print(f"  [{a['category']}] {a['title']}")


if __name__ == "__main__":
    main()
