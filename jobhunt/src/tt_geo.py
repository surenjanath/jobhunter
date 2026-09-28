"""
tt_geo.py — Trinidad & Tobago geography and job-category helpers.

Every local board describes places differently ("Port-of-Spain", "Port Of Spain/
St James/ Morvant", "Couva/Point Lisas", "Chaguanas / Caroni / Freeport"...).
`normalize_region` maps any of those onto one canonical region name so the
dashboard can filter and count by region no matter which board a job came from.
"""

from __future__ import annotations

import re

# canonical region -> aliases (lowercase, punctuation-free)
REGIONS: dict[str, list[str]] = {
    "Port of Spain": ["port of spain", "pos", "st james", "woodbrook", "belmont", "morvant", "laventille",
                      "st ann", "cascade", "maraval", "newtown", "st clair", "diego martin", "carenage",
                      "westmoorings", "chaguaramas", "cocorite", "petit valley", "glencoe", "four roads"],
    "San Juan / Laventille": ["san juan", "santa cruz", "el socorro", "barataria", "aranguez", "mt lambert", "mount lambert"],
    "Tunapuna / Piarco": ["tunapuna", "st augustine", "curepe", "piarco", "trincity", "tacarigua", "st joseph", "el dorado", "arouca",
                          "maloney", "mt hope", "mount hope", "cunupia"],
    "Arima / Sangre Grande": ["arima", "sangre grande", "valencia", "toco", "matelot", "blanchisseuse",
                              "guanapo", "wallerfield"],
    "Chaguanas / Caroni": ["chaguanas", "caroni", "freeport", "montrose", "charlieville", "endeavour",
                           "edinburgh", "felicity", "cunupia", "longdenville", "munroe road"],
    "Couva / Point Lisas": ["couva", "point lisas", "pt lisas", "claxton bay", "gasparillo", "california",
                            "esperanza", "preysal", "pointe a pierre", "point a pierre", "pointe pierre"],
    "San Fernando": ["san fernando", "marabella", "gulf view", "cocoyea", "la romain", "vistabella",
                     "pleasantville", "mon repos", "les efforts"],
    "Penal / Debe / Siparia": ["penal", "debe", "siparia", "fyzabad", "la brea", "palo seco", "santa flora",
                               "moruga", "rousillac", "point fortin"],
    "Princes Town / Rio Claro": ["princes town", "rio claro", "mayaro", "tabaquite", "williamsville",
                                 "st julien", "ste madeleine", "sainte madeleine", "guayaguayare"],
    "Tobago": ["tobago", "scarborough", "crown point", "canaan", "plymouth", "roxborough", "charlotteville"],
}

# Nationwide roles
NATIONWIDE = ("nationwide", "island wide", "islandwide", "all regions", "trinidad and tobago", "trinidad tobago",
              "trinidad")

_PUNCT = re.compile(r"[^a-z0-9 ]+")


def _norm(text: str) -> str:
    text = (text or "").lower().replace("&", " and ")
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", text)).strip()


def find_regions(*fields: str) -> list[str]:
    """All canonical regions mentioned, in order of first appearance."""
    blob = " " + _norm(" ".join(f for f in fields if f)) + " "
    hits: list[tuple[int, str]] = []
    for region, aliases in REGIONS.items():
        best = None
        for a in aliases:
            i = blob.find(f" {a} ")
            if i >= 0 and (best is None or i < best):
                best = i
        if best is not None:
            hits.append((best, region))
    hits.sort()
    return [r for _, r in hits]


def normalize_region(*fields: str) -> str:
    """Primary region for a job, or 'Trinidad & Tobago' (nationwide) if none is recognised."""
    found = find_regions(*fields)
    if found:
        return found[0]
    return "Trinidad & Tobago"


def is_trinidad(*fields: str) -> bool:
    blob = _norm(" ".join(f for f in fields if f))
    if "trinidad" in blob or "tobago" in blob:
        return True
    return bool(find_regions(blob))


# ordered: first match wins, so specific categories go before generic ones
CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("Technology", ("software", "developer", "programmer", "devops", "data analyst", "data engineer", "database",
                    "network", "cyber", "it support", "help desk", "helpdesk", "systems administrator",
                    "system administrator", "web ", "ict", "information technology", "technical support",
                    "full stack", "python", "django", "cloud", "machine learning", " ai ", "erp")),
    ("Finance & Accounting", ("accountant", "accounting", "accounts", "finance", "financial", "audit", "payroll",
                              "bookkeeper", "treasury", "tax ", "credit", "banking", "bank ", "teller",
                              "loan", "actuar", "underwrit", "claims", "insurance")),
    ("Legal & Compliance", ("legal", "attorney", "lawyer", "paralegal", "compliance", "counsel", "risk")),
    ("Logistics & Supply Chain", ("logistic", "warehouse", "forklift", "supply chain", "procurement", "purchasing", "driver",
                                  "dispatch", "inventory", "stores", "distribution", "shipping", "freight",
                                  "customs")),
    ("Engineering & Technical", ("engineer", "technician", "mechanic", "electrician", "electrical",
                                 "mechanical", "maintenance", "instrument", "surveyor", "draughts", "welder",
                                 "fitter", "machine operator", "plant operator", "artisan", "plumber", "hvac")),
    ("Healthcare", ("nurse", "nursing", "pharmac", "medical", "doctor", "dental", "clinic", "laborator",
                    "health", "physio", "radiograph", "paramedic", "caregiver", "veterin", "animal health")),
    ("Sales & Marketing", ("sales", "marketing", "merchandis", "brand", "business development", "account executive",
                           "account manager", "social media", "content creat", "advertis", "promotion")),
    ("Customer Service", ("customer service", "customer care", "call cent", "contact cent", "receptionist",
                          "front desk", "cashier", "guest")),
    ("Human Resources", ("human resource", "hr ", "recruit", "talent", "learning and development", "training officer")),
    ("Admin & Clerical", ("administrative", "admin ", "clerk", "secretary", "office assistant", "data entry",
                          "executive assistant", "personal assistant", "records", "registry")),
    ("Education & Training", ("teacher", "lecturer", "instructor", "tutor", "professor", "education", "school",
                              "librar", "trainer")),
    ("Hospitality & Tourism", ("hotel", "chef", "cook", "restaurant", "waiter", "waitress", "bartender", "hospitality",
                               "housekeeping", "tour ", "kitchen")),
    ("Management", ("manager", "director", "head of", "supervisor", "superintendent", "coordinator", "chief",
                    "general manager", "executive")),
    ("Public Sector", ("public officer", "ministry", "government", "police", "officer i", "officer ii")),
]


def classify_category(title: str, description: str = "") -> str:
    """Best-effort category from the title (strong signal) then the opening of the description."""
    t = f" {(title or '').lower()} "
    for name, kws in CATEGORIES:
        if any(k in t for k in kws):
            return name
    d = f" {(description or '')[:200].lower()} "
    for name, kws in CATEGORIES:
        if any(k in d for k in kws):
            return name
    return "Other"
