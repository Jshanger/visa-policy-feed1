#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Policy / international-student-visa tracker — example-style
(GOV: UK/CA/US/AU + PIE/ICEF/IDP + Taiwan News; gov sources enriched)

STRICT:
- Every item must impact international students / graduate mobility / HE,
  except explicit URL whitelist (e.g., UK sponsor register, specific PIE/DHS/Taiwan News links you asked for).

Coverage:
- TRUE 6-month window with robust date extraction:
  <meta> (article:published_time, og:updated_time, itemprop dates, last-modified),
  <time datetime>, JSON-LD (datePublished / dateModified), HTTP Last-Modified.
- Deep pagination:
  * WordPress (PIE/ICEF/IDP): up to MAX_WP_PAGES
  * GOV.UK Search Atom: keyworded, page 1..N (stop only when page fully outside window)
  * GOV.UK Publications Atom: page 1..N
- Curated URLs:
  * data/extra_urls.txt — one URL per line; fetched + filtered each run.

Output (with "Load more"):
- data/policyNews.json            -> page 1
- data/policyNews.p2.json, ...    -> subsequent pages
- data/policyNews.index.json      -> navigation meta
"""

from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional
import json, pathlib, hashlib, sys, re, math, os
from urllib.parse import urlparse, urlencode, urlsplit, urlunsplit, parse_qsl
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests

# ---------------- Settings ----------------
SITE_ROOT   = pathlib.Path(__file__).resolve().parent
OUTPUT_DIR  = SITE_ROOT / "data"
OUTPUT_FILE = OUTPUT_DIR / "policyNews.json"
EXTRA_URLS_FILE = OUTPUT_DIR / "extra_urls.txt"

NOW_UTC     = datetime.now(timezone.utc)
WINDOW_DAYS = int(os.getenv("WINDOW_DAYS", "183"))   # ~6 months
WINDOW_FROM = (NOW_UTC - timedelta(days=WINDOW_DAYS)).date()

HTTP_TIMEOUT = 25
UA = "policy-student-mobility/4.4 (+github actions bot)"

# Crawl depths (high for fuller coverage)
MAX_WP_PAGES   = int(os.getenv("MAX_WP_PAGES", "40"))
MAX_GOV_PAGES  = int(os.getenv("MAX_GOV_PAGES", "20"))
PAGE_SIZE      = int(os.getenv("PAGE_SIZE", "30"))

# ---------------- Domains (strict whitelist) ----------------
MEDIA_HOSTS = {
    "monitor.icef.com",
    "thepienews.com",
    "www.idp.com",
    "idp.com",
    "www.taiwannews.com.tw",   # Taiwan News
    "taiwannews.com.tw",
}
GOV_HOSTS = {
    "gov.uk",
    "homeoffice.gov.uk",
    "ukvi.homeoffice.gov.uk",
    "canada.ca",
    "cic.gc.ca",
    "uscis.gov",
    "state.gov",
    "travel.state.gov",
    "immi.homeaffairs.gov.au",
    "homeaffairs.gov.au",
    "education.gov.au",
    "trade.gov",   # I-94 page
    "dhs.gov",     # DHS releases
    "cbp.gov",
    # Optional Taiwan gov (future-proof):
    "moe.gov.tw", "immigration.gov.tw", "boca.gov.tw",
}
ALLOWED_HOSTS = MEDIA_HOSTS | GOV_HOSTS

# Explicit include (requested pages; stored normalized at runtime)
URL_WHITELIST_RAW = {
    # UK GOV register of sponsors (Workers)
    "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers",
    # PIE articles
    "https://thepienews.com/us-trump-pauses-new-student-visa-interviews/",
    "https://thepienews.com/july-sees-drastic-fall-in-us-student-visa-arrivals/",
    # DHS news
    "https://www.dhs.gov/news/2025/08/27/trump-administration-proposes-new-rule-end-foreign-student-visa-abuse",
    # Taiwan News (user-provided)
    "https://www.taiwannews.com.tw/news/6190827",
}

def _host(url: str) -> str:
    try: return urlparse(url).netloc.lower()
    except Exception: return ""

def _path(url: str) -> str:
    try: return urlparse(url).path or "/"
    except Exception: return "/"

def normalize_url(u: str) -> str:
    """Strip marketing params (utm_*, _hsenc, fbclid, etc.) and normalize path."""
    try:
        s = urlsplit(u.strip())
        params = []
        for k, v in parse_qsl(s.query, keep_blank_values=True):
            kl = k.lower()
            if kl.startswith("utm_") or kl in {"_hsenc","_hsmi","fbclid","gclid","mc_cid","mc_eid"}:
                continue
            params.append((k, v))
        path = s.path.rstrip("/") if s.path not in ("", "/") else s.path
        return urlunsplit((s.scheme, s.netloc.lower(), path, urlencode(params), ""))
    except Exception:
        return u.strip()

URL_WHITELIST = {normalize_url(u) for u in URL_WHITELIST_RAW}

def _allowed(url: str) -> bool:
    h = _host(url)
    return any(h == d or h.endswith("." + d) for d in ALLOWED_HOSTS)

# Optional path gates (weed out non-policy sections)
# NOTE: no gating for thepienews.com so root-article slugs are allowed
PATH_ALLOW: Dict[str, List[re.Pattern]] = {
    "monitor.icef.com": [re.compile(r"/\d{4}/\d{2}/", re.I)],
    "idp.com":          [re.compile(r"/blog/", re.I), re.compile(r"/[a-z]{2}/blog/", re.I)],
}
def _path_allowed(url: str) -> bool:
    h = _host(url)
    gates = PATH_ALLOW.get(h, [])
    if not gates: return True
    p = _path(url)
    return any(rx.search(p) for rx in gates)

# ---------------- Feeds ----------------
FEEDS: List[str] = [
    # Canada (IRCC)
    "https://www.canada.ca/en/immigration-refugees-citizenship/atom.xml",
    # United States (USCIS)
    "https://www.uscis.gov/news/rss.xml",
    # Australia (Dept of Education newsroom)
    "https://www.education.gov.au/newsroom/all.atom",
    # Sector media (WordPress)
    "https://monitor.icef.com/feed/",
    "https://thepienews.com/feed/",
    "https://thepienews.com/category/news/government/feed/",
    "https://www.idp.com/blog/feed/",
    # (If Taiwan News exposes a feed later, add it here)
]

# GOV.UK — Search Atom with keywords + pagination
GOVUK_SEARCH_BASE = "https://www.gov.uk/search/all.atom"
GOVUK_QUERIES = [
    "student visa", "study visa", "study permit", "immigration", "UKVI",
    "graduate route", "post study", "licensed sponsor", "sponsorship",
]

# GOV.UK — Publications Atom (broad, we filter + whitelist; supports ?page=N)
GOVUK_PUBLICATIONS_ATOM = "https://www.gov.uk/government/publications.atom"

WP_FEEDS = {
    "https://monitor.icef.com/feed/",
    "https://thepienews.com/feed/",
    "https://thepienews.com/category/news/government/feed/",
    "https://www.idp.com/blog/feed/",
}

# Static official pages (timestamped updates incl. your requests)
STATIC_PAGES = [
    # Australia
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
    # UK register (explicit)
    (
        "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers",
        "UK: Register of Licensed Sponsors (Workers) — page update",
        "Sponsorship",
    ),
    # US I-94 arrivals (explicit)
    (
        "https://www.trade.gov/i-94-arrivals-program",
        "US: I-94 Arrivals Program — data update",
        "Arrivals Data",
    ),
    # US DHS news (explicit)
    (
        "https://www.dhs.gov/news/2025/08/27/trump-administration-proposes-new-rule-end-foreign-student-visa-abuse",
        "US DHS: Proposed rule regarding foreign student visas — update",
        "Policy Update",
    ),
    # Taiwan News (explicit curated page you gave)
    (
        "https://www.taiwannews.com.tw/news/6190827",
        "Taiwan News: policy/update relevant to international students",
        "Policy Update",
    ),
]

# ---------------- Relevance (example-style + impact) ----------------
CORE_RX = re.compile(
    r"\b(visa|visas|student visa|study permit|immigration|graduate route|post[- ]?study|psw|opt|pgwp|"
    r"subclass(?:\s|-)?500|subclass(?:\s|-)?485|temporary graduate|f-1|j-1|ukvi|ircc|uscis|sponsor[s]?|sponsorship)\b",
    re.I,
)
ACTIONS_RX = re.compile(
    r"\b(propose[sd]?|introduce[sd]?|cap(?:ped|s)?|limit(?:ed|s|ing)?|ban(?:ned|s)?|restrict(?:ed|ion|s)?|"
    r"grant(?:s|ed)?|issuances?|processing|backlog|fast-?track|updated?|update|change[sd]?|"
    r"fall(?:s|ing)?|rise[sn]?|increase[sd]?|decrease[sd]?|strengthen(?:ing|ed)?|tighten(?:ed|ing)?)\b",
    re.I,
)
COUNTRY_RX = re.compile(
    r"\b(US|U\.S\.|United States|UK|U\.K\.|United Kingdom|Britain|British|Canada|Canadian|Australia|Australian|"
    r"Home Office|IRCC|USCIS|UKVI|Taiwan|Taipei)\b",   # includes Taiwan
    re.I,
)
IMPACT_RX = re.compile(
    r"\b("
    r"international student[s]?|overseas student[s]?|foreign student[s]?|"
    r"graduate(?:s)?(?:\s+(?:mobility|employment|outcomes|returnees?))?|"
    r"post[-\s]?study(?:\s+work)?|PSW|OPT|PGWP|Temporary Graduate|485|Graduate Route|"
    r"student\s+(?:visa|visas|arrivals|grants|applications|permits?)|study\s+permit[s]?|"
    r"higher education|HE sector|university|universities|campus|"
    r"international education|transnational education|agent[s]?|recruitment agent[s]?"
    r")\b",
    re.I,
)
EXCLUDES_RX = re.compile(
    r"\b(celebrity|restaurant|football|cricket|movie|tv show|tourism only|property prices|IPO)\b",
    re.I,
)

def like_examples(title: str, summary: str, link: str) -> bool:
    """
    Keep only items that:
      - are on the whitelist, OR
      - mention visa/immigration core terms (CORE_RX), AND
      - clearly impact international students / HE (IMPACT_RX), AND
      - GOV: action cue optional
      - MEDIA: IMPACT + (ACTION OR country/system cue)
    """
    nlink = normalize_url(link)
    if nlink in URL_WHITELIST:
        return True

    blob = f"{title} {summary}"
    if EXCLUDES_RX.search(blob): return False
    if not CORE_RX.search(blob): return False
    if not IMPACT_RX.search(blob): return False

    host = _host(nlink)
    is_gov = any(host == d or host.endswith("." + d) for d in GOV_HOSTS)
    has_action = bool(ACTIONS_RX.search(blob))
    has_country = bool(COUNTRY_RX.search(blob) or "sponsor" in blob.lower())

    if is_gov:
        return True
    else:
        return has_action or has_country

# ---------------- Utilities ----------------
def clean_text(s: str) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", s).strip()

def entry_datetime(e) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed", "created_parsed", "issued_parsed"):
        st = getattr(e, key, None)
        if st:
            try:
                return datetime(st.tm_year, st.tm_mon, st.tm_mday, tzinfo=timezone.utc)
            except Exception:
                pass
    for key in ("published", "updated", "created", "issued", "dc_date", "date", "pubDate"):
        s = getattr(e, key, None)
        if s:
            try:
                return parsedate_to_datetime(s).astimezone(timezone.utc)
            except Exception:
                try:
                    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
                except Exception:
                    pass
    return None

def within_window(dt: Optional[datetime]) -> bool:
    return bool(dt and dt.date() >= WINDOW_FROM)

def smart_excerpt(text: str, limit: int = 260) -> str:
    t = clean_text(text)
    if len(t) <= limit:
        return t
    cut = t[:limit]
    last = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if last > 40:
        return cut[: last + 1] + " …"
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 0 else cut) + " …"

def category_for(title: str, summary: str) -> str:
    b = f"{title} {summary}".lower()
    if re.search(r"\b(graduate route|post[- ]?study|psw|opt|pgwp|temporary graduate|485)\b", b):
        return "Post-Study Work"
    if re.search(r"\b(student visa|study permit|subclass(?:\s|-)?500|f-1|j-1)\b", b):
        return "Student Visas"
    if re.search(r"\b(licensed sponsor|sponsor|sponsorship)\b", b):
        return "Sponsorship"
    if re.search(r"\b(arrivals|grants|processing|issuances?|backlog)\b", b):
        return "Processing & Grants"
    return "Policy Update"

def sig(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

# ---------------- HTTP & date helpers ----------------
META_DT_RES = [
    re.compile(r'<meta[^>]+property=["\']article:(?:published|modified)_time["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+property=["\']og:updated_time["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+itemprop=["\'](?:datePublished|dateModified)["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']last-modified["\'][^>]+content=["\']([^"\']+)["\']', re.I),
]
LDJSON_DATE_RES = [
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"', re.I),
    re.compile(r'"dateModified"\s*:\s*"([^"]+)"', re.I),
]
TIME_TAG_RE = re.compile(r"<time[^>]*datetime=[\"']([^\"']+)[\"'][^>]*>", re.I)
TITLE_RE    = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
A_HREF_RE   = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>', re.I)

def http_get(url: str) -> Tuple[str, Optional[requests.Response]]:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        if 200 <= r.status_code < 300:
            return r.text, r
    except Exception as ex:
        print(f"  [warn] GET failed: {url} -> {ex}")
    return "", None

def parse_any_dt(s: str) -> Optional[datetime]:
    try:
        dt = parsedate_to_datetime(s)
    except Exception:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def best_article_datetime(url: str) -> Optional[datetime]:
    html, resp = http_get(url)
    if html:
        # <meta> variants
        for rx in META_DT_RES:
            m = rx.search(html)
            if m:
                dt = parse_any_dt(m.group(1))
                if dt: return dt
        # <time> tag
        m = TIME_TAG_RE.search(html)
        if m:
            dt = parse_any_dt(m.group(1))
            if dt: return dt
        # JSON-LD (datePublished / dateModified)
        for rx in LDJSON_DATE_RES:
            m = rx.search(html)
            if m:
                dt = parse_any_dt(m.group(1))
                if dt: return dt
    # HTTP Last-Modified
    if resp is not None:
        lm = resp.headers.get("Last-Modified") or resp.headers.get("last-modified")
        if lm:
            dt = parse_any_dt(lm)
            if dt: return dt
    return None

def extract_title_desc(html: str) -> Tuple[str, str]:
    title = ""
    desc = ""
    if html:
        mt = TITLE_RE.search(html)
        if mt:
            title = clean_text(re.sub(r"\s+", " ", mt.group(1)))
        md = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if md:
            desc = clean_text(md.group(1))
    return title, desc

def extract_gov_links(html: str) -> List[str]:
    if not html: return []
    out, seen = [], set()
    for href in A_HREF_RE.findall(html):
        nh = normalize_url(href)
        h = _host(nh)
        if any(h == d or h.endswith("." + d) for d in GOV_HOSTS):
            if nh not in seen:
                seen.add(nh)
                out.append(nh)
    return out

# ---------------- Feed fetching (+ pagination) ----------------
def fetch_feed_once(url: str):
    try:
        fp = feedparser.parse(url, request_headers={"User-Agent": UA})
        if getattr(fp, "bozo", False) and not getattr(fp, "entries", None):
            r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            fp = feedparser.parse(r.text)
        return getattr(fp, "entries", []) or []
    except Exception as ex:
        print(f"  [warn] feed failed: {url} -> {ex}")
        return []

def paginate_wp_feed(base_url: str, max_pages: int) -> List[Any]:
    all_entries: List[Any] = []
    seen_links: set[str] = set()
    def page_url(i: int) -> str:
        if i == 1: return base_url
        sep = "&" if "?" in base_url else "?"
        return f"{base_url}{sep}paged={i}"
    for i in range(1, max_pages + 1):
        entries = fetch_feed_once(page_url(i))
        if not entries: break
        new_entries = [e for e in entries if getattr(e, "link", None) not in seen_links]
        for e in new_entries:
            if getattr(e, "link", None): seen_links.add(e.link)
        if not new_entries: break
        all_entries.extend(new_entries)
        # stop when the whole page is older than the window
        dates = [entry_datetime(e) for e in new_entries]
        if dates and all(d and d.date() < WINDOW_FROM for d in dates if d):
            break
    return all_entries

def paginate_atom(base_url: str, max_pages: int) -> List[Any]:
    """Generic ?page=N pagination for Atom feeds (e.g., GOV.UK publications)."""
    all_entries: List[Any] = []
    for i in range(1, max_pages + 1):
        sep = "&" if "?" in base_url else "?"
        url = f"{base_url}{sep}page={i}"
        entries = fetch_feed_once(url)
        if not entries:
            break
        all_entries.extend(entries)
        dates = [entry_datetime(e) for e in entries]
        if dates and all(d and d.date() < WINDOW_FROM for d in dates if d):
            break
    return all_entries

# ---------------- GOV.UK Search (keywords + pagination) ----------------
def govuk_search_feed(query: str, page: int) -> str:
    params = {"q": query, "order": "updated-newest", "page": page}
    return f"{GOVUK_SEARCH_BASE}?{urlencode(params)}"

def items_from_govuk_search() -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    for q in GOVUK_QUERIES:
        for page in range(1, MAX_GOV_PAGES + 1):
            url = govuk_search_feed(q, page)
            entries = fetch_feed_once(url)
            if not entries:
                break

            page_dates: List[Optional[datetime]] = []
            for e in entries:
                link_ = normalize_url((getattr(e, "link", "") or "").strip())
                dt = entry_datetime(e) or best_article_datetime(link_)
                page_dates.append(dt)
            if page_dates and all(d and d.date() < WINDOW_FROM for d in page_dates if d):
                break  # page outside window

            for e in entries:
                title = clean_text(getattr(e, "title", "") or "")
                link  = normalize_url((getattr(e, "link", "") or "").strip())
                if not title or not link or not _allowed(link):
                    continue

                dt = entry_datetime(e) or best_article_datetime(link)
                # Whitelist fallback: if undated + whitelisted, assume today
                if (link in URL_WHITELIST) and (dt is None):
                    dt = NOW_UTC
                if not within_window(dt):
                    continue

                summary = clean_text(getattr(e, "summary", "") or getattr(e, "description", "") or "")
                if not like_examples(title, summary, link):
                    continue

                kept.append({
                    "date": dt.date().isoformat(),
                    "category": category_for(title, summary),
                    "headline": title[:200],
                    "description": smart_excerpt(summary, 260),
                    "source": _host(link),
                    "url": link,
                    "gov_sources": [link] if _host(link) in GOV_HOSTS else [],
                })
    return kept

# ---------------- GOV.UK Publications (broad Atom + whitelist) ----------------
def items_from_govuk_publications() -> List[Dict[str, Any]]:
    entries = paginate_atom(GOVUK_PUBLICATIONS_ATOM, MAX_GOV_PAGES)
    kept: List[Dict[str, Any]] = []
    for e in entries:
        title = clean_text(getattr(e, "title", "") or "")
        link  = normalize_url((getattr(e, "link", "") or "").strip())
        if not title or not link or not _allowed(link):
            continue

        dt = entry_datetime(e) or best_article_datetime(link)
        if (link in URL_WHITELIST) and (dt is None):
            dt = NOW_UTC
        if not within_window(dt):
            # already tried best_article_datetime; if outside window, skip
            continue

        summary = clean_text(getattr(e, "summary", "") or getattr(e, "description", "") or "")

        if (link not in URL_WHITELIST) and (not like_examples(title, summary, link)):
            continue

        kept.append({
            "date": dt.date().isoformat(),
            "category": category_for(title, summary),
            "headline": title[:200],
            "description": smart_excerpt(summary, 260) or "GOV.UK publication update.",
            "source": _host(link),
            "url": link,
            "gov_sources": [link],
        })
    return kept

# ---------------- Items from standard feeds ----------------
def items_from_feed(url: str) -> List[Dict[str, Any]]:
    entries = paginate_wp_feed(url, MAX_WP_PAGES) if url in WP_FEEDS else fetch_feed_once(url)
    kept: List[Dict[str, Any]] = []
    seen = 0
    for e in entries:
        seen += 1
        title = clean_text(getattr(e, "title", "") or "")
        raw   = (getattr(e, "link", "") or "").strip()
        link  = normalize_url(raw)
        if not title or not link:
            continue
        if not _allowed(link) or not _path_allowed(link):
            continue

        dt = entry_datetime(e) or best_article_datetime(link)
        if (link in URL_WHITELIST) and (dt is None):
            dt = NOW_UTC
        if not within_window(dt):
            continue

        summary = clean_text(getattr(e, "summary", "") or getattr(e, "description", "") or "")
        # allow whitelist regardless of regex gates (still within window by this point)
        if (link not in URL_WHITELIST) and (not like_examples(title, summary, link)):
            continue

        gov_sources: List[str] = []
        if _host(link) in MEDIA_HOSTS:
            html, _ = http_get(link)
            gov_sources = extract_gov_links(html)

        kept.append({
            "date": dt.date().isoformat(),
            "category": category_for(title, summary),
            "headline": title[:200],
            "description": smart_excerpt(summary, 260),
            "source": _host(link),
            "url": link,
            "gov_sources": gov_sources,
        })
    print(f"→ feed: {url}  kept {len(kept)} / {seen}")
    return kept

# ---------------- Curated URLs (data/extra_urls.txt) ----------------
def items_from_extra_urls() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not EXTRA_URLS_FILE.exists():
        return items
    try:
        lines = EXTRA_URLS_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return items
    for line in lines:
        u = line.strip()
        if not u or u.startswith("#"):  # comments/blank lines
            continue
        link = normalize_url(u)
        if not _allowed(link) and (link not in URL_WHITELIST):
            continue
        html, resp = http_get(link)
        dt = best_article_datetime(link)
        if (link in URL_WHITELIST) and (dt is None):
            dt = NOW_UTC
        if not within_window(dt):
            continue
        title, desc = extract_title_desc(html)
        if not title:
            title = link
        summary = desc or ""
        if (link not in URL_WHITELIST) and (not like_examples(title, summary, link)):
            continue
        gov_sources = extract_gov_links(html)
        items.append({
            "date": dt.date().isoformat(),
            "category": category_for(title, summary),
            "headline": title[:200],
            "description": smart_excerpt(summary or "Direct source.", 260),
            "source": _host(link),
            "url": link,
            "gov_sources": gov_sources,
        })
    print(f"→ curated URLs kept {len(items)}")
    return items

# ---------------- Static pages (official updates) ----------------
def items_from_static_pages() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for url, headline, category in STATIC_PAGES:
        link = normalize_url(url)
        html, resp = http_get(link)
        if not html and not resp:
            continue
        dt: Optional[datetime] = None
        m = TIME_TAG_RE.search(html or "")
        if m:
            dt = parse_any_dt(m.group(1))
        if not dt and html:
            # Also check JSON-LD on static pages
            for rx in LDJSON_DATE_RES:
                mm = rx.search(html)
                if mm:
                    dt = parse_any_dt(mm.group(1))
                    if dt: break
        if not dt and resp is not None:
            lm = resp.headers.get("Last-Modified") or resp.headers.get("last-modified")
            if lm:
                dt = parse_any_dt(lm)
        if (link in URL_WHITELIST) and (dt is None):
            dt = NOW_UTC
        if not within_window(dt):
            print(f"→ page: {link} (no recent timestamp; skipped)")
            continue
        items.append({
            "date": dt.date().isoformat(),
            "category": category,
            "headline": headline,
            "description": f"Official page updated on {dt.date().isoformat()}.",
            "source": _host(link),
            "url": link,
            "gov_sources": [link] if _host(link) in GOV_HOSTS else [],
        })
    print(f"→ static pages kept {len(items)}")
    return items

# ---------------- Diversity caps (page 1 only) ----------------
PRIORITY_CAPS = {
    "monitor.icef.com": 0.25,
    "thepienews.com":   0.25,
}
def apply_diversity_caps(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not items:
        return items
    total = len(items)
    per_host: Dict[str, int] = {}
    caps: Dict[str, int] = {h: max(1, int(math.floor(total * share))) for h, share in PRIORITY_CAPS.items()}
    kept: List[Dict[str, Any]] = []
    for it in items:
        h = it["source"]
        cap = caps.get(h)
        if cap is None:
            kept.append(it)
            continue
        c = per_host.get(h, 0)
        if c < cap:
            kept.append(it)
            per_host[h] = c + 1
    return kept

# ---------------- Build & write ----------------
def chunk(lst: List[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
    return [lst[i:i+size] for i in range(0, len(lst), size)]

def collect_items() -> List[Dict[str, Any]]:
    all_items: List[Dict[str, Any]] = []

    # GOV.UK search (keyworded + pagination)
    all_items.extend(items_from_govuk_search())

    # GOV.UK publications (broad + whitelist)
    all_items.extend(items_from_govuk_publications())

    # Standard feeds (IRCC, USCIS, AU Edu, PIE/ICEF/IDP)
    for f in FEEDS:
        all_items.extend(items_from_feed(f))

    # Static pages (AU + UK register + I-94 + DHS + Taiwan News)
    all_items.extend(items_from_static_pages())

    # Curated URLs (data/extra_urls.txt)
    all_items.extend(items_from_extra_urls())

    # sort newest → oldest (by date string)
    def key(it): return (it["date"], it["headline"].strip().lower(), it["url"])
    all_items.sort(key=lambda it: key(it), reverse=True)

    # dedupe (by normalized url + headline)
    seen_pairs: set[tuple[str, str]] = set()
    deduped: List[Dict[str, Any]] = []
    for it in all_items:
        k = (it["headline"].strip().lower(), normalize_url(it["url"]))
        if k in seen_pairs:
            continue
        seen_pairs.add(k)
        deduped.append(it)

    # window/domain safety (redundant but safe)
    deduped = [it for it in deduped if it["date"] >= WINDOW_FROM.isoformat() and (_allowed(it["url"]) or normalize_url(it["url"]) in URL_WHITELIST)]

    print(f"✔ total items in window: {len(deduped)} (since {WINDOW_FROM.isoformat()})")
    return deduped

def write_paginated(items: List[Dict[str, Any]]):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Page 1: apply caps for a balanced front page
    page1_candidates = apply_diversity_caps(items)
    page1 = page1_candidates[:PAGE_SIZE]

    # Remaining pages: no caps
    remaining_urls = {normalize_url(it["url"]) for it in page1}
    rest = [it for it in items if normalize_url(it["url"]) not in remaining_urls]
    other_pages = chunk(rest, PAGE_SIZE)

    # Write page 1 (legacy shape)
    payload1 = {"policyNews": page1}
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload1, f, ensure_ascii=False, indent=2)
    print(f"✅ wrote page 1: {OUTPUT_FILE} ({len(page1)} items)")

    # Write subsequent pages
    pages_total = 1
    for i, page in enumerate(other_pages, start=2):
        pfile = OUTPUT_DIR / f"policyNews.p{i}.json"
        with open(pfile, "w", encoding="utf-8") as f:
            json.dump({"policyNews": page}, f, ensure_ascii=False, indent=2)
        print(f"✅ wrote page {i}: {pfile} ({len(page)} items)")
        pages_total += 1

    # Index / metadata
    index_payload = {
        "pages": pages_total,
        "page_size": PAGE_SIZE,
        "generated_at": NOW_UTC.isoformat(),
        "window_from": WINDOW_FROM.isoformat(),
        "files": ["policyNews.json"] + [f"policyNews.p{i}.json" for i in range(2, pages_total+1)],
    }
    with open(OUTPUT_DIR / "policyNews.index.json", "w", encoding="utf-8") as f:
        json.dump(index_payload, f, ensure_ascii=False, indent=2)
    print(f"🧭 wrote index: {OUTPUT_DIR / 'policyNews.index.json'}")

def main():
    print(f"🔄 Building feed (last {WINDOW_DAYS} days from {WINDOW_FROM.isoformat()})")
    items = collect_items()
    write_paginated(items)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[fatal] {e}")
        sys.exit(1)






















