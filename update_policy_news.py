#!/usr/bin/env python3
"""
update_policy_news.py
Fetches visa- and immigration-policy headlines, cleans them,
and writes data/policyNews.json for your static site.

Run with:  python update_policy_news.py
Schedule with cron, Lambda, or GitHub Actions as needed.
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
MAX_ITEMS = 40  # keep your JSON light for quick client fetches

# Add or remove RSS/Atom/JSON endpoints here
FEEDS = [
    # UK Home Office news RSS
    "https://www.gov.uk/government/organisations/home-office.atom",
    # Australian Home Affairs newsroom RSS  
    "https://minister.homeaffairs.gov.au/newsroom/Pages/Newsroom.aspx?rss=true",
    # IRCC news RSS
    "https://www.canada.ca/content/canadasite/en/immigration-refugees-citizenship/news/2025.atom",
    # ICA Singapore newsroom RSS
    "https://www.ica.gov.sg/newsroom.rss",
    # SCMP China politics RSS (visa policies often appear here)
    "https://www.scmp.com/rss/91/feed",
]

# Keywords that signal a policy or visa change
KEYWORDS = (
    "visa", "immigration", "student pass", "skilled worker", "permanent resident",
    "visa exemption", "K-visa", "salary threshold", "work permit", "entry", "stay",
    "border", "travel", "tourist", "visitor", "sponsor", "points", "requirement"
)

# Mapping from hostname to display "Source: xxx"
SOURCE_MAP = {
    "gov.uk": "UK Home Office",
    "homeaffairs": "Department of Home Affairs AU", 
    "canada.ca": "IRCC Canada",
    "ica.gov.sg": "ICA Singapore",
    "scmp.com": "South China Morning Post",
    "reuters.com": "Reuters",
    "bbc.com": "BBC News",
    "cnn.com": "CNN",
}

def looks_policy_related(title: str, summary: str) -> bool:
    """Check if content appears to be about visa/immigration policy."""
    blob = (title + " " + summary).lower()
    return any(keyword in blob for keyword in KEYWORDS)

def clean_text(text: str, limit: int = 300) -> str:
    """Clean and truncate text."""
    if not text:
        return ""
    return " ".join(text.replace("\n", " ").split())[:limit].strip()

def human_date(dt) -> str:
    """Return YYYY-MM-DD from datetime or struct_time."""
    if isinstance(dt, datetime.date):
        return dt.strftime("%Y-%m-%d")
    try:
        return datetime.date(*dt[:3]).isoformat()
    except (TypeError, ValueError):
        return datetime.date.today().isoformat()

def category_from_title(title: str) -> str:
    """Basic heuristic for card badge category."""
    lowered = title.lower()
    if "student" in lowered:
        return "Student Visas"
    elif "skilled" in lowered or "work" in lowered:
        return "Work Visas" 
    elif "tourist" in lowered or "visitor" in lowered:
        return "Tourist Visas"
    elif "exempt" in lowered:
        return "Visa Exemption"
    elif "permanent" in lowered or "resident" in lowered:
        return "Immigration Policy"
    else:
        return "Policy Update"

def source_from_link(link: str) -> str:
    """Extract source name from URL."""
    for key, label in SOURCE_MAP.items():
        if key in link:
            return label
    try:
        return link.split('/')[2]  # fallback to hostname
    except (IndexError, AttributeError):
        return "Unknown Source"

def fetch_policy_news() -> List[Dict[str, Any]]:
    """Fetch and parse policy news from configured feeds."""
    cards = []

    for feed_url in FEEDS:
        try:
            print(f"Fetching {feed_url}...")
            feed = feedparser.parse(feed_url, 
                                  request_headers={"User-Agent": "policy-bot/1.0"})

            for entry in feed.entries:
                title = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()

                if not title or not looks_policy_related(title, summary):
                    continue

                link = entry.get("link", "")
                date_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                date_str = human_date(date_parsed)

                cards.append({
                    "date": date_str,
                    "category": category_from_title(title),
                    "headline": clean_text(title, 140),
                    "description": clean_text(summary, 230),
                    "source": source_from_link(link),
                    "url": link
                })

        except Exception as e:
            print(f"Error processing {feed_url}: {e}")
            continue

    return cards

def deduplicate_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate entries based on headline and date."""
    seen = set()
    deduped = []

    # Sort by date, newest first
    sorted_cards = sorted(cards, key=lambda x: x["date"], reverse=True)

    for card in sorted_cards:
        key = (card["headline"], card["date"])
        if key not in seen:
            deduped.append(card)
            seen.add(key)

    return deduped

def main():
    """Main function to update policy news."""
    print("🔄 Fetching policy news updates...")

    # Fetch news from all feeds
    cards = fetch_policy_news()

    # Remove duplicates and limit
    deduped_cards = deduplicate_cards(cards)[:MAX_ITEMS]

    # Create output payload
    payload = {"policyNews": deduped_cards}

    # Ensure output directory exists
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Write JSON file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"✅ Wrote {len(deduped_cards)} items → {OUTPUT_FILE}")
    print(f"📅 Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
