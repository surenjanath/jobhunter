"""
coach.py — everything that turns single mock interviews into actual preparation. Pure functions, no Django:

* voice baseline  — your calm voice, recorded once, so nerves are judged against YOU, not a generic speaker
* story bank      — your best answers as reusable STAR stories, tagged by the skills they prove, and which of a
                    posting's requirements they cover (the gaps are where interviews are lost)
* drills          — spaced repetition for the questions you scored low on
* interview types — recruiter screen, technical, salary negotiation, "questions for them", each with its own scoring
* prep plan       — a day-by-day countdown to a real interview date, plus a research brief from the posting
* inbox           — classify a recruiter email (invite / rejection / offer / assessment) and suggest the pipeline move
* camera          — eye contact / framing / stillness from on-device face tracking numbers (no video leaves the page)
* weekly report   — is the search working, not just busy

Every judgement here is a rule you can read. Where a number is a heuristic, the output says so.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from src import skills_taxonomy as tax

# ---------------------------------------------------------------------------
# voice baseline
# ---------------------------------------------------------------------------

BASELINE_PASSAGE = ("I'd like to tell you a little about how I work. I enjoy taking a messy problem, finding out what really "
                    "matters to the people involved, and building something simple that fixes it. On my last project, that "
                    "meant sitting with the team for a week before writing any code. It paid off: the tool we shipped was "
                    "used every day, and it saved us hours each week.")
BASELINE_KEYS = ("pace_wpm", "pitch_mean_hz", "pitch_stdev_hz", "jitter", "pitch_range_st", "uptalk_ratio", "volume_mean", "pause_ratio")


def baseline_from(voice: dict | None) -> dict | None:
    """Keep what a calm read-aloud tells us about your normal voice. Needs enough signal to be worth trusting."""
    if not voice or (voice.get("duration_sec") or 0) < 10 or not voice.get("pitch_mean_hz"):
        return None
    if (voice.get("pace_wpm") or 0) > 240:   # nobody reads aloud this fast: they stopped before the end of the passage
        return None
    return {k: voice[k] for k in BASELINE_KEYS if voice.get(k) is not None}


def personal_thresholds(baseline: dict | None) -> dict:
    """Composure thresholds, tightened or loosened around your own calm voice. Without a baseline: the generic ones."""
    t = {"jitter": 0.045, "rush_wpm": 180, "narrow_st": 2.0, "raised_pitch": None, "uptalk": 0.4}
    if not baseline:
        return t
    if baseline.get("jitter"):
        t["jitter"] = max(0.03, baseline["jitter"] * 1.6)          # 60% shakier than your calm voice
    if baseline.get("pace_wpm"):
        t["rush_wpm"] = max(150, round(baseline["pace_wpm"] * 1.25))  # a naturally fast talker isn't "rushing" at 170
    if baseline.get("pitch_range_st"):
        t["narrow_st"] = min(2.0, baseline["pitch_range_st"] * 0.6)
    if baseline.get("pitch_mean_hz"):
        t["raised_pitch"] = baseline["pitch_mean_hz"] * 1.12        # ~2 semitones above your normal: a classic stress cue
    if baseline.get("uptalk_ratio") is not None:
        t["uptalk"] = max(0.4, baseline["uptalk_ratio"] + 0.25)     # some people always rise a little; only more than usual counts
    return t


# ---------------------------------------------------------------------------
# story bank
# ---------------------------------------------------------------------------

_STAR = {
    "situation": r"\b(when|at my|in my|while|during|our team|we had|the company|last year|a client|the project)\b",
    "task": r"\b(responsible|goal|needed to|had to|my role|asked to|objective|challenge|problem|deadline)\b",
    "action": r"\bI (?:built|wrote|led|designed|created|automated|decided|proposed|ran|set up|worked|started|found|tested|talked|chose|fixed|migrated|shipped|delivered|reduced|improved)\b",
    "result": r"(\d[\d,.]*\s*(?:%|hours?|days?|weeks?|users|customers|clients|k\b|x\b)|resulted|reduced|increased|saved|improved|launched|delivered|adopted)",
}


def story_from(question: str, answer: str, score: int | None = None) -> dict:
    """A reusable story from an answer: a short title, the skills it proves, STAR coverage."""
    text = (answer or "").strip()
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    title = (first[:80] + "…") if len(first) > 80 else first
    return {"title": title or "Untitled story", "question": question or "", "text": text,
            "skills": sorted(tax.find_skills(text)), "star": {k: bool(re.search(rx, text, re.I)) for k, rx in _STAR.items()},
            "numbers": bool(re.search(r"\d", text)), "score": score}


def story_coverage(requirements: list[dict], skills_needed: list[str], stories: list[dict]) -> dict:
    """requirements: [{text, skills?}], skills_needed: skill names the posting asks for. Which stories back which
    requirement, and which requirements have none — those are the questions you'd be improvising on."""
    by_skill: dict[str, list[dict]] = {}
    for s in stories:
        for sk in s.get("skills") or []:
            by_skill.setdefault(sk.lower(), []).append(s)
    rows = []
    for sk in skills_needed:
        hits = by_skill.get(sk.lower(), [])
        partial = False
        if not hits:   # a story about a closely related skill is partial evidence (RAG work speaks to "LLMs"), and says so
            for rel in sorted(tax.related(sk)):
                hits = by_skill.get(rel.lower(), [])
                if hits:
                    partial = rel
                    break
        rows.append({"skill": sk, "partial": partial, "stories": [{"id": h.get("id"), "title": h["title"], "score": h.get("score")} for h in hits[:3]]})
    for req in requirements:
        words = {w for w in re.findall(r"[a-z]{5,}", (req.get("text") or "").lower())} - {"experience", "years", "strong", "ability", "working", "knowledge"}
        hits = [s for s in stories if len(words & set(re.findall(r"[a-z]{5,}", s["text"].lower()))) >= 2]
        rows.append({"requirement": req["text"][:160], "stories": [{"id": h.get("id"), "title": h["title"], "score": h.get("score")} for h in hits[:3]]})
    covered = sum(1 for r in rows if r["stories"] and not r.get("partial"))
    return {"rows": rows, "covered": covered, "partial": sum(1 for r in rows if r.get("partial") and r["stories"]), "total": len(rows),
            "gaps": [r.get("skill") or r.get("requirement") for r in rows if not r["stories"]]}


# ---------------------------------------------------------------------------
# drills — spaced repetition, deliberately simple: good answers come back later, weak ones tomorrow
# ---------------------------------------------------------------------------

def schedule(interval_days: float, score: int, today: date | None = None) -> dict:
    today = today or date.today()
    if score >= 80:
        nxt = max(3.0, interval_days * 2.5)
    elif score >= 60:
        nxt = max(1.0, interval_days * 1.4)
    else:
        nxt = 1.0
    nxt = min(nxt, 60.0)
    return {"interval_days": round(nxt, 1), "next_due": (today + timedelta(days=round(nxt))).isoformat(),
            "mastered": score >= 80 and nxt >= 20}


# ---------------------------------------------------------------------------
# interview types beyond behavioural
# ---------------------------------------------------------------------------

KINDS = {
    "behavioural": "Behavioural (tell me about a time…)",
    "screen": "Recruiter phone screen",
    "technical": "Technical",
    "negotiation": "Salary negotiation",
    "reverse": "Your questions for them",
}


def typed_questions(kind: str, job: dict, required_skills: list[str], offer: dict | None = None) -> list[dict]:
    company = job.get("company") or "the company"
    title = job.get("title") or "this role"
    if kind == "screen":
        return [{"q": "Thanks for making time. To start, can you give me a quick overview of your background?", "why": "The 60-second pitch"},
                {"q": f"What made you apply for the {title} role at {company}?", "why": "Genuine interest vs mass-applying"},
                {"q": "Why are you looking to leave your current role?", "why": "Screens for negativity and flight risk"},
                {"q": "What are your salary expectations for this role?", "why": "Recruiters check you're in budget early"},
                {"q": "What's your notice period, and when could you start?", "why": "Logistics"}]
    if kind == "technical":
        qs = []
        for sk in required_skills[:4]:
            qs.append({"q": f"How have you used {sk} in practice? Walk me through a decision you made with it and the trade-off involved.",
                       "why": f"Depth in {sk}, not just familiarity"})
        qs.append({"q": "Tell me about the hardest bug you've tracked down. How did you find it?", "why": "Debugging method under pressure"})
        if re.search(r"senior|lead|principal|architect|staff", title, re.I):
            qs.append({"q": f"How would you design a system for {company}'s core product to handle ten times today's load?", "why": "System design at a senior level"})
        return qs
    if kind == "negotiation":
        return [{"q": _offer_line(offer), "why": "The first offer is rarely the best one"},
                {"q": "I hear you. Honestly, that's near the top of our band. What would it take for you to accept today?", "why": "Pressure to close"},
                {"q": "We might have some flexibility on other parts of the package. What matters most to you besides base pay?", "why": "Total compensation"}]
    if kind == "reverse":
        return [{"q": "That's everything from my side. What questions do you have for me?", "why": "Your chance to show you've thought about the job"}]
    return []


_SPOKEN_UNIT = {"TT$/mo": "TT dollars a month", "US$/mo": "US dollars a month", "TT$ a month": "TT dollars a month", "US$ a month": "US dollars a month"}


def _offer_line(offer: dict | None) -> str:
    """Read aloud, so the unit is written the way a person says it ("US dollars a month", not "US$/mo")."""
    if offer and offer.get("amount"):
        offer = {**offer, "unit": _SPOKEN_UNIT.get(offer.get("unit", ""), offer.get("unit") or "a month")}
        return (f"We'd like to make you an offer: {offer['amount']:,} {offer.get('unit', 'per month')}. "
                "How does that sound?")
    return "We'd like to make you an offer at the midpoint of our band for this role. How does that sound?"


def offer_for(benchmark: dict | None, peers: dict | None, local: bool) -> dict:
    """A realistic, slightly-low opening offer to negotiate against: the low end of what's posted, else peers' p25."""
    if benchmark:
        key = "monthly_ttd_min" if local else "monthly_usd_min"
        if benchmark.get(key):
            return {"amount": int(round(benchmark[key], -2)), "unit": "TT$ a month" if local else "US$ a month", "basis": "the low end of the posted range"}
    if peers and peers.get("p25"):
        return {"amount": int(round(peers["p25"], -2)), "unit": peers.get("unit", "a month"), "basis": "what similar roles pay (lower quartile)"}
    return {}


_NEGATIVE = re.compile(r"\b(hate|terrible|toxic|awful|my boss is|incompetent|stupid|bored out of my mind|can't stand)\b", re.I)
_HEDGE = re.compile(r"\b(i guess|i think maybe|kind of|sort of|whatever you think|i'm not sure|if that's ok)\b", re.I)


def kind_feedback(kind: str, question: str, answer: str, job: dict, offer: dict | None = None) -> dict:
    """Content scoring for the non-behavioural kinds. Returns {score, checks: {name: bool}, tips, honest}."""
    a = answer.strip()
    low = a.lower()
    words = a.split()
    nums = re.findall(r"\d[\d,.]*", a)
    checks: dict[str, bool] = {}
    tips: list[str] = []
    if kind == "negotiation":
        amounts = [float(n.replace(",", "")) for n in nums if n.replace(",", "").replace(".", "").isdigit()]
        counter = [x for x in amounts if x >= 100]
        checks["named a number"] = bool(counter)
        checks["anchored above the offer"] = bool(counter and offer and offer.get("amount") and max(counter) > offer["amount"])
        checks["justified with value or market data"] = bool(re.search(r"\b(market|similar roles|experience|deliver|value|research|benchmark|range|skills|results?)\b", low))
        checks["didn't accept on the spot"] = not re.search(r"\b(sounds great|i accept|that works|deal|yes,? (that|i'll))\b", low) or bool(counter)
        checks["asked about the whole package"] = bool(re.search(r"\b(bonus|equity|benefits|leave|vacation|pension|health|allowance|signing|review|package|flexib)\w*", low))
        checks["stayed warm and confident"] = not _HEDGE.search(a) and not _NEGATIVE.search(a)
        if not checks["named a number"]:
            tips.append("Name a specific number. Without one, you've let them set the terms.")
        if checks["named a number"] and not checks["anchored above the offer"]:
            tips.append("Counter above their offer, around 10-20% higher, so there's room to meet in the middle.")
        if not checks["justified with value or market data"]:
            tips.append("Give a reason: what similar roles pay, or the specific value you bring.")
        if not checks["asked about the whole package"]:
            tips.append("Ask about the rest of the package: bonus, leave, benefits, review timing.")
        if not checks["stayed warm and confident"]:
            tips.append("Drop the hedging (\"I guess\", \"if that's ok\"). Say the number plainly, then stop talking.")
    elif kind == "reverse":
        qs = [q for q in re.split(r"(?<=\?)\s*|\n", a) if q.strip().endswith("?")] or [s for s in re.split(r"(?<=[.!?])\s", a) if re.match(r"\s*(what|how|who|why|when|where|could|can|do|does|is|are|would)\b", s, re.I)]
        checks["asked at least two questions"] = len(qs) >= 2
        checks["about the work itself"] = bool(re.search(r"\b(team|day|week|project|success|first (90|three|six)|challenge|priorit|roadmap|measure|goals?)\b", low))
        checks["about how they work"] = bool(re.search(r"\b(culture|process|decisions?|feedback|review|collaborat|remote|on-?call|deploy|stack)\b", low))
        checks["not salary or perks first"] = not re.search(r"^\W*(what('s| is) the (salary|pay)|how much|vacation|holidays?|benefits)", low)
        desc = (job.get("description") or "").lower()
        checks["not answered by the posting"] = not any(re.search(p, low) and re.search(p, desc) for p in (r"\bremote\b", r"\bsalary\b", r"\blocation\b"))
        if not checks["asked at least two questions"]:
            tips.append("Always have at least two questions. \"No questions\" reads as low interest.")
        if not checks["about the work itself"]:
            tips.append("Ask what success looks like in the first 90 days, or what the team's biggest challenge is right now.")
        if not checks["about how they work"]:
            tips.append("Ask how decisions get made, or how feedback and reviews work.")
        if not checks["not salary or perks first"]:
            tips.append("Leave pay and perks for the recruiter, or for after an offer.")
    elif kind == "technical":
        skills = tax.find_skills(a)
        checks["named the tools involved"] = bool(skills)
        checks["explained a trade-off"] = bool(re.search(r"\b(trade-?off|instead of|rather than|downside|cost|versus|vs\.?|chose|because|depends)\b", low))
        checks["gave a concrete example"] = bool(re.search(r"\b(for example|for instance|in one|on a project|we had|i built|i wrote|once)\b", low))
        checks["quantified something"] = bool(nums)
        checks["right length (60-250 words)"] = 60 <= len(words) <= 250
        if not checks["explained a trade-off"]:
            tips.append("Say what you chose AND what you gave up. Trade-offs are what separate seniority levels.")
        if not checks["gave a concrete example"]:
            tips.append("Anchor it in one real project; abstract answers sound memorised.")
        if not checks["quantified something"]:
            tips.append("Put a number on it: latency, rows, users, time saved.")
        if not checks["named the tools involved"]:
            tips.append("Name the actual tools and libraries you used.")
    else:  # screen
        checks["concise (30-150 words)"] = 30 <= len(words) <= 150
        checks["no negativity about past employers"] = not _NEGATIVE.search(a)
        checks["confident, no hedging"] = not _HEDGE.search(a)
        if re.search(r"salary|expectation|pay|compensation", question, re.I):
            checks["gave a number or range"] = bool(nums)
            if not nums:
                tips.append("Give a range. \"I'm open\" makes the recruiter guess, usually low. Anchor on research.")
        if re.search(r"why .*(apply|interested)|what made you", question, re.I):
            checks["mentioned something specific about them"] = bool(job.get("company") and job["company"].lower() in low) or len(tax.find_skills(a)) >= 2
            if not checks["mentioned something specific about them"]:
                tips.append("Mention something specific about this company or role; generic answers sound like mass-applying.")
        if not checks["concise (30-150 words)"]:
            tips.append("Screens reward short, clear answers: 30 to 90 seconds." if len(words) > 150 else "A little more detail: give one concrete point.")
        if not checks["no negativity about past employers"]:
            tips.append("Never criticise a current or past employer, even when it's deserved. Talk about what you're moving towards.")
        if not checks["confident, no hedging"]:
            tips.append("Cut the hedging; state it plainly.")
    score = round(100 * sum(checks.values()) / len(checks)) if checks else 0
    honest = ("Honest take: this would land well." if score >= 80 else
              "Honest take: fine, but you'd leave something on the table." if score >= 60 else
              "Honest take: this would hurt you. Fix the first tip before the real thing.")
    return {"score": score, "checks": checks, "tips": tips[:5], "honest": honest}


# ---------------------------------------------------------------------------
# prep plan + research brief
# ---------------------------------------------------------------------------

_NOT_STACK = {"Education", "English", "Spanish", "French", "Agile", "Scrum", "Insurance", "Underwriting", "Claims", "Accounting"}


def research_brief(job: dict, required_skills: list[str]) -> dict:
    desc = job.get("description") or ""
    sents = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", desc))
    about = [s for s in sents if re.search(r"\b(we are|we're|our mission|founded|leading|our clients|we help|we build|we provide|headquartered)\b", s, re.I)][:3]
    values = sorted({m.lower() for m in re.findall(r"\b(ownership|collaborat\w*|curios\w*|customer[- ]first|integrity|innovation|diversity|inclusion|impact|transparen\w*|autonomy|quality|agile|fast-paced)\b", desc, re.I)})
    stack = sorted(s for s in tax.find_skills(desc) if s not in tax.SOFT and s not in _NOT_STACK)[:12]
    company = job.get("company") or "the company"
    questions = [f"What does success look like in the first 90 days for this {job.get('title') or 'role'}?",
                 "What's the biggest challenge the team is facing right now?",
                 "How do you decide what gets built next, and who's involved?"]
    if values:
        questions.append(f"The posting mentions {values[0]}. What does that look like day to day?")
    if stack:
        questions.append(f"How is {stack[0]} used across the team, and what would you change about the current setup?")
    return {"company": company, "about": about, "values": values, "stack": stack, "focus": required_skills[:6],
            "questions_to_ask": questions[:5],
            "look_up": [f"{company}'s website: products, customers, recent news", f"{company} on LinkedIn: team size, who you'd work with",
                        "Glassdoor or similar for their interview process"]}


def prep_plan(job: dict, interview_on: date, stage: str, today: date | None = None, gaps: list[str] | None = None,
              has_baseline: bool = False, stories: int = 0) -> dict:
    """Day-by-day tasks up to the interview date. Compresses gracefully when the interview is tomorrow."""
    today = today or date.today()
    days = (interview_on - today).days
    kind = {"screen": "screen", "technical": "technical", "final": "behavioural", "onsite": "behavioural"}.get(stage, "behavioural")
    tasks: list[tuple[int, str, str]] = []  # (days before interview, key, text)
    tasks.append((min(days, 6), "research", "Read the research brief and look up the company: products, customers, recent news."))
    if not has_baseline:
        tasks.append((min(days, 6), "baseline", "Record your calm-voice baseline once (Interview page), so nerves are judged against your own voice."))
    if gaps:
        tasks.append((min(days, 5), "stories", f"Write stories for the requirements you have none for: {', '.join(gaps[:3])}."))
    elif stories < 3:
        tasks.append((min(days, 5), "stories", "Build at least three stories in your story bank: a win, a failure you learned from, a conflict."))
    tasks.append((min(days, 4), "mock1", f"Full mock interview ({KINDS[kind]}) for this role; review the honest takes."))
    tasks.append((min(days, 2), "drill", "Drill the questions you scored lowest on."))
    tasks.append((min(days, 2), "mock2", "Second mock interview on the tough setting. Aim to beat your first score."))
    tasks.append((min(days, 1), "questions", "Pick three questions to ask them; practise the \"questions for them\" drill."))
    tasks.append((min(days, 1), "logistics", "Logistics: link or address, route, outfit, a quiet room, charged devices, a glass of water."))
    tasks.append((0, "breathe", "On the day: re-read your top three stories, one calm breath out before you start, arrive or log in 10 minutes early."))
    tasks.append((-1, "log", "After: log the questions you were actually asked and how it felt, while it's fresh."))
    tasks.append((-1, "thanks", "Send a short thank-you note within 24 hours (Outreach tab on the job)."))
    out = []
    for before, key, text in sorted(tasks, key=lambda t: -t[0]):
        d = interview_on - timedelta(days=before)
        if d < today:
            d = today
        out.append({"key": key, "date": d.isoformat(), "text": text, "overdue": False})
    return {"days_left": days, "kind": kind, "tasks": out}


# ---------------------------------------------------------------------------
# real interviews vs mocks
# ---------------------------------------------------------------------------

def real_vs_mock(real: list[dict], mocks: list[dict]) -> dict | None:
    """real: [{felt (1-5), outcome}], mocks: [{overall}]. Are your mock scores predicting how real ones go?"""
    done = [r for r in real if r.get("felt")]
    if not done or not mocks:
        return None
    felt = sum(r["felt"] for r in done) / len(done)
    mock = sum(m["overall"] for m in mocks) / len(mocks)
    advanced = [r for r in done if r.get("outcome") in ("advanced", "offer")]
    rate = round(100 * len(advanced) / len(done)) if done else None
    felt_pct = round((felt - 1) / 4 * 100)
    if felt_pct < mock - 20:
        read = "Real interviews feel harder than your mocks. Practise on the tough setting, with follow-ups on."
    elif felt_pct > mock + 20:
        read = "You feel better in real interviews than your mock scores suggest. The mocks may be harsher than needed, which is fine."
    else:
        read = "Your mock scores roughly match how real interviews feel. The practice is calibrated."
    return {"real": len(done), "felt_avg": round(felt, 1), "mock_avg": round(mock), "advance_rate": rate, "read": read}


# ---------------------------------------------------------------------------
# inbox: classify a recruiter email
# ---------------------------------------------------------------------------

_EMAIL_RULES = [
    ("offer", r"\b(pleased to (extend|offer)|offer letter|job offer|we('d| would) like to offer|offer of employment)\b", "Offer"),
    ("rejection", r"\b(unfortunately|not (be )?(moving|proceed)\w*|decided to (move|go) forward with other|other candidates|not selected|position has been filled|regret to inform)\b", "Rejected"),
    ("invite", r"\b(schedule (an|a|your) (interview|call|chat)|invite you to (an )?interview|availability for (an )?(interview|call)|next (round|stage|step)|would like to (speak|meet|chat)|book a time|calendly)\b", "Interviewing"),
    ("assessment", r"\b(assessment|take-?home|coding (challenge|test)|hackerrank|codility|testgorilla|assignment)\b", "Interviewing"),
    ("received", r"\b(received your application|thank you for (applying|your application)|application (has been )?received)\b", "Applied"),
]
_DATE_PAT = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+(\d{1,2}(?:st|nd|rd|th)?\s+[a-z]{3,9}|[a-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?)\b|\b\d{4}-\d{2}-\d{2}\b", re.I)


def classify_email(subject: str, body: str, sender: str = "") -> dict:
    text = f"{subject}\n{body}"
    hits = [(kind, status) for kind, rx, status in _EMAIL_RULES if re.search(rx, text, re.I)]
    kind, status = hits[0] if hits else ("other", None)
    # a rejection email often also says "thank you for applying": the stronger signal (listed first) wins, already
    when = _DATE_PAT.search(text)
    dom = re.search(r"@([a-z0-9-]+)\.", sender.lower())
    return {"kind": kind, "suggested_status": status, "mentions_date": when.group(0) if when else None,
            "sender_domain": dom.group(1) if dom else None, "all_signals": [k for k, _ in hits]}


def match_email_to_jobs(subject: str, body: str, sender: str, jobs: list[dict]) -> list[dict]:
    """jobs: [{job_id, title, company, status}]. Company name in the text or sender domain; title words as a tie-break."""
    text = f"{subject}\n{body}".lower()
    dom = (re.search(r"@([a-z0-9-]+)\.", sender.lower()) or [None, ""])[1] or ""
    scored = []
    for j in jobs:
        co = (j.get("company") or "").lower().strip()
        if not co:
            continue
        core = re.sub(r"\b(inc|ltd|limited|llc|plc|group|holdings|company|co|the)\b\.?", "", co).strip()
        s = 0
        if core and core in text:
            s += 3
        if core and dom and re.sub(r"[^a-z0-9]", "", core)[:12] in dom:
            s += 3
        s += sum(1 for w in re.findall(r"[a-z]{4,}", (j.get("title") or "").lower()) if w in text) * 0.5
        if s >= 3:
            scored.append({**j, "match": s})
    return sorted(scored, key=lambda x: -x["match"])[:3]


# ---------------------------------------------------------------------------
# camera (on-device face tracking summary numbers)
# ---------------------------------------------------------------------------

def camera_feedback(cam: dict | None) -> dict | None:
    """cam: {frames, face_ratio, eye_contact_ratio, head_motion_deg, smile_ratio}. Heuristic, and says so."""
    if not cam or (cam.get("frames") or 0) < 20:
        return None
    tips, notes, score = [], [], 100
    face, eye, motion, smile = cam.get("face_ratio"), cam.get("eye_contact_ratio"), cam.get("head_motion_deg"), cam.get("smile_ratio")
    if face is not None and face < 0.85:
        tips.append("You were out of frame some of the time. Centre the camera at eye level, about an arm's length away.")
        score -= 20
    if eye is not None:
        if eye < 0.45:
            tips.append(f"You looked at the camera about {round(eye * 100)}% of the time. Glance at the lens when you make a key point; on a video call that is eye contact.")
            score -= 25
        elif eye > 0.9:
            notes.append("Strong eye contact.")
        else:
            notes.append("Natural eye contact: you looked at the camera most of the time and away to think, which is normal.")
    if motion is not None and motion > 12:
        tips.append("Lots of head movement. Settle your posture; stillness reads as calm.")
        score -= 15
    if smile is not None:
        if smile < 0.03:
            tips.append("Barely any smile. A brief smile at the start and end makes a big difference to warmth.")
            score -= 10
        else:
            notes.append("Warm expression.")
    return {"score": max(0, score), "tips": tips, "notes": notes,
            "caveat": "Estimated from on-device face tracking (no video is stored or sent). Lighting and camera angle affect it."}


# ---------------------------------------------------------------------------
# weekly report
# ---------------------------------------------------------------------------

def weekly_report(this: dict, last: dict) -> dict:
    """this/last: {applied, responses, interviews, offers, rejections, mocks, mock_avg, composure_avg, drills, stories}."""
    def delta(k):
        a, b = this.get(k), last.get(k)
        return None if a is None or b is None else a - b
    rate = round(100 * this["responses"] / this["applied"]) if this.get("applied") else None
    reads = []
    if not this.get("applied"):
        reads.append("No applications this week. Momentum matters: aim for a few well-targeted ones.")
    elif rate is not None and this["applied"] >= 5 and rate < 10:
        reads.append(f"Only {rate}% of this week's applications got a response. Tailor fewer, better-matched applications (Tier 1 roles).")
    if this.get("interviews") and not this.get("mocks"):
        reads.append("You have real interviews but did no mock practice this week.")
    if this.get("mock_avg") is not None and last.get("mock_avg") is not None:
        d = this["mock_avg"] - last["mock_avg"]
        reads.append(f"Mock scores {'up' if d >= 0 else 'down'} {abs(round(d))} points on last week.")
    if this.get("composure_avg") is not None and last.get("composure_avg") is not None and this["composure_avg"] - last["composure_avg"] >= 8:
        reads.append("You're sounding calmer than last week.")
    if not reads:
        reads.append("Steady week. Keep the rhythm: apply, practise, follow up.")
    return {"this": this, "last": last, "response_rate": rate, "deltas": {k: delta(k) for k in this}, "reads": reads}


# ---------------------------------------------------------------------------
# offers — compare job offers on the whole package, in one currency
# ---------------------------------------------------------------------------

def offer_value(o: dict, fx_ttd_per_usd: float) -> dict:
    """o: {base_monthly, currency ('TT$'|'US$'), bonus_pct, signing, leave_days, remote_days, commute_minutes}.
    -> the package in TT$ a month (bonus and signing spread over the first year), plus the parts."""
    rate = fx_ttd_per_usd if (o.get("currency") or "TT$").upper().startswith("US") else 1.0
    base = float(o.get("base_monthly") or 0) * rate
    bonus = base * float(o.get("bonus_pct") or 0) / 100
    signing = float(o.get("signing") or 0) * rate / 12
    total = base + bonus + signing
    commute_h_week = float(o.get("commute_minutes") or 0) * 2 * max(0, 5 - int(o.get("remote_days") or 0)) / 60
    return {"base_ttd": round(base), "bonus_ttd": round(bonus), "signing_ttd": round(signing), "total_ttd": round(total),
            "leave_days": int(o.get("leave_days") or 0), "remote_days": int(o.get("remote_days") or 0),
            "commute_hours_week": round(commute_h_week, 1)}


def compare_offers(offers: list[dict], fx_ttd_per_usd: float, floor_ttd: float = 0) -> dict:
    """Rank offers by first-year monthly value, and say plainly what separates them."""
    rows = [{**o, "value": offer_value(o, fx_ttd_per_usd)} for o in offers]
    rows.sort(key=lambda r: -r["value"]["total_ttd"])
    notes = []
    if len(rows) >= 2:
        a, b = rows[0], rows[1]
        gap = a["value"]["total_ttd"] - b["value"]["total_ttd"]
        notes.append(f"{a.get('company') or 'The top offer'} is worth about TT${gap:,} a month more than {b.get('company') or 'the next'} in year one.")
        if b["value"]["commute_hours_week"] + 2 < a["value"]["commute_hours_week"]:
            notes.append(f"But {a.get('company')} costs about {a['value']['commute_hours_week'] - b['value']['commute_hours_week']:g} more hours a week commuting.")
        if b["value"]["leave_days"] > a["value"]["leave_days"] + 3:
            notes.append(f"{b.get('company')} gives {b['value']['leave_days'] - a['value']['leave_days']} more days of leave.")
    for r in rows:
        r["below_floor"] = bool(floor_ttd and r["value"]["base_ttd"] < floor_ttd)
    if floor_ttd and any(r["below_floor"] for r in rows):
        notes.append(f"Offers marked below your floor (TT${floor_ttd:,.0f}/month base) are worth negotiating before you consider them.")
    return {"offers": rows, "notes": notes, "fx": fx_ttd_per_usd, "floor_ttd": round(floor_ttd or 0)}
