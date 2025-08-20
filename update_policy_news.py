#!/usr/bin/env python3
"""
update_policy_news.py - Broader visa/policy filter
Keeps articles about visas, immigration, student policy, or work permits.
Less restrictive than the strict script, so more items are included.
"""

import json
import datetime
import pathlib
import requests
import feedparser
from typing import List, Dict, Any

# -------- configuration -------- #
SITE_ROOT = pathlib.Path(__file__).resolve().parent
OUTPUT_FILE = SITE_ROOT / "data" / "policyNews.json"
MAX_ITEMS = 60  # keep JSON light for quick client fetches

# Feeds to scan (government + sector press)
FEEDS = [
    "https://www.gov.uk/government/organisations/home-office.atom",
    "https://www.gov.uk/government/announcements.rss",
    "https://www.canada.ca/en/immigration-refugees-citizenship/atom.xml",
    "https://www.uscis.gov/news/rss.xml",
    "https://www.homeaffairs.gov.au/news-media/rss",
    "https://monitor.icef.com/feed/",
    "https://www.studyinternational.com/news/feed/",
    "https://www.timeshighereducation.com/rss/International",
    "https://thepienews.com/feed/",
    "https://thepienews.com/news/feed/",
    "https://www.universityworldnews.com/rss/",
]

# Broader keyword set (looser filter)
KEYWORDS = (
    "visa", "immigration", "student", "graduate route", "post-study", "psw",
    "opt", "pgwp", "work permit", "skilled worker", "border", "entry", "stay",
    "residency", "international student", "fee", "tuition", "ihs", "surcharge",
    "dependant", "dependent", "work hours", "work rights", "policy", "rules"
)

# Mapping from hostname substring → display name
SOURCE_MAP = {
    "gov.uk": "UK Government",
    "canada.ca": "IRCC Canada",
    "uscis.gov": "USCIS",
    "homeaffairs": "Dept. of Home Affairs (AU)",
    "monitor.icef": "ICEF Monitor",
    "studyinternational": "Study International",
    "timeshighereducation": "Times Higher Education",
    "thepienews": "The PIE News",
    "universityworldnews": "University World News",
}

# -------- helpers -------- #
def looks_policy_related(title: str, summary: str) -> bool:
    blob = (title + " " + summary).lower()
    return any(k in blob for k in KEYWORDS)

def clean_text(text: str, limit: int = 280) -> str:
    if not text:
        return ""
    txt = " ".join(text.replace("\n", " ").split())
    return txt[:limit].strip()

def human_date(dt) -> str:
    if isinstance(dt, datetime.date):
        return dt.strftime("%Y-%m-%d")
    try:
        return datetime.date(*dt[:3]).isoformat()
    except Exception:
        return datetime.date.today().isoformat()

def category_from_title(title: str) -> str:
    lowered = title.lower()
    if "student" in lowered:
        return "Student / Education"
    elif "work" in lowered or "skilled" in lowered:
        return "Work / Skilled Migration"
    elif "tourist" in lowered or "visitor" in lowered:
        return "Tourist / Visitor"
    elif "resident" in lowered or "permanent" in lowered:
        return "Residency / Immigration"
    else:
        return "Policy Update"

def source_from_link(link: str) -> str:
    for key, label in SOURCE_MAP.items():
        if key in link:
            return label
    try:
        return link.split("/")[2]
    except Exception:
        return "Source"

# -------- main fetcher -------- #
def fetch_policy_news() -> List[Dict[str, Any]]:
    items = []
    for feed_url in FEEDS:
        try:
            print(f"Fetching {feed_url}...")
            feed = feedparser.parse(feed_url, request_headers={"User-Agent": "policy-bot/loose"})
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()
                if not title or not looks_policy_related(title, summary):
                    continue
                link = entry.get("link", "")
                date_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                if not date_parsed:
                    continue
                date_str = human_date(date_parsed)
                items.append({
                    "date": date_str,
                    "category": category_from_title(title),
                    "headline": clean_text(title, 160),
                    "description": clean_text(summary, 240),
                    "source": source_from_link(link),
                    "url": link
                })
        except Exception as e:
            print(f"[warn] failed feed {feed_url}: {e}")
            continue
    return items

def dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for it in sorted(items, key=lambda x: x["date"], reverse=True):
        key = (it["headline"].lower(), it["date"])
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out

def main():
    print("🔄 Fetching policy news...")
    cards = fetch_policy_news()
    deduped = dedupe(cards)[:MAX_ITEMS]
    if not deduped:
        print("⚠️ No matches found, not overwriting existing file.")
        return
    payload = {"policyNews": deduped}
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"✅ Wrote {len(deduped)} items → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()


