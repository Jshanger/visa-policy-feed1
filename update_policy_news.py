#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Policy & international student mobility tracker (strict + caps + robust)
- Only keeps stories clearly tied to immigration/visas + (action OR intl students / higher-ed).
- Strong excludes (business/IPO, economy/restaurants, welfare/health, entertainment, K-12 domestic).
- PIE Gov / SCMP / Korea Herald soft boosts WITH visa/immigration or mobility terms.
- Explicit allow for SCMP “new K-visa / young talent visa” phrasing.
- Per-feed error isolation; per-domain caps; write only on change; cap 30 cards.
"""

from __future__ import annotations
from typing import List, Dict, Any
import json, datetime, pathlib, hashlib, sys, collections
from urllib.parse import urlparse
import feedparser
import requests

SITE_ROOT   = pathlib.Path(__file__).resolve().parent
OUTPUT_FILE = SITE_ROOT / "data" / "policyNews.json"
MAX_ITEMS   = 30
HTTP_TIMEOUT = 20

# ---------------- Curated feeds ----------------
FEEDS = [
    # Government & Regulators (stable)
    "https://www.gov.uk/government/organisations/home-office.atom",
    "https://www.gov.uk/government/organisations/uk-visas-and-immigration.atom",
    "https://www.canada.ca/en/immigration-refugees-citizenship/atom.xml",
    "https://www.uscis.gov/newsroom/all-news/rss.xml",

    # International orgs / think tanks
    "https://oecdedutoday.com/feed/",
    "https://wenr.wes.org/feed",
    "https://www.migrationpolicy.org/rss.xml",
    "https://www.unesco.org/en/rss-feeds/rss/education",

    # Sector media
    "https://monitor.icef.com/feed/",
    "https://thepienews.com/news/feed/",
    "https://thepienews.com/category/news/government/feed/",
    "https://www.universityworldnews.com/rss/",
    "https://studytravel.network/magazine/rss",
    "https://www.qs.com/feed/",

    # Regional / Asia
    "https://www.scmp.com/rss/91/feed",            # SCMP Education
    "https://www.scmp.com/rss/318824/feed",       # SCMP China Policy
    "https://www.koreaherald.com/rss/013018000000.html",
    "https://timesofindia.indiatimes.com/rssfeeds/913168846.cms",
    "https://www.thehindu.com/education/feeder/default.rss",
]

# ---------------- Vocabulary ----------------
CORE_TOPICS = (
    "visa", "visas", "immigration", "student visa", "graduate route",
    "post-study", "psw", "opt", "pgwp", "work permit", "skilled worker",
    "sponsor licence", "sponsorship", "ukvi", "ircc", "uscis", "sevis",
    "f-1", "j-1", "dependant", "dependent", "ihs", "surcharge",
)
ACTION_CUES = (
    "update", "updated", "change", "changes", "amend", "amended", "amendment",
    "introduce", "introduces", "introduced", "launch", "launched",
    "create", "creates", "created",
    "cap", "caps", "limit", "limits", "ban", "bans", "restrict", "restriction",
    "suspend", "suspended", "revoke", "revoked", "end", "ended", "close", "closed",
    "increase", "increased", "decrease", "decreased", "rise", "raised",
    "fee", "fees", "threshold", "salary threshold", "work hours", "work rights",
)
MOBILITY_CUES = (
    "international student", "overseas student", "foreign student", "student mobility",
    "graduate route", "post-study", "psw", "opt", "pgwp",
    "inbound student", "outbound student", "study abroad", "exchange",
)
EDU_TERMS = (
    "higher education", "university", "universities", "college", "campus",
    "degree", "postgraduate", "undergraduate", "admissions", "enrolment", "enrollment",
    "scholarship", "tuition", "ranking", "research", "partnership", "collaboration",
    "faculty", "institution", "education policy", "ministry of education", "department of education",
)
POLICY_TERMS = (
    "policy", "policies", "policy update", "policy changes", "regulation", "regulations",
    "legislation", "legislative", "bill", "act", "ordinance", "decree", "minister",
    "ministry", "department", "government", "cabinet", "white paper", "consultation",
    "directive", "guidance", "statement", "statutory", "gazette", "circular",
)

# Off-topic noise
EXCLUDES = (
    "firearm", "shotgun", "weapons", "asylum", "deportation", "prison",
    "terrorism", "extradition", "passport office", "civil service", "tax credit",
    "entertainment", "documentary", "celebrity", "magazine",
    "primary school", "secondary school", "govt schools", "government schools",
    "k-12", "k12", "schoolchildren",
    "dental", "dentist", "healthcare", "medical", "hospital", "social welfare",
    "restaurant", "dining", "cuisine", "chef",
    "economy", "retail sales", "inflation", "property market",
    "ipo", "initial public offering", "listing", "stock exchange", "shares",
    "spin off", "spinoff", "merger", "acquisition", "earnings", "profit", "revenue",
    "venture capital", "startup", "semiconductor", "robotics",
    "tourist visa only", "visitor visa only",
)

SOURCE_MAP = {
    "gov.uk": "UK Government",
    "canada.ca": "IRCC Canada",
    "uscis.gov": "USCIS",
    "monitor.icef": "ICEF Monitor",
    "thepienews": "The PIE News",
    "universityworldnews": "University World News",
    "studyinternational": "Study International",
    "timeshighereducation": "Times Higher Education",
    "scmp.com": "South China Morning Post",
    "koreaherald.com": "Korea Herald",
    "europa.eu": "EU Commission",
    "indiatimes.com": "Times of India",
    "thehindu.com": "The Hindu",
}

# Section guards
SCMP_EXCLUDE_SECTIONS = (
    "/news/hong-kong/hong-kong-economy/",
    "/tech/",
    "/magazines/style/entertainment/",
)
HINDU_EXCLUDE_SECTIONS = ("/education/schools/",)  # K-12

# Explicit SCMP visa phrases (e.g., K-visa for young talent)
SCMP_VISA_BONUS_PHRASES = (
    "k-visa", "creates new visa", "new visa for young", "young talent visa",
    "young science and technology", "young s&t", "talent visa",
)

# ---------------- Per-domain caps ----------------
DEFAULT_CAP = 3
DOMAIN_CAPS = {
    # Prioritise official & sector policy sources
    "gov.uk": 12,
    "canada.ca": 8,
    "uscis.gov": 8,
    "thepienews.com": 8,
    "monitor.icef.com": 6,
    "universityworldnews.com": 5,

    # Regional general media (avoid flooding)
    "scmp.com": 3,
    "indiatimes.com": 2,
    "timesofindia.indiatimes.com": 2,  # alternate host
    "thehindu.com": 1,                 # <-- strict cap per your request
    "koreaherald.com": 2,
}

# ---------------- Helpers ----------------
def _clean(text: str, limit: int) -> str:
    if not text: return ""
    t = " ".join(text.replace("\n", " ").split())
    return t[:limit].strip()

def _human_date(st) -> str | None:
    if not st: return None
    try:
        return datetime.date(st.tm_year, st.tm_mon, st.tm_mday).isoformat()
    except Exception:
        return None

def _source_name(link: str) -> str:
    try:
        host = urlparse(link).netloc
        for k, v in SOURCE_MAP.items():
            if k in host: return v
        return host or "Source"
    except Exception:
        return "Source"

def _host(link: str) -> str:
    try:
        return urlparse(link).netloc.lower()
    except Exception:
        return ""

def _category(title: str, summary: str) -> str:
    b = (title + " " + summary).lower()
    if any(x in b for x in ("graduate route", "post-study", "psw", "opt", "pgwp", "international student", "student visa")):
        return "Student Visas"
    if any(x in b for x in ("skilled", "work permit", "sponsor", "threshold", "work hours", "work rights")):
        return "Work Visas"
    if "visa exemption" in b or "visa-free" in b:
        return "Visa Exemption"
    if any(x in b for x in ("permanent", "resident", "pr")):
        return "Residency"
    if any(p in b for p in POLICY_TERMS) and any(e in b for e in EDU_TERMS):
        return "Education Policy"
    return "Policy Update"

def _signature(payload: Dict[str, Any]) -> str:
    s = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _domain_path(link: str) -> tuple[str, str]:
    u = urlparse(link)
    return u.netloc.lower(), u.path.lower()

# ---------------- Robust fetching ----------------
def _fetch_feed(url: str):
    """Try feedparser; if bozo & empty, requests→feedparser. Never raise."""
    try:
        fp = feedparser.parse(url, request_headers={"User-Agent": "policy-mobility/1.9"})
        if (getattr(fp, "bozo", False) and not getattr(fp, "entries", None)):
            try:
                r = requests.get(url, headers={"User-Agent": "policy-mobility/1.9"}, timeout=HTTP_TIMEOUT)
                r.raise_for_status()
                fp = feedparser.parse(r.text)
            except Exception as ex:
                print(f"  [warn] fallback failed: {url} -> {ex}")
        return fp
    except Exception as ex:
        print(f"  [warn] feed fetch failed: {url} -> {ex}")
        class _Empty: entries = []
        return _Empty()

# ---------------- Inclusion logic (STRICT) ----------------
def _is_relevant(title: str, summary: str, link: str) -> bool:
    """
    STRICT: require VISA/IMMIGRATION cues.
    Keep if:
      - strong_path: CORE_TOPICS + ACTION_CUES
      - edu_mobility_path: CORE_TOPICS + (MOBILITY_CUES or EDU_TERMS)
      - PIE Gov page WITH (CORE_TOPICS or MOBILITY_CUES)
      - SCMP/KoreaHerald WITH (visa/CORE_TOPICS) AND (ACTION_CUES or POLICY_TERMS)
      - SCMP K-visa allow phrases
    """
    blob = (title + " " + summary).lower()
    host, path = _domain_path(link)

    # hard excludes first
    if any(x in blob for x in EXCLUDES):
        return False

    # section guards (drop outright)
    if "scmp.com" in host and any(path.startswith(sec) for sec in SCMP_EXCLUDE_SECTIONS):
        return False
    if "thehindu.com" in host and any(path.startswith(sec) for sec in HINDU_EXCLUDE_SECTIONS):
        return False

    # gov.uk: only immigration sections (others require core+mobility/edu)
    if "gov.uk" in host:
        if not any(k in path for k in ("/visas-immigration", "/uk-visas-and-immigration", "/immigration")):
            if not (any(k in blob for k in CORE_TOPICS) and (any(s in blob for s in MOBILITY_CUES) or any(e in blob for e in EDU_TERMS))):
                return False

    strong_path = (any(k in blob for k in CORE_TOPICS) and any(a in blob for a in ACTION_CUES))
    edu_mobility_path = (any(k in blob for k in CORE_TOPICS) and (any(s in blob for s in MOBILITY_CUES) or any(e in blob for e in EDU_TERMS)))

    if strong_path or edu_mobility_path:
        return True

    if "thepienews.com" in host and "/category/news/government" in path:
        if any(k in blob for k in CORE_TOPICS) or any(s in blob for s in MOBILITY_CUES):
            return True

    if ("scmp.com" in host or "koreaherald.com" in host):
        if (("visa" in blob) or any(k in blob for k in CORE_TOPICS)) and \
           (any(a in blob for a in ACTION_CUES) or any(p in blob for p in POLICY_TERMS)):
            return True
        if "scmp.com" in host and any(phrase in blob for phrase in SCMP_VISA_BONUS_PHRASES):
            return True

    return False

# ---------------- Build list ----------------
def fetch_items() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for url in FEEDS:
        print(f"→ Fetching: {url}")
        fp = _fetch_feed(url)
        entries = getattr(fp, "entries", []) or []
        kept = 0; seen = 0
        for e in entries:
            title   = (e.get("title") or "").strip()
            summary = (e.get("summary") or e.get("description") or "").strip()
            if not title:
                continue
            link = e.get("link") or ""
            seen += 1
            if not _is_relevant(title, summary, link):
                continue
            st = e.get("published_parsed") or e.get("updated_parsed")
            date_str = _human_date(st)
            if not date_str:
                continue
            items.append({
                "date": date_str,
                "category": _category(title, summary),
                "headline": _clean(title, 160),
                "description": _clean(summary, 260),
                "source": _source_name(link),
                "url": link
            })
            kept += 1
        print(f"   kept {kept:3d} / {seen:3d}")
    return items

def _xhash(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:12]

def apply_domain_caps(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply per-domain caps, preferring newest first."""
    items_sorted = sorted(items, key=lambda x: (x["date"], x["headline"].lower(), x["url"]), reverse=True)
    counts = collections.Counter()
    out: List[Dict[str, Any]] = []
    for it in items_sorted:
        host = _host(it["url"])
        cap = DOMAIN_CAPS.get(host, DOMAIN_CAPS.get(host.replace("www.", ""), DEFAULT_CAP))
        if counts[host] < cap:
            out.append(it)
            counts[host] += 1
        if len(out) >= MAX_ITEMS:
            break
    return out

# ---------------- Main ----------------
def main():
    print("🔄 Fetching policy & student-mobility updates …")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    raw_items = fetch_items()
    capped_items = apply_domain_caps(raw_items)
    # Final trim (safety)
    if len(capped_items) > MAX_ITEMS:
        capped_items = capped_items[:MAX_ITEMS]

    if not capped_items:
        if OUTPUT_FILE.exists():
            print("⚠️ No relevant items; kept existing policyNews.json.")
            return
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump({"policyNews": []}, f, ensure_ascii=False, indent=2)
        print("⚠️ No items; wrote empty scaffold.")
        return

    payload  = {"policyNews": capped_items}
    new_hash = _signature(payload)

    old_hash = None
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                old_hash = _signature(json.load(f))
        except Exception as ex:
            print(f"[warn] could not hash existing file: {ex}")

    if new_hash != old_hash:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"✅ Wrote {len(capped_items)} items (domain-capped, max {MAX_ITEMS}) → {OUTPUT_FILE}")
    else:
        print("ℹ️ No changes; left existing file untouched (hash match).")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[fatal] {e}")
        sys.exit(1)





