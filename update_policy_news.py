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
    "https://www.gov.uk/government/announcements.rss",             # broad; filter keeps immigration only
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

# Optional (commented out due to occasional 404s on CI runners)
# "https://www.homeaffairs.gov.au/news-media/rss",
# "https://enz.govt.nz/news/feed/",
# "https://www.education.gov.au/news/rss",

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

# Off-topic noise (restaurants/economy/IPO/entertainment/K-12/welfare/health)
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
HINDU_EXCLUDE_SECTIONS = ("/education/schools/",)  # K-12

# Explicit SCMP allow phrases (young talent K-visa, etc.)
SCMP_VISA_BONUS_PHRASES = (
    "k-visa", "creates new visa", "new visa for young", "young talent visa",
    "young science and technology", "talent visa",
)

# Domain caps (avoid floods)
DEFAULT_CAP = 3
DOMAIN_CAPS = {
    # prioritise official & sector policy sources
    "gov.uk": 12,
    "canada.ca": 8,
    "uscis.gov": 8,
    "europa.eu": 6,
    "thepienews.com": 8,
    "monitor.icef.com": 6,
    "universityworldnews.com": 5,
    # regional media (tighter)
    "scmp.com": 3,
    "indiatimes.com": 2,
    "timesofindia.indiatimes.com": 2,
    "thehindu.com": 1,
    "koreaherald.com": 2,
}

# Hosts counted as "government" for the MIN_GOV_ITEMS rule
GOV_HOST_HINTS = ("gov.uk", "canada.ca", "uscis.gov", "europa.eu")

# -------- Helpers --------
def _clean(text: str, limit: int) -> str:
    if not text: return ""
    t = " ".join(text.replace("\n", " ").split())
    return t[:limit].strip()

def _human_date(st) -> str | None:
    if not st: return None
    try: return datetime.date(st.tm_year, st.tm_mon, st.tm_mday).isoformat()
    except Exception: return None

def _source_name(link: str) -> str:
    try:
        host = urlparse(link).netloc
        for k, v in SOURCE_MAP.items():
            if k in host: return v
        return host or "Source"
    except Exception:
        return "Source"

def _host(link: str) -> str:
    try: return urlparse(link).netloc.lower()
    except Exception: return ""

def _category(title: str, summary: str) -> str:
    b = (title + " " + summary).lower()
    if any(x in b for x in ("graduate route", "post-study", "psw", "opt", "pgwp", "international student", "student visa")):
        return "Student Visas"
    if any(x in b for x in ("skilled", "work permit", "sponsor", "threshold", "work hours", "work rights")):
        return "Work Visas"
    if "visa exemption" in b or "






