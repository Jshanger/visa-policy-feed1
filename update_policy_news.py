#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
update_policy_news.py
Fetches immigration / international-education headlines, filters for
student / study-abroad / mobility relevance, and writes data/policyNews.json
for the static site.
"""

from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlparse
import json
import pathlib

import feedparser
import requests

# ----------------------------
# Config
# ----------------------------
SITE_ROOT = pathlib.Path(__file__).resolve().parent
OUTPUT_FILE = SITE_ROOT / "data" / "policyNews.json"
MAX_ITEMS = 300  # keep the JSON light

# Feeds (add/remove freely)
FEEDS = [
    # Government / immigration
    "https://www.gov.uk/government/announcements.rss",
    "https://www.gov.uk/government/organisations/uk-visas-and-immigration.atom",
    "https://www.homeaffairs.gov.au/news-media/rss",
    "https://www.canada.ca/en/immigration-refugees-citizenship.atom",
    "https://www.uscis.gov/news/rss.xml",
    "https://www.immigration.govt.nz/about-us/media-centre/rss",  # NZ Immigration (if 404, harmless)

    # International education industry
    "https://monitor.icef.com/feed/",
    "https://thepienews.com/feed/",
    "https://www.studyinternational.com/news/feed/",
    "https://www.timeshighereducation.com/rss/International",
]

# ----------------------------
# Relevance filters
# ----------------------------

# Keep if any of these terms appear (international students / mobility focus)
KEEP_KEYWORDS = [
    # core student/visa/study abroad
    "student visa", "study visa", "study permit", "international student",
    "study abroad", "exchange student", "erasmus", "graduate route",
    "post-study work", "post study work", "psw", "opt", "stem opt",
    "f-1 visa", "j-1 visa", "sevis", "ds-160", "ukvi", "home office",
    "ircc", "uscis", "department of home affairs",

    # admissions / requirements / costs
    "university admissions", "offer letter", "cas letter", "atas",
    "scholarship", "bursary", "tuition fee", "application deadline",
    "ielts", "toefl", "pte", "ukvi ielts",

    # dependants / rights / work / ihs
    "dependent visa", "dependants", "spouse visa", "work hours", "work rights",
    "health surcharge", "ihs", "nhs surcharge",

    # international student mobility / tne / recruitment
    "student mobility", "international student mobility", "inbound mobility",
    "outbound mobility", "cross-border education", "transnational education",
    "tne", "branch campus", "satellite campus", "pathway provider",
    "pre-sessional", "recruitment agent", "education agent", "agent commission",
    "enrolment", "enrollment", "intake", "cohort", "student flows",
    "visa approvals", "visa refusals", "acceptance rate", "offer rate",
    "visa processing time", "backlog",

    # frameworks / regulators often present in mobility context
    "ucas", "qaa", "teqsa", "cricos", "sevp", "sevp portal", "sevp-certified",
]

# Drop if any of these appear (unrelated geopolitics, non-student visa)
EXCLUDE_TERMS = [
    "diplomat", "ambassador", "sanction", "ceasefire", "arms deal",
    "military", "consulate attack", "asylum seeker", "deportation flight",
    "tourist visa only", "business visa only", "resident diplomat",
]

# ----------------------------
# Helpers
# ----------------------------
def norm_date(entry) -> str:
    """Return YYYY-MM-DD from typical feed date fields; fallback to today (UTC)."""
    dt = None
    for k in ("published_parsed", "updated_parsed"):
        if getattr(entry, k, None):
            dt = getattr(entry, k)
            break
        if isinstance(entry.get(k), tuple):
            dt = entry.get(k)
            break
    if dt:
        try:
            return datetime(*dt[:6], tzinfo=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def host_to_source(url_or_title: str) -> str:
    try:
        netloc = urlparse(url_or_title).netloc
        if netloc:
            return netloc.replace("www.", "")
    except Exception:
        pass
    return (url_or_title or "").strip()[:60]


def clean_html(s: str) -> str:
    if not s:
        return ""
    s = unescape(s)
    # quick tag strip
    out, inside = [], 0
    for ch in s:
        if ch == "<":
            inside = 1
            continue
        if ch == ">":
            inside = 0
            out.append(" ")
            continue
        if not inside:
            out.append(ch)
    return " ".join("".join(out).split())


def is_relevant(text: str) -> bool:
    t = (text or "").lower()
    if any(x in t for x in (e.lower() for e in EXCLUDE_TERMS)):
        return False
    return any(kw in t for kw in (k.lower() for k in KEEP_KEYWORDS))


def dedupe(items):
    seen = set()
    out = []
    for it in items:
        key = (it.get("url") or "").strip().lower() or (it.get("headline") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


# ----------------------------
# Fetch & build
# ----------------------------
def fetch_feed(url: str):
    try:
        parsed = feedparser.parse(url)
        return parsed.entries or []
    except Exception:
        return []


def build_item(entry, feed_url: str):
    link = entry.get("link") or ""
    headline = clean_html(entry.get("title") or "")
    desc = clean_html(entry.get("summary") or entry.get("description") or "")
    date_str = norm_date(entry)
    source = host_to_source(link or feed_url)
    return {
        "date": date_str,
        "category": "Policy Update",
        "headline": headline,
        "description": desc,
        "source": source,
        "url": link or feed_url,
    }


def main():
    collected = []
    for feed in FEEDS:
        for e in fetch_feed(feed):
            item = build_item(e, feed)
            text = f"{item['headline']} {item['description']} {item['source']}"
            if is_relevant(text):
                collected.append(item)

    collected.sort(key=lambda x: x["date"], reverse=True)
    collected = dedupe(collected)[:MAX_ITEMS]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"policyNews": collected}, fh, ensure_ascii=False, indent=2)

    print(f"Saved {len(collected)} items to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

