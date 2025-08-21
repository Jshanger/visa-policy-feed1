#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_policy_news.py — Policy & international student mobility tracker
Outputs: data/policyNews.json → {"policyNews":[...]}

Inclusion (source-agnostic):
 A) Student-mobility immigration change:
    - immigration/visa CORE_TOPICS
    - + ACTION_CUES (change/update/cap/fees/work hours/etc.)
    - + STUDENT_CUES (student/graduate route/PSW/etc.)
 B) Policy + Immigration:
    - POLICY_TERMS
    - + CORE_TOPICS
 C) Policy + Higher-Ed + Student/Mobility:
    - POLICY_TERMS
    - + EDU_TERMS (HE context)
    - + STUDENT_CUES

Safeguards:
- Strong EXCLUDES (remove welfare/health/irrelevant topics like dental care)
- gov.uk guard to UKVI/immigration unless it clearly matches (C)
- Skip undated items; dedupe; stable sort; write only on change
- Limit to MAX_ITEMS=30 (newest first)
"""

from typing import List, Dict, Any
import json, datetime, pathlib, hashlib
from urllib.parse import urlparse
import feedparser

SITE_ROOT   = pathlib.Path(__file__).resolve().parent
OUTPUT_FILE = SITE_ROOT / "data" / "policyNews.json"
MAX_ITEMS   = 30  # show up to 30 relevant cards

# ---------------- Curated feeds ----------------
FEEDS = [
    # --- Government & Regulators ---
    "https://www.gov.uk/government/organisations/home-office.atom",
    "https://www.gov.uk/government/organisations/uk-visas-and-immigration.atom",
    "https://www.canada.ca/en/immigration-refugees-citizenship/atom.xml",
    "https://www.uscis.gov/news/rss.xml",
    "https://www.homeaffairs.gov.au/news-media/rss",
    "https://www.education.gov.au/news/rss",         # Australia Dept of Education
    "https://enz.govt.nz/news/feed/",                # Education New Zealand
    "https://ec.europa.eu/home-affairs/news/feed_en", # EU Migration & Home Affairs

    # --- International Orgs / Think Tanks ---
    "https://oecdedutoday.com/feed/",
    "https://wenr.wes.org/feed",                     # WES Research (WENR)
    "https://www.migrationpolicy.org/rss.xml",       # Migration Policy Institute
    "https://www.unesco.org/en/rss-feeds/rss/education",

    # --- Sector Media ---
    "https://monitor.icef.com/feed/",
    "https://thepienews.com/news/feed/",
    "https://thepienews.com/category/news/government/feed/",  # PIE Government
    "https://www.universityworldnews.com/rss/",
    "https://studytravel.network/magazine/rss",
    "https://www.qs.com/feed/",

    # --- Regional / Asia Focused ---
    "https://www.scmp.com/rss/91/feed",              # SCMP Education
    "https://www.scmp.com/rss/318824/feed",          # SCMP China Policy
    "https://www.koreaherald.com/rss/013018000000.html",  # Korea Herald (National)
    "https://timesofindia.indiatimes.com/rssfeeds/913168846.cms", # ToI Education
    "https://www.thehindu.com/education/feeder/default.rss",
]

# ---------------- Keyword sets ----------------
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

STUDENT_CUES = (
    "student", "international student", "student mobility", "graduate route",
    "post-study", "psw", "opt", "pgwp", "cas", "enrolment", "enrollment",
    "dependant", "dependent", "overseas student", "study abroad", "exchange",
)

EDU_TERMS = (
    "higher education", "university", "universities", "college",
    "campus", "degree", "postgraduate", "undergraduate", "admissions",
    "enrolment", "enrollment", "scholarship", "tuition", "ranking",
    "research", "partnership", "collaboration", "faculty", "institution",
    "education policy", "ministry of education", "department of education",
)

POLICY_TERMS = (
    "policy", "policies", "policy update", "policy changes", "regulation", "regulations",
    "legislation", "legislative", "bill", "act", "ordinance", "decree", "minister",
    "ministry", "department", "government", "cabinet", "white paper", "consultation",
    "directive", "guidance", "statement", "statutory", "gazette", "circular",
)

# Non-mobility / off-topic noise (e.g., dental care)
EXCLUDES = (
    "firearm", "shotgun", "weapons", "asylum", "deportation", "prison",
    "terrorism", "extradition", "passport office", "civil service", "tax credit",
    "planning permission", "driving licence", "driving license",
    "dental", "dentist", "healthcare", "medical", "hospital", "social welfare",
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

def _category(title: str, summary: str) -> str:
    b = (title + " " + summary).lower()
    if any(x in b for x in ("graduate route", "post-study", "psw", "opt", "pgwp", "student")):
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

def _is_pie_government(path: str, tags_text: str) -> bool:
    return ("/category/news/government" in path) or ("government" in tags_text)

# ---------------- Inclusion logic ----------------
def _is_relevant(title: str, summary: str, link: str, categories: List[str]) -> bool:
    blob = (title + " " + summary).lower()

    # strong excludes (e.g., dental/healthcare welfare story)
    if any(x in blob for x in EXCLUDES):
        return False

    # gov.uk guard — keep Home Office/UKVI immigration content
    if "gov.uk" in link:
        path = link.split("gov.uk")[-1].lower()
        gov_guard = any(k in path for k in ("visas-immigration", "uk-visas-and-immigration", "immigration"))
        if not gov_guard:
            # allow explicit education policy impacting students (Path C)
            allow_edu_policy = (any(p in blob for p in POLICY_TERMS)
                                and any(e in blob for e in EDU_TERMS)
                                and any(s in blob for s in STUDENT_CUES))
            if not allow_edu_policy:
                return False

    # Path A: explicit student-mobility immigration change
    path_a = (any(k in blob for k in CORE_TOPICS)
              and any(a in blob for a in ACTION_CUES)
              and any(s in blob for s in STUDENT_CUES))

    # Path B: policy + immigration
    path_b = (any(p in blob for p in POLICY_TERMS)
              and any(k in blob for k in CORE_TOPICS))

    # Path C: policy + higher-ed + student/mobility
    path_c = (any(p in blob for p in POLICY_TERMS)
              and any(e in blob for e in EDU_TERMS)
              and any(s in blob for s in STUDENT_CUES))

    if path_a or path_b or path_c:
        return True

    # Soft boosts for high-signal sources where phrasing is softer:
    host = urlparse(link).netloc.lower()
    path = urlparse(link).path.lower()
    cats_text = " ".join([c.lower() for c in (categories or [])])

    # PIE Government
    if "thepienews.com" in host and _is_pie_government(path, cats_text):
        if any(p in blob for p in POLICY_TERMS) and (
            any(k in blob for k in CORE_TOPICS) or
            (any(e in blob for e in EDU_TERMS) and any(s in blob for s in STUDENT_CUES))
        ):
            return True

    # SCMP / Korea Herald: include when 'visa' or 'international student' appears + action/policy cue
    if ("scmp.com" in host or "koreaherald.com" in host):
        if (("visa" in blob) or ("international student" in blob) or ("student visa" in blob)) and \
           (any(a in blob for a in ACTION_CUES) or any(p in blob for p in POLICY_TERMS)):
            return True

    return False

# ---------------- Fetch & build ----------------
def fetch_items() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for url in FEEDS:
        try:
            print(f"Fetching {url} …")
            feed = feedparser.parse(url, request_headers={"User-Agent": "policy-mobility/1.3"})
            for e in feed.entries:
                title   = (e.get("title") or "").strip()
                summary = (e.get("summary") or e.get("description") or "").strip()
                if not title:
                    continue

                link = e.get("link") or ""
                tags = []
                if "tags" in e and isinstance(e["tags"], list):
                    tags = [t.get("term", "") for t in e["tags"] if isinstance(t, dict)]

                if not _is_relevant(title, summary, link, tags):
                    continue

                st = e.get("published_parsed") or e.get("updated_parsed")
                date_str = _human_date(st)
                if not date_str:
                    continue  # skip undated

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
    # newest first; stable by (date, headline, url)
    for it in sorted(items, key=lambda x: (x["date"], x["headline"].lower(), x["url"]), reverse=True):
        key = (it["headline"].lower(), _xhash(it["url"]))
        if key in seen: 
            continue
        seen.add(key); out.append(it)
    return out[:MAX_ITEMS]

# ---------------- Main ----------------
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
    new_hash = _signature(payload)

    old_hash = None
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                old_hash = _signature(json.load(f))
        except Exception:
            pass

    if new_hash != old_hash:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"✅ Wrote {len(items)} items → {OUTPUT_FILE}")
    else:
        print("ℹ️ No changes; left existing file untouched.")

if __name__ == "__main__":
    main()




