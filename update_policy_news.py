#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Policy / international-student-visa tracker
- Sources: ONLY your approved domains (+ ICEF Monitor)
- Strict relevance: visa/immigration required + (action/policy OR intl-students/HE context)
- Time window: last 6 months (183 days) from "now"
- Robust date parsing & logging
- Output: data/policyNews.json  -> {"policyNews":[ ... ]}
"""

from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional
import json, pathlib, hashlib, sys, re
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests

# ---------------- Settings ----------------
SITE_ROOT   = pathlib.Path(__file__).resolve().parent
OUTPUT_FILE = SITE_ROOT / "data" / "policyNews.json"

NOW_UTC     = datetime.now(timezone.utc)
WINDOW_DAYS = 183  # ~6 months
WINDOW_FROM = (NOW_UTC - timedelta(days=WINDOW_DAYS)).date()

HTTP_TIMEOUT = 25
UA = "policy-student-mobility/3.2 (+github actions bot)"

# ---------------- Domains (whitelist) ----------------
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

# Optional per-domain path gates to cut noise from general feeds
PATH_ALLOW: Dict[str, List[re.Pattern]] = {
    "economictimes.indiatimes.com": [re.compile(r"/nri/study/", re.I)],
    "timeshighereducation.com":     [re.compile(r"/student/", re.I), re.compile(r"/news/", re.I)],
    "ndtv.com":                     [re.compile(r"/education/", re.I), re.compile(r"/world-news/", re.I)],
    "internationalstudent.com":     [re.compile(r"/study", re.I), re.compile(r"/student-visa", re.I)],
}

def _host(url: str) -> str:
    try: return urlparse(url).netloc.lower()
    except Exception: return ""

def _path(url: str) -> str:
    try: return urlparse(url).path or "/"
    except Exception: return "/"

def _allowed(url: str) -> bool:
    h = _host(url)
    ok = any(h == d or h.endswith("." + d) for d in ALLOWED_HOSTS)
    if not ok: return False
    # if we have path-gates for this host, one must match
    gates = PATH_ALLOW.get(h, [])
    if not gates: return True
    p = _path(url)
    return any(rx.search(p) for rx in gates)

# ---------------- Feeds ----------------
FEEDS: List[str] = [
    # ICEF + PIE (core sector policy)
    "https://monitor.icef.com/feed/",
    "https://thepienews.com/feed/",
    "https://thepienews.com/category/news/government/feed/",

    # Research/briefings
    "https://migrationobservatory.ox.ac.uk/feed/",
    "https://commonslibrary.parliament.uk/feed/",

    # Student/visa advisory outlets
    "https://www.idp.com/blog/feed/",
    "https://www.applyboard.com/feed",
    "https://www.visasupdate.com/feed/",
    "https://www.internationalstudent.com/rss.xml",

    # General but filtered by domain/path rules & relevance
    "https://www.timeshighereducation.com/rss",
    "https://www.ndtv.com/education/rss",
    # ET feed is general; we still filter by path + relevance
    "https://economictimes.indiatimes.com/rssfeedsdefault.cms",
]

# Static official pages to check for timestamped updates
STATIC_PAGES = [
    (
        "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500",
        "Australia: Student visa (subclass 500) page update",
        "Student Visas",
    ),
    (
        "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/temporary-graduate-485/post-higher-education-work",
        "Australia: Temporary Graduate (485) Post-Higher Education Work page update",
        "Post-Study Work",
    ),
    (
        "https://www.education.gov.au/international-education-data-and-research/other-international-education-data-and-research",
        "Australia: International education data & research — page update",
        "Education Policy",
    ),
]

# ---------------- Relevance ----------------
# Require *visa/immigration* term (title or summary)
CORE_RX = re.compile(
    r"\b(visa|visas|student visa|study permit|immigration|graduate route|post[- ]?study|psw|opt|pgwp|"
    r"subclass(?:\s|-)?500|subclass(?:\s|-)?485|temporary graduate|f-1|j-1|ukvi|ircc|uscis)\b",
    re.I,
)

# And one of: action/policy verbs OR explicit intl-student/HE context
ACTIONS_RX = re.compile(
    r"\b(update|updated|change|changes|amend|amended|introduce|introduced|launch|launched|create|created|"
    r"cap|caps|limit|limits|ban|bans|restrict|restriction|suspend|revok\w*|end|close\w*|"
    r"increase|decrease|raise|fee|fees|threshold|work hours|work rights|policy|policies|guidance|"
    r"statement|white paper|consultation|legislation|bill|act)\b",
    re.I,
)

INTL_STUDENTS_RX = re.compile(
    r"\b(international student|international students|student mobility|higher education|university|universities|college|campus)\b",
    re.I,
)

# Remove obvious non-policy noise (even if words overlap)
EXCLUDES_RX = re.compile(
    r"\b(restaurant|dining|celebrity|entertainment|ipo|stock market|football|cricket|movie|tv show|"
    r"tourist (?:only)?|property prices)\b",
    re.I,
)

def is_relevant(title: str, summary: str) -> bool:
    blob = f"{title} {summary}"
    if EXCLUDES_RX.search(blob): return False
    if not CORE_RX.search(blob): return False
    if ACTIONS_RX.search(blob) or INTL_STUDENTS_RX.search(blob):
        return True
    return False

# ---------------- Utilities ----------------
def clean_text(s: str) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", s).strip()

def entry_datetime(e) -> Optional[datetime]:
    # Try struct_time fields first
    for key in ("published_parsed", "updated_parsed", "created_parsed", "issued_parsed"):
        st = getattr(e, key, None)
        if st:
            try:
                return datetime(st.tm_year, st.tm_mon, st.tm_mday, tzinfo=timezone.utc)
            except Exception:
                pass
    # Then common string fields
    for key in ("published", "updated", "created", "issued", "dc_date", "date", "pubDate"):
        s = getattr(e, key, None)
        if s:
            try:
                return parsedate_to_datetime(s).astimezone(timezone.utc)
            except Exception:
                # try ISO-ish
                try:
                    return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc)
                except Exception:
                    pass
    return None

def within_window(dt: Optional[datetime]) -> bool:
    return bool(dt and dt.date() >= WINDOW_FROM)

def smart_excerpt(text: str, limit: int = 260) -> str:
    t = clean_text(text)
    if len(t) <= limit: return t
    cut = t[:limit]
    last = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if last > 40: return cut[: last + 1] + " …"
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 0 else cut) + " …"

def category_for(title: str, summary: str) -> str:
    b = f"{title} {summary}".lower()
    if re.search(r"\b(graduate route|post[- ]?study|psw|opt|pgwp|temporary graduate|485)\b", b):
        return "Post-Study Work"
    if re.search(r"\b(student visa|study permit|subclass(?:\s|-)?500|f-1|j-1)\b", b):
        return "Student Visas"
    if "visa-free" in b or "visa exemption" in b:
        return "Visa Exemption"
    if "policy" in b or "white paper" in b or "guidance" in b or "act" in b or "bill" in b:
        return "Policy Update"
    return "Update"

def sig(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

# ---------------- Feed pipeline ----------------
def fetch_feed(url: str):
    print(f"→ feed: {url}")
    try:
        fp = feedparser.parse(url, request_headers={"User-Agent": UA})
        if getattr(fp, "bozo", False) and not getattr(fp, "entries", None):
            # Fallback: requests text
            r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            fp = feedparser.parse(r.text)
        return getattr(fp, "entries", []) or []
    except Exception as ex:
        print(f"  [warn] feed failed: {ex}")
        return []

def items_from_feed(url: str) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    entries = fetch_feed(url)
    seen = 0
    for e in entries:
        seen += 1
        title = clean_text(getattr(e, "title", "") or "")
        link  = (getattr(e, "link", "") or "").strip()
        if not title or not link: continue
        if not _allowed(link):     continue

        dt = entry_datetime(e)
        if not within_window(dt):  continue

        summary = clean_text(getattr(e, "summary", "") or getattr(e, "description", "") or "")
        if not is_relevant(title, summary): continue

        kept.append({
            "date": dt.date().isoformat(),
            "category": category_for(title, summary),
            "headline": title[:200],
            "description": smart_excerpt(summary, 260),
            "source": _host(link),
            "url": link,
        })
    print(f"  kept {len(kept)} / {seen}")
    return kept

# ---------------- Static pages (official AU) ----------------
TIME_TAG_RE = re.compile(r"<time[^>]*datetime=[\"']([^\"']+)[\"'][^>]*>", re.I)

def http_get(url: str) -> Tuple[str, Optional[requests.Response]]:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        if 200 <= r.status_code < 300:
            return r.text, r
    except Exception as ex:
        print(f"  [warn] GET failed: {url} -> {ex}")
    return "", None

def parse_http_date(h: str) -> Optional[datetime]:
    # RFC 2822 / 7231 formats
    try: return parsedate_to_datetime(h).astimezone(timezone.utc)
    except Exception: return None

def items_from_static_pages() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for url, headline, category in STATIC_PAGES:
        print(f"→ page: {url}")
        html, resp = http_get(url)
        if not html and not resp: continue

        dt: Optional[datetime] = None
        m = TIME_TAG_RE.search(html or "")
        if m:
            try:
                dt = datetime.fromisoformat(m.group(1).replace("Z","+00:00")).astimezone(timezone.utc)
            except Exception:
                dt = None
        if not dt and resp is not None:
            lm = resp.headers.get("Last-Modified") or resp.headers.get("last-modified")
            if lm:
                dt = parse_http_date(lm)

        if not within_window(dt):  # skip if no recent page timestamp
            print("  (no recent timestamp; skipped)")
            continue

        items.append({
            "date": dt.date().isoformat(),
            "category": category,
            "headline": headline,
            "description": f"Official page updated on {dt.date().isoformat()}.",
            "source": _host(url),
            "url": url,
        })
    print(f"  kept {len(items)} static updates")
    return items

# ---------------- Build & write ----------------
def collect_items() -> List[Dict[str, Any]]:
    all_items: List[Dict[str, Any]] = []
    for f in FEEDS:
        all_items.extend(items_from_feed(f))
    all_items.extend(items_from_static_pages())

    # sort + dedupe
    def key(it): return (it["date"], it["headline"].strip().lower(), it["url"])
    all_items.sort(key=lambda it: key(it), reverse=True)

    seen = set()
    out: List[Dict[str, Any]] = []
    for it in all_items:
        k = (it["headline"].strip().lower(), it["url"])
        if k in seen:
            continue
        seen.add(k)
        out.append(it)

    # sanity filter: ensure all are within window and domain-allowed (again)
    out = [it for it in out if it["date"] >= WINDOW_FROM.isoformat() and _allowed(it["url"])]
    print(f"✔ total after dedupe/filter: {len(out)} (window since {WINDOW_FROM.isoformat()})")
    return out

def write_json(items: List[Dict[str, Any]]):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"policyNews": items}
    new = sig(payload)
    old = None
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                old = sig(json.load(f))
        except Exception:
            pass
    if new != old:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"✅ wrote {len(items)} items → {OUTPUT_FILE}")
    else:
        print("ℹ️ no changes; left existing file untouched")

def main():
    print(f"🔄 Building feed (last 6 months from {WINDOW_FROM.isoformat()})")
    items = collect_items()
    write_json(items)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[fatal] {e}")
        sys.exit(1)









