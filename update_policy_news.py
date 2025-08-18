#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
import requests
import json
from datetime import datetime

# ----------------------------
# Relevance filters — STRICT
# ----------------------------

# Hard excludes (always drop these)
EXCLUDE_TERMS = [
    "diplomat", "ambassador", "ceasefire", "arms deal", "sanction",
    "military", "consulate attack", "asylum seeker", "deportation flight",
    "tourist visa only", "business visa only", "cultural exchange", "short course"
]

# Core immigration/policy keywords — must be present
CORE_IMM_TOKENS = [
    "visa", "study permit", "permit", "ukvi", "home office", "ircc", "uscis",
    "post-study work", "psw", "graduate route", "opt", "dependant", "dependent visa",
    "work rights", "work hours", "ihs", "immigration", "student route",
    "cap", "quota", "restriction", "policy", "regulation", "rule change",
    "threshold", "compliance", "processing time", "backlog"
]

def is_relevant(article):
    """Keep only immigration & visa policy-related articles"""
    text = (
        (article.get("headline") or "")
        + " "
        + (article.get("description") or "")
    ).lower()
    source = (article.get("source") or "").lower()

    # Exclude unwanted categories (geopolitics, trends, surveys, etc.)
    if any(term in text for term in EXCLUDE_TERMS):
        return False

    # Must include at least one visa/immigration/policy keyword
    if not any(core in text for core in CORE_IMM_TOKENS):
        return False

    return True


# ----------------------------
# Fetch & Update JSON
# ----------------------------

def fetch_articles():
    # 🔹 Replace this with your real fetch logic / API calls
    url = "https://your-feed-endpoint.com/news.json"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()
        return data.get("articles", [])
    except Exception as e:
        print("Fetch error:", e)
        return []


def main():
    articles = fetch_articles()

    # Apply strict relevance filter
    filtered = [a for a in articles if is_relevant(a)]

    # Sort newest first
    filtered.sort(
        key=lambda x: datetime.strptime(x["date"], "%Y-%m-%d"),
        reverse=True
    )

    # Save back into JSON
    with open("data/policyNews.json", "w", encoding="utf-8") as f:
        json.dump({"policyNews": filtered}, f, ensure_ascii=False, indent=2)

    print(f"✅ Saved {len(filtered)} relevant visa/policy articles.")


if __name__ == "__main__":
    main()




