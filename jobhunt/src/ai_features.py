"""
ai_features.py — the "AI" layer, built so every feature works WITHOUT a language model and gets better with one.

Each feature has a deterministic baseline (rules over your resume, the posting and your history) and an optional
LLM pass (`use_llm=True`) through whichever provider you configured (Ollama stays local; Claude / API send the text
you give them). LLM output is validated against your resume: rewrites may not add tools, numbers or claims that the
source bullet did not contain, or they are discarded and the deterministic version is used.

    posting_summary   TL;DR of a posting, red flags, green flags, questions to ask
    rewrite_bullets   your best bullets, re-worded for this posting (truthful by construction)
    interview_feedback  score a practice answer (STAR structure, specificity, numbers, filler)
    outreach          follow-up / thank-you / recruiter intro / referral drafts
    similar_jobs / recommendations   "more like this" and "because you starred X" (BM25, no LLM)
    resume_review     what is weak in the resume itself (verbs, numbers, buzzwords, gaps, unused skills)
    ask               natural-language search -> ledger filters
    roadmap           a learning plan for one missing skill
"""

from __future__ import annotations

import json
import re
from datetime import date

from src import matching, retrieval
from src import skills_taxonomy as tax

STRONG_VERBS = {
    "built", "developed", "designed", "led", "created", "automated", "deployed", "delivered", "engineered", "reduced", "increased",
    "launched", "migrated", "implemented", "architected", "owned", "drove", "improved", "cut", "saved", "streamlined", "introduced",
    "integrated", "scaled", "optimized", "optimised", "wrote", "shipped", "recovered", "consolidated", "managed", "mentored", "negotiated",
}
WEAK_STARTS = ("responsible for", "worked on", "helped", "assisted", "involved in", "duties included", "tasked with", "participated in", "worked with")
BUZZ = ("team player", "hard-working", "hardworking", "results-driven", "go-getter", "synergy", "self-motivated", "detail-oriented",
        "dynamic", "passionate", "think outside the box", "proven track record", "excellent communication skills")


# ---------------------------------------------------------------------------
# LLM plumbing
# ---------------------------------------------------------------------------

def llm_status() -> dict:
    """Which providers exist and what would leave your machine if you use them."""
    try:
        from src import llm
        d = llm.describe()
    except Exception:  # noqa: BLE001
        d = {}
    avail = {k: bool(v.get("available")) for k, v in d.items() if k != "template"}
    return {"providers": avail, "any": any(avail.values()),
            "privacy": {"ollama": "stays on this machine", "claude_code": "sent to Anthropic via the Claude Code CLI",
                        "anthropic": "sent to the Anthropic API"}}


def _ask_llm(system: str, user: str, cfg: dict | None = None) -> tuple[str | None, str]:
    try:
        from src import llm
        text, backend = llm.generate(system, user, cfg or {})
        return text, backend
    except Exception as exc:  # noqa: BLE001  (LLMUnavailable, timeouts…)
        return None, f"unavailable: {str(exc)[:80]}"


def _json_from(text: str | None):
    if not text:
        return None
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def _nums(s: str) -> set[str]:
    return set(re.findall(r"\d[\d,.]*%?", s or ""))


def grounded(original: str, rewritten: str) -> bool:
    """A rewrite may not introduce numbers or tools the original bullet did not contain."""
    if not _nums(rewritten) <= _nums(original):
        return False
    return set(tax.find_skills(rewritten)) <= set(tax.find_skills(original))


def _lead(m: dict, k: int = 3) -> list[dict]:
    """Resume bullets closest to what the posting asks: the tailoring picks, else the best evidence at any strength."""
    lead = list(m["tailoring"]["lead_with"])[:k]
    seen = {x["bullet"] for x in lead}
    for r in sorted(m.get("requirements") or [], key=lambda r: -r["score"]):
        e = r.get("evidence")
        if len(lead) >= k:
            break
        if e and r["score"] >= 0.2 and e["section"] in ("experience", "projects") and e["text"] not in seen:
            seen.add(e["text"])
            lead.append({"requirement": r["text"][:140], "bullet": e["text"], "where": e["label"]})
    return lead


def _ctx():
    return matching.current_context()


# ---------------------------------------------------------------------------
# posting summary + red flags
# ---------------------------------------------------------------------------

RED = [
    (r"\b(rockstar|ninja|guru|wizard|superhero)\b", 1, "Buzzword job title or copy", "Often a sign of vague scope or a chaotic team."),
    (r"wear (?:many|multiple|several) hats", 2, "“Wear many hats”", "Scope is unclear; you may be covering several jobs."),
    (r"fast[- ]paced|high[- ]pressure|work hard,? play hard", 1, "High-pressure language", "Ask about workload, hours and turnover."),
    (r"unlimited (?:pto|vacation|leave|time off)", 1, "“Unlimited PTO”", "Usually means little time off is actually taken."),
    (r"\b24/7\b|on[- ]call|weekends?\b|nights? (?:and|&) weekends", 2, "Out-of-hours expectations", "Clarify on-call rotation and compensation."),
    (r"commission[- ]only|unpaid|volunteer|equity only|no base salary", 3, "Unpaid or commission-only", "Not a salaried role."),
    (r"other duties as assigned|and any other|various tasks", 1, "Open-ended duties", "Scope can grow beyond the title."),
    (r"we(?:'re| are) (?:like )?a family", 1, "“We're a family”", "Can signal blurred boundaries."),
    (r"competitive salary|attractive (?:salary|package|remuneration)", 1, "Pay not stated", "“Competitive” hides the number; ask for the range first."),
    (r"must (?:be able to )?(?:start|join) immediately|immediate(?:ly)? (?:start|available)", 1, "Urgent start", "Sometimes a backfill or a rushed hire."),
]
GREEN = [
    (r"worldwide|anywhere in the world|work from anywhere", "Open to candidates worldwide"),
    (r"employer of record|\bdeel\b|remote\.com|\boyster\b|contractors? (?:welcome|ok|are welcome)", "Contractors / employer of record welcome"),
    (r"visa sponsorship|relocation (?:assistance|support|package)", "Sponsorship or relocation support mentioned"),
    (r"health insurance|medical (?:plan|insurance|benefits)|pension|nis\b", "Benefits mentioned"),
    (r"professional development|training budget|learning budget|tuition", "Learning budget / training"),
    (r"salary range|compensation range|\$\d[\d,]*\s*[-–]\s*\$?\d", "Pay range stated"),
]


def red_flags(job: dict) -> list[dict]:
    low = f"{job.get('title', '')}\n{job.get('description', '')}".lower()
    a = matching.analyze_job(job)
    out = []
    for rx, sev, name, why in RED:
        if re.search(rx, low):
            if name == "Pay not stated" and a["pay"]:
                continue
            out.append({"flag": name, "why": why, "severity": sev})
    if a["min_years"] and a["min_years"] >= 8 and a["level"] <= 1.0:
        out.append({"flag": "Years asked don't match the level", "why": f"Asks for {a['min_years']}+ years but the title reads mid-level.", "severity": 2})
    if a["entry"] and a["min_years"] and a["min_years"] >= 3:
        out.append({"flag": "“Entry level” that asks for experience", "why": f"Says entry-level but asks for {a['min_years']}+ years.", "severity": 2})
    if (job.get("company") or "").lower() in ("confidential", "employer confidential", "unknown", ""):
        out.append({"flag": "Employer not named", "why": "You can't research the company before applying.", "severity": 1})
    try:
        age = (date.today() - date.fromisoformat((job.get("posted_at") or "")[:10])).days
        if age > 45:
            out.append({"flag": "Old posting", "why": f"Posted {age} days ago; it may already be filled.", "severity": 1})
    except ValueError:
        pass
    if not a["pay"] and not any(f["flag"] == "Pay not stated" for f in out):
        out.append({"flag": "Pay not stated", "why": "Ask for the range before investing in an application.", "severity": 1})
    return sorted(out, key=lambda f: -f["severity"])


def posting_summary(job: dict, use_llm: bool = False, cfg: dict | None = None) -> dict:
    a = matching.analyze_job(job)
    low = f"{job.get('title', '')}\n{job.get('description', '')}".lower()
    ctx = _ctx()
    ev = matching.evaluate(dict(job), ctx) if ctx else None
    must = [n for n, m in a["skills"].items() if m["kind"] == "required" and n not in tax.SOFT][:8]
    nice = [n for n, m in a["skills"].items() if m["kind"] == "nice"][:6]
    duties = [u for s, u in matching._units(job.get("description") or "") if s == "duty"][:5]
    greens = [g for rx, g in GREEN if re.search(rx, low)]
    where = ("local, " + (job.get("region") or "Trinidad & Tobago")) if job.get("region") else (a["work_mode"] + (f", {a['remote_scope'].replace('_', ' ')}" if a["remote_scope"] else ""))
    pay = a["pay"]
    parts = [f"{job.get('title', 'This role')} at {job.get('company') or 'an unnamed employer'} ({where})."]
    if must:
        parts.append("Wants " + ", ".join(must[:4]) + (f" and {a['min_years']}+ years' experience" if a["min_years"] else "") + ".")
    parts.append(f"Pay: TT${pay['monthly_ttd_min']:,}–{pay['monthly_ttd_max']:,}/mo." if pay else "Pay is not stated.")
    if ev:
        parts.append(f"For you: fit {ev['fit']}, odds {ev['verdict'].lower()} (~{ev['interview_chance']}% interview)" + (f", blocked: {ev['blockers'][0]}" if ev["blockers"] else "") + ".")
    asks = ["What would success look like in the first 90 days?"]
    if not pay:
        asks.append("What is the salary range for this role?")
    if a["work_mode"] == "remote" and a["remote_scope"] in ("unknown", ""):
        asks.append("Which countries can you hire in, and can you contract with someone in Trinidad & Tobago?")
    if ev and ev["skills"]["missing_required"]:
        asks.append(f"How much weight do you put on {ev['skills']['missing_required'][0]} versus adjacent experience?")
    asks.append("How big is the team, and who would I report to?")
    out = {"tldr": " ".join(parts), "must_have": must, "nice_to_have": nice, "responsibilities": duties, "red_flags": red_flags(job),
           "green_flags": greens, "questions_to_ask": asks[:5], "provider": "rules"}
    if use_llm:
        text, backend = _ask_llm("You summarise job postings for a candidate. Use ONLY the facts given. Two sentences, plain words, no hype.",
                                 "Facts:\n" + out["tldr"] + "\nRed flags: " + "; ".join(f["flag"] for f in out["red_flags"][:4]), cfg)
        if text and len(text) > 40:
            out.update(tldr=text.strip(), provider=backend)
        else:
            out["provider_note"] = backend
    return out


# ---------------------------------------------------------------------------
# rewrite bullets
# ---------------------------------------------------------------------------

def _strengthen(b: str) -> str:
    low = b.lower()
    for w in WEAK_STARTS:
        if low.startswith(w):
            rest = b[len(w):].lstrip()
            return "Delivered " + rest[0].lower() + rest[1:] if rest else b
    return b


def rewrite_bullets(job: dict, use_llm: bool = False, cfg: dict | None = None, limit: int = 3) -> dict:
    ctx = _ctx()
    if not ctx:
        return {"error": "add a resume first", "bullets": []}
    m = matching.evaluate(dict(job), ctx, deep=True)
    wanted = {i["name"] for i in m["skills"]["items"] if i["status"] == "have"}
    src = _lead(m, limit)
    out = []
    for item in src:
        b = item["bullet"]
        have_in = sorted(set(tax.find_skills(b)) & wanted)
        tips = []
        if not _nums(b):
            tips.append("Add a number (users, hours saved, revenue) if you have one.")
        if have_in:
            tips.append("Keep these terms visible, the posting uses them: " + ", ".join(have_in[:4]) + ".")
        det = _strengthen(b)
        rec = {"original": b, "where": item["where"], "requirement": item["requirement"], "rewrite": det, "method": "rules", "tips": tips, "keywords": have_in}
        out.append(rec)
    used = "rules"
    if use_llm and out:
        text, backend = _ask_llm(
            "You rewrite resume bullets. For EACH input bullet return a rewrite of at most 28 words that leads with the strongest verb and uses the "
            "posting's wording ONLY where the bullet already supports it. Never add tools, numbers, employers or claims not in the bullet. "
            "Return only a JSON list of strings, same order.",
            "Posting title: " + (job.get("title") or "") + "\nPosting keywords: " + ", ".join(sorted(wanted)[:12]) + "\nBullets:\n" +
            "\n".join(f"{i + 1}. {r['original']}" for i, r in enumerate(out)), cfg)
        arr = _json_from(text)
        if isinstance(arr, list) and len(arr) == len(out):
            for rec, new in zip(out, arr):
                new = str(new).strip()
                if new and grounded(rec["original"], new):
                    rec.update(rewrite=new, method=backend)
                    used = backend
                else:
                    rec["tips"].append("The AI rewrite was rejected because it added something not in your bullet.")
        else:
            used = f"rules ({backend})"
    return {"bullets": out, "provider": used, "job": job.get("title", "")}


# ---------------------------------------------------------------------------
# interview practice feedback
# ---------------------------------------------------------------------------

_STAR = {
    "situation": r"\b(when|at (?:my|the|a)|we had|the team|the company|our|during|in \d{4}|last (?:year|quarter)|project|client)\b",
    "task": r"\b(responsible|goal|needed to|had to|my role|asked to|objective|challenge|problem|deadline)\b",
    "action": r"\bI (?:" + "|".join(sorted(STRONG_VERBS | {"decided", "proposed", "ran", "set up", "worked", "started", "found", "wrote", "tested", "talked", "chose"})) + r")\b",
    "result": r"(\d[\d,.]*\s*(?:%|hours?|days?|users|customers|clients|policies|k\b|x\b)|resulted|reduced|increased|saved|improved|launched|delivered|adopted|so that|which meant)",
}
FILLER = re.compile(r"\b(kind of|sort of|basically|actually|i guess|i think|maybe|um+|uh+|you know|stuff|things like that)\b", re.I)


def interview_feedback(job: dict, question: str, answer: str, use_llm: bool = False, cfg: dict | None = None) -> dict:
    answer = (answer or "").strip()
    if len(answer.split()) < 8:
        return {"error": "write at least a couple of sentences to get feedback"}
    words = answer.split()
    low = answer.lower()
    star = {k: bool(re.search(rx, answer, re.I)) for k, rx in _STAR.items()}
    first_i, first_we = len(re.findall(r"\bI\b", answer)), len(re.findall(r"\bwe\b", low))
    skills = list(tax.find_skills(answer))
    has_nums = bool(_nums(answer))
    filler = FILLER.findall(answer)
    length_ok = 70 <= len(words) <= 260
    score = (sum(star.values()) * 14 + (12 if has_nums else 0) + (10 if skills else 0) + (10 if first_i >= max(2, first_we) else 4)
             + (10 if length_ok else 3) - min(12, len(filler) * 3))
    score = max(0, min(100, round(score)))
    tips = []
    if not star["situation"]:
        tips.append("Set the scene in one sentence: where, when, what was at stake.")
    if not star["task"]:
        tips.append("Say what YOU were responsible for, not only what the team did.")
    if not star["action"]:
        tips.append("Describe your own actions with “I built / I decided / I wrote…” so the interviewer can tell your part.")
    if not star["result"] or not has_nums:
        tips.append("End with a result and a number: time saved, users, money, errors avoided.")
    if first_we > first_i * 2:
        tips.append("Too much “we”. Make your individual contribution explicit.")
    if filler:
        tips.append("Cut hedging and filler: " + ", ".join(sorted({f.lower() for f in filler})[:4]) + ".")
    if len(words) < 70:
        tips.append("A little short. Aim for 90–200 words (about a minute).")
    if len(words) > 260:
        tips.append("Too long. Trim to the most relevant story; you can offer more if asked.")
    ctx = _ctx()
    if ctx and job:
        m = matching.evaluate(dict(job), ctx)
        asked = [i["name"] for i in m["skills"]["items"] if i["kind"] == "required" and i["status"] == "have" and i["name"] not in tax.SOFT][:4]
        missing_terms = [s for s in asked if s not in skills]
        if missing_terms:
            tips.append("You could name the skills the posting cares about that you actually used: " + ", ".join(missing_terms) + ".")
    verdict = "Strong" if score >= 75 else "Solid, tighten it" if score >= 55 else "Needs structure"
    out = {"score": score, "star": star, "words": len(words), "numbers": has_nums, "skills_named": skills[:8], "tips": tips[:6],
           "verdict": verdict, "provider": "rules"}
    if use_llm:
        text, backend = _ask_llm("You are an interview coach. Give three short, specific improvements to this answer. Do not invent facts. Plain words.",
                                 f"Question: {question}\nAnswer: {answer}", cfg)
        if text:
            out.update(coach=text.strip(), provider=backend)
    # what a voice interviewer would say back — plain text; actual speech synthesis (optional, needs Kokoro) is src.voice.synthesize()
    speak_tip = re.sub(r"^[A-Za-z ,]+: ", "", tips[0]) if tips else ""
    out["speech"] = f"You scored {score} out of 100. {verdict}." + (f" The main thing to work on: {speak_tip}" if speak_tip else " Nicely done.")
    return out


# ---------------------------------------------------------------------------
# outreach drafts
# ---------------------------------------------------------------------------

def outreach(job: dict, kind: str = "follow_up", use_llm: bool = False, cfg: dict | None = None) -> dict:
    ctx = _ctx()
    cand = {}
    try:
        from src import config
        cand = (config.load_profile().get("candidate") or {})
    except Exception:  # noqa: BLE001
        pass
    name = cand.get("name") or "Your Name"
    title, company = job.get("title") or "the role", job.get("company") or "your team"
    bullet = ""
    if ctx:
        lw = _lead(matching.evaluate(dict(job), ctx, deep=True), 1)
        if lw:
            bullet = lw[0]["bullet"].rstrip(".")
            if re.match(r"^(built|developed|designed|led|created|automated|deployed|delivered|engineered)\b", bullet, re.I):
                bullet = "I " + bullet[0].lower() + bullet[1:]
    kinds = {
        "follow_up": ("Following up: " + title,
                      f"Hello,\n\nI applied for the {title} role at {company} and wanted to follow up. "
                      + (f"The closest thing I've done to what you describe: {bullet}. " if bullet else "")
                      + "I'd be glad to answer any questions or send more detail.\n\nThank you,\n" + name),
        "thank_you": ("Thank you: " + title,
                      f"Hello,\n\nThank you for taking the time to talk about the {title} role at {company}. "
                      "I enjoyed learning more about the team's priorities. "
                      + (f"One point I wanted to add: {bullet}. " if bullet else "")
                      + "I'm still very interested and happy to provide anything else you need.\n\nThank you,\n" + name),
        "recruiter_intro": ("Interested in " + title,
                            f"Hello,\n\nI saw the {title} opening at {company} and it lines up with my background. "
                            + (f"For example, {bullet}. " if bullet else "")
                            + "I've attached my resume. Could we set up a short call this week?\n\nBest,\n" + name),
        "referral": ("Quick question about " + company,
                     f"Hi,\n\nI'm applying for the {title} role at {company} and noticed you work there. "
                     + (f"I think I'm a good match: {bullet}. " if bullet else "")
                     + "Would you be open to referring me, or telling me what the team is like? Happy to send my resume.\n\nThanks,\n" + name),
    }
    if kind not in kinds:
        return {"error": f"kind must be one of {', '.join(kinds)}"}
    subject, body = kinds[kind]
    out = {"kind": kind, "subject": subject, "body": body, "provider": "template"}
    if use_llm:
        text, backend = _ask_llm("Polish this short message. Keep every fact, add none. Plain, warm, under 110 words. No hype words. No em dashes.", body, cfg)
        if text and grounded(body, text) and len(text.split()) < 160:
            out.update(body=re.sub(r"\s*[—–]\s*", ", ", text.strip()), provider=backend)
        else:
            out["provider_note"] = "AI version discarded (it added facts or was unavailable)" if text else backend
    return out


# ---------------------------------------------------------------------------
# similar jobs & recommendations (BM25 over postings, no LLM)
# ---------------------------------------------------------------------------

def _doc(j: dict) -> str:
    return f"{j.get('title') or ''} {j.get('title') or ''} {j.get('title') or ''} {j.get('company') or ''} {(j.get('description') or '')[:1800]}"


def similar_jobs(target: dict, corpus: list[dict], k: int = 6) -> list[dict]:
    """Postings most like `target` (excluding itself). Each result lists the skills they share."""
    pool = [j for j in corpus if j.get("job_id") != target.get("job_id")]
    if not pool:
        return []
    idx = retrieval.BM25([_doc(j) for j in pool])
    sc = idx.score(_doc(target))
    tskills = set(tax.find_skills(_doc(target)))
    best = max(sc) or 1.0
    ranked = sorted(range(len(pool)), key=lambda i: -sc[i])[:k]
    return [{"job_id": pool[i]["job_id"], "title": pool[i].get("title", ""), "company": pool[i].get("company", ""), "score": round(sc[i] / best, 2),
             "shared": sorted(tskills & set(tax.find_skills(_doc(pool[i]))))[:5], "fit": pool[i].get("fit_score")} for i in ranked if sc[i] > 0]


def recommendations(corpus: list[dict], liked: list[dict], k: int = 8) -> list[dict]:
    """Untouched postings closest to the ones you starred / applied to / interviewed for."""
    if not liked:
        return []
    liked_ids = {j["job_id"] for j in liked}
    pool = [j for j in corpus if j["job_id"] not in liked_ids and (j.get("app_status") or "New") == "New" and not j.get("blocked")]
    if not pool:
        return []
    idx = retrieval.BM25([_doc(j) for j in pool])
    scores = [0.0] * len(pool)
    why = [""] * len(pool)
    for src in liked:
        s = idx.score(_doc(src))
        top = max(s) or 1.0
        for i, v in enumerate(s):
            if v / top > scores[i]:
                scores[i], why[i] = v / top, src.get("title", "")
    ranked = sorted(range(len(pool)), key=lambda i: -(scores[i] * 60 + (pool[i].get("fit_score") or 0) * 0.4))[:k]
    return [{"job_id": pool[i]["job_id"], "title": pool[i].get("title", ""), "company": pool[i].get("company", ""), "similarity": round(scores[i], 2),
             "because": why[i], "fit": pool[i].get("fit_score")} for i in ranked if scores[i] > 0.15]


# ---------------------------------------------------------------------------
# resume review
# ---------------------------------------------------------------------------

def resume_review(profile: dict | None = None, text: str | None = None) -> dict:
    from src import profile_store
    profile = profile or profile_store.active_profile()
    if not profile:
        return {"error": "add a resume first"}
    if text is None:
        text = profile_store.get_resume_text(profile["_resume_id"]) if profile.get("_resume_id") else ""
    bullets = [b for r in profile.get("roles", []) for b in r.get("bullets", [])]
    issues, wins = [], []

    def add(sev, title, detail, examples=None):
        issues.append({"severity": sev, "title": title, "detail": detail, "examples": (examples or [])[:3]})

    n = len(bullets)
    weak = [b for b in bullets if b.lower().startswith(WEAK_STARTS)]
    strong = [b for b in bullets if (b.split() or [""])[0].lower().strip(",.") in STRONG_VERBS]
    nonum = [b for b in bullets if not _nums(b)]
    long_b = [b for b in bullets if len(b.split()) > 38]
    if n < 4:
        add(3, "Very few achievements", f"Only {n} bullet points were found under your roles. Recruiters and ATS scans look for 3–6 per role.")
    if weak:
        add(2, "Weak openers", f"{len(weak)} bullet(s) start with phrases like “responsible for” or “worked on”. Lead with what you did.", weak)
    if n and len(nonum) / n > 0.5:
        add(2, "Few numbers", f"{len(nonum)} of {n} bullets have no number. Add scale or results (users, hours saved, revenue, records).", nonum)
    if long_b:
        add(1, "Long bullets", f"{len(long_b)} bullet(s) run past ~38 words. Split or trim to the result.", long_b)
    buzz = [w for w in BUZZ if w in (text or "").lower()]
    if buzz:
        add(1, "Buzzwords", "Empty phrases weaken the resume: " + ", ".join(buzz) + ". Replace them with evidence.")
    words = len((text or "").split())
    if words and words < 300:
        add(2, "Very short", f"About {words} words. Add detail on your most relevant projects.")
    elif words > 1100:
        add(1, "Long", f"About {words} words. Aim for one or two pages; keep the strongest roles detailed.")
    if not profile.get("summary"):
        add(1, "No summary", "A two-line summary that names your target role and your best proof helps both people and ATS.")
    if not profile.get("education"):
        add(1, "No education found", "Add an Education section (even if it is short) so parsers pick it up.")
    if not (profile.get("contact") or {}).get("email"):
        add(2, "No email found in the header", "Put your email and phone at the top in plain text.")
    listed_only = [s for s, m in profile.get("skills", {}).items() if m.get("in_skills_section") and not m.get("years") and m.get("source") != "manual"]
    if len(listed_only) >= 4:
        add(1, "Skills listed but never shown", "These appear in your Skills list but in no role bullet: " + ", ".join(sorted(listed_only)[:8]) + ". Show each in a bullet or drop it.")
    roles = sorted((r for r in profile.get("roles", []) if r.get("start")), key=lambda r: r["start"])
    for a, b in zip(roles, roles[1:]):
        if a.get("end") and b.get("start") and a["end"] < b["start"]:
            ay, am = map(int, a["end"].split("-"))
            by, bm = map(int, b["start"].split("-"))
            if (by * 12 + bm) - (ay * 12 + am) > 6:
                add(1, "Gap between roles", f"A gap of about {(by * 12 + bm) - (ay * 12 + am)} months between {a.get('company') or 'one role'} and {b.get('company') or 'the next'}: add a line explaining it.")
    if strong and n and len(strong) / n >= 0.6:
        wins.append("Most bullets open with a strong action verb.")
    if n and len(nonum) / n <= 0.4:
        wins.append("Good use of numbers and scale.")
    if len(profile.get("skills", {})) >= 15:
        wins.append(f"{len(profile['skills'])} recognisable skills, which gives matching plenty to work with.")
    if profile.get("years_experience", 0) >= 3 and not weak:
        wins.append("No weak “responsible for” openers.")
    score = max(0, 100 - sum({3: 22, 2: 12, 1: 5}[i["severity"]] for i in issues))
    return {"score": score, "verdict": "Strong" if score >= 80 else "Good, a few fixes" if score >= 60 else "Needs work",
            "issues": sorted(issues, key=lambda i: -i["severity"]), "wins": wins, "stats": {"bullets": n, "with_numbers": n - len(nonum), "words": words}}


# ---------------------------------------------------------------------------
# natural-language search
# ---------------------------------------------------------------------------

_REGION_WORDS = {"port of spain": "Port of Spain", "pos": "Port of Spain", "chaguanas": "Chaguanas / Caroni", "san fernando": "San Fernando", "couva": "Couva / Point Lisas",
                 "point lisas": "Couva / Point Lisas", "arima": "Arima / Sangre Grande", "sangre grande": "Arima / Sangre Grande", "tobago": "Tobago",
                 "san juan": "San Juan / Laventille", "tunapuna": "Tunapuna / Piarco", "piarco": "Tunapuna / Piarco", "princes town": "Princes Town / Rio Claro", "penal": "Penal / Debe / Siparia"}
_CAT_WORDS = {"finance": "Finance & Accounting", "accounting": "Finance & Accounting", "tech": "Technology", "technology": "Technology", "software": "Technology",
              "engineering": "Engineering & Technical", "healthcare": "Healthcare", "medical": "Healthcare", "sales": "Sales & Marketing", "marketing": "Sales & Marketing",
              "hr": "Human Resources", "customer": "Customer Service", "legal": "Legal & Compliance", "admin": "Admin & Clerical", "logistics": "Logistics & Supply Chain", "hospitality": "Hospitality & Tourism",
              "education": "Education & Training", "government": "Public Sector", "management": "Management"}
_STOP = set("a an the and or in for with of to at on roles role jobs job that are is me my show find list get all any some please".split())


def ask(query: str) -> dict:
    """Turn a plain-English request into Ledger filters. Rule-based (no model), so it is instant and predictable."""
    q = (query or "").strip()
    if not q:
        return {"error": "type what you're looking for"}
    low = " " + q.lower() + " "
    params: dict = {}
    said: list[str] = []
    used: list[str] = []

    def take(pattern: str) -> bool:
        m = re.search(pattern, low)
        if m:
            used.append(m.group(0).strip())
        return bool(m)

    if take(r"\b(?:in )?(?:trinidad|t&t|tt|local|locally|in tobago)\b") or any(k in low for k in _REGION_WORDS):
        params["mode"] = "local"; said.append("local roles")
    if take(r"\bremote\b|\bwork from home\b|\bwfh\b"):
        params["mode"] = "remote"; said.append("remote roles")
    if take(r"\b(?:abroad|overseas|relocat\w*|on-?site abroad)\b"):
        params["mode"] = "abroad"; said.append("on-site abroad")
    for k, v in sorted(_REGION_WORDS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(k)}\b", low):
            params["region"] = v; params["mode"] = "local"; said.append(f"in {v}"); used += k.split()
            break
    for k, v in _CAT_WORDS.items():
        if re.search(rf"\b{re.escape(k)}\b", low):
            params["category"] = v; said.append(v); used.append(k)
            break
    if take(r"\b(?:worth applying|best odds|high odds|good odds|best chance|likely|strong match|top matches?|best)\b"):
        params["sort"] = "likelihood"; params["odds"] = "40"; said.append("decent odds or better, best first")
    if take(r"\b(?:new|today|latest|this week|recent|fresh)\b"):
        params["sort"] = params.get("sort", "new"); said.append("newest first")
    if take(r"\b(?:closing|urgent|deadline|expiring|last chance|about to close|soon)\b"):
        params["closing"] = "1"; params["sort"] = "closing"; said.append("closing within 7 days")
    if take(r"\b(?:starred|favou?rites?|saved)\b"):
        params["starred"] = "1"; said.append("starred")
    m = re.search(r"\b(applied|interviewing|shortlisted|rejected)\b", low)
    if m:
        params["status"] = m.group(1).capitalize(); said.append(f"status {m.group(1)}"); used.append(m.group(1))
    skills = list(tax.find_skills(q))
    words = [w for w in re.findall(r"[a-z0-9+#.]+", low) if w not in _STOP and w not in used and w not in ("worth", "applying", "odds", "closing", "new", "roles")]
    text = " ".join(skills) if skills else " ".join(words[:4])
    if text:
        params["q"] = text; said.append(f"matching “{text}”")
    if not params:
        params["q"] = q
        said.append(f"matching “{q}”")
    return {"params": params, "explain": "Showing " + ", ".join(said) + ".", "query": q}


# ---------------------------------------------------------------------------
# skill roadmap
# ---------------------------------------------------------------------------

_PLAN = {
    "Languages": ["Do a focused crash course on the syntax and idioms (one week of daily practice).", "Port a small script you already wrote into {skill}.", "Read the standard library docs for the modules the postings mention."],
    "Web & Backend": ["Complete the official tutorial end to end.", "Rebuild one small service you already run using {skill}.", "Add tests and a README, then deploy it somewhere public."],
    "Data & Databases": ["Install it locally and model a dataset you already know.", "Write the ten queries / transformations the postings mention most.", "Benchmark or explain one design choice you made."],
    "AI & ML": ["Build the smallest end-to-end demo (data → model/prompt → evaluation).", "Add an evaluation step: a small labelled set and a metric.", "Write up what worked and what didn't."],
    "Cloud & DevOps": ["Use the free tier to deploy something real.", "Automate the deploy (CI/CD) and add monitoring or logs.", "Document the setup so someone else could repeat it."],
    "Automation & Tools": ["Automate one real task you do weekly.", "Add error handling and a run log.", "Screenshot or record the result for your portfolio."],
    "Insurance & Finance": ["Read two industry primers and learn the vocabulary the postings use.", "Map one process you know to the terms in the postings.", "Add a bullet showing the domain experience you do have."],
    "Engineering practice": ["Pick one real project and apply the practice properly (write it up as you go).", "Add it to your resume as a result, not a tool name.", "Prepare a two-minute explanation for interviews."],
}


def roadmap(skill: str, demand: dict | None = None, use_llm: bool = False, cfg: dict | None = None) -> dict:
    canon = next((k for k in tax.TAXONOMY if k.lower() == (skill or "").lower()), None)
    if not canon:
        return {"error": f"“{skill}” is not a skill I recognise"}
    cat = tax.CATEGORY.get(canon, "Engineering practice")
    ctx = _ctx()
    have = set((ctx or {}).get("skills", {}))
    near = sorted(tax.related(canon) & have)
    steps = [s.format(skill=canon) for s in _PLAN.get(cat, _PLAN["Engineering practice"])]
    if near:
        steps.insert(0, f"You already know {', '.join(near[:3])}, which shortens the ramp: focus on how {canon} differs.")
    pair = sorted(have & set(tax.related(canon) | {"Python", "Django", "PostgreSQL", "Docker"}))[:3]
    idea = f"Build a small project that uses {canon}" + (f" together with {', '.join(pair)}" if pair else "") + " and solves a problem from your own work."
    out = {"skill": canon, "category": cat, "why": ("Asked for by " + f"{demand['jobs']} of your listings" + (f", and the only gap in {demand['sole_gap']}" if demand.get("sole_gap") else "") + ".") if demand else "",
           "steps": steps, "project": idea, "weeks": 2 if near else 3,
           "resume_line": f"Built [what] with {canon}, [scale/result]. (Write this only after you have really done it.)", "close_the_gap": near, "provider": "rules"}
    if use_llm:
        text, backend = _ask_llm("You are a practical career coach. Give a 4-step, 2-3 week learning plan with one portfolio project. Plain words, no hype.",
                                 f"Skill: {canon}. Learner already knows: {', '.join(sorted(have)[:12])}.", cfg)
        if text and len(text) > 80:
            out.update(plan_text=text.strip(), provider=backend)
    return out
