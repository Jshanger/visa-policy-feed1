#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pulls ONLY from the specified domains (+ ICEF Monitor) and writes all
relevant items from the LAST 6 MONTHS (newest → oldest) to:
  data/policyNews.json   → {"policyNews":[ ... ]}

Relevance: student visas / immigration / international students / post-study work.
Domains (whitelist):
  - espiconsultants.com
  - idp.com
  - immi.homeaffairs.gov.au   (Student 500 + 485 pages)
  - visasupdate.com
  - migrationobservatory.ox.ac.uk
  - education.gov.au (international-education-data-and-research landing)
  - ndtv.com (education / world student-visa items)
  - applyboard.com (ApplyInsights)
  - economictimes.indiatimes.com (NRI/study)
  - commonslibrary.parliament.uk
  - timeshighereducation.com (student/advice & visa items)
  - internationalstudent.com
  - thepienews.com
  - monitor.icef.com   (ICEF Monitor)

Notes:
- For the two Home Affairs pages (Student 500 + Temporary Graduate 485), we scrape
  the page and attempt to parse an <time> tag or Last-Modified header; if present and
  within the window, we add/update a single “page updated” item.
"""

from __future__ import annotations
from typing import List, Dict, Any, Tuple
import json, pathlib, hashlib, sys, time, re
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone

import feedparser
import requests

# ---------- Settings ----------
SITE_ROOT   = pathlib.Path(__file__).resolve().parent
OUTPUT_FILE = SITE_ROOT / "data" / "policyNews.json"

TODAY_UTC   = datetime.now(timezone.utc)
WINDOW_DAYS = 183  # ~ 6 months
WINDOW_FROM = (TODAY_UTC - timedelta(days=WINDOW_DAYS)).date()  # inclusive (YYYY-MM-DD)

HTTP_TIMEOUT = 25
UA = "policy-student-mobility/3.0 (+github actions bot)"

# ---------- Whitelisted domains ----------
ALLOWED_HOSTS = {
    "espiconsultants.com",
    "idp.com",
    "immi.homeaffairs.gov.au",
    "visasupdate.com",
    "migrationobservatory.ox.ac.uk",
    "education.gov.au",
    "ndtv.com",
    "applyboard.com",
    "economictimes.indiatimes.com",
    "commonslibrary.parliament.uk",
    "timeshighereducation.com",
    "internationalstudent.com",
    "thepienews.com",
    "monitor.icef.com",
}

# ---------- RSS/Atom sources (domain-scoped) ----------
FEEDS: List[str] = [
    # Your list + ICEF Monitor (only these domains)
    "https://thepienews.com/feed/",
    "https://thepienews.com/category/news/government/feed/",
    "https://monitor.icef.com/feed/",
    "https://migrationobservatory.ox.ac.uk/feed/",
    "https://commonslibrary.parliament.uk/feed/",           # includes research briefings
    "https://www.timeshighereducation.com/rss",            # global feed; we filter by domain+relevance
    "https://www.applyboard.com/feed",                     # ApplyBoard (covers ApplyInsights)
    "https://www.idp.com/blog/feed/",                      # IDP blog
    "https://www.visasupdate.com/feed/",
    "https://www.internationalstudent.com/rss.xml",        # site RSS
    "https://www.ndtv.com/education/rss",                  # NDTV education
    "https://economictimes.indiatimes.com/markets/stocks/etmarketsfeed.cms",  # general; we hard-filter
]

# ---------- Static pages to check (Home Affairs) ----------
STATIC_PAGES = [
    # (url, title, category)
    (
        "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500",
        "Australia: Student visa (subclass 500) page update",
        "Student Visas"
    ),
    (
        "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/temporary-graduate-485/post-higher-education-work",
        "Australia: Temporary Graduate (485) Post-Higher Education Work page update",
        "Post-Study Work"
    ),
    # (optional) Landing page for Department of Education AU (we attempt a last-mod)
    (
        "https://www.education.gov.au/international-education-data-and-research/other-international-education-data-and-research",
        "Australia: International education data & research page update",
        "Education Policy"
    ),
]

# ---------- Relevance lexicon ----------
CORE = (
    "visa", "visas", "immigration", "student visa", "graduate route",
    "post-study", "post study", "psw", "opt", "pgwp", "work permit",
    "student mobility", "international student", "international students",
    "study permit", "dependent", "dependant", "sponsor", "ukvi", "ircc", "uscis",
    "subclass 500", "subclass 485", "temporary graduate", "visa rules", "visa policy",
)

ACTIONS = (
    "update", "updated", "change", "changes", "amend", "introduced", "introduces",
    "launch", "created", "caps", "limit", "ban", "restrict", "suspend", "revoke",
    "increase", "decrease", "raise", "fee", "fees", "threshold", "work hours",
    "work rights", "policy", "policies", "guidance", "statement", "white paper",
)

# Regions of interest (to help keep Asia-angle items when present)
ASIA_HINTS = ("malaysia", "singapore", "hong kong", "hk", "china", "japan", "korea", "south korea", "korean", "thailand")

# Hard excludes (avoid general business/entertainment/etc.)
EXCLUDES = (
    "restaurant", "dining", "celebrity", "entertainment", "ipo", "stock market",
    "football", "cricket", "movie", "tv show", "property prices", "tourist only",
)

# ---------- Helpers ----------
def _clean_text(s: str) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", s).strip()

def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

def _allowed(url: str) -> bool:
    h = _host(url)
    return any(h == d or h.endswith("." + d) for d in ALLOWED_HOSTS)

def _date_from_struct(st) -> datetime | None:
    if not st: return None
    try:
        return datetime(st.tm_year, st.tm_mon, st.tm_mday, tzinfo=timezone.utc)
    except Exception:
        return None

def _within_window(dt: datetime | None) -> bool:
    if not dt: return False
    return dt.date() >= WINDOW_FROM

def _smart_excerpt(text: str, limit: int = 300) -> str:
    t = _clean_text(text)
    if len(t) <= limit: return t
    cut = t[:limit]
    last = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if last > 40: return cut[: last + 1] + " …"
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 0 else cut) + " …"

def _category_for(title: str, summary: str) -> str:
    b = (title + " " + summary).lower()
    if any(k in b for k in ("graduate route", "post-study", "psw", "opt", "pgwp", "temporary graduate", "485")):
        return "Post-Study Work"
    if any(k in b for k in ("student visa", "subclass 500", "study permit", "f-1", "j-1")):
        return "Student Visas"
    if "visa-free" in b or "visa exemption" in b:
        return "Visa Exemption"
    if "policy" in b or "white paper" in b or "guidance" in b:
        return "Policy Update"
    return "Update"

def _is_relevant(title: str, summary: str) -> bool:
    blob = (title + " " + summary).lower()
    if any(x in blob for x in EXCLUDES):
        return False
    # require at least one CORE term
    if not any(k in blob for k in CORE):
        return False
    # encourage action/policy language OR explicit international-student language
    if any(a in blob for a in ACTIONS) or ("international student" in blob or "international students" in blob):
        return True
    # allow if strong Asia target words present too (for your regional focus)
    if any(k in blob for k in ASIA_HINTS):
        return True
    return False

def _sig(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

# ---------- Feed fetching ----------
def _fetch_feed(url: str):
    print(f"→ feed: {url}")
    try:
        fp = feedparser.parse(url, request_headers={"User-Agent": UA})
        # sometimes feedparser fails silently; requests fallback
        if getattr(fp, "bozo", False) and not getattr(fp, "entries", None):
            r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            fp = feedparser.parse(r.text)
        return getattr(fp, "entries", []) or []
    except Exception as ex:
        print(f"  [warn] feed failed: {ex}")
        return []

def _items_from_feed(url: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in _fetch_feed(url):
        title   = _clean_text(getattr(e, "title", "") or "")
        link    = (getattr(e, "link", "") or "").strip()
        if not title or not link: 
            continue
        if not _allowed(link):
            continue
        # pick date
        st = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
        dt = _date_from_struct(st)
        if not _within_window(dt):
            continue
        summary = _clean_text(getattr(e, "summary", "") or getattr(e, "description", "") or "")
        if not _is_relevant(title, summary):
            continue
        date_str = dt.date().isoformat()
        out.append({
            "date": date_str,
            "category": _category_for(title, summary),
            "headline": title[:200],
            "description": _smart_excerpt(summary, 260),
            "source": _host(link),
            "url": link
        })
    print(f"  kept {len(out)} from {url}")
    return out

# ---------- Static page checks (Home Affairs + AU Education landing) ----------
TIME_TAG_RE = re.compile(r"<time[^>]*datetime=[\"']([^\"']+)[\"'][^>]*>", re.I)

def _http_get(url: str) -> Tuple[str, requests.Response | None]:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        if 200 <= r.status_code < 300:
            return r.text, r
    except Exception as ex:
        print(f"  [warn] GET failed: {url} -> {ex}")
    return "", None

def _parse_http_date(h: str) -> datetime | None:
    # Try a few common formats
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(h, fmt).astimezone(timezone.utc)
        except Exception:
            pass
    return None

def _items_from_static_pages() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for url, headline, category in STATIC_PAGES:
        print(f"→ page: {url}")
        html, resp = _http_get(url)
        if not html and not resp:
            continue

        dt = None

        # 1) Try <time datetime="...">
        m = TIME_TAG_RE.search(html or "")
        if m:
            try:
                dt = datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).astimezone(timezone.utc)
            except Exception:
                dt = None

        # 2) Try Last-Modified header
        if not dt and resp is not None:
            lm = resp.headers.get("Last-Modified") or resp.headers.get("last-modified")
            if lm:
                dt = _parse_http_date(lm)

        # 3) Fallback: if no date, skip (avoid polluting the 6-month filter)
        if not dt or not _within_window(dt):
            print("  (no recent update date found; skipping)")
            continue

        # Build a short description from page title line
        desc = f"Official page update detected on {dt.date().isoformat()}."
        items.append({
            "date": dt.date().isoformat(),
            "category": category,
            "headline": headline,
            "description": desc,
            "source": _host(url),
            "url": url
        })

    print(f"  kept {len(items)} from static pages")
    return items

# ---------- Pipeline ----------
def collect_items() -> List[Dict[str, Any]]:
    all_items: List[Dict[str, Any]] = []

    # From feeds
    for f in FEEDS:
        all_items.extend(_items_from_feed(f))

    # From static pages (Home Affairs + AU Education landing)
    all_items.extend(_items_from_static_pages())

    # Dedupe (by headline lower + url hash), newest first
    def _key(it: Dict[str, Any]):
        return (it["headline"].strip().lower(), it["url"])
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for it in sorted(all_items, key=lambda x: (x["date"], x["headline"].lower(), x["url"]), reverse=True):
        k = _key(it)
        if k in seen:
            continue
        seen.add(k)
        deduped.append(it)

    print(f"✔ collected {len(all_items)}; after dedupe {len(deduped)}")
    return deduped

def write_json(items: List[Dict[str, Any]]):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"policyNews": items}

    new_sig = _sig(payload)
    old_sig = None
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                old_sig = _sig(json.load(f))
        except Exception:
            pass

    if new_sig != old_sig:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"✅ wrote {len(items)} items → {OUTPUT_FILE}")
    else:
        print("ℹ️ no changes; left existing file untouched")

# ---------- Main ----------
def main():
    print(f"🔄 Building last-6-month feed (since {WINDOW_FROM.isoformat()})")
    items = collect_items()
    write_json(items)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[fatal] {e}")
        sys.exit(1)








