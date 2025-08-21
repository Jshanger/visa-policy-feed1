#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_policy_news.py — International student mobility & education policy feed
Outputs: data/policyNews.json → {"policyNews":[...]}

Loosened logic:
- Keep classic student-mobility policy changes (visa routes, fees, dependants, work hours).
- ALSO keep posts that have a clear "policy" angle *and* connect to immigration or to
  higher-education + student mobility context (e.g., caps on int'l students, admissions policy).
- Skip undated items; dedupe; stable sort; write only on change.
"""

import json, datetime, pathlib, hashlib
from typing import List, Dict, Any
import feedparser

SITE_ROOT   = pathlib.Path(__file__).resolve().parent
OUTPUT_FILE = SITE_ROOT / "data" / "policyNews.json"
MAX_ITEMS   = 80

# ---------------- Feeds (edit to taste) ----------------
FEEDS = [
    # Government & regulators
    "https://www.gov.uk/government/organisations/home-office.atom",
    "https://www.gov.uk/government/organisations/uk-visas-and-immigration.atom",
    "https://www.canada.ca/en/immigration-refugees-citizenship/atom.xml",
    "https://www.uscis.gov/news/rss.xml",
    "https://www.homeaffairs.gov.au/news-media/rss",

    # Sector press
    "https://monitor.icef.com/feed/",
    "https://thepienews.com/news/feed/",
    "https://www.universityworldnews.com/rss/",
    "https://www.studyinternational.com/news/feed/",
    "https://www.timeshighereducation.com/rss/International",
]

# ---------------- Keyword sets ----------------
# Immigration/visa core
CORE_TOPICS = (
    "visa", "visas", "immigration", "student visa", "graduate route",
    "post-study", "psw", "opt", "pgwp", "work permit", "skilled worker",
    "sponsor licence", "sponsorship", "ukvi", "ircc", "uscis", "sevis",
    "f-1", "j-1", "dependant", "dependent", "ihs", "surcharge",
)

# Action/change cues
ACTION_CUES = (
    "update", "updated", "change", "changes", "amend", "amended", "amendment",
    "introduce", "introduces", "introduced", "launch", "launched",
    "cap", "caps", "limit", "limits", "ban", "bans", "restrict", "restriction",
    "suspend", "suspended", "revoke", "revoked", "end", "ended", "close", "closed",
    "increase", "increased", "decrease", "decreased", "rise", "raised",
    "fee", "fees", "threshold", "salary threshold", "work hours", "work rights",
)

# Student-mobility framing
STUDENT_CUES = (
    "student", "international student", "student mobility", "graduate route",
    "post-study", "psw", "opt", "pgwp", "cas", "enrolment", "enrollment",
    "dependant", "dependent", "overseas student", "study abroad", "exchange",
)

# Higher education context
EDU_TERMS = (
    "higher education", "university", "universities", "college",
    "campus", "degree", "postgraduate", "undergraduate", "admissions",
    "enrolment", "enrollment", "scholarship", "tuition", "ranking",
    "research", "partnership", "collaboration", "faculty",
)

# Policy term(s) that trigger the new relaxed pathway
POLICY_TERMS = ("policy", "policies", "policy update", "policy changes")

# Strong excludes (noise)
EXCLUDES = (
    "firearm", "shotgun", "weapons", "asylum", "deportation", "prison",
    "terrorism", "extradition", "passport office", "civil service", "tax credit",
    "planning permission", "driving licence", "tourist visa only", "visitor visa only",
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
        host = link.split("/")[2]
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
    # education-policy angle
    if any(p in b for p in POLICY_TERMS) and any(e in b for e in EDU_TERMS):
        return "Education Policy"
    return "Policy Update"

def _signature(payload: Dict[str, Any]) -> str:
    s = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

# ---------------- Inclusion logic ----------------
def _is_relevant(title: str, summary: str, link: str) -> bool:
    """
    Relevance if ANY of these pathways is true:

    A) Classic student-mobility policy change:
       - mentions immigration/visa CORE_TOPICS
       - and has ACTION_CUES (change/update/cap/fees/work-hours/etc.)
       - and has STUDENT_CUES (student/graduate route/PSW/etc.)
       - *plus* excludes & gov.uk guard

    B) Policy+immigration pathway (loosened):
       - mentions POLICY_TERMS
       - AND mentions immigration/visa CORE_TOPICS

    C) Education-policy mobility pathway (loosened):
       - mentions POLICY_TERMS
       - AND mentions EDU_TERMS
       - AND mentions STUDENT_CUES (mobility framing)
    """
    blob = (title + " " + summary).lower()

    # strong excludes first
    if any(x in blob for x in EXCLUDES):
        return False

    # gov.uk guard — keep Home Office/UKVI immigration content
    if "gov.uk" in link:
        path = link.split("gov.uk")[-1].lower()
        if not any(k in path for k in ("visas-immigration", "uk-visas-and-immigration", "immigration")):
            # allow education-policy items when explicitly policy + education + student
            if not (any(p in blob for p in POLICY_TERMS) and any(e in blob for e in EDU_TERMS) and any(s in blob for s in STUDENT_CUES)):
                return False

    # Path A: classic policy change for students
    path_a = (any(k in blob for k in CORE_TOPICS)
              and any(a in blob for a in ACTION_CUES)
              and any(s in blob for s in STUDENT_CUES))

    # Path B: policy + immigration
    path_b = (any(p in blob for p in POLICY_TERMS)
              and any(k in blob for k in CORE_TOPICS))

    # Path C: policy + education + student/mobility framing
    path_c = (any(p in blob for p in POLICY_TERMS)
              and any(e in blob for e in EDU_TERMS)
              and any(s in blob for s in STUDENT_CUES))

    return bool(path_a or path_b or path_c)

# ---------------- Fetch & build ----------------
def fetch_items() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for url in FEEDS:
        try:
            print(f"Fetching {url} …")
            feed = feedparser.parse(url, request_headers={"User-Agent": "policy-student-mobility/1.1"})
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
            print(f"[warn] failed {url}: {ex}")
    return items

def dedupe_sort(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set(); out: List[Dict[str, Any]] = []
    for it in sorted(items, key=lambda x: (x["date"], x["headline"].lower(), x["url"]), reverse=True):
        key = (it["headline"].lower(), it["url"])
        if key in seen: continue
        seen.add(key); out.append(it)
    return out[:MAX_ITEMS]

# ---------------- Main ----------------
def main():
    print("🔄 Fetching policy & student-mobility updates (loosened policy inclusion) …")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    items = dedupe_sort(fetch_items())

    if not items:
        # keep existing file if present
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


