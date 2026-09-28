"""
job_details.py — a job posting broken into technologies, requirements and "what they want", mapped to your resume.

Technologies come from the shared skills taxonomy (skills_taxonomy.py), so the Tech tab, the Match tab and the
scoring all agree on what a "skill" is; have / adjacent / missing is decided against your active resume profile.
"""

from __future__ import annotations

import re
from typing import Any

from src import matching
from src import skills_taxonomy as tax

NON_ENG_TITLES = ("human resources", "people operations", "talent", "recruiter", "hr ")
_EDU = re.compile(r"(bachelor'?s?|master'?s?|ph\.?d|doctorate|degree in [a-z ,&]+|b\.?sc|m\.?sc|diploma|associate'?s? degree|cape|csec)", re.I)
_EMP = re.compile(r"(full[- ]?time|part[- ]?time|contract(?:or)?|freelance|permanent|temporary|internship)", re.I)
_REMOTE = re.compile(r"(fully remote|remote[- ]first|remote|hybrid|on-?site|work from home|distributed)", re.I)


def extract_technologies(text: str) -> dict[str, list[str]]:
    """{category: [skill, …]} for every taxonomy skill named in `text` (soft skills excluded)."""
    found: dict[str, list[str]] = {}
    for name in tax.find_skills(text or ""):
        if name in tax.SOFT:
            continue
        found.setdefault(tax.CATEGORY.get(name, "Other"), []).append(name)
    return found


def extract_requirements(job: dict) -> dict[str, Any]:
    a = matching.analyze_job(job)
    text = f"{job.get('title', '')} {job.get('description', '')} {job.get('location', '')}"
    first = lambda rx: (m.group(0).strip() if (m := rx.search(text)) else None)  # noqa: E731
    yrs = a["min_years"]
    return {
        "experience_raw": (f"{yrs}+ years" if yrs else ("entry level" if a["entry"] else None)),
        "education_raw": first(_EDU), "remote_raw": first(_REMOTE), "employment_raw": first(_EMP),
        "needs": a["requirements"][:8], "needs_raw": "\n".join(a["requirements"])[:2000],
        "work_mode": a["work_mode"], "remote_scope": a["remote_scope"],
        "is_non_eng": any(p in (job.get("title") or "").lower() for p in NON_ENG_TITLES) and "engineer" not in (job.get("title") or "").lower(),
    }


def analyze(job: dict, profile: dict | None = None) -> dict:
    """Full analysis for the Tech / Needs tabs. `profile` is accepted for compatibility; the active resume is used."""
    ctx = matching.current_context()
    a = matching.analyze_job(job)
    have_skills = (ctx or {}).get("skills", {})
    cov = matching.skill_coverage({k: v for k, v in a["skills"].items() if k not in tax.SOFT}, have_skills)
    status = {i["name"]: i["status"] for i in cov["items"]}
    techs = extract_technologies(f"{job.get('title', '')} {job.get('description', '')}")
    with_status = {cat: [{"tech": t, "have": status.get(t) == "have", "status": status.get(t, "missing"),
                          "years": (have_skills.get(t) or {}).get("years", 0)} for t in lst] for cat, lst in techs.items()}
    total = sum(len(v) for v in techs.values())
    have = sum(1 for lst in with_status.values() for i in lst if i["have"])
    return {
        "technologies": techs, "technologies_with_status": with_status, "requirements": extract_requirements(job),
        "summary": {"total_techs": total, "have": have, "gap": total - have,
                    "coverage": round(have / total * 100) if total else 0, "has_resume": bool(ctx)},
    }
