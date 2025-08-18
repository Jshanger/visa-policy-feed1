#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
update_policy_news.py — VISA/POLICY-PHRASE ONLY
Keeps ONLY items that explicitly mention visa/policy changes or updates.
Examples that PASS:
  - "visa changes", "change to visa rules", "update to visa policy"
  - "immigration policy update", "changes to immigration rules"
Everything else (acceptances rising, forecasts, podcasts, generic trends) is dropped.

Requires: feedparser, requests
"""

from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlparse
import json
import pathlib
import re

import feedparser
import requests

# ----------------------------
# Config
# ----------------------------
SITE_ROOT = pathlib.Path(__file__).resolve().parent
OUTPUT_FILE = SITE_ROOT / "data" / "policyNews.json"
MAX_ITEMS = 300

FEEDS = [
    # Government / regulator (high signal)
    "https://www.gov.uk/government/organisations/uk-visas-and-immigration.atom",
    "https://www.gov.uk/government/announcements.rss",
    "https://www.canada.ca/en/immigration-refugees-citizenship/atom.xml",
    "https://www.uscis.gov/news/rss.xml",
    "https://www.homeaffairs.gov.au/news-media/rss",
    # Sector press (strictly filtered by phrases below)
    "https://monitor.icef.com/feed/",
    "https://thepienews.com/feed/",
    "https://www.studyinternational.com/news/feed/",
    "https://www.timeshighereducation.com/rss/International",
]

# ----------------------------
# Phrase-based relevance (STRICT)
# ----------------------------
# Must match at least ONE of these regexes (case-insensitive).
# These cover "visa change(s)/update(s)/rule(s)" and "immigration policy/rules changes/updates".
PHRASE_PATTERNS = [
    r"\bvisa (change|changes|update|updates|rule|rules|visa policy|visa policies)\b",
    r"\b(change|changes|update|updates) to (?:the )?visa (?:rules|policy|policies)\b",
    r"\bvisa (?:rule|policy) (?:change|changes|update|updates)\b",
    r"\bvisa (?:requirements?|conditions?) (?:change|changes|updated|update)\b",

    r"\bimmigration (?:policy|policies|rule|rules) (?:change|changes|update|updates)\b",
    r"\b(change|changes|update|updates) to (?:the )?immigration (?:rules|policy|policies)\b",

    # student-route / graduate-route policy phrasings
    r"\bstudent (?:route|visa) (?:change|changes|update|updates)\b",
    r"\bgraduate route (?:change|changes|update|updates)\b",
    r"\bpost[- ]study work (?:change|changes|update|updates)\b",
    r"\bopt\b.*\b(update|change|changes|updated)\b",          # OPT update/change
    r"\b(work hours|work rights).*(update|change|changes|updated)\b",
    r"\bIH?S\b.*\b(update|change|changes|increase|decrease)\b",  # IHS / NHS surcharge
]

PHRASE_RES = [re.compile(p, re.IGNORECASE) for p in PHRASE_PATTERNS]

# Hard excludes (unrelated visa contexts / geopolitics)
EXCLUDE_TERMS = [
    "diplomat", "ambassador", "ceasefire", "arms deal", "sanction",
    "military", "consulate attack", "asylum seeker", "deportation flight",
    "tourist visa only", "business visa only", "turkey", "turkish"
]

def mentions_required_phrase(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    # quick drops
    if any(e in t for e in (x.lower() for x in EXCLUDE_TERMS)):
        return False
    # require an explicit change/update phrase around visa/immigration
    return any(rx.search(t) for rx in PHRASE_RES)

# ----------------------------
# Utils
# ----------------------------
TAG_RE = re.compile(r"<[^>]+>")

def clean_html(text: str) -> str:
    if not text:
        return ""
    return unescape(TAG_RE.sub("", text)).strip()

def norm_date_from_struct(d) -> str:
    return datetime(d.tm_year, d.tm_mon, d.tm_mday, tzinfo=timezone.utc).date().isoformat()

def iso_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()

def host_to_source(url: str) -> str:
    try:
        host = urlparse(url).netloc
        if host.startswith("www."):
            host = host[4:]
        return host or "Source"
    except Exception:
        return "Source"

def smart_excerpt(text: str, limit: int = 480) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_sentence = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if last_sentence > 50:
        return cut[: last_sentence + 1] + " …"
    last_space = cut.rfind(" ")
    return (cut[:last_space] if last_space > 0 else cut) + " …"

# ----------------------------
# Fetch & build
# ----------------------------
def fetch_feed(url: str):
    fp = feedparser.parse(url)
    if fp.bozo and not fp.entries:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        fp = feedparser.parse(r.text)
    return fp.entries or []

def category_for(text: str) -> str:
    # Simple badge (optional)
    t = (text or "").lower()
    if "policy" in t or "rule" in t:
        return "Policy Update"
    if "visa" in t or "permit" in t:
        return "Visa & Immigration"
    return "Update"

def build_item(entry) -> dict:
    title = clean_html(getattr(entry, "title", "") or "")
    url = getattr(entry, "link", "") or ""
    summary = clean_html(getattr(entry, "summary", "") or "")
    content_txt = summary
    try:
        if not content_txt and getattr(entry, "content", None):
            content_txt = clean_html(entry.content[0].value)
    except Exception:
        pass

    # date
    if getattr(entry, "published_parsed", None):
        date_str = norm_date_from_struct(entry.published_parsed)
    elif getattr(entry, "updated_parsed", None):
        date_str = norm_date_from_struct(entry.updated_parsed)
    else:
        date_str = iso_today()

    score_text = f"{title} {content_txt}"
    return {
        "date": date_str,
        "category": category_for(score_text),
        "headline": title[:300],
        "description": smart_excerpt(content_txt, 480),
        "source": host_to_source(url),
        "url": url,
        "_scoretext": score_text,  # stripped before write
    }

def dedupe(items):
    seen = set()
    out = []
    for it in items:
        key = (it["headline"].strip().lower(), it["url"])
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out

# ----------------------------
# Main
# ----------------------------
def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    collected = []
    for feed in FEEDS:
        try:
            for e in fetch_feed(feed):
                it = build_item(e)
                if mentions_required_phrase(it["_scoretext"]):
                    collected.append(it)
        except Exception as ex:
            print(f"[warn] feed failed: {feed} -> {ex}")

    # strip temp key
    for it in collected:
        it.pop("_scoretext", None)

    # dedupe & sort
    items = dedupe(collected)
    items.sort(key=lambda x: x["date"], reverse=True)
    items = items[:MAX_ITEMS]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"policyNews": items}, f, ensure_ascii=False, indent=2)

    print(f"wrote {len(items)} items -> {OUTPUT_FILE}")

if __name__ == "__main__":
    main()




