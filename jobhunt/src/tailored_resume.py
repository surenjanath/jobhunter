"""
tailored_resume.py — your resume, arranged for one posting.

It only SELECTS and REORDERS what your resume already says: bullets that back the posting's requirements lead each
role, skills the posting asks for come first, the most relevant projects are kept. Nothing is reworded or added, so
every line stays something you actually wrote. Your headline and summary are kept word for word.

build() returns a plain dict the web page renders (print → Save as PDF); to_markdown() and to_text() give the
same content for pasting into application forms (plain text is what ATS parsers read most reliably).
"""

from __future__ import annotations

import re

from src import matching
from src import skills_taxonomy as tax

MAX_BULLETS_LATEST, MAX_BULLETS_OTHER, MAX_SKILLS, MAX_PROJECTS = 6, 4, 18, 3


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9+#.]{2,}", (s or "").lower())}


def _bullet_score(bullet: str, job_skills: set[str], evidence: set[str], req_words: set[str]) -> float:
    if bullet in evidence:
        return 3.0   # the matcher already picked this line as proof of a requirement
    s = 1.0 * len(set(tax.find_skills(bullet)) & job_skills)
    s += 0.15 * len(_words(bullet) & req_words)
    s += 0.3 if re.search(r"\d", bullet) else 0.0   # quantified lines are worth leading with
    return s


def build(job: dict, ctx: dict | None = None) -> dict:
    ctx = ctx or matching.current_context()
    if not ctx:
        return {"error": "add your resume on the Profile page first"}
    prof = ctx["profile"]
    m = matching.evaluate(dict(job), ctx)
    items = m["skills"]["items"]
    job_skills = {i["name"] for i in items}
    evidence = {(r.get("evidence") or {}).get("text") for r in m.get("requirements") or [] if r.get("evidence")}
    req_words = set().union(*[_words(r["text"]) for r in m.get("requirements") or []]) if m.get("requirements") else set()

    roles, left_out = [], 0
    for k, role in enumerate(prof.get("roles") or []):
        bullets = list(role.get("bullets") or [])
        ranked = sorted(bullets, key=lambda b: -_bullet_score(b, job_skills, evidence, req_words))
        cap = MAX_BULLETS_LATEST if k == 0 else MAX_BULLETS_OTHER
        keep = ranked[:cap]
        left_out += len(bullets) - len(keep)
        roles.append({"title": role.get("title") or "", "company": role.get("company") or "",
                      "dates": " – ".join(x for x in (role.get("start") or "", "Present" if role.get("current") else role.get("end") or "") if x),
                      "bullets": keep})

    have = prof.get("skills") or {}
    wanted = [i["name"] for i in items if i["status"] == "have" and i["kind"] == "required"]
    nice = [i["name"] for i in items if i["status"] == "have" and i["kind"] != "required"]
    job_cats = {i.get("category") for i in items}   # after the posting's own skills: the same kinds of skill it asks for
    rest = sorted((s for s in have if s not in wanted and s not in nice and s not in tax.SOFT),
                  key=lambda s: (have[s].get("category") not in job_cats, -(have[s].get("years") or 0), -(have[s].get("mentions") or 0)))
    skills = list(dict.fromkeys(wanted + nice + rest))[:MAX_SKILLS]

    projects = sorted(prof.get("projects") or [], key=lambda p: -_bullet_score(f"{p.get('name', '')}: {p.get('text', '')}", job_skills, evidence, req_words))
    contact = prof.get("contact") or {}
    return {
        "name": contact.get("name") or "",
        "headline": prof.get("headline") or "",
        "contact": [x for x in [contact.get("email"), contact.get("phone"), *(contact.get("links") or [])] if x],
        "summary": prof.get("summary") or "",
        "skills": skills,
        "skills_matched": [s for s in skills if s in set(wanted) | set(nice)],
        "roles": roles,
        "projects": projects[:MAX_PROJECTS],
        "education": [e.get("text") or "" for e in prof.get("education") or []],
        "certifications": list(prof.get("certifications") or []),
        "for_job": {"title": job.get("title") or "", "company": job.get("company") or ""},
        "notes": {
            "missing_required": [i["name"] for i in items if i["status"] == "missing" and i["kind"] == "required"][:6],
            "bullets_left_out": left_out,
            "how": "Reordered and selected from your own resume. Nothing reworded or added.",
        },
    }


def to_markdown(r: dict) -> str:
    out = [f"# {r['name']}".rstrip(), r["headline"], " · ".join(r["contact"]), ""]
    if r["summary"]:
        out += ["## Summary", r["summary"], ""]
    if r["skills"]:
        out += ["## Skills", ", ".join(r["skills"]), ""]
    if r["roles"]:
        out.append("## Experience")
        for role in r["roles"]:
            out += [f"### {role['title']} · {role['company']}".rstrip(" ·"), role["dates"]] + [f"- {b}" for b in role["bullets"]] + [""]
    if r["projects"]:
        out.append("## Projects")
        out += [f"- **{p.get('name', '')}**: {p.get('text', '')}" for p in r["projects"]] + [""]
    if r["education"]:
        out += ["## Education"] + [f"- {e}" for e in r["education"]] + [""]
    if r["certifications"]:
        out += ["## Certifications"] + [f"- {c}" for c in r["certifications"]] + [""]
    return "\n".join(x for x in out if x is not None).strip() + "\n"


def to_text(r: dict) -> str:
    """Plain text: no markup, section names in capitals, '-' bullets. What ATS form parsers handle best."""
    md = to_markdown(r)
    md = re.sub(r"^#{1,3} (.+)$", lambda m: m.group(1).upper() if m.group(0).startswith("## ") else m.group(1), md, flags=re.M)
    return md.replace("**", "")
