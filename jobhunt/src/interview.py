"""
interview.py — interview prep built from THIS posting and YOUR resume.

* a question for each thing the posting asks for that you can answer, seeded with your own resume bullet as the STAR material
* an honest question for each required skill you're missing (how you'd ramp up)
* seniority / work-mode questions that follow from the posting (remote in UTC-4, on-site availability, level gap)
No canned stories: if your resume has no evidence for something, the prep says so.
"""

from __future__ import annotations

from src import matching
from src import skills_taxonomy as tax


def _star(bullet: dict | None, skill: str) -> str:
    if not bullet:
        return f"No {skill} story on your resume yet — prepare one real example (situation, what you did, measurable result) before the call."
    return f"Your material: “{bullet['text'][:200]}” ({bullet['label'][:60]}). Structure it as Situation → your action → measurable result."


def questions(job: dict) -> dict:
    ctx = matching.current_context()
    title = job.get("title") or ""
    if not ctx:
        return {"questions": [{"q": "Why this role, and why this company?", "why": "Asked in every interview", "star": "Cite something specific from the posting."}],
                "count": 1, "title": title}
    m = matching.evaluate(dict(job), ctx)
    a = matching.analyze_job(job)
    prof = ctx["profile"]
    qs: list[dict] = []

    qs.append({"q": f"Walk me through your background and why {job.get('company') or 'this company'} / {title}.",
               "why": "Every interview opens here — 90 seconds, ending on why this role",
               "star": (f"Open with: {prof.get('summary')[:220]}" if prof.get("summary") else
                        f"{prof['years_experience']:g} years of experience, most recently {prof['titles'][0]}." if prof.get("titles") else
                        "Two sentences on what you do, one on what you want next.")})

    for req in m["requirements"]:
        if req["status"] == "met" and req["evidence"] and len(qs) < 4:
            qs.append({"q": f"The posting asks: “{req['text'][:150]}”. Tell me about a time you did that.",
                       "why": "They will probe the strongest match on your resume — be ready with detail",
                       "star": _star({"text": req["evidence"]["text"], "label": req["evidence"]["label"]}, "this")})
    gaps = [i for i in m["skills"]["items"] if i["status"] == "missing" and i["kind"] == "required"][:2]
    for g in gaps:
        qs.append({"q": f"This role needs {g['name']}. Your resume doesn't mention it — how would you get up to speed?",
                   "why": "An honest gap answered well is better than a bluffed one",
                   "star": f"Say you haven't used {g['name']} yet, name the closest thing you have "
                           f"({', '.join(sorted(tax.related(g['name']) & set(ctx['skills'])) or ['a related skill'])}), and give a concrete ramp-up plan with a timeframe."})
    rel = [i for i in m["skills"]["items"] if i["status"] == "related" and i["kind"] != "nice"][:1]
    for r in rel:
        qs.append({"q": f"We use {r['name']}; you've used {r['via']}. How do the two compare?", "why": "Tests whether your adjacent experience transfers",
                   "star": f"Be specific about what carries over from {r['via']} and what you'd need to learn."})

    if a["level"] - ctx["level"] >= 0.75:
        qs.append({"q": "This role is more senior than your current title. What makes you ready for it?", "why": "The posting is above your resume's level",
                   "star": "Lead with scope you owned (systems, people, money, users), not years."})
    if a["work_mode"] == "remote" and not m["job"]["local"]:
        qs.append({"q": "How do you work with a distributed team from Trinidad & Tobago (UTC-4)?", "why": "Remote roles worry about time zones and reliability",
                   "star": "Overlap with US Eastern is full; mention async habits, written updates, how you handle on-call." + (" Contractor / EOR arrangements were mentioned in the posting." if a["eor"] else "")})
    elif m["job"]["local"]:
        qs.append({"q": "When could you start, and are you available for the on-site schedule described?", "why": "Local roles ask about notice period and availability", "star": "Have your notice period and preferred start date ready."})
    if prof.get("achievements"):
        qs.append({"q": "Pick the result you're proudest of and walk me through how you measured it.", "why": "Quantified results are what interviewers remember",
                   "star": f"Your material: “{prof['achievements'][0][:200]}”"})
    return {"questions": qs[:7], "count": min(7, len(qs)), "title": title}


def prep(job: dict) -> dict:
    qs = questions(job)
    ctx = matching.current_context()
    check = []
    if ctx:
        m = matching.evaluate(dict(job), ctx)
        for it in m["skills"]["items"]:
            if it["kind"] == "nice" or it["status"] == "soft":
                continue
            if it["status"] == "have":
                yrs = f" ({it['years']:g}y)" if it["years"] else ""
                check.append(f"Refresh {it['name']}{yrs}: be ready to explain one real project and a tradeoff you made")
            elif it["status"] == "missing":
                check.append(f"Skim {it['name']} basics — the posting requires it and it isn't on your resume")
        tip = (m["advice"] + ". " if m["advice"] else "") + "Lead with a shipped result, acknowledge one gap plainly, and show you read the posting."
    else:
        tip = "Add a resume on the Profile page to get prep based on your own experience."
    if not check:
        check = ["Prepare one end-to-end story: problem → what you built → measurable result", "Write down three questions to ask them"]
    return {"questions": qs["questions"], "checklist": check[:6], "tip": tip}
