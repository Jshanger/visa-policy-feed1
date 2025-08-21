#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Policy & international student mobility tracker (30 items, gov-priority, robust)

Keeps ONLY content clearly tied to:
  • visas/immigration + an action/change, or
  • visas/immigration + (international students OR higher education)

Quality gates:
  • Strong off-topic excludes (IPO/markets, restaurants/economy, entertainment, K-12 domestic,
    generic welfare/health, tourism-only)
  • Section guards for SCMP and The Hindu
  • PIE Government / SCMP / Korea Herald soft boosts (still require visa/mobility cues)
  • Explicit allow for SCMP “new K-visa / young talent visa” phrasing

Output: data/policyNews.json  →  {"policyNews":[...]}
"""

from __future__ import annotations
from typing import List, Dict, Any
import json, datetime, pathlib, hashlib, sys, collections
from urllib.parse import urlparse
import feedparser, requests

# -------- Settings --------
SITE_ROOT        = pathlib.Path(__file__).resolve().parent
OUTPUT_FILE      = SITE_ROOT / "data" / "policyNews.json"
MAX_ITEMS        = 30
MIN_GOV_ITEMS    = 10          # ensure at least this many gov items if available
HTTP_TIMEOUT     = 20

# -------- Feeds (stable core) --------
FEEDS = [
    # Government/regulators
    "https://www.gov.uk/government/organisations/home-office.atom",
    "https://www.gov.uk/government/organisations/uk-visas-and-immigration.atom",
    "https://www.gov.uk/government/announcements.rss",
    "https://www.canada.ca/en/immigration-refugees-citizenship/atom.xml",
    "https://www.uscis.gov/newsroom/all-news/rss.xml",
    "https://ec.europa.eu/home-affairs/news/feed_en",

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
    "https://www.scmp.com/rss/91/feed",              # SCMP Education
    "https://www.scmp.com/rss/318824/feed",          # SCMP China Policy
    "https://www.koreaherald.com/rss/013018000000.html",
    "https://timesofindia.indiatimes.com/rssfeeds/913168846.cms",
    "https://www.thehindu.com/education/feeder/default.rss",
]

# -------- Lexicons --------
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
    "policy", "policies", "regulation", "regulations",
    "legislation", "bill", "act", "ordinance", "decree", "minister",
    "ministry", "department", "government", "cabinet", "consultation",
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
    "europa.eu": "EU Commission",
    "monitor.icef": "ICEF Monitor",
    "thepienews": "The PIE News",
    "universityworldnews": "University World News",
    "studyinternational": "Study International",
    "timeshighereducation": "Times Higher Education",
    "scmp.com": "South China Morning Post",
    "koreaherald.com": "Korea Herald",
    "indiatimes.com": "Times of India",
    "timesofindia.indiatimes.com": "Times of India",
    "thehindu.com": "The Hindu",
}

# Section guards (drop outright)
SCMP_EXCLUDE_SECTIONS  = ("/news/hong-kong/hong-kong-economy/", "/tech/", "/magazines/style/entertainment/",)
HINDU_EXCLUDE_SECTIONS = ("/education/schools/",)

# Explicit SCMP allow phrases
SCMP_VISA_BONUS_PHRASES = (
    "k-visa", "creates new visa", "new visa for young", "young talent visa",
    "young science and technology", "talent visa",
)

# Domain caps (avoid floods)
DEFAULT_CAP = 3
DOMAIN_CAPS = {
    "gov.uk": 12, "canada.ca": 8, "uscis.gov": 8, "europa.eu": 6,
    "thepienews.com": 8, "monitor.icef.com": 6, "universityworldnews.com": 5,
    "scmp.com": 3, "indiatimes.com": 2, "timesofindia.indiatimes.com": 2,
    "thehindu.com": 1, "koreaherald.com": 2,
}

GOV_HOST_HINTS = ("gov.uk", "canada.ca", "uscis.gov", "europa.eu")

# -------- Helpers --------
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

# -------- Robust fetching --------
def _fetch_feed(url: str):
    try:
        fp = feedparser.parse(url, request_headers={"User-Agent": "policy-mobility/2.0"})
        if (getattr(fp, "bozo", False) and not getattr(fp, "entries", None)):
            try:
                r = requests.get(url, headers={"User-Agent": "policy-mobility/2.0"}, timeout=HTTP_TIMEOUT)
                r.raise_for_status()
                fp = feedparser.parse(r.text)
            except Exception as ex:
                print(f"  [warn] fallback failed: {url} -> {ex}")
        return fp
    except Exception as ex:
        print(f"  [warn] feed fetch failed: {url} -> {ex}")
        class _Empty: entries = []
        return _Empty()

# -------- Inclusion logic (STRICT) --------
def _is_relevant(title: str, summary: str, link: str) -> bool:
    blob = (title + " " + summary).lower()
    host, path = _domain_path(link)

    # hard excludes
    if any(x in blob for x in EXCLUDES):
        return False
    # section guards (drop outright)
    if "scmp.com" in host and any(path.startswith(sec) for sec in SCMP_EXCLUDE_SECTIONS):
        return False
    if "thehindu.com" in host and any(path.startswith(sec) for sec in HINDU_EXCLUDE_SECTIONS):
        return False
    # gov.uk guard – only immigration sections, else require core+mobility/edu
    if "gov.uk" in host and not any(k in path for k in ("/visas-immigration", "/uk-visas-and-immigration", "/immigration")):
        if not (any(k in blob for k in CORE_TOPICS) and (any(s in blob for s in MOBILITY_CUES) or any(e in blob for e in EDU_TERMS))):
            return False

    # main keep paths (both require core visa/immigration cues)
    strong_path = (any(k in blob for k in CORE_TOPICS) and any(a in blob for a in ACTION_CUES))
    edu_mobility_path = (any(k in blob for k in CORE_TOPICS) and (any(s in blob for s in MOBILITY_CUES) or any(e in blob for e in EDU_TERMS)))
    if strong_path or edu_mobility_path:
        return True

    # PIE Government: keep only if visas/immigration or mobility is present
    if "thepienews.com" in host and "/category/news/government" in path:
        if any(k in blob for k in CORE_TOPICS) or any(s in blob for s in MOBILITY_CUES):
            return True

    # SCMP / Korea Herald: require visa/core + (action or policy)
    if ("scmp.com" in host or "koreaherald.com" in host):
        if (("visa" in blob) or any(k in blob for k in CORE_TOPICS)) and \
           (any(a in blob for a in ACTION_CUES) or any(p in blob for p in POLICY_TERMS)):
            return True
        if "scmp.com" in host and any(phrase in blob for phrase in SCMP_VISA_BONUS_PHRASES):
            return True

    return False

# -------- Build list --------
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

def _is_gov_host(host: str) -> bool:
    return any(hint in host for hint in GOV_HOST_HINTS)

def apply_caps_and_gov_quota(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # newest first
    items_sorted = sorted(items, key=lambda x: (x["date"], x["headline"].lower(), x["url"]), reverse=True)
    domain_counts = collections.Counter()
    gov_pool, non_gov_pool = [], []

    # Apply per-domain caps while splitting gov vs non-gov pools
    for it in items_sorted:
        host = _host(it["url"])
        cap = DOMAIN_CAPS.get(host, DOMAIN_CAPS.get(host.replace("www.", ""), DEFAULT_CAP))
        if domain_counts[host] >= cap:
            continue
        domain_counts[host] += 1
        (gov_pool if _is_gov_host(host) else non_gov_pool).append(it)

    # Compose final list honouring MIN_GOV_ITEMS (if available)
    final: List[Dict[str, Any]] = []
    take_gov = min(len(gov_pool), max(MIN_GOV_ITEMS, min(MAX_ITEMS, len(gov_pool))))
    final.extend(gov_pool[:take_gov])
    remaining = MAX_ITEMS - len(final)
    if remaining > 0:
        final.extend(non_gov_pool[:remaining])

    # Safety trim
    return final[:MAX_ITEMS]

# -------- Main --------
def main():
    print("🔄 Fetching policy & student-mobility updates …")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    raw_items = fetch_items()
    if not raw_items:
        if OUTPUT_FILE.exists():
            print("⚠️ No relevant items; kept existing policyNews.json.")
            return
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump({"policyNews": []}, f, ensure_ascii=False, indent=2)
        print("⚠️ No items; wrote empty scaffold.")
        return

    selected = apply_caps_and_gov_quota(raw_items)
    print(f"✔ selected {len(selected)} (max {MAX_ITEMS})")

    payload  = {"policyNews": selected}
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
        print(f"✅ Wrote {len(selected)} items → {OUTPUT_FILE}")
    else:
        print("ℹ️ No changes; left existing file untouched (hash match).")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[fatal] {e}")
        sys.exit(1)







