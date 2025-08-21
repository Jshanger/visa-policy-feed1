#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_policy_news.py — Policy & international student mobility tracker (refined)
Output: data/policyNews.json → {"policyNews":[...]}

Inclusion (must match at least one):
 A) Student-mobility immigration change:
    - CORE_TOPICS (visa/immigration)
    - + ACTION_CUES
    - + MOBILITY_CUES (international/overseas students, PSW/OPT/PGWP, etc.)
 B) Policy + Immigration:
    - POLICY_TERMS
    - + CORE_TOPICS
 C) Policy + Higher-Ed + Mobility (stricter):
    - POLICY_TERMS
    - + EDU_TERMS (HE context)
    - + MOBILITY_CUES (must reference international/overseas/inbound/outbound/mobility)

Safeguards:
- Strong EXCLUDES (economy/restaurant/tech-investment/entertainment/K-12-only, etc.)
- Domain path guards (e.g., SCMP economy/tech/style excluded unless immigration/mobility also present)
- Skip undated; dedupe; stable sort; write only on change; cap 30 items.
"""

from typing import List, Dict, Any
import json, datetime, pathlib, hashlib, re
from urllib.parse import urlparse
import feedparser

SITE_ROOT   = pathlib.Path(__file__).resolve().parent
OUTPUT_FILE = SITE_ROOT / "data" / "policyNews.json"
MAX_ITEMS   = 30

# ---------- Feeds ----------
FEEDS = [
    # Government & Regulators
    "https://www.gov.uk/government/organisations/home-office.atom",
    "https://www.gov.uk/government/organisations/uk-visas-and-immigration.atom",
    "https://www.canada.ca/en/immigration-refugees-citizenship/atom.xml",
    "https://www.uscis.gov/news/rss.xml",
    "https://www.homeaffairs.gov.au/news-media/rss",
    "https://www.education.gov.au/news/rss",
    "https://enz.govt.nz/news/feed/",
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
    "https://www.scmp.com/rss/91/feed",          # SCMP Education
    "https://www.scmp.com/rss/318824/feed",      # SCMP China Policy
    "https://www.koreaherald.com/rss/013018000000.html",
    "https://timesofindia.indiatimes.com/rssfeeds/913168846.cms",
    "https://www.thehindu.com/education/feeder/default.rss",
]

# ---------- Vocab ----------
CORE_TOPICS = (
    "visa", "visas", "immigration", "student visa", "graduate route",
    "post-study", "psw", "opt", "pgwp", "work permit", "skilled worker",
    "sponsor licence", "sponsorship", "ukvi", "ircc", "uscis", "sevis",
    "f-1", "j-1", "dependant", "dependent", "ihs", "surcharge",
)
ACTION_CUES = (
    "update", "updated", "change", "changes", "amend", "amended", "amendment",
    "introduce", "introduces", "introduced", "launch", "launched",
    "cap", "caps", "limit", "limits", "ban", "bans", "restrict", "restriction",
    "suspend", "suspended", "revoke", "revoked", "end", "ended", "close", "closed",
    "increase", "increased", "decrease", "decreased", "rise", "raised",
    "fee", "fees", "threshold", "salary threshold", "work hours", "work rights",
)
# Mobility cues MUST imply international student mobility, not just generic “students”
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

# Hard excludes (noise/off-topic)
EXCLUDES = (
    # general crime/defence/welfare/health/celebrity/entertainment/economy/tech-investment
    "firearm", "shotgun", "weapons", "asylum", "deportation", "prison",
    "terrorism", "extradition", "passport office", "civil service", "tax credit",
    "planning permission", "driving licence", "driving license",
    "restaurant", "dining", "recipe", "cuisine", "chef",
    "economy", "retail sales", "inflation", "property market",
    "investment", "venture capital", "startup", "semiconductor", "robotics", "foxconn",
    "entertainment", "documentary", "celebrity", "magazine",
    # K-12 domestic schooling (exclude unless mobility present)
    "primary school", "secondary school", "govt schools", "government schools",
    "k-12", "k12", "schoolchildren",
    # generic healthcare
    "dental", "dentist", "healthcare", "medical", "hospital", "social welfare",
    # tourism only
    "tourist visa only", "visitor visa only",
)

SOURCE_MAP = {
    "gov.uk": "UK Government",
    "canada.ca": "IRCC Canada",
    "uscis.gov": "USCIS",
    "homeaffairs": "Dept. of Home Affairs (AU)",
    "monitor.icef": "ICEF Monitor",
    "thepienews": "The PIE News",
    "universityworldnews": "University World News",
    "studyinternational": "Study International",
    "timeshighereducation": "Times Higher Education",
    "scmp.com": "South China Morning Post",
    "koreaherald.com": "Korea Herald",
    "education.gov.au": "Dept of Education (AU)",
    "enz.govt.nz": "Education New Zealand",
    "europa.eu": "EU Commission",
}

SCMP_EXCLUDE_SECTIONS = (
    "/news/hong-kong/hong-kong-economy/",
    "/tech/", "/magazines/style/entertainment/",
)
HINDU_EXCLUDE_SECTIONS = (
    "/education/schools/",  # K-12 domestic
)

# ---------- Helpers ----------
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

# ---------- Inclusion logic ----------
def _is_relevant(title: str, summary: str, link: str) -> bool:
    blob = (title + " " + summary).lower()
    host, path = _domain_path(link)

    # hard excludes first
    if any(x in blob for x in EXCLUDES):
        return False

    # section guards for some domains (require explicit mobility/immigration cues)
    if "scmp.com" in host and any(path.startswith(sec) for sec in SCMP_EXCLUDE_SECTIONS):
        if not (("visa" in blob or any(k in blob for k in CORE_TOPICS)) and (any(a in blob for a in ACTION_CUES) or any(p in blob for p in POLICY_TERMS))):
            return False

    if "thehindu.com" in host and any(path.startswith(sec) for sec in HINDU_EXCLUDE_SECTIONS):
        # allow only if it clearly references international students/mobility or visas
        if not (any(k in blob for k in CORE_TOPICS) and any(s in blob for s in MOBILITY_CUES)):
            return False

    # gov.uk guard — keep UKVI/immigration only unless education-policy + mobility
    if "gov.uk" in host:
        gov_guard = any(k in path for k in ("/visas-immigration", "/uk-visas-and-immigration", "/immigration"))
        if not gov_guard:
            allow_edu_policy = (any(p in blob for p in POLICY_TERMS)
                                and any(e in blob for e in EDU_TERMS)
                                and any(s in blob for s in MOBILITY_CUES))
            if not allow_edu_policy:
                return False

    # Path A: explicit student-mobility immigration change
    path_a = (any(k in blob for k in CORE_TOPICS)
              and any(a in blob for a in ACTION_CUES)
              and any(s in blob for s in MOBILITY_CUES))

    # Path B: policy + immigration
    path_b = (any(p in blob for p in POLICY_TERMS)
              and any(k in blob for k in CORE_TOPICS))

    # Path C: policy + HE + mobility (requires mobility cues, not just "students")
    path_c = (any(p in blob for p in POLICY_TERMS)
              and any(e in blob for e in EDU_TERMS)
              and any(s in blob for s in MOBILITY_CUES))

    # Soft boost for PIE Government pages
    if "thepienews.com" in host and "/category/news/government" in path:
        if any(p in blob for p in POLICY_TERMS) and (
            any(k in blob for k in CORE_TOPICS) or any(s in blob for s in MOBILITY_CUES)
        ):
            return True

    # Soft boost for SCMP/Korea Herald if visa or international student + action/policy
    if ("scmp.com" in host or "koreaherald.com" in host):
        if (("visa" in blob) or any(s in blob for s in MOBILITY_CUES)) and \
           (any(a in blob for a in ACTION_CUES) or any(p in blob for p in POLICY_TERMS)):
            return True

    return bool(path_a or path_b or path_c)

# ---------- Fetch & build ----------
def fetch_items() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for url in FEEDS:
        try:
            print(f"Fetching {url} …")
            feed = feedparser.parse(url, request_headers={"User-Agent": "policy-mobility/1.4"})
            for e in feed.entries:
                title   = (e.get("title") or "").strip()
                summary = (e.get("summary") or e.get("description") or "").strip()
                if not title:
                    continue
                link = e.get("link") or ""
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
        except Exception as ex:
            print(f"[warn] feed failed: {url} -> {ex}")
    return items

def _xhash(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:12]

def dedupe_sort(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set(); out: List[Dict[str, Any]] = []
    for it in sorted(items, key=lambda x: (x["date"], x["headline"].lower(), x["url"]), reverse=True):
        key = (it["headline"].lower(), _xhash(it["url"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out[:MAX_ITEMS]

# ---------- Main ----------
def main():
    print("🔄 Fetching policy & student-mobility updates …")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    items = dedupe_sort(fetch_items())
    if not items:
        if OUTPUT_FILE.exists():
            print("⚠️ No relevant items; kept existing policyNews.json.")
            return
        else:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump({"policyNews": []}, f, ensure_ascii=False, indent=2)
            print("⚠️ No items; wrote empty scaffold.")
            return

    payload  = {"policyNews": items}
    new_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    old_hash = None
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                old_hash = hashlib.sha256(json.dumps(json.load(f), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        except Exception:
            pass

    if new_hash != old_hash:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"✅ Wrote {len(items)} items (max {MAX_ITEMS}) → {OUTPUT_FILE}")
    else:
        print("ℹ️ No changes; left existing file untouched.")

if __name__ == "__main__":
    main()




