#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_policy_news.py - VISA/POLICY-PHRASE ONLY (deterministic)
- Strictly keeps articles about visa/immigration/policy changes affecting international student mobility.
- Deterministic: skips undated items, stable sort, write-only-on-change.
- Failsafe: does NOT overwrite JSON if zero items would be written.
- Broad fallback: if strict results are very small, a guarded broader filter adds a few clearly relevant items.
"""

from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime
import hashlib
import json
import pathlib
import re
import os
import unicodedata

import feedparser
import requests

# ----------------------------
# Config
# ----------------------------
SITE_ROOT = pathlib.Path(__file__).resolve().parent
OUTPUT_FILE = SITE_ROOT / "data" / "policyNews.json"
MAX_ITEMS = 300
DEBUG = os.getenv("DEBUG", "0") == "1"
STRICT_MIN = 5  # if strict keeps fewer than this, try a guarded broad pass

# Feeds: governments (visa rules) + sector press
FEEDS = [
    # Government / regulator (high signal)
    "https://www.gov.uk/government/organisations/uk-visas-and-immigration.atom",
    "https://www.gov.uk/government/announcements.rss",
    "https://www.canada.ca/en/immigration-refugees-citizenship/atom.xml",
    "https://www.uscis.gov/news/rss.xml",
    "https://www.homeaffairs.gov.au/news-media/rss",
    # Sector press (strictly filtered)
    "https://monitor.icef.com/feed/",
    "https://www.studyinternational.com/news/feed/",
    "https://www.timeshighereducation.com/rss/International",
    "https://thepienews.com/feed/",
    "https://thepienews.com/news/feed/",
    "https://www.universityworldnews.com/rss/",
]

# ----------------------------
# Phrase-based relevance (STRICT)
# ----------------------------
PHRASE_PATTERNS = [
    # Direct "visa/immigration ... change/update"
    r"\bvisa (?:change|changes|update|updates|rule|rules|policy|policies|requirement|requirements)\b",
    r"\b(?:change|changes|update|updates) to (?:the )?visa (?:rules|policy|policies|requirements)\b",
    r"\bvisa (?:rule|policy|requirement)s? (?:change|changes|update|updates)\b",
    r"\bimmigration (?:policy|policies|rule|rules) (?:change|changes|update|updates)\b",
    r"\b(?:change|changes|update|updates) to (?:the )?immigration (?:rules|policy|policies)\b",
    # Route/program specifics
    r"\bstudent (?:route|visa).*(?:change|changes|update|updates|reform|tighten|restriction|cap|limit)\b",
    r"\bgraduate route\b.*\b(?:change|changes|update|updates|reform|cap|limit|closure|end|abolish|suspend|introduce)\b",
    r"\bgraduate visa\b.*\b(?:change|changes|update|updates|reform|cap|limit|closure|end|abolish|suspend|introduce)\b",
    r"\bpost[- ]study work\b.*\b(?:change|changes|update|updates|reform|tighten|restriction)\b",
    r"\bPSW\b.*\b(?:update|change|changes|updated|reform)\b",
    r"\bOPT\b.*\b(?:update|change|changes|updated|reform)\b",
    r"\bPGWP\b.*\b(?:update|change|changes|updated|reform)\b",
    r"\b(?:F-1|CPT)\b.*\b(?:rule|policy|update|change|changes|updated)\b",
    r"\b(?:subclass 500|GTE|Genuine Student)\b.*\b(?:update|change|policy|rules?)\b",
    # Work rights/hours, dependants, fees
    r"\b(?:work hours|work rights)\b.*\b(?:update|change|changes|updated|increase|decrease|lift|reduce|extend)\b",
    r"\b(?:dependants?|dependents?)\b.*\b(?:ban|restriction|cap|limit|update|change|changes|updated)\b",
    r"\b(?:visa fees?|application fees?|charges?)\b.*\b(?:increase|rise|raised|decrease|cut|change|updated)\b",
    r"\b(?:IHS|NHS surcharge)\b.*\b(?:increase|decrease|change|changes|update|updates)\b",
    # Government phrasing
    r"\bstatement of changes\b.*\bimmigration rules\b",
    r"\b(?:introduce|introduces|introduced|launch|open|opens)\b.*\b(?:visa|student route|graduate route|immigration rules?)\b",
    r"\b(?:end|ends|ended|close|closed|closure|abolish|suspend|revoke)\b.*\b(?:visa|student route|graduate route)\b",
    # International student policy caps/limits
    r"\binternational students?\b.*\b(?:cap|caps|limit|limits|restriction|restrictions|ban|curb|reduce|tighten)\b",
]
PHRASE_RES = [re.compile(p, re.IGNORECASE) for p in PHRASE_PATTERNS]

# Broad fallback (topic + action must both be present)
TOPIC_RE = re.compile(
    r"\b(visa|immigration|student route|graduate route|post[- ]study|psw|opt|pgwp|ihs|surcharge|work (?:rights?|hours?)|dependents?|dependants?|fees?|international students?)\b",
    re.IGNORECASE,
)
ACTION_RE = re.compile(
    r"\b(update|change|changes|updated|introduce|announc\w*|increase|decrease|rise|cut|tighten|restrict\w*|cap|limit|ban|suspend|revoke|end|close|closure|abolish)\b",
    re.IGNORECASE,
)

# Hard excludes incl. Pakistan/Turkey (ASCII-folded for robustness)
EXCLUDE_TERMS = [
    "diplomat", "ambassador", "ceasefire", "arms deal", "sanction",
    "military", "consulate attack", "asylum seeker", "deportation flight",
    "tourist visa only", "business visa only",
    "pakistan", "pakistani", "pakistand",
    "turkey", "turkish", "turky", "turkiye",
]

TAG_RE = re.compile(r"<[^>]+>")

# ----------------------------
# Helpers
# ----------------------------
def ascii_fold(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")

def clean_html(text: str) -> str:
    if not text:
        return ""
    return unescape(TAG_RE.sub("", text)).strip()

def parse_date(entry) -> str | None:
    # struct_time first
    for attr in ("published_parsed", "updated_parsed"):
        st = getattr(entry, attr, None)
        if st:
            return datetime(st.tm_year, st.tm_mon, st.tm_mday, tzinfo=timezone.utc).date().isoformat()
    # RFC 2822 string fallbacks
    for attr in ("published", "updated", "pubDate"):
        s = getattr(entry, attr, None)
        if s:
            try:
                dt = parsedate_to_datetime(s).astimezone(timezone.utc)
                return dt.date().isoformat()
            except Exception:
                pass
    return None  # skip undated to avoid churn

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
        return cut[: last_sentence + 1] + " ..."
    last_space = cut.rfind(" ")
    return (cut[:last_space] if last_space > 0 else cut) + " ..."

def excluded(text: str) -> bool:
    t = text.lower()
    tf = ascii_fold(t)
    return any(term in t or term in tf for term in EXCLUDE_TERMS)

def matches_strict(text: str) -> bool:
    return any(rx.search(text) for rx in PHRASE_RES)

def matches_broad(text: str) -> bool:
    return bool(TOPIC_RE.search(text) and ACTION_RE.search(text))

def fetch_feed(url: str):
    fp = feedparser.parse(url)
    if fp.bozo and not fp.entries:
        try:
            r = requests.get(url, headers={"User-Agent": "policy-bot/1.0"}, timeout=20)
            r.raise_for_status()
            fp = feedparser.parse(r.text)
        except Exception:
            return []
    return fp.entries or []

def category_for(text: str) -> str:
    t = (text or "").lower()
    if "policy" in t or "rule" in t:
        return "Policy Update"
    if "visa" in t or "permit" in t:
        return "Visa & Immigration"
    if "international student" in t:
        return "International Students Policy"
    return "Update"

def build_item(entry, mode: str = "strict") -> dict | None:
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
        return None  # skip undated

    score_text = f"{title} {content_txt}"
    if excluded(score_text):
        return None

    ok = matches_strict(score_text) if mode == "strict" else matches_broad(score_text)
    if not ok:
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

# ----------------------------
# Main
# ----------------------------
def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Pass 1: strict
    strict_collected = []
    total_kept = 0
    for feed in FEEDS:
        kept_this = 0
        try:
            for e in fetch_feed(feed):
                it = build_item(e, mode="strict")
                if it:
                    strict_collected.append(it)
                    kept_this += 1
        except Exception as ex:
            print(f"[warn] feed failed: {feed} -> {ex}")
        if DEBUG:
            print(f"[debug] strict {feed} -> kept {kept_this}")
        total_kept += kept_this
    if DEBUG:
        print(f"[debug] strict total kept: {total_kept}")

    collected = strict_collected

    # Pass 2: guarded broad fallback (only if strict too small)
    if len(collected) < STRICT_MIN:
        if DEBUG:
            print(f"[debug] strict kept {len(collected)} < {STRICT_MIN}; trying broad fallback")
        broad_collected = []
        for feed in FEEDS:
            kept_this = 0
            try:
                for e in fetch_feed(feed):
                    it = build_item(e, mode="broad")
                    if it:
                        broad_collected.append(it)
                        kept_this += 1
            except Exception as ex:
                print(f"[warn] feed failed (broad): {feed} -> {ex}")
            if DEBUG:
                print(f"[debug] broad {feed} -> kept {kept_this}")
        # Merge & dedupe
        collected.extend(broad_collected)

    items = dedupe(collected)
    items.sort(key=lambda x: (x["date"], x["headline"].lower(), x["url"]), reverse=True)
    items = items[:MAX_ITEMS]

    # ---- FAILSAFE: don't overwrite with empty ----
    if not items:
        if OUTPUT_FILE.exists():
            print("no matches; kept existing policyNews.json (not overwritten)")
            return
        else:
            # Nothing existing - still write an empty scaffold once
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump({"policyNews": []}, f, ensure_ascii=False, indent=2)
            print("no matches; wrote empty scaffold (first run)")
            return

    payload = {"policyNews": items}
    new_hash = stable_hash(payload)

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

