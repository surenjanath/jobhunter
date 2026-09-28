"""
ats.py — how well YOUR resume text would pass an applicant-tracking scan for THIS posting.

Deterministic, no LLM. Keywords come from the posting (required skills first) and are looked for in the real text of your
active resume; format checks run on that same text (contact details, sections, dates, bullets, length).
Returns: score, verdict, breakdown{keywords,format,length,title}, must_have, have, missing, nice_to_have, advice, words, checks.
"""

from __future__ import annotations

import re

from src import matching
from src import skills_taxonomy as tax


def _format_checks(text: str) -> list[dict]:
    low = text.lower()
    checks = [
        ("Email address", bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)), "Add an email address in the header"),
        ("Phone number", bool(re.search(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", text)), "Add a phone number in the header"),
        ("Experience section", bool(re.search(r"^\W*(work |professional )?(experience|employment|work history)", low, re.M)), "Use a plain 'Experience' heading — ATS parsers look for it"),
        ("Skills section", bool(re.search(r"^\W*(technical )?skills", low, re.M)), "Add a 'Skills' section listing tools by name"),
        ("Education section", bool(re.search(r"^\W*education", low, re.M)), "Add an 'Education' heading"),
        ("Dated roles", bool(re.search(r"(19|20)\d{2}\s*[-–—]\s*((19|20)\d{2}|present|current)", low)), "Write role dates as 'Mon YYYY – Mon YYYY'"),
        ("Bullet points", len(re.findall(r"^\s*[-•*▪]\s+", text, re.M)) >= 4, "Use bullet points for achievements"),
        ("Numbers / results", len(re.findall(r"\d[\d,.]*\s*(?:\+|%|k\b|hours?|users|clients|policies|customers)", low)) >= 2, "Quantify a few results (users, hours saved, revenue)"),
    ]
    return [{"check": n, "ok": ok, "fix": fix} for n, ok, fix in checks]


def score(job: dict, resume_text: str | None = None) -> dict:
    resume_text = resume_text if resume_text is not None else matching.resume_text()
    a = matching.analyze_job(job)
    resume_skills = set(tax.find_skills(resume_text))
    ctx = matching.current_context()
    if ctx:
        resume_skills |= set(ctx["skills"])          # skills you added by hand count too

    must = [n for n, m in a["skills"].items() if m["kind"] == "required" and n not in tax.SOFT][:12]
    nice = [n for n, m in a["skills"].items() if m["kind"] != "required" and n not in tax.SOFT][:8]
    have = [k for k in must if k in resume_skills]
    missing = [k for k in must if k not in resume_skills]
    # An ATS matches words, not concepts: a related skill does not count as a keyword hit
    keyword_score = round(len(have) / len(must) * 100) if must else 70

    checks = _format_checks(resume_text)
    format_score = round(sum(c["ok"] for c in checks) / len(checks) * 100)
    words = len(resume_text.split())
    length_score = 90 if 450 <= words <= 900 else 75 if 300 <= words <= 1200 else 55
    jt = [w for w in re.findall(r"[a-z]{4,}", (job.get("title") or "").lower()) if w not in ("senior", "junior", "lead", "staff", "engineer", "developer", "manager")]
    core = jt or re.findall(r"[a-z]{4,}", (job.get("title") or "").lower())
    title_hit = [w for w in core if w in resume_text.lower()]
    title_score = round(len(title_hit) / len(core) * 100) if core else 70

    overall = round(keyword_score * 0.45 + format_score * 0.2 + length_score * 0.15 + title_score * 0.2)
    verdict = ("Excellent — will parse cleanly" if overall >= 80 else "Good — minor tailoring helps" if overall >= 65
               else "Fair — tailor your resume for this posting" if overall >= 50 else "Poor — heavy tailoring needed")

    advice = []
    if missing:
        shown = ", ".join(missing[:5])
        if ctx:
            rel = [(m, next((r for r in tax.related(m) if r in resume_skills), None)) for m in missing[:5]]
            adj = [f"{m} (you have {r})" for m, r in rel if r]
            if adj:
                advice.append("Mention only if true — you have related experience: " + "; ".join(adj))
        advice.append(f"Keywords in the posting but not in your resume: {shown}. Add them only where you have genuinely used them.")
    bad = [c["fix"] for c in checks if not c["ok"]]
    advice += bad[:2]
    if words > 1200:
        advice.append("Resume is long for an ATS — aim for 1–2 pages, bullets under two lines")
    if words < 300:
        advice.append("Resume text is very short — an ATS may read little to match against")
    if not advice:
        advice.append("Already well aligned — reorder your top bullets to mirror the posting's first three requirements")

    return {
        "score": overall, "verdict": verdict,
        "breakdown": {"keywords": keyword_score, "format": format_score, "length": length_score, "title": title_score},
        "must_have": must, "have": have, "missing": missing, "nice_to_have": nice, "advice": advice[:4], "words": words, "checks": checks,
    }
