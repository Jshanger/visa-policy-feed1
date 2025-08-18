#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
update_policy_news.py  (STRICT)
Focuses the feed on Immigration & Visa policy updates, while still including
student mobility items only when there is a clear visa/immigration/policy angle.
Writes data/policyNews.json for the static site.

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
MAX_ITEMS = 300  # keep output lean for the browser

FEEDS = [
    # Government / regulator sources (high signal)
    "https://www.gov.uk/government/organisations/uk-visas-and-immigration.atom",
    "https://www.gov.uk/government/announcements.rss",
    "https://www.canada.ca/en/immigration-refugees-citizenship/atom.xml",
    "https://www.uscis.gov/news/rss.xml",
    "https://www.homeaffairs.gov.au/news-media/rss",
    # Sector press (scored/filtered)
    "https://monitor.icef.com/feed/",
    "https://thepienews.com/feed/",
    "https://www.studyinternational.com/news/feed/",
    "https://www.timeshighereducation.com/rss/International",
]

# ----------------------------
# Relevance filters (weighted) — STRICT
# ----------------------------

# Hard excludes (non-policy geopolitics etc.)
EXCLUDE_TERMS = [
    "diplomat", "ambassador", "ceasefire", "arms deal", "sanction",
    "military", "consulate attack", "asylum seeker", "deportation flight",
    "tourist visa only", "business visa only"
]

# Admissions-volume words we want to block unless a visa/policy angle is present
ADMISSIONS_VOLUME_TERMS = [
    "accepted", "acceptances", "acceptance rate",
    "application", "applications", "applicants",
    "enrolment", "enrollment", "offer rate", "offers", "intake", "cohort"
]

# A small list of **core** immigration tokens that MUST appear for inclusion
CORE_IMM_TOKENS = [
    "visa", "study permit", "permit", "ukvi", "home office", "ircc", "uscis",
    "department of home affairs", "home affairs",
    # student-immigration pathways that imply immigration context
    "student visa", "study visa", "graduate route", "post-study work", "psw", "opt", "stem opt",
    "dependent", "dependant", "work rights", "work hours", "health surcharge", "ihs"
]

# Strong immigration/visa signals and authorities (weighted)
IMMIGRATION_TERMS = {
    "visa": 3, "immigration": 3, "permit": 2, "e-visa": 3, "evisa": 3,
    "border control": 2, "biometric": 2, "entry ban": 2, "travel ban": 2,
    "residency": 2, "residence permit": 2, "citizenship": 1,
    "ukvi": 3, "home office": 3, "ircc": 3, "uscis": 3,
    "department of home affairs": 3, "home affairs": 2, "immigration new zealand": 2,
    # student-immigration signals (count as immigration)
    "student visa": 3, "study visa": 3, "study permit": 3,
    "graduate route": 3, "post-study work": 3, "psw": 3, "opt": 3, "stem opt": 3,
    "dependent": 2, "dependant": 2, "work rights": 2, "work hours": 2, "health surcharge": 2, "ihs": 2,
}

# Policy/operational change language (weighted)
POLICY_ACTION_TERMS = {
    "policy update": 2, "policy change": 2, "regulation": 2, "rule change": 2,
    "guidance": 1, "threshold": 2, "thresholds": 2, "minimum salary": 2,
    "cap": 2, "quota": 2, "processing time": 2, "backlog": 2, "priority service": 1,
    "application fee": 2, "fees": 2, "increase": 1, "decrease": 1,
    "dependant": 2, "dependent": 2, "work hours": 2, "work rights": 2,
    "extension": 1, "ban": 1, "suspension": 1, "introduction": 1
}

# Student mobility (for badges/context, NOT sufficient alone)
STUDENT_MOBILITY_TERMS = {
    "international student": 2, "study abroad": 2, "exchange": 1, "erasmus": 1,
    "cas letter": 2, "atas": 1, "ielts": 1, "toefl": 1, "pte": 1, "ukvi ielts": 1,
    "student mobility": 2, "tne": 1, "transnational education": 1,
    "branch campus": 1, "pathway provider": 1
}

def _score(text: str, weights: dict) -> int:
    t = text.lower()
    return sum(w for k, w in weights.items() if k in t)

def is_relevant(text: str) -> bool:
    """
    STRICT mode:
    - Always require at least one **core immigration token**.
    - Drop admissions-volume stories unless there's a policy/immigration signal.
    - Prefer items with policy-action language.
    """
    t = (text or "").lower()

    # quick drops
    if any(x in t for x in (e.lower() for e in EXCLUDE_TERMS)):
        return False

    # must have core immigration token
    if not any(core in t for core in (c.lower() for c in CORE_IMM_TOKENS)):
        return False

    # block admissions-only pieces unless immigration/policy is clearly present
    if any(word in t for word in (w.lower() for w in ADMISSIONS_VOLUME_TERMS)):
        imm_tmp = _score(t, IMMIGRATION_TERMS)
        act_tmp = _score(t, POLICY_ACTION_TERMS)
        if imm_tmp == 0 and act_tmp < 2:
            return False

    # final scoring gate (loose because we already required a core token)
    imm = _score(t, IMMIGRATION_TERMS)
    act = _score(t, POLICY_ACTION_TERMS)
    return (imm + act) >= 3

# ----------------------------
# Utilities
# ----------------------------

def norm_date(d) -> str:
    """Convert feed date to ISO (YYYY-MM-DD). If missing, use now UTC."""
    if hasattr(d, "tm_year"):
        dt = datetime(d.tm_year, d.tm_mon, d.tm_mday, tzinfo=timezone.utc)
    else:
        try:
            dt = datetime.fromisoformat(str(d))
        except Exception:
            dt = datetime.now(timezone.utc)
    return dt.date().isoformat()

def host_to_source(url: str) -> str:
    try:
        host = urlparse(url).netloc
        if host.startswith("www."):
            host = host[4:]
        return host or "Source"
    except Exception:
        return "Source"

TAG_RE = re.compile(r"<[^>]+>")

def clean_html(text: str) -> str:
    if not text:
        return ""
    return unescape(TAG_RE.sub("", text)).strip()

def smart_excerpt(text: str, limit: int = 480) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    trimmed = text[:limit]
    last_sentence = max(trimmed.rfind(". "), trimmed.rfind("! "), trimmed.rfind("? "))
    if last_sentence > 50:
        return trimmed[: last_sentence + 1] + " …"
    last_space = trimmed.rfind(" ")
    return (trimmed[:last_space] if last_space > 0 else trimmed) + " …"

# ----------------------------
# Fetching & building
# ----------------------------

def fetch_feed(url: str):
    """Fetch a feed and return entries (feedparser entries)."""
    fp = feedparser.parse(url)
    if fp.bozo and not fp.entries:
        # try via requests then parse
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        fp = feedparser.parse(r.text)
    return fp.entries or []

def category_for(text: str) -> str:
    """Assign a simple category badge."""
    t = (text or "").lower()
    if _score(t, POLICY_ACTION_TERMS) >= 3 or "policy" in t or "rule" in t or "regulation" in t:
        return "Policy Update"
    if _score(t, IMMIGRATION_TERMS) >= 3:
        return "Visa & Immigration"
    if _score(t, STUDENT_MOBILITY_TERMS) >= 3:
        return "Student Mobility"
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

    score_src = f"{title} {content_txt}"

    if getattr(entry, "published_parsed", None):
        dt = norm_date(entry.published_parsed)
    elif getattr(entry, "updated_parsed", None):
        dt = norm_date(entry.updated_parsed)
    else:
        dt = datetime.now(timezone.utc).date().isoformat()

    return {
        "date": dt,
        "category": category_for(score_src),
        "headline": title[:300],
        "description": smart_excerpt(content_txt, 480),
        "source": host_to_source(url),
        "url": url,
        "_scoretext": score_src,  # stripped before write
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
                if is_relevant(it["_scoretext"]):
                    collected.append(it)
        except Exception as ex:
            print(f"[warn] feed failed: {feed} -> {ex}")

    # strip scoring text
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



