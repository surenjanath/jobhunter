"""
ai_resume.py — per-job tailoring advice built from your real resume bullets and the posting's real requirements.
Truthful by construction: it only reorders and re-words what you have, and lists what you must NOT claim.
"""

from __future__ import annotations

from src import matching


def tailor(job: dict, resume_text: str | None = None) -> dict:
    ctx = matching.current_context()
    if not ctx:
        return {"lead_with": "", "missing_keywords": [], "injections": [], "bullets": ["Add a resume on the Profile page first."], "cover_open": "", "lead_bullets": []}
    m = matching.evaluate(dict(job), ctx)
    t = m["tailoring"]
    prof = ctx["profile"]
    lead = t["lead_with"][0] if t["lead_with"] else None
    matched = [s["name"] for s in m["skills"]["matched"] if s["kind"] != "nice"][:3]
    quant = [a for a in prof.get("achievements", []) if any(s.lower() in a.lower() for s in matched)] or prof.get("achievements", [])
    title, company = job.get("title") or "this role", job.get("company") or "your team"

    bullets = []
    if lead:
        bullets.append(f"Lead with: {lead['bullet']}")
    for extra in t["lead_with"][1:]:
        bullets.append(f"Then: {extra['bullet']}")
    if quant:
        bullets.append(f"Quantify with a result you already have: {quant[0][:200]}")
    for miss in t["do_not_claim"][:2]:
        bullets.append(f"If asked about {miss}: say you haven't used it yet and describe how you'd learn it — don't claim it.")
    opener = (f"I'm applying for {title} at {company}. "
              + (f"The closest thing I've shipped to what you describe: {lead['bullet'].rstrip('.')}." if lead else
                 f"I bring {prof.get('years_experience', 0):g} years of experience"
                 + (f" with {', '.join(matched)}." if matched else ".")))
    return {
        "lead_with": (lead["bullet"] + f"  ({lead['where']})") if lead else "No resume passage answers this posting well — consider whether it's a fit",
        "lead_bullets": t["lead_with"],
        "missing_keywords": t["do_not_claim"] + [k["skill"] for k in t["add_keywords"]],
        "injections": [k["advice"] for k in t["add_keywords"]] + [f"Don't claim {x}: it isn't on your resume." for x in t["do_not_claim"][:3]],
        "bullets": bullets, "cover_open": opener,
        "fit": m["fit"], "likelihood": m["likelihood"],
    }
