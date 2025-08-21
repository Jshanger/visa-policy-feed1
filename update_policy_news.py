#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_policy_news.py — Policy & student-mobility tracker (enhanced source handling)
Outputs: data/policyNews.json → {"policyNews":[...]}

What's new:
- Boosts SCMP + Korea Herald if they mention student-mobility policy even subtly.
- General, source-agnostic detection paths:
    A) explicit student-mobility policy change (visa routes, fees, caps...)
    B) policy + immigration terms
    C) policy + higher-ed + student
- Adds strong excludes; skips undated; dedupe/sort; writes only if changed.
"""

import json, datetime, pathlib, hashlib
from typing import List, Dict, Any
import feedparser
from urllib.parse import urlparse

SITE_ROOT   = pathlib.Path(__file__).resolve().parent
OUTPUT_FILE = SITE_ROOT / "data" / "policyNews.json"
MAX_ITEMS   = 100

# --- Feeds (extend as needed) ---
FEEDS = [
    "https://www.gov.uk/government/organisations/home-office.atom",
    "https://www.gov.uk/government/organisations/uk-visas-and-immigration.atom",
    "https://www.canada.ca/en/immigration-refugees-citizenship/atom.xml",
    "https://www.uscis.gov/news/rss.xml",
    "https://www.homeaffairs.gov.au/news-media/rss",

    "https://monitor.icef.com/feed/",
    "https://thepienews.com/news/feed/",
    "https://thepienews.com/category/news/government/feed/",
    "https://www.universityworldnews.com/rss/",
    "https://www.studyinternational.com/news/feed/",
    "https://www.timeshighereducation.com/rss/International",
    "https://www.scmp.com/rss/91/feed",  # SCMP education/politics
    "https://www.koreaherald.com/rss/013018000000.html",  # Korea Herald general
]

# --- Keyword sets ---
CORE_TOPICS = ("visa", "immigration", "student visa", "graduate route", "post-study", 
               "psw", "opt", "pgwp", "work permit", "skilled worker")
ACTION_CUES = ("create", "creates", "introduce", "launch", "cap", "increase", "update", "change")
STUDENT_CUES = ("student", "international student", "graduate route", "post-study", "exchange", "mobility")
EDU_TERMS = ("education", "university", "campus", "degree", "admission", "scholarship")
POLICY_TERMS = ("policy", "policies", "regulation", "legislation", "minister", "government")
EXCLUDES = ("firearm", "asylum", "tourist visa only", "visitor visa only")

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
    "scmp.com": "SCMP",
    "koreaherald.com": "Korea Herald",
}

# --- Helpers ---
def clean(txt, limit):
    return " ".join(txt.replace("\n", " ").split())[:limit] if txt else ""

def date_iso(st):
    try: return datetime.date(st.tm_year, st.tm_mon, st.tm_mday).isoformat()
    except: return None

def source_name(link):
    try:
        h = urlparse(link).netloc
        for k, v in SOURCE_MAP.items():
            if k in h: return v
        return h or "Source"
    except:
        return "Source"

def category_for(txt):
    b = txt.lower()
    if "visa" in b and "student" in b: return "Student Visas"
    if "work permit" in b or "skilled worker" in b: return "Work Visas"
    if "education policy" in b or ("education" in b and "policy" in b): return "Education Policy"
    return "Policy Update"

def signature(obj):
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

# --- Inclusion logic ---
def is_relevant(title, summary, link):
    blob = (title + " " + summary).lower()
    if any(x in blob for x in EXCLUDES): return False

    # Gov UK guard
    if "gov.uk" in link and not any(x in blob for x in CORE_TOPICS + POLICY_TERMS):
        return False

    # Path A: explicit student mobility change
    if any(t in blob for t in CORE_TOPICS) and any(a in blob for a in ACTION_CUES) and any(s in blob for s in STUDENT_CUES):
        return True

    # Path B: policy + immigration
    if any(p in blob for p in POLICY_TERMS) and any(t in blob for t in CORE_TOPICS):
        return True

    # Path C: policy + HE + student
    if any(p in blob for p in POLICY_TERMS) and any(e in blob for e in EDU_TERMS) and any(s in blob for s in STUDENT_CUES):
        return True

    # Boost SCMP / Korea Herald if they mention 'visa' or 'education' and action / policy cues  
    if "scmp.com" in link or "koreaherald.com" in link:
        if ("visa" in blob or "international student" in blob) and any(a in blob for a in ACTION_CUES + POLICY_TERMS):
            return True

    return False

# --- Fetch & build ---
def fetch_items():
    out = []
    for u in FEEDS:
        try:
            print("Fetching", u)
            feed = feedparser.parse(u)
            for e in feed.entries:
                t = e.get("title", "")
                s = e.get("summary", e.get("description", ""))
                if not t: continue
                link = e.get("link", "")
                if not is_relevant(t, s, link): continue
                st = date_iso(e.get("published_parsed") or e.get("updated_parsed"))
                if not st: continue
                out.append({
                    "date": st,
                    "category": category_for(t + " " + s),
                    "headline": clean(t, 160),
                    "description": clean(s, 240),
                    "source": source_name(link),
                    "url": link
                })
        except Exception as ex:
            print("Feed failed:", ex)
    return out

def dedupe_sort(items):
    seen = set(); out = []
    for it in sorted(items, key=lambda x: x["date"], reverse=True):
        key = (it["headline"].lower(), it["url"])
        if key in seen: continue
        seen.add(key); out.append(it)
    return out[:MAX_ITEMS]

def main():
    print("Updating policyNews …")
    SITE_ROOT.mkdir(parents=True, exist_ok=True)

    items = dedupe_sort(fetch_items())
    if not items:
        print("No items — keeping existing file.")
        return

    payload = {"policyNews": items}
    new_sig = signature(payload)
    old_sig = None
    if OUTPUT_FILE.exists():
        try:
            old_sig = signature(json.load(open(OUTPUT_FILE)))
        except: pass
    if new_sig != old_sig:
        json.dump(payload, open(OUTPUT_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"Wrote {len(items)} items.")
    else:
        print("No changes.")

if __name__ == "__main__":
    main()



