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
from collections import Counter
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

def llm_status(cfg: dict | None = None) -> dict:
    """Which providers exist, which one a request would ACTUALLY use (the pinned provider, else the first available
    in llm.ORDER, or the next ready one when fallback is on — the same choice llm.generate() makes), and what would leave your machine if you use it."""
    try:
        from src import llm
        d = llm.describe(cfg)
        where = llm.privacy(cfg)
    except Exception:  # noqa: BLE001
        d, where = {}, {}
    avail = {k: bool(v.get("available")) for k, v in d.items() if k != "template"}
    try:
        active = llm.active_provider(cfg or {}, avail)
    except Exception:  # noqa: BLE001
        active = None
    return {"providers": avail, "any": active is not None, "active": active,
            "privacy": where}


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
    raw = m.group(1)
    for attempt in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):   # small local models often leave trailing commas
        try:
            return json.loads(attempt)
        except ValueError:
            continue
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


# ---------------------------------------------------------------------------
# voice delivery — pace, pitch variety, pauses, volume. Computed client-side from the raw microphone signal
# (Web Audio API: an autocorrelation pitch estimate + RMS energy per frame — see static/js/interview.js), sent
# here as summary numbers only; no audio is ever uploaded. This is a practical coaching signal, not a validated
# acoustic analysis — thresholds are deliberately generous so it only speaks up on something clearly notable.
# ---------------------------------------------------------------------------

def delivery_feedback(voice: dict | None) -> dict | None:
    """voice: {duration_sec, words, pace_wpm, pitch_mean_hz, pitch_stdev_hz, pause_ratio, long_pauses,
    volume_mean, volume_stdev} — every key optional; missing ones are simply skipped, never guessed at."""
    if not voice or not voice.get("duration_sec"):
        return None
    tips: list[str] = []
    notes: list[str] = []
    scores: list[float] = []

    pace = voice.get("pace_wpm")
    if pace:
        if pace < 105:
            tips.append(f"Pace: about {round(pace)} words/minute — on the slow side. A little more pace reads as more prepared and confident.")
            scores.append(60)
        elif pace > 175:
            tips.append(f"Pace: about {round(pace)} words/minute — quite fast. Slow down on the key point so it lands.")
            scores.append(65)
        else:
            notes.append(f"Good pace ({round(pace)} words/minute).")
            scores.append(95)

    mean_p, sd_p = voice.get("pitch_mean_hz"), voice.get("pitch_stdev_hz")
    # a wavering voice also has a big pitch spread; that's a composure cue (composure_feedback), never "lively" tone
    if (voice.get("jitter") or 0) > 0.045:
        mean_p = None
    if mean_p and sd_p is not None:
        cv = sd_p / mean_p if mean_p else 0
        if cv < 0.06:
            tips.append("Tone stayed fairly flat. A bit more natural variation in pitch reads as more engaged.")
            scores.append(65)
        else:
            notes.append("Natural variation in your tone — didn't sound flat.")
            scores.append(95)

    pr, longp = voice.get("pause_ratio"), voice.get("long_pauses") or 0
    if pr is not None:
        if pr > 0.38 or longp >= 3:
            tips.append("A fair amount of silence between thoughts. Pausing to think is fine — long or frequent pauses can read as unprepared.")
            scores.append(60)
        else:
            notes.append("Kept good momentum, no long dead air.")
            scores.append(95)

    vm, vs = voice.get("volume_mean"), voice.get("volume_stdev")
    if vm is not None:
        if vm < 0.12:
            tips.append("Volume was quite low. Speaking a bit louder reads as more confident, especially over a call.")
            scores.append(65)
        elif vs is not None and vm and vs / vm > 0.9:
            tips.append("Volume varied a lot, like trailing off at the end of sentences. Keep it steady through to the end of each point.")
            scores.append(70)
        else:
            notes.append("Clear, steady volume.")
            scores.append(95)

    if not scores:
        return None
    return {"score": round(sum(scores) / len(scores)), "tips": tips[:4], "notes": notes,
           "metrics": {k: voice.get(k) for k in ("pace_wpm", "pitch_mean_hz", "pitch_stdev_hz", "pause_ratio", "long_pauses", "volume_mean") if voice.get(k) is not None}}


# ---------------------------------------------------------------------------
# composure — does this person SOUND nervous? Read from vocal cues the browser measures (startMetrics, static/js/ai.js):
# a wavering voice (frame-to-frame pitch instability), pitch that starts high and settles, statements rising at the end like
# questions (uptalk), trailing off, a long wait before the first word, rushing, a narrow pitch range, and filler words
# (from the transcript). Each cue is a well-known correlate of speaking anxiety, none is proof on its own — so the
# read is stated plainly, with the evidence next to it, and never as a diagnosis. Thresholds err on the side of
# silence: a cue only counts when it's clearly past what calm conversational speech produces.
# ---------------------------------------------------------------------------

_COMPOSURE_CUES = [
    # key, test(voice, thresholds) -> bool, weight, what a listener hears, the fix. Thresholds come from
    # coach.personal_thresholds(): generic without a voice baseline, fitted around YOUR calm voice with one.
    ("jitter", lambda v, t: (v.get("jitter") or 0) > t["jitter"], 16, "your pitch wavered from moment to moment (a shaky voice)",
     "Slow your breathing before you start: a full breath out steadies the voice more than anything else."),
    ("raised", lambda v, t: bool(t["raised_pitch"]) and (v.get("pitch_mean_hz") or 0) > t["raised_pitch"], 12,
     "your voice sat noticeably higher than your normal speaking pitch, a common stress response",
     "Before answering, breathe out slowly and start the first sentence a little lower than feels natural."),
    ("drift", lambda v, t: (v.get("pitch_drift_st") or 0) > 1.5, 12, "your pitch started noticeably higher than it ended, a classic sign of nerves in the opening",
     "Rehearse your first two sentences until they're automatic, so the opening doesn't carry the adrenaline."),
    ("uptalk", lambda v, t: (v.get("uptalk_ratio") or 0) > t["uptalk"] and (v.get("phrases") or 0) >= 3, 12, "many statements rose at the end like questions, which sounds unsure",
     "Land your statements: let the pitch fall at the end of each sentence, especially the result."),
    ("trail", lambda v, t: (v.get("trail_off_ratio") or 0) > 0.4 and (v.get("phrases") or 0) >= 3, 10, "you often trailed off at the end of sentences",
     "Finish each sentence at full volume; the last words are usually the important ones."),
    ("latency", lambda v, t: (v.get("start_latency_sec") or 0) > 4, 8, "you took a long time to start",
     "It's fine to buy a second (\"Good question — let me think of the best example\"), then begin."),
    ("rush", lambda v, t: (v.get("pace_wpm") or 0) > t["rush_wpm"], 12, "you were rushing",
     "Deliberately slow down; pausing after a key point reads as confidence."),
    ("narrow", lambda v, t: v.get("pitch_range_st") is not None and v["pitch_range_st"] < t["narrow_st"], 8, "your pitch range was very narrow, which reads as tense or held back",
     "Let your voice move: stress the words that matter (the action, the number)."),
]


def composure_feedback(voice: dict | None, filler_per_100: float = 0.0, baseline: dict | None = None) -> dict | None:
    if not voice or not voice.get("duration_sec") or (voice.get("duration_sec") or 0) < 5:
        return None
    from src import coach
    th = coach.personal_thresholds(baseline)
    signals, fixes, penalty = [], [], 0
    for key, test, w, heard, fix in _COMPOSURE_CUES:
        try:
            hit = test(voice, th)
        except (TypeError, ValueError):
            hit = False
        if hit:
            signals.append({"cue": key, "heard": heard})
            fixes.append(fix)
            penalty += w
    if filler_per_100 > 5:
        signals.append({"cue": "filler", "heard": f"lots of filler words ({filler_per_100:g} per 100 words)"})
        fixes.append("Replace filler with a silent pause; it sounds more composed than \"um\" or \"basically\".")
        penalty += 10
    score = max(0, 100 - penalty)
    label = "Calm and confident" if score >= 80 else "Some nerves showing" if score >= 60 else "Noticeably nervous"
    heard = [x["heard"] for x in signals]
    if not heard:
        honest = "You sounded composed: steady voice, statements landed, no rushing."
    elif score >= 80:
        honest = f"Mostly composed. One thing a listener might pick up: {heard[0]}."
    else:
        honest = (f"Honestly, you sounded {'quite ' if score < 60 else 'a bit '}nervous: " + "; ".join(heard[:3])
                  + (". An interviewer would likely notice." if score < 60 else ". Most interviewers make allowances for this, but it's worth fixing."))
    return {"score": score, "label": label, "signals": signals, "honest": honest, "fixes": fixes[:3], "personal": bool(baseline),
            "caveat": ("Compared with your own calm-voice baseline. " if baseline else
                       "Judged against generic thresholds; record a calm-voice baseline to judge against your own voice. ")
                      + "Estimated from vocal cues (pitch, volume, timing), not a diagnosis. A cold or a noisy room can trip these."}


def honest_take(score: int, star: dict, has_nums: bool, n_words: int, composure: dict | None) -> str:
    """One blunt sentence: would this answer get you through? Content decides; composure can pull it down a notch."""
    missing = [k for k in ("situation", "action", "result") if not star.get(k)]
    if score >= 80 and (not composure or composure["score"] >= 60):
        return "Honest take: this answer would hold up in a real interview."
    if score >= 60:
        gap = ("it has no number to prove the result" if not has_nums else f"it's missing the {missing[0]}" if missing else "it could be tighter")
        return f"Honest take: acceptable but forgettable, {gap}. Against strong candidates it probably wouldn't stand out."
    if n_words < 50:
        return "Honest take: too thin. An interviewer would have to drag the story out of you, and most won't."
    return f"Honest take: this wouldn't get you through yet. It's missing the {', '.join(missing) or 'concrete detail'}, so it's hard to tell what you actually did."


PERSONAS = {
    "friendly": "a warm, encouraging interviewer who still wants specifics",
    "neutral": "a professional, neutral interviewer",
    "tough": "a demanding senior interviewer who probes vague claims and pushes for evidence and numbers",
}


def interview_feedback(job: dict, question: str, answer: str, use_llm: bool = False, cfg: dict | None = None, voice: dict | None = None,
                       persona: str = "neutral", kind: str = "behavioural", baseline: dict | None = None, camera: dict | None = None,
                       interrupted: bool = False, offer: dict | None = None) -> dict:
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
    from src import coach
    checks = None
    if kind in coach.KINDS and kind != "behavioural":
        # a non-behavioural answer isn't judged on STAR: its own checks replace the content score, tips and verdict
        kf = coach.kind_feedback(kind, question, answer, job, offer)
        score, checks, tips = kf["score"], kf["checks"], kf["tips"] + [t for t in tips if t.startswith("Cut hedging")]
    if interrupted:
        tips.insert(0, "The interviewer had to cut you off. Aim to land the point inside two minutes, then offer more detail if they want it.")
        score = max(0, score - 8)
    delivery = delivery_feedback(voice)
    composure = composure_feedback(voice, round(len(filler) / len(words) * 100, 1) if words else 0, baseline)
    if delivery and composure:
        delivery["score"] = round(delivery["score"] * 0.6 + composure["score"] * 0.4)
    overall = round(score * 0.7 + delivery["score"] * 0.3) if delivery else score
    verdict = "Strong" if overall >= 75 else "Solid, tighten it" if overall >= 55 else "Needs structure"
    out = {"score": score, "overall_score": overall, "star": star, "words": len(words), "numbers": has_nums, "skills_named": skills[:8], "tips": tips[:6],
           "verdict": verdict, "provider": "rules", "delivery": delivery,
           "filler": dict(Counter(f.lower() for f in filler).most_common(6)), "filler_count": len(filler),
           "follow_up": follow_up_question(star, has_nums, first_i, first_we, len(words)), "follow_up_by": "rules",
           "composure": composure, "honest": honest_take(score, star, has_nums, len(words), composure),
           "kind": kind, "checks": checks, "camera": coach.camera_feedback(camera), "interrupted": interrupted}
    if checks is not None:
        out["honest"] = kf["honest"]
        out["follow_up"] = None       # typed interviews run their own scripted sequence (e.g. negotiation pressure)
        out["verdict"] = "Strong" if overall >= 75 else "Solid, tighten it" if overall >= 55 else "Needs work"
    if persona == "tough" and kind == "behavioural" and not out["follow_up"] and overall < 80:
        out["follow_up"] = "Let me push on that. What would you do differently if you did it again, and why?"
    if use_llm:
        out.update(_llm_answer_review(job, question, answer, out, persona, cfg))
    # what a voice interviewer would say back — plain text; actual speech synthesis (optional, needs Kokoro) is src.voice.synthesize()
    speak_tip = re.sub(r"^[A-Za-z ,]+: ", "", tips[0]) if tips else (delivery["tips"][0] if delivery and delivery["tips"] else "")
    take = out["honest"].replace("Honest take: ", "")
    out["speech"] = (f"You scored {overall} out of 100. {take[:1].upper() + take[1:]}"
                     + (f" {composure['honest']}" if composure and composure["score"] < 80 else "")
                     + (f" The main thing to work on: {speak_tip}" if speak_tip else ""))
    return out


def _llm_answer_review(job: dict, question: str, answer: str, rules: dict, persona: str, cfg: dict | None) -> dict:
    """One model call per answer: coach notes, a follow-up that reacts to what was actually said, and a stronger
    version of the answer. The stronger version may only reword the candidate's own facts (grounded(): no new numbers
    or tools); if the model invents any, it is dropped rather than shown."""
    comp = rules.get("composure") or {}
    system = ("You are " + PERSONAS.get(persona, PERSONAS["neutral"]) + " and an honest interview coach. Reply with JSON only: "
              '{"coach": ["three short, specific, candid improvements"], "follow_up": "one probing follow-up question that reacts to '
              'something specific the candidate said, or empty string if the answer fully covered it", "stronger": "the same answer '
              'rewritten to be clearer and better structured (situation, action, result), in first person, using ONLY facts, numbers, '
              'tools, job titles and claims the candidate actually said in the answer — never add new ones, never take them from the '
              'question, and never upgrade their role (e.g. \\"helped\\" must not become \\"led\\" or \\"owned\\")"}. Be honest, not flattering.')
    user = (f"Role: {job.get('title','')} at {job.get('company','')}\nQuestion: {question}\nAnswer: {answer}\n"
            f"Rule-based read: content {rules['score']}/100; missing: {', '.join(k for k, v in rules['star'].items() if not v) or 'nothing'}"
            + (f"; voice: {comp.get('label')} ({'; '.join(x['heard'] for x in comp.get('signals', []))})" if comp else ""))
    text, backend = _ask_llm(system, user, cfg)
    data = _json_from(text)
    if not isinstance(data, dict):
        # prose is still useful coaching; broken JSON is not something to show a person
        return {"coach": text.strip(), "provider": backend} if text and not text.lstrip().startswith(("{", "[")) else {}
    out: dict = {"provider": backend}
    coach = data.get("coach")
    if isinstance(coach, list):
        coach = "\n".join(f"• {c}" for c in coach if isinstance(c, str) and c.strip())
    if isinstance(coach, str) and coach.strip():
        out["coach"] = coach.strip()
    fu = data.get("follow_up")
    if isinstance(fu, str) and len(fu.strip()) > 10:
        out.update(follow_up=fu.strip(), follow_up_by=backend)
    elif isinstance(fu, str) and not fu.strip():
        out.update(follow_up=None, follow_up_by=backend)
    st = data.get("stronger")
    if isinstance(st, str) and len(st.split()) >= 15:
        if grounded(answer, st) and _no_new_claims(answer, st):
            out["stronger"] = st.strip()
        else:
            out["stronger_dropped"] = "The model's rewrite added facts you didn't say, so it isn't shown."
    return out


_CLAIM_UPGRADES = ("led", "owned", "managed", "architected", "spearheaded", "headed", "directed", "founded")
_COMMON_CAPS = {"i", "a", "an", "the", "my", "when", "at", "as", "in", "on", "we", "our", "it", "this", "that", "after", "before", "because",
                "so", "then", "while", "during", "by", "to", "for", "with", "and", "but", "once", "since", "over", "through", "using"}


def _no_new_claims(original: str, rewritten: str) -> bool:
    """grounded() covers numbers and tools; this covers what a model most often slips in besides: proper nouns and
    titles (capitalised words mid-sentence, e.g. a job title lifted from the question) and upgraded ownership verbs."""
    low = original.lower()
    for m in re.finditer(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-zA-Z]+)", rewritten):
        w = m.group(1)
        if w.lower() not in _COMMON_CAPS and w.lower() not in low:
            return False
    return not any(re.search(rf"\b{v}\b", rewritten, re.I) and not re.search(rf"\b{v}\b", original, re.I) for v in _CLAIM_UPGRADES)


def ai_questions(job: dict, n: int = 5, persona: str = "neutral", cfg: dict | None = None) -> dict:
    """Questions written by the model for THIS posting and resume. Falls back to the rule-built set on any failure."""
    from src import interview as _iv
    base = _iv.questions(job).get("questions") or []
    ctx = _ctx()
    prof = (ctx or {}).get("profile") or {}
    resume = f"Titles: {', '.join(prof.get('titles') or [])[:200]}. Skills: {', '.join(list(prof.get('skills') or [])[:25])}. Summary: {(prof.get('summary') or '')[:400]}"
    system = ("You are " + PERSONAS.get(persona, PERSONAS["neutral"]) + ". Write realistic interview questions for this exact role and "
              f"candidate: a mix of behavioural (tell me about a time), role-specific technical/judgement, and one on a gap between the "
              f"posting and the resume. They will be READ ALOUD, so each is one question, at most two short sentences (under 35 words), "
              f'no lists, no multi-part questions. Reply with JSON only: {{"questions": [{{"q": "...", "why": "what it tests"}}]}} with exactly {n} items.')
    user = f"Role: {job.get('title','')} at {job.get('company','')}\nPosting:\n{(job.get('description') or '')[:3500]}\n\nCandidate: {resume}"
    text, backend = _ask_llm(system, user, cfg)
    data = _json_from(text)
    items = data.get("questions") if isinstance(data, dict) else data if isinstance(data, list) else None
    qs = [{"q": str(x["q"]).strip(), "why": str(x.get("why") or "").strip(), "by": backend}
          for x in (items or []) if isinstance(x, dict) and isinstance(x.get("q"), str) and 12 < len(x["q"].strip())
          and len(x["q"].split()) <= 60][:n]   # a paragraph-long question is unanswerable out loud; drop, don't truncate
    if len(qs) < max(2, n // 2):
        return {"questions": base[:n], "provider": "rules", "note": "The model didn't return usable questions, so these are the built-in ones."}
    # always open with the classic opener if the model didn't
    if not re.search(r"background|about yourself|walk me through", qs[0]["q"], re.I) and base:
        qs = [base[0]] + qs[: n - 1]
    return {"questions": qs, "provider": backend}


# ---------------------------------------------------------------------------
# follow-up — what a real interviewer would probe after a thin answer. Rules only, picked from what the answer
# is actually missing (checked in priority order), so the probe is always about THIS answer. None = no probe needed.
# ---------------------------------------------------------------------------

def follow_up_question(star: dict, has_nums: bool, first_i: int, first_we: int, n_words: int) -> str | None:
    if n_words < 45 and not star.get("situation"):
        return "Can you walk me through a specific example of that? Where were you, and what was going on?"
    if first_we > first_i * 2 and first_we >= 3:
        return "You mentioned what the team did. What was your own part in it, specifically?"
    if not star.get("action"):
        return "What did you personally do? Walk me through the steps you took."
    if not star.get("result") or not has_nums:
        return "How did it turn out? Is there a number you can put on the result?"
    return None


# ---------------------------------------------------------------------------
# whole-session wrap-up — averages, the strongest and weakest answer, and patterns across every tip given,
# built entirely from the per-question interview_feedback() results already collected client-side. No
# re-scoring, no re-reading of audio: this is a summary of a summary.
# ---------------------------------------------------------------------------

def session_summary(results: list[dict], use_llm: bool = False, cfg: dict | None = None) -> dict:
    scored = [r for r in (results or []) if isinstance(r, dict) and isinstance(r.get("overall_score"), (int, float))]
    if not scored:
        return {"error": "no scored answers in this session yet"}
    n = len(scored)
    content_avg = round(sum(r["score"] for r in scored) / n)
    overall_avg = round(sum(r["overall_score"] for r in scored) / n)
    delivery_scores = [r["delivery"]["score"] for r in scored if r.get("delivery")]
    delivery_avg = round(sum(delivery_scores) / len(delivery_scores)) if delivery_scores else None
    best = max(scored, key=lambda r: r["overall_score"])
    worst = min(scored, key=lambda r: r["overall_score"])
    tips = Counter(t for r in scored for t in (r.get("tips") or []))
    tips.update(t for r in scored for t in (r.get("delivery") or {}).get("tips", []))
    recurring = [t for t, c in tips.most_common(8) if c >= 2 or n <= 2][:5]
    verdict = "Strong" if overall_avg >= 75 else "Solid, some rough edges" if overall_avg >= 55 else "Needs more prep"
    comp = [r["composure"]["score"] for r in scored if r.get("composure")]
    composure_avg = round(sum(comp) / len(comp)) if comp else None
    nerves = None
    if len(comp) >= 2:
        first, last = comp[0], comp[-1]
        nerves = ("You settled in: you sounded noticeably calmer by the end than at the start." if last - first >= 12 else
                  "You got more tense as the interview went on, which usually means fatigue or a question that rattled you." if first - last >= 12 else
                  "Your composure was consistent from start to finish.")
    cues = Counter(sig["heard"] for r in scored for sig in ((r.get("composure") or {}).get("signals") or []))
    readiness = ("Ready: you'd likely advance with answers like these." if overall_avg >= 78 and (composure_avg is None or composure_avg >= 60) else
                 "Borderline: you'd advance with some interviewers and not others." if overall_avg >= 60 else
                 "Not ready yet: in a real interview these answers would most likely not get you to the next round.")
    filler_total = sum(r.get("filler_count") or 0 for r in scored)
    words_total = sum(r.get("words") or 0 for r in scored)
    fillers = Counter()
    for r in scored:
        fillers.update(r.get("filler") or {})
    out = {"n": n, "content_avg": content_avg, "filler_total": filler_total,
           "filler_per_100": round(filler_total / words_total * 100, 1) if words_total else 0,
           "top_fillers": [w for w, _ in fillers.most_common(4)], "overall_avg": overall_avg, "delivery_avg": delivery_avg, "verdict": verdict,
           "best": {"question": best.get("question", ""), "score": best["overall_score"]},
           "worst": {"question": worst.get("question", ""), "score": worst["overall_score"]},
           "recurring_tips": recurring, "provider": "rules", "composure_avg": composure_avg,
           "composure_trend": comp, "nerves": nerves, "nerve_cues": [c for c, _ in cues.most_common(3)], "readiness": readiness}
    if use_llm:
        lines = "\n".join(f"- Q: {r.get('question','')}\n  Content {r['score']}/100, overall {r['overall_score']}/100. "
                          f"Voice: {(r.get('composure') or {}).get('label') or 'not measured'}"
                          f"{' (' + '; '.join(x['heard'] for x in (r.get('composure') or {}).get('signals', [])) + ')' if (r.get('composure') or {}).get('signals') else ''}. "
                          f"Tips: {'; '.join(r.get('tips') or []) or 'none'}" for r in scored)
        text, backend = _ask_llm(
            "You are a candid interview coach debriefing after a mock interview. In 4-5 sentences: would this candidate advance, "
            "honestly (don't flatter); how they came across, including whether they sounded nervous; and the ONE thing to fix first. "
            "Use only what's given below — never invent an example or a fact not present in it.",
            lines + f"\nSession: overall {overall_avg}/100, composure {composure_avg if composure_avg is not None else 'not measured'}. "
            f"The rule-based verdict is \"{readiness}\" — if you disagree, say so explicitly and why.", cfg)
        if text:
            out.update(coach=text.strip(), provider=backend)
    out["speech"] = (f"Overall, you scored {overall_avg} out of 100 across {n} question{'s' if n != 1 else ''}. {readiness}"
                     + (f" On nerves: {nerves}" if nerves else "")
                     + (f" Keep working on: {re.sub(r'^[A-Za-z ,:]+: ', '', recurring[0])}" if recurring else ""))
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
