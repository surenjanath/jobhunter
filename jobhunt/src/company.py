"""
company.py — lightweight company intelligence from JD + known ATS.

For each job, surface: HQ, size hints, stage, stack clues, and a
1-line research starter so the letter can be specific.
"""

from __future__ import annotations

import re

STAGE_CLUES = {
    "seed": ["seed", "pre-seed", "angel"],
    "series a": ["series a", "series-a"],
    "scaleup": ["series b", "series c", "scaleup", "growth stage"],
    "public": ["publicly traded", "nasdaq", "ipo"],
}

SIZE_CLUES = {
    "small team": 8, "small team, wear many hats": 10,
    "seed stage": 7, "series a": 7, "startup": 6,
}

def research(job: dict) -> dict:
    blob = f"{job.get('title','')} {job.get('description','')} {job.get('company','')}".lower()
    company = job.get("company") or "Unknown"
    title = job.get("title") or ""

    # Stage hint
    stage = None
    for k, words in STAGE_CLUES.items():
        if any(w in blob for w in words):
            stage = k
            break

    # Size hint
    size = None
    if "small team" in blob or "wear many hats" in blob:
        size = "Small (<50) — wear many hats"
    elif "founding" in title.lower():
        size = "Founding — first engineers"
    elif "enterprise" in blob:
        size = "Enterprise — 1000+"

    # Stack clues for letter
    stack = []
    for tech in ["python","django","react","typescript","aws","gcp","azure","docker","kubernetes","snowflake","airflow","dbt"]:
        if tech in blob:
            stack.append(tech.title())

    # Research prompt (what to google before writing)
    prompt = f"Search: '{company} {title.split('—')[0].strip()[:40]}' engineering blog, product, recent launch, tech stack. Find one specific sentence to open the letter."

    # Quick company link
    link = job.get("url") or f"https://www.google.com/search?q={company.replace(' ','+')}+careers"

    return {
        "company": company,
        "stage": stage or "unknown",
        "size": size or "unknown",
        "stack": stack[:8],
        "prompt": prompt,
        "link": link,
    }
