#!/usr/bin/env python3
"""
Daily Long COVID News agent.
Fetches recent news via Google News RSS, writes articles using Claude,
prepends them to articles.json.
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

QUERIES = [
    "long COVID research study",
    "long COVID treatment symptoms",
    "long COVID disability lawsuit",
    "long COVID policy government",
]

CATEGORIES = {
    "research": ["study", "research", "journal", "finding", "scientists", "clinical trial", "published"],
    "legal": ["lawsuit", "court", "disability", "claim", "attorney", "settlement", "ruling", "ssdi"],
    "policy": ["policy", "government", "congress", "fda", "nih", "cdc", "funding", "legislation"],
    "treatment": ["treatment", "therapy", "drug", "vaccine", "symptom", "recovery", "medication"],
}

def fetch_rss(query: str) -> list[dict]:
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            xml = r.read()
        tree = ElementTree.fromstring(xml)
        cutoff = datetime.now(timezone.utc) - timedelta(days=2)
        items = []
        for item in tree.findall(".//item"):
            title = item.findtext("title", "").split(" - ")[0].strip()
            link  = item.findtext("link", "")
            desc  = item.findtext("description", "")
            pub   = item.findtext("pubDate", "")
            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub).astimezone(timezone.utc)
                if pub_dt < cutoff:
                    continue
                pub_iso = pub_dt.isoformat()
            except Exception:
                pub_iso = datetime.now(timezone.utc).isoformat()
            if title and "long covid" in (title + desc).lower():
                items.append({"title": title, "url": link, "desc": desc, "pub": pub_iso})
        return items
    except Exception as e:
        print(f"RSS fetch failed for '{query}': {e}", file=sys.stderr)
        return []


def guess_category(text: str) -> str:
    text = text.lower()
    for cat, keywords in CATEGORIES.items():
        if any(k in text for k in keywords):
            return cat
    return "research"


def make_slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:80]


def write_articles(items: list[dict], client: anthropic.Anthropic) -> list[dict]:
    if not items:
        return []

    headlines = "\n".join(f"{i+1}. {x['title']} — {x['desc'][:120]}" for i, x in enumerate(items))

    # Ask Claude to pick the 3 best and write articles
    prompt = f"""You are the editor of longcovidnews.com, a trusted daily digest covering long COVID research, law, and policy.

Here are today's headlines (last 48 hours):

{headlines}

Pick the 3 most newsworthy and write a separate 350-500 word article for each. Each article must:
- Have a clear, factual headline (no clickbait)
- Open with the key fact in the first sentence
- Explain the significance for long COVID patients, researchers, or advocates
- Be written in plain, authoritative prose — not sensationalist
- End with a 1-sentence "why this matters" conclusion

Return ONLY a JSON array with exactly 3 objects, each with these fields:
- "title": string
- "excerpt": string (1-2 sentences, used as preview)
- "body": string (HTML paragraphs using <p> and <h2> tags only)
- "category": one of: research, legal, policy, treatment, community
- "source_url": string (the source URL from the headline list, or "" if unknown)

Return raw JSON only, no markdown fences."""

    try:
        msg = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        # Strip markdown fences if present
        raw = re.sub(r"^```json\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        articles = json.loads(raw)
    except Exception as e:
        print(f"Claude error: {e}", file=sys.stderr)
        return []

    today = datetime.now(timezone.utc).date().isoformat()
    results = []
    for a in articles:
        results.append({
            "slug":       make_slug(a.get("title", "")),
            "title":      a.get("title", ""),
            "excerpt":    a.get("excerpt", ""),
            "body":       a.get("body", ""),
            "category":   a.get("category", "research"),
            "date":       today,
            "source_url": a.get("source_url", ""),
        })
    return results


def main():
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Gather headlines from all queries, deduplicate by title
    seen, all_items = set(), []
    for q in QUERIES:
        for item in fetch_rss(q):
            key = item["title"].lower()
            if key not in seen:
                seen.add(key)
                all_items.append(item)
        time.sleep(0.5)

    print(f"Found {len(all_items)} unique headlines", file=sys.stderr)

    if not all_items:
        print("No headlines found, skipping.", file=sys.stderr)
        return

    new_articles = write_articles(all_items, client)
    if not new_articles:
        print("No articles written, skipping.", file=sys.stderr)
        return

    articles_path = os.path.join(os.path.dirname(__file__), "..", "articles.json")
    try:
        with open(articles_path) as f:
            existing = json.load(f)
    except Exception:
        existing = []

    # Deduplicate by slug
    existing_slugs = {a["slug"] for a in existing}
    fresh = [a for a in new_articles if a["slug"] not in existing_slugs]

    if not fresh:
        print("All articles already exist, skipping.", file=sys.stderr)
        return

    merged = fresh + existing
    # Keep latest 500 articles
    merged = merged[:500]

    with open(articles_path, "w") as f:
        json.dump(merged, f, indent=2)

    print(f"Published {len(fresh)} new article(s): {[a['title'] for a in fresh]}")


if __name__ == "__main__":
    main()
