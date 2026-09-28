"""
resume.py — the structured view of your resume that the dashboard and coach use.

Everything comes from the active resume in profile_store (parsed from what you uploaded, plus your corrections).
Nothing here is hard-coded about a particular person. `parse()` keeps the shape older callers expect.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "config" / "profile.yaml"


def _yaml() -> dict:
    try:
        return yaml.safe_load(PROFILE.read_text()) or {}
    except Exception:  # noqa: BLE001
        return {}


def market_gaps(limit: int = 6) -> list[dict]:
    """Skills your stored listings ask for as *required* that your resume lacks, most common first."""
    try:
        import json
        from src import db
        c = db._conn()
        rows = c.execute("SELECT match_json, fit_score FROM jobs WHERE match_json != ''").fetchall()
        c.close()
    except Exception:  # noqa: BLE001
        return []
    from src import profile_store
    from src import skills_taxonomy as tax
    prof = profile_store.active_profile() or {}
    cats = Counter(m.get("category") for m in prof.get("skills", {}).values())
    focus = {k for k, v in cats.items() if v >= 2 and k not in ("Domains", "Languages (spoken)")}   # areas you actually work in
    cnt: Counter = Counter()
    for r in rows:
        try:
            m = json.loads(r["match_json"])
        except ValueError:
            continue
        for it in (m.get("skills") or {}).get("items", []):
            if it["status"] == "missing" and it["kind"] == "required" and it["name"] not in tax.SOFT and (not focus or it.get("category") in focus):
                cnt[it["name"]] += 1
    return [{"skill": k, "jobs": v} for k, v in cnt.most_common(limit)]


def parse() -> dict:
    from src import profile_store
    yml = _yaml()
    cand = yml.get("candidate") if isinstance(yml.get("candidate"), dict) else {}
    p = profile_store.active_profile()
    if not p:
        return {"name": cand.get("name", ""), "title": "", "email": cand.get("email", ""), "has_resume": False,
                "location": {"location": cand.get("location", "Trinidad & Tobago"), "timezone": cand.get("timezone", "UTC-4"),
                             "note": cand.get("timezone_note", ""), "auth": cand.get("work_authorization", "")},
                "years": cand.get("years_experience", 0), "skills": {}, "projects": [], "strengths": [], "gaps": [],
                "targets": yml.get("targets", {}), "fact_bank_chars": 0, "resume_chars": 0, "profile": yml}
    contact = p.get("contact") or {}
    skills: dict[str, list[str]] = {}
    for name, m in sorted(p.get("skills", {}).items(), key=lambda kv: (-kv[1].get("years", 0), kv[0])):
        skills.setdefault(m.get("category", "Other"), []).append(name)
    top = sorted(p.get("skills", {}).items(), key=lambda kv: -kv[1].get("years", 0))[:4]
    strengths = [f"{p['years_experience']:g} years of experience, most recently as {p['titles'][0]}" if p.get("titles") else f"{p['years_experience']:g} years of experience"]
    if top:
        strengths.append("Longest-used skills: " + ", ".join(f"{n} ({m['years']:g}y)" for n, m in top if m.get("years")))
    strengths += (p.get("achievements") or [])[:3]
    strengths += ((p.get("llm") or {}).get("strengths") or [])[:2]
    gaps = [f"{g['skill']} — required by {g['jobs']} of your listings, not on your resume" for g in market_gaps(5)]
    gaps += ((p.get("llm") or {}).get("gaps") or [])[:2]
    return {
        "name": contact.get("name") or cand.get("name", ""), "title": (p.get("titles") or [""])[0], "email": contact.get("email") or cand.get("email", ""),
        "has_resume": True,
        "location": {"location": cand.get("location", "Trinidad & Tobago"), "timezone": cand.get("timezone", "UTC-4"),
                     "note": cand.get("timezone_note", ""), "auth": cand.get("work_authorization", "")},
        "years": p.get("years_experience", 0), "skills": skills,
        "projects": [{"name": x.get("name", ""), "status": "", "scope": x.get("text", "")} for x in p.get("projects", [])],
        "strengths": strengths, "gaps": gaps, "targets": yml.get("targets", {}),
        "fact_bank_chars": 0, "resume_chars": p.get("chars", 0), "profile": yml,
    }
