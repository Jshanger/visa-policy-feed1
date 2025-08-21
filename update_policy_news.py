#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_policy_news.py — Policy & international student mobility tracker (amended)
Output: data/policyNews.json → {"policyNews":[...]}

Inclusion (must match at least one):
 A) Student-mobility immigration change:
    - CORE_TOPICS (visa/immigration)
    - + ACTION_CUES
    - + MOBILITY_CUES (international/overseas students, PSW/OPT/PGWP, etc.)
 B) Policy + Immigration:
    - POLICY_TERMS
    - + CORE_TOPICS
 C) Policy + Higher-Ed + Mobility (requires mobility cues):
    - POLICY_TERMS
    - + EDU_TERMS (HE context)
    - + MOBILITY_CUES

Safeguards:
- Strong EXCLUDES (now also blocks business/IPO/listing etc.)
- Domain path guards (gov.uk immigration sections; SCMP section checks)
- SCMP/KoreaHerald/PIE Gov soft boosts (visa/policy + mobility)
- Explicit SCMP K-visa inclusion
- Skip undated; dedupe; stable sort; write only on change; cap 30 items.
"""

from typing import List, Dict, Any
import json, datetime, pathlib, hashlib
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
    "https://www.scmp.com/rss/91/feed",           # SCMP Education
    "https://www.scmp.com/rss/318824/feed",       # SCMP China Policy
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

# Hard excludes (noise/off-topic; add business/IPO etc.)
EXCLUDES = (
    # crime/defence/welfare/health/celebrity/entertainment
    "firearm", "shotgun", "weapons", "asylum", "deportation", "prison",
    "terrorism", "extradition", "passport office", "civil service", "tax credit",
    "entertainment", "documentary", "celebrity", "magazine",
    # K-12 domestic schooling (unless mobility present, handled elsewhere)
    "primary school", "secondary school", "govt schools", "government schools",
    "k-12", "k12", "schoolchildren",
    # healthcare
    "dental", "dentist", "healthcare", "medical", "hospital", "social welfare",
    # tourism only
    "tourist visa only", "visitor visa only",
    # business/markets/IPO/investment (new)
    "ipo", "initial public offering", "listing", "stock exchange", "shares",
    "spin off", "spinoff", "merger", "acquisition", "earnings", "profit", "revenue",
    "venture capital", "startup", "semiconductor", "r





