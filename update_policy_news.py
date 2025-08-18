#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
update_policy_news.py VISA/POLICY-PHRASE ONLY (deterministic)
- Keeps ONLY items that explicitly mention visa/immigration rule changes/updates.
- Deterministic output: skips undated items, stable tie-breaking, write-only-on-change.
"""

from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlparse
import hashlib
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
    "https://www.studyinternational.com/news/feed/",
    "https://www.timeshighereducation.com/rss/International",
]

# ----------------------------
# Phrase-based relevance (STRICT)
# ----------------------------
PHRASE_PATTERNS = [
    r"\bvisa (change|changes|update|updates|rule|rules|policy|policies|requirement|requirements)\b",
    r"\b(change|changes|update|updates) to (?:the )?visa (?:rules|policy|policies|requirements)\b",
    r"\bvisa (?:rule|policy|requirement)s? (?:change|changes|update|updates)\b",
    r"\bimmigration (?:policy|policies|rule|rules) (?:change|changes|update|updates)\b",
    r"\b(change|changes|update|updates) to (?:the )?immigration (?:rules|policy|policies)\b",
    # route-specific
    r"\bstudent (?:route|visa).*(?:change|changes|update|updates)\b",
    r"\bgraduate route (?:change|changes|update|updates)\b",
    r"\bpost[- ]study work (?:change|changes|update|updates)\b",
    r"\bPSW\b.*\b(update|change|changes|updated)\b",
    r"\bOPT\b.*\b(update|change|changes|updated)\b",
    r"\bdependant|dependent.*\b(work|visa|right)s?.*\b(update|change|changes|updated)\b",
    r"\b(work hours|work rights).*(update|change|changes|updated)\b",
    r"\bIHS|NHS surcharge\b.*\b(update|change|changes|increase|decrease)\b",
    # permit/agency keywords
    r"\b(study|work|residence) permit(s)?\b.*\b(change|changes|update|updates|updated)\b",
    r"\b(UKVI|Home Office|IRCC|USCIS)\b.*\b(update|change|changes|updated)\b",
]

PHRASE_RES = [re.compile(p, re.IGNORECASE) for p in PHRASE_PATTERNS]

EXCLUDE_TERMS = [
    "diplomat", "ambassador", "ceasefire", "arms deal", "sanction",
    "military", "consulate attack", "asylum seeker", "deportation flight",
    "tourist visa only", "business visa only", "turkey", "turkish",
]

TAG_RE = re.compile(r"<[^>]+>")

def clean_html(text: str) -> str:
    if not text:
        return ""
    return unescape(TAG_RE.sub("", text)).strip()

def parse_date(entry) -> str | None:
    """Return ISO date (YYYY-MM-DD, UTC) or None if unavailable."""
    try_order = [
        ("published_parsed", None),
        ("updated_parsed", None),
        ("published", "%a, %d %b %Y %H:%M:%S %Z"),
        ("updated", "%a, %d %b %Y %H:%M:%S %Z"),
        ("pubDate", "%a, %d %b %Y %H:%M:%S %Z"),
    ]
    # struct_time first
    for attr, _fmt in try_order[:2]:
        st = getattr(entry, attr, None)
        if st:
            return datetime(st.tm_year, st.tm_mon, st.tm_mday, tzinfo=timezone.utc).date().isoformat()
    # string fallbacks
    for attr, fmt in try_order[2:]:
        s = getattr(entry, attr, None)
        if s:
            try:
                dt = datetime.strptime(s, fmt).astimezone(timezone.utc)
                return dt.date().isoformat()
            except Exception:
                pass
    return None  # <— we now skip undated items entirely

def host_to_source(url: str) -> str:
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else (host or "Source")
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

def mentions_required_phrase(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    if any(e in t for e in (x.lower() for x in EXCLUDE_TERMS)):
        return False
    return any(rx.search(t) for rx in PHRASE_RES)

def fetch_feed(url: str):
    fp = feedparser.parse(url)
    if fp.bozo and not fp.entries:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        fp = feedparser.parse(r.text)
    return fp.entries or []

def category_for(text: str) -> str:
    t = (text or "").lower()
    if "policy" in t or "rule" in t:
        return "Policy Update"
    if "visa" in t or "permit" in t:
        return "Visa & Immigration"
    return "Update"

def build_item(entry) -> dict | None:
    title = clean_html(getattr(entry, "title", "") or "")
    url = getattr(entry, "link", "") or ""
    summary = clean_html(getattr(entry, "summary", "") or "")
    content_txt = summary
    try:
        if not content_txt and getattr(entry, "content", None):
            content_txt = clean_html(entry.content[0].value)
    except Exception:
        pass

    date_str = parse_date(entry)
    if not date_str:
        return None  # skip undated to avoid churn

    score_text = f"{title} {content_txt}"
    if not mentions_required_phrase(score_text):
        return None

    return {
        "date": date_str,
        "category": category_for(score_text),
        "headline": title[:300],
        "description": smart_excerpt(content_txt, 480),
        "source": host_to_source(url),
        "url": url,
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

def stable_hash(obj) -> str:
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    collected = []
    for feed in FEEDS:
        try:
            for e in fetch_feed(feed):
                it = build_item(e)
                if it:
                    collected.append(it)
        except Exception as ex:
            print(f"[warn] feed failed: {feed} -> {ex}")

    items = dedupe(collected)
    # Deterministic sort: newest date first, then headline, then url
    items.sort(key=lambda x: (x["date"], x["headline"].lower(), x["url"]), reverse=True)
    items = items[:MAX_ITEMS]

    payload = {"policyNews": items}
    new_hash = stable_hash(payload)

    # Write only if changed
    old_hash = None
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                old_payload = json.load(f)
            old_hash = stable_hash(old_payload)
        except Exception:
            pass

    if new_hash != old_hash:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"wrote {len(items)} items -> {OUTPUT_FILE}")
    else:
        print("no changes; left existing policyNews.json untouched")

if __name__ == "__main__":
    main()
