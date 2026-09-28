"""
matching.py — profile-driven fit and likelihood.

Everything here is derived from the user's *parsed resume* (profile_store) and *preferences*, not from
hard-coded skills. For one job it produces:

  fit               0-100  how well this role matches you (skills, evidence, title, experience, domain, preferences)
  likelihood        0-100  index of your odds relative to a typical applicant to this kind of job
  interview_chance  %      estimated probability of getting an interview (see calibration.py)
  requirements      each requirement in the posting, the resume text that answers it, and a met/partial/gap status
  skills            matched / related / missing (required vs nice-to-have), with your years of use
  factors           every adjustment that moved the likelihood, with its size — nothing is a black box

The likelihood is a transparent log-odds model, not a trained classifier: a prior interview rate for the job
type (local vs remote), adjusted by your qualification match, seniority gap, geographic access, freshness,
pay fit and blockers. Once you record application outcomes, calibration.py replaces the priors with your own
observed rates.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from typing import Any

from src import retrieval
from src import skills_taxonomy as tax

# ---------------------------------------------------------------------------
# reading a job description
# ---------------------------------------------------------------------------

_REQ_MARK = re.compile(r"\b(required|requirements?|must|minimum|essential|proficien\w*|experience (?:with|in|using|of)|strong|"
                       r"solid|demonstrated|hands-on|at least|mandatory|you have|you['’]?ll need|need to have)\b", re.I)
_NICE_MARK = re.compile(r"\b(preferred|nice to have|a plus|bonus|ideally|desirable|an asset|advantageous|would be (?:great|a plus)|"
                        r"familiarity|exposure to|not required|optional)\b", re.I)
_H_REQ = re.compile(r"^(?:#+\s*)?(requirements?|qualifications?|what you['’]?ll need|what we['’]?re looking for|must[- ]haves?|"
                    r"you have|about you|who you are|skills(?: and experience)?|minimum qualifications|essential (?:skills|criteria)|"
                    r"education (?:and|&) experience|key requirements)\b", re.I)
_H_NICE = re.compile(r"^(?:#+\s*)?(nice to have|preferred(?: qualifications| skills)?|bonus(?: points)?|desirable|a plus|good to have)\b", re.I)
_H_DUTY = re.compile(r"^(?:#+\s*)?(responsibilities|what you['’]?ll do|duties|the role|key duties|your role|day[- ]to[- ]day|"
                     r"main duties|scope|position summary|job summary|nature (?:and|&) scope)\b", re.I)

LEVELS = {"entry": 0.0, "mid": 1.0, "mid-senior": 1.5, "senior": 2.0, "lead": 3.0}


def _units(text: str) -> list[tuple[str, str]]:
    """(section, unit) pairs; section in req|nice|duty|none. Units are bullets / short sentences."""
    out: list[tuple[str, str]] = []
    section = "none"
    for raw in re.split(r"\n+", text or ""):
        line = raw.strip()
        if not line:
            continue
        head = re.sub(r"[*_:]+", "", line).strip()
        line_section = section
        if len(head) < 200 and head:
            for name, rx in (("nice", _H_NICE), ("req", _H_REQ), ("duty", _H_DUTY)):
                m = rx.match(head)
                if not m:
                    continue
                rest = head[m.end():].strip(" -–—:")
                if len(rest) <= 3:          # a heading on its own line: switches the section
                    section = name
                    line = ""
                else:                        # "Nice to have: Snowflake" — applies to this line only
                    line_section = name
                    line = rest
                break
        if not line:
            continue
        for sent in re.split(r"(?<=[.;!?])\s+(?=[A-Z•\-])", line):
            s = re.sub(r"^(?:[\s•\-*·▪●○]+|\d{1,2}[.)]\s+)", "", sent).strip()
            if len(s) >= 3:
                out.append((line_section, s))
    return out


def analyze_job(job: dict) -> dict:
    """Skills (with importance), requirement sentences, years, level, work mode, remote scope, pay."""
    title = job.get("title") or ""
    desc = job.get("description") or ""
    loc = job.get("location") or ""
    low = f"{title} {desc} {loc}".lower()

    # -- skills with importance
    weight = {"required": 1.0, "duty": 0.6, "mention": 0.6, "nice": 0.3}
    skills: dict[str, dict] = {}
    for section, unit in _units(desc):
        found = tax.find_skills(unit)
        if not found:
            continue
        if _NICE_MARK.search(unit) or section == "nice":
            kind = "nice"
        elif section == "req" or _REQ_MARK.search(unit):
            kind = "required"
        elif section == "duty":
            kind = "duty"
        else:
            kind = "mention"
        for s in found:
            cur = skills.get(s)
            if not cur or weight[kind] > weight[cur["kind"]]:
                skills[s] = {"kind": kind, "weight": weight[kind], "text": unit[:200]}
    for s in tax.find_skills(title):
        skills[s] = {"kind": "required", "weight": 1.0, "text": title}  # the title names it: it's core to the role

    # -- requirement sentences (what we retrieve resume evidence for)
    reqs: list[str] = []
    for section, unit in _units(desc):
        if section == "nice":
            continue
        substantive = bool(tax.find_skills(unit) or re.search(r"\d+\s*\+?\s*years?|degree|diploma|bachelor|certif", unit, re.I))
        if 20 <= len(unit) <= 260 and unit not in reqs and substantive and (section == "req" or _REQ_MARK.search(unit)):
            reqs.append(unit)
    if not reqs:  # thin posting: use any sentence that names a skill or years
        for section, unit in _units(desc):
            if 20 <= len(unit) <= 260 and (tax.find_skills(unit) or re.search(r"\d+\s*\+?\s*years?", unit, re.I)):
                reqs.append(unit)
    reqs = reqs[:10]

    # -- years of experience
    min_years, max_years = None, None
    ys = []
    for m in re.finditer(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2}))?\s*\+?\s*years?", low):
        ctx = low[max(0, m.start() - 60): m.end() + 60]
        if re.search(r"experience|working|background|proven|track record|in (?:a|the)|as a|\bwith\b|\bof\b|using|building|developing|designing|managing|hands-on|professional|minimum|at least", ctx):
            lo, hi = int(m.group(1)), int(m.group(2)) if m.group(2) else None
            if 0 < lo <= 20:
                ys.append((lo, hi))
    if ys:
        min_years = max(y[0] for y in ys)
        his = [y[1] for y in ys if y[1]]
        max_years = max(his) if his else None
    entry = bool(re.search(r"\b(entry[- ]level|junior|graduate|no experience (?:required|necessary)|trainee|apprentice|intern(?:ship)?)\b", low))
    if entry and min_years is None:
        min_years = 0

    # -- job level from the title
    tl = title.lower()
    if re.search(r"\b(intern|trainee|apprentice|junior|jr\.?|entry|graduate|assistant)\b", tl):
        level = 0.0
    elif re.search(r"\b(principal|staff|director|head of|vp|vice president|chief|general manager)\b", tl):
        level = 3.0
    elif re.search(r"\b(senior|sr\.?|lead|manager|supervisor|superintendent|architect)\b", tl):
        level = 2.0
    else:
        level = 1.0
    if min_years is not None and level == 1.0:
        level = 0.5 if min_years <= 1 else 1.0 if min_years <= 4 else 2.0

    mode = work_mode(job, low)
    scope = remote_scope(job, low) if mode in ("remote", "hybrid") or job.get("remote") else ""
    pay = parse_pay(f"{job.get('salary') or ''}\n{desc[:3000]}", local=bool(job.get("region")))

    return {"skills": skills, "requirements": reqs, "min_years": min_years, "max_years": max_years, "level": level,
            "entry": entry, "work_mode": mode, "remote_scope": scope, "pay": pay,
            "eor": bool(re.search(r"employer of record|\bdeel\b|remote\.com|\boyster\b|independent contractor|contractors? (?:welcome|ok)|b2b", low)),
            "sponsorship": bool(re.search(r"visa sponsorship|sponsor(?:ship)? (?:available|provided|offered)|relocation (?:assistance|support|package)|we sponsor", low)),
            "desc_chars": len(desc)}


def work_mode(job: dict, low: str | None = None) -> str:
    low = low or f"{job.get('title', '')} {job.get('description', '')} {job.get('location', '')}".lower()
    if re.search(r"\bhybrid\b", low):
        return "hybrid"
    if job.get("remote") or re.search(r"\b(fully remote|100% remote|remote[- ]first|work from (?:home|anywhere)|remote (?:position|role|job|work)|"
                                      r"this is a remote|location: remote|\(remote\))\b", low):
        return "remote"
    if re.search(r"\bon-?site\b|in[- ]office|in[- ]person|on location", low):
        return "onsite"
    if job.get("region") or (job.get("location") or "").strip():
        return "onsite"   # a concrete place and no sign of remote work
    return "unknown"


_SCOPE = [
    ("us_only", r"\b(?:us|u\.s\.|usa|united states)[- ]?(?:only|based|residents?|citizens?)\b|\bmust (?:be )?(?:located|reside|residing|based|live|living) in (?:the )?(?:us|u\.s\.|usa|united states)\b|"
                r"\b(?:authori[sz]ed|eligible|legally authori[sz]ed|right) to work in (?:the )?(?:us|u\.s\.|united states)\b|\bus work authori[sz]ation\b|\busa only\b|\bus timezones? only\b"),
    ("eu_only", r"\b(?:eu|europe|european|uk|emea)[- ]?(?:only|based|residents?)\b|\bmust (?:be )?(?:located|based|reside) in (?:the )?(?:eu|europe|uk|united kingdom|emea)\b|"
                r"\bright to work in the (?:uk|eu)\b|\beea\b"),
    ("canada_only", r"\bcanada[- ]?(?:only|based)\b|\bauthori[sz]ed to work in canada\b|\bmust (?:be )?(?:located|based|reside) in canada\b"),
]
_WORLD = r"\b(?:worldwide|anywhere|global(?:ly)?|work from anywhere|anywhere in the world|any country|all countries|location[- ]independent|international (?:candidates|contractors?))\b"
_AMERICAS = r"\b(?:latam|latin america|americas|north america|south america|western hemisphere|caribbean|utc[- ]?-?[3-6]|(?:eastern|est|edt|central|cst) (?:time|timezone|tz)|overlap with (?:us )?(?:eastern|est))\b"


def remote_scope(job: dict, low: str | None = None) -> str:
    """worldwide | americas | us_only | eu_only | canada_only | unknown — where a remote hire may live."""
    low = low or f"{job.get('title', '')} {job.get('description', '')} {job.get('location', '')}".lower()
    loc = (job.get("location") or "").lower()
    if re.search(_AMERICAS, loc):
        return "americas"
    for name, rx in _SCOPE:
        if re.search(rx, low):
            return name
    if re.search(_WORLD, low) or loc.strip() in ("worldwide", "anywhere", "global", "remote worldwide"):
        return "worldwide"
    if re.search(_AMERICAS, low):
        return "americas"
    return "unknown"


_CUR = r"(?P<cur>US\$|USD|TT\$|TTD|T&T\$|\$|£|€|GBP|EUR|CAD)?"
_NUM = r"(?P<n>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<k>k)?"
_PAY_RE = re.compile(rf"{_CUR}\s*{_NUM}\s*(?:(?:-|–|—|to)\s*(?:US\$|USD|TT\$|TTD|\$|£|€)?\s*(?P<n2>\d{{1,3}}(?:,\d{{3}})+|\d+(?:\.\d+)?)\s*(?P<k2>k)?)?"
                     r"\s*(?P<per>per (?:year|annum|month|hour|week)|/\s*(?:yr|year|mo|month|hr|hour)|a year|a month|annually|monthly|hourly|p\.?a\.?|pa)?", re.I)


def parse_pay(text: str, *, local: bool = False, fx: float = 6.78) -> dict | None:
    """Best-effort pay range -> monthly figures in both currencies. None if no credible pay is stated."""
    for m in _PAY_RE.finditer(text or ""):
        cur_raw = (m.group("cur") or "").upper()
        per = (m.group("per") or "").lower()
        if not cur_raw and not per:
            continue  # bare number with nothing money-like around it
        try:
            lo = float(m.group("n").replace(",", "")) * (1000 if m.group("k") else 1)
            hi = float(m.group("n2").replace(",", "")) * (1000 if m.group("k2") else 1) if m.group("n2") else lo
        except ValueError:
            continue
        if hi < lo:
            lo, hi = hi, lo
        if lo <= 0:
            continue
        if cur_raw in ("TT$", "TTD", "T&T$"):
            cur = "TTD"
        elif cur_raw in ("£", "GBP"):
            cur, lo, hi = "USD", lo * 1.27, hi * 1.27
        elif cur_raw in ("€", "EUR"):
            cur, lo, hi = "USD", lo * 1.08, hi * 1.08
        elif cur_raw == "CAD":
            cur, lo, hi = "USD", lo * 0.73, hi * 0.73
        elif cur_raw in ("US$", "USD"):
            cur = "USD"
        else:
            cur = "TTD" if local else "USD"
        if "hour" in per or per.endswith(("hr", "hourly")):
            period, f = "hour", 160
        elif "week" in per:
            period, f = "week", 4.33
        elif "month" in per or per.endswith(("mo", "monthly")):
            period, f = "month", 1
        elif per:
            period, f = "year", 1 / 12
        else:  # infer from magnitude
            annual_min = 20000 if cur == "USD" else 60000
            period, f = ("year", 1 / 12) if lo >= annual_min else ("month", 1)
            if cur == "USD" and lo < 500:
                period, f = "hour", 160
        mlo, mhi = lo * f, hi * f
        floor = 300 if cur == "USD" else 2000
        if mhi < floor or mhi > 2_000_000:
            continue
        rate = fx if cur == "TTD" else 1 / fx
        return {"currency": cur, "period": period, "monthly_min": round(mlo), "monthly_max": round(mhi),
                "monthly_ttd_min": round(mlo if cur == "TTD" else mlo * fx), "monthly_ttd_max": round(mhi if cur == "TTD" else mhi * fx),
                "monthly_usd_min": round(mlo if cur == "USD" else mlo / fx), "monthly_usd_max": round(mhi if cur == "USD" else mhi / fx),
                "_rate": rate}
    return None


# ---------------------------------------------------------------------------
# scoring pieces
# ---------------------------------------------------------------------------

_LEVEL_WORDS = {"senior", "sr", "junior", "jr", "lead", "principal", "staff", "ii", "iii", "iv", "i", "assistant", "associate", "chief", "head"}


def _title_tokens(t: str) -> set[str]:
    return {w for w in retrieval.tokens(re.sub(r"[/,()\-–]", " ", t)) if w not in _LEVEL_WORDS}


def title_alignment(title: str, ctx: dict) -> tuple[float, str]:
    jt = _title_tokens(title)
    if not jt:
        return 0.4, ""
    best, why = 0.0, ""
    for target, w in ctx["titles"]:
        tt = _title_tokens(target)
        if not tt:
            continue
        inter = len(jt & tt)
        sim = inter / len(tt) if inter else 0.0
        if target.lower() in title.lower():
            sim = 1.0
        elif inter and inter / len(jt | tt) >= 0.34:
            sim = max(sim, 0.75)
        s = sim * w
        if s > best:
            best, why = s, target
    skills_in_title = [s for s in tax.find_skills(title) if s in ctx["skills"]]
    if skills_in_title:
        s = 0.7 + min(0.25, 0.08 * len(skills_in_title))
        if s > best:
            best, why = s, skills_in_title[0]
    return round(min(1.0, best), 3), why


# Broad skills that many unrelated jobs mention ("communication", "reporting", "supply chain"). They still count, but
# less, so a clerical posting doesn't look like a great match just because you also list "regulatory reporting".
_GENERIC_CATS = {"Business & Operations", "Domains", "Insurance & Finance", "Languages (spoken)", "Healthcare & Education", "Engineering & Trades"}
_PRIOR_MASS = 1.2   # pseudo-weight of "unknown" evidence: with few skills named, coverage stays near neutral


def skill_coverage(job_skills: dict, prof_skills: dict) -> dict:
    tot = got = 0.0
    matched, related, miss_req, miss_other, items = [], [], [], [], []
    for name, meta in job_skills.items():
        w = meta["weight"] * (0.5 if tax.CATEGORY.get(name) in _GENERIC_CATS else 1.0)
        item = {"name": name, "kind": meta["kind"], "weight": round(meta["weight"], 2), "category": tax.CATEGORY.get(name, "Other"),
                "status": "missing", "years": 0, "via": ""}
        items.append(item)
        tot += w
        have = prof_skills.get(name)
        if have:
            credit = 1.0 if (have.get("years", 0) >= 1 or have.get("in_skills_section") or have.get("source") == "manual") else 0.85
            got += w * credit
            matched.append({"name": name, "years": have.get("years", 0), "recent": bool(have.get("recent")), "kind": meta["kind"]})
            item.update(status="have", years=have.get("years", 0))
            continue
        if name in tax.SOFT:                       # universal skills: neutral, never reported as a gap
            got += w * 0.6
            item.update(status="soft")
            continue
        rel = [r for r in tax.related(name) if r in prof_skills]
        if rel:
            got += w * 0.5
            related.append({"name": name, "via": rel[0], "kind": meta["kind"]})
            item.update(status="related", via=rel[0], years=ctx_years(prof_skills, rel[0]))
        elif meta["kind"] == "required":
            miss_req.append(name)
        else:
            miss_other.append(name)
    return {"coverage": ((got + 0.5 * _PRIOR_MASS) / (tot + _PRIOR_MASS)) if tot else None, "matched": matched, "related": related,
            "missing_required": miss_req, "missing_other": miss_other, "n": len(job_skills),
            "items": sorted(items, key=lambda i: (-i["weight"], i["status"] != "have", i["name"]))}


def ctx_years(prof_skills: dict, name: str) -> float:
    return float((prof_skills.get(name) or {}).get("years", 0) or 0)


def requirement_evidence(reqs: list[str], index, *, deep: bool = False) -> list[dict]:
    if not index or not reqs:
        return []
    qvecs = None
    method = "lexical"
    if deep and index.has_vectors and index.embed_model:
        qvecs = retrieval.embed(reqs, index.embed_model)
        if qvecs:
            method = "hybrid"
    out = []
    for i, r in enumerate(reqs):
        hits = index.retrieve(r, k=1, qvec=qvecs[i] if qvecs else None)
        best = hits[0] if hits else None
        score = best["score"] if best else 0.0
        status = "met" if score >= 0.5 else "partial" if score >= 0.3 else "gap"
        out.append({"text": r, "score": score, "status": status, "method": method,
                    "evidence": ({"label": best["label"], "section": best["section"], "text": best["text"][:320],
                                  "semantic": best["semantic"]} if best and score >= 0.22 else None)})
    return out


# ---------------------------------------------------------------------------
# context (profile + prefs + config, loaded once per scoring run)
# ---------------------------------------------------------------------------

def load_context(cfg: dict | None = None, *, profile: dict | None = None, index=None, prefs: dict | None = None,
                 priors: dict | None = None) -> dict | None:
    """Everything evaluate() needs. Returns None when there is no resume (callers fall back to keyword scoring)."""
    from src import calibration, profile_store

    prof = profile or profile_store.active_profile()
    if not prof:
        return None
    prefs = prefs or profile_store.get_prefs()
    cfg = cfg or {}
    titles: list[tuple[str, float]] = []
    for t in prefs.get("target_titles", []):
        titles.append((t, 1.0))
    for t in prof.get("target_titles", []) or []:
        titles.append((t, 1.0))
    for t in ((prof.get("llm") or {}).get("target_titles") or []):
        titles.append((t, 0.9))
    for t in prof.get("titles", []):
        titles.append((re.sub(r"\(.*?\)", "", t).strip(), 0.85))
    tg = cfg.get("targets") or {}
    for t in tg.get("tier_1", []):
        titles.append((t, 0.95))
    for t in tg.get("tier_2", []):
        titles.append((t, 0.75))
    return {
        "profile": prof,
        "skills": prof.get("skills", {}),
        "years": float(prof.get("years_experience") or 0),
        "level": LEVELS.get(prof.get("seniority", "mid"), 1.5),
        "titles": titles,
        "domains": set(prof.get("domains", [])),
        "prefs": prefs,
        "index": index if index is not None else profile_store.active_index(),
        "priors": priors or calibration.priors(prefs),
    }


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------

def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def is_local(job: dict) -> bool:
    return bool(job.get("region")) or bool(re.search(r"trinidad|tobago", (job.get("location") or ""), re.I))


def _age_days(job: dict) -> int | None:
    for k in ("posted_at", "first_seen"):
        v = (job.get(k) or "")[:10]
        if v:
            try:
                return (date.today() - date.fromisoformat(v)).days
            except ValueError:
                continue
    return None


def evaluate(job: dict, ctx: dict, *, deep: bool = False) -> dict:
    """Full profile-driven evaluation of one job. `deep` also uses embeddings for requirement evidence."""
    prefs = ctx["prefs"]
    a = analyze_job(job)
    local = is_local(job)
    strengths: list[str] = []
    gaps: list[str] = []
    blockers: list[str] = []
    factors: list[dict] = []

    # ---- components (0..1 each; None = unknown) ---------------------------------
    sk = skill_coverage(a["skills"], ctx["skills"])
    skills_v = sk["coverage"] if sk["n"] >= 2 else (sk["coverage"] if sk["coverage"] is not None else None)
    ev = requirement_evidence(a["requirements"], ctx["index"], deep=deep)
    if ev:
        weights = [1.0 if tax.find_skills(r["text"]) else 0.7 for r in ev]
        evidence_v = sum(r["score"] * w for r, w in zip(ev, weights)) / sum(weights)
        evidence_v = min(1.0, evidence_v * 1.25)  # a chunk matching ~80% of a requirement's terms is a full match
    else:
        evidence_v = None
    title_v, title_why = title_alignment(job.get("title") or "", ctx)

    # experience
    Y, R = ctx["years"], a["min_years"]
    if R is None:
        exp_v = None
    elif Y >= R:
        exp_v = 1.0
    else:
        exp_v = max(0.0, (Y / R)) ** 1.2 if R else 1.0
    if a["entry"] and Y >= 4:
        gaps.append("Posting looks entry-level — you may be overqualified")
        exp_v = min(exp_v if exp_v is not None else 1.0, 0.75)

    # domain
    job_domains = {s for s in a["skills"] if tax.CATEGORY.get(s) in ("Insurance & Finance", "Domains")}
    dom_hit = sorted(job_domains & ctx["domains"])
    domain_v = min(1.0, len(dom_hit) / 2) if job_domains else None
    if dom_hit:
        strengths.append(f"Domain experience: {', '.join(dom_hit[:3])}")

    # preferences alignment
    pref_v, pref_notes = _preference_alignment(job, a, local, prefs, ctx)
    for kind, msg in pref_notes:
        (blockers if kind == "block" else gaps if kind == "gap" else strengths).append(msg)

    # ---- fit --------------------------------------------------------------------
    parts = [("skills", skills_v, 0.32), ("evidence", evidence_v, 0.18), ("title", title_v, 0.20),
             ("experience", exp_v, 0.10), ("domain", domain_v, 0.06), ("preferences", pref_v, 0.14)]
    known = [(n, v, w) for n, v, w in parts if v is not None]
    profile_fit = round(100 * sum(v * w for _, v, w in known) / sum(w for *_, w in known)) if known else 0
    kw_fit = int(job["kw_fit"] if job.get("kw_fit") is not None else (job.get("fit_score") or 0))  # keyword-pass fit, never a blended one
    fit = round(0.7 * profile_fit + 0.3 * kw_fit) if kw_fit or known else profile_fit

    # reliability of the evidence behind the numbers
    signal = (min(sk["n"], 6) / 6) * 0.5 + min(a["desc_chars"], 1500) / 1500 * 0.5
    confidence = "high" if signal >= 0.6 else "medium" if signal >= 0.3 else "low"
    shrink = {"high": 1.0, "medium": 0.85, "low": 0.65}[confidence]

    # ---- strengths / gaps from the pieces ---------------------------------------
    top = sorted((m for m in sk["matched"] if m["kind"] != "nice"), key=lambda m: -m["years"])[:4]
    if top:
        strengths.append("You have: " + ", ".join(f"{m['name']}" + (f" ({m['years']:g}y)" if m["years"] else "") for m in top))
    if sk["related"]:
        strengths.append("Adjacent experience: " + ", ".join(f"{r['name']} (via {r['via']})" for r in sk["related"][:3]))
    for name in sk["missing_required"][:5]:
        gaps.append(f"No {name} on your resume (asked for by the posting)")
    if R and Y < R:
        gaps.append(f"Asks for {R}+ years; your resume shows {Y:g}")
    elif R and Y >= R:
        strengths.append(f"Experience meets the {R}+ year ask ({Y:g} years)")
    if title_v >= 0.75 and title_why:
        strengths.append(f"Title matches your target: {title_why}")
    elif title_v < 0.3:
        gaps.append("Title is outside your target roles")
    unmet = [r for r in ev if r["status"] == "gap"]
    if unmet and len(unmet) >= max(2, len(ev) // 2):
        gaps.append(f"{len(unmet)} of {len(ev)} requirements have no support in your resume")

    # ---- likelihood -------------------------------------------------------------
    adj = 0.0

    def factor(name: str, delta: float, note: str = "") -> None:
        nonlocal adj
        if abs(delta) >= 0.02:
            adj += delta
            factors.append({"name": name, "delta": round(delta, 2), "note": note})

    q_parts = [(skills_v, 0.40), (exp_v, 0.15), (evidence_v, 0.25), (title_v, 0.20)]
    q_known = [(v, w) for v, w in q_parts if v is not None]
    q = sum(v * w for v, w in q_known) / sum(w for _, w in q_known) if q_known else 0.5
    factor("Qualification match", 3.6 * (q - 0.5) * shrink, f"{round(q * 100)}% of what the posting asks for")

    gap = a["level"] - ctx["level"]
    if gap > 0.25:
        factor("Seniority gap", -0.9 * (gap - 0.25), "posting is more senior than your profile")
        gaps.append("Role is more senior than your experience level") if gap >= 1 else None
    elif gap < -1.0:
        factor("Overqualified", -0.4, "posting is junior for your level")

    geo, geo_note = 0.0, ""
    mode, scope = a["work_mode"], a["remote_scope"]
    if local:
        geo_note = "based where you live"
    elif mode == "remote":
        geo = {"worldwide": 0.7, "americas": 0.4, "unknown": 0.0, "us_only": -2.3, "eu_only": -2.0, "canada_only": -2.2}.get(scope, 0.0)
        if a["eor"] and geo < 0.5:
            geo += 0.5
        if scope in ("us_only", "eu_only", "canada_only") and a["sponsorship"] and prefs.get("willing_to_relocate"):
            geo += 1.2
        geo_note = f"remote · {scope or 'unknown'} eligibility"
        if scope in ("us_only", "eu_only", "canada_only"):
            (blockers if not (a["sponsorship"] and prefs.get("willing_to_relocate")) else gaps).append(
                f"Remote but restricted to {scope.replace('_only', '').upper()} residents — you're in Trinidad & Tobago")
        elif scope == "worldwide":
            strengths.append("Open to candidates worldwide" + (" (contractors welcome)" if a["eor"] else ""))
        elif scope == "americas":
            strengths.append("Remote and open to the Americas — your timezone fits")
    elif mode == "unknown":
        geo, geo_note = -0.6, "no location or remote information in the posting"
    elif mode in ("onsite", "hybrid"):
        geo = -0.8 if (a["sponsorship"] and prefs.get("willing_to_relocate")) else -2.5
        geo_note = f"{mode}, outside Trinidad & Tobago"
        if geo < -1:
            blockers.append(f"{mode.title()} role outside Trinidad & Tobago — needs relocation")
    factor("Geographic access", geo, geo_note)

    age = _age_days(job)
    if age is not None:
        factor("Freshness", 0.35 if age <= 3 else 0.1 if age <= 14 else -0.15 if age <= 30 else -0.5, f"posted {age}d ago")
    if pref_v is not None:
        factor("Fits your preferences", 1.0 * (pref_v - 0.6), "work mode, salary, regions")
    if dom_hit:
        factor("Domain edge", 0.3, ", ".join(dom_hit[:2]))

    hard_rx = r"citizen|clearance|permanent residen|phd|10\+ years" + ("" if local else r"|no sponsorship")
    hard = [f for f in (job.get("flags") or "").split(" | ") if re.search(hard_rx, f, re.I) and not re.search(r"\(good\)", f, re.I)]
    for f in hard:
        if f not in blockers:
            blockers.append(f)
    if blockers:
        factor("Blockers", -min(3.6, 1.2 * len(blockers)), "; ".join(blockers[:2])[:100])
    if any(k.lower() in f"{job.get('title', '')} {job.get('description', '')}".lower() for k in prefs.get("avoid_keywords", []) if k):
        hit = next(k for k in prefs["avoid_keywords"] if k.lower() in f"{job.get('title', '')} {job.get('description', '')}".lower())
        blockers.append(f"Mentions “{hit}” (on your avoid list)")
        factor("Avoid list", -2.0, hit)

    prior = ctx["priors"]["local" if local else "remote"]["p"]
    p = min(0.65, _sig(_logit(prior) + adj))
    p_ref = 0.45 if local else 0.22
    likelihood = round(min(1.0, p / p_ref) * 100)
    thr = (65, 40, 20)
    verdict = "High" if likelihood >= thr[0] else "Medium" if likelihood >= thr[1] else "Low" if likelihood >= thr[2] else "Long shot"
    if blockers and verdict in ("High", "Medium"):
        verdict = "Low"

    fit_cap = 25 if any(re.search(r"citizen|clearance|permanent residen|phd", b, re.I) for b in blockers) else 100
    fit = min(fit, fit_cap)

    advice = _advice(verdict, local, blockers, sk, R, Y, a)
    tailoring = _tailoring(ev, sk)

    pct = lambda v: None if v is None else round(v * 100)  # noqa: E731
    return {
        "fit": fit, "fit_profile": profile_fit, "fit_keyword": kw_fit,
        "likelihood": likelihood, "interview_chance": round(p * 100), "verdict": verdict, "confidence": confidence,
        "breakdown": {"skills": pct(skills_v), "evidence": pct(evidence_v), "title": pct(title_v), "experience": pct(exp_v),
                      "domain": pct(domain_v), "preferences": pct(pref_v), "qualification": round(q * 100)},
        "skills": {k: v for k, v in sk.items() if k != "coverage"} | {"coverage": pct(sk["coverage"])},
        "requirements": ev,
        "job": {"work_mode": a["work_mode"], "remote_scope": a["remote_scope"], "min_years": a["min_years"], "level": a["level"],
                "pay": {k: v for k, v in (a["pay"] or {}).items() if not k.startswith("_")} or None, "local": local,
                "eor": a["eor"], "sponsorship": a["sponsorship"], "age_days": age},
        "strengths": strengths[:8], "gaps": gaps[:8], "blockers": blockers[:6], "advice": advice,
        "factors": factors, "tailoring": tailoring, "prior": round(prior * 100, 1), "prior_source": ctx["priors"]["local" if local else "remote"]["source"],
        "method": (ev[0]["method"] if ev else "lexical"),
    }


def _tailoring(ev: list[dict], sk: dict) -> dict:
    """Truthful tailoring advice: which resume bullets to lead with, which keywords you can honestly weave in."""
    lead, seen = [], set()
    for r in sorted(ev, key=lambda r: -r["score"]):
        e = r.get("evidence")
        if r["score"] >= 0.45 and e and e["section"] in ("experience", "projects") and e["text"] not in seen:
            seen.add(e["text"])
            lead.append({"requirement": r["text"][:140], "bullet": e["text"], "where": e["label"]})
        if len(lead) == 3:
            break
    add = []
    for it in sk.get("items", []):
        if it["status"] == "related" and it["kind"] != "nice":
            add.append({"skill": it["name"], "via": it["via"],
                        "advice": f"You have {it['via']}, which is related. Describe it plainly; add {it['name']} only if you have genuinely used it."})
    dont = [it["name"] for it in sk.get("items", []) if it["status"] == "missing" and it["kind"] == "required"]
    return {"lead_with": lead, "add_keywords": add[:5], "do_not_claim": dont[:6]}


def _preference_alignment(job: dict, a: dict, local: bool, prefs: dict, ctx: dict) -> tuple[float | None, list[tuple[str, str]]]:
    notes: list[tuple[str, str]] = []
    wm = prefs.get("work_mode", "both")
    remote = a["work_mode"] == "remote" and not local
    v = 0.8
    if wm == "local_only":
        v = 1.0 if local else 0.05
    elif wm == "remote_only":
        v = 1.0 if remote else 0.05
    elif wm == "local_first":
        v = 1.0 if local else 0.6
    elif wm == "remote_first":
        v = 1.0 if remote else 0.6
    if wm == "local_only" and not local:
        notes.append(("block", "You set “local only” — this role is not in Trinidad & Tobago"))
    if wm == "remote_only" and not remote:
        notes.append(("block", "You set “remote only” — this role is not remote"))
    if local and prefs.get("preferred_regions"):
        if job.get("region") in prefs["preferred_regions"]:
            v = min(1.0, v + 0.15)
            notes.append(("strength", f"In one of your preferred regions ({job['region']})"))
        else:
            v = max(0.0, v - 0.1)
    pay = a["pay"]
    fx = float(prefs.get("fx_ttd_per_usd") or 6.78)
    floor_ttd = prefs.get("min_salary_monthly_ttd") or (prefs.get("min_salary_monthly_usd") or 0) * fx
    if pay and floor_ttd:
        top_ttd = pay["monthly_ttd_max"]
        if top_ttd >= floor_ttd:
            v = min(1.0, v + 0.15)
            notes.append(("strength", f"Pay meets your floor (up to ~TT${top_ttd:,}/mo)"))
        else:
            v = max(0.0, v - 0.35)
            notes.append(("gap", f"Pay tops out around TT${top_ttd:,}/mo, below your TT${int(floor_ttd):,} floor"))
    if not prefs.get("open_to_contract", True) and re.search(r"\bcontract(or)?\b", (job.get("title") or "").lower()):
        v = max(0.0, v - 0.2)
        notes.append(("gap", "Contract role — you prefer permanent"))
    return v, notes


def _advice(verdict: str, local: bool, blockers: list[str], sk: dict, R, Y, a: dict) -> str:
    if blockers:
        return f"Likely a dead end: {blockers[0]}"
    missing = sk["missing_required"][:2]
    if verdict == "High":
        return "Apply this week" + (" — tailor for " + ", ".join(m["name"] for m in sk["matched"][:2]) if sk["matched"] else "")
    if verdict == "Medium":
        return ("Worth applying" + (f"; address {', '.join(missing)} in your letter" if missing else "; lead with your closest project"))
    if verdict == "Low":
        return "Apply only if the company is a priority" + (f"; gaps: {', '.join(missing)}" if missing else "")
    return "Long shot — skim, don't invest a tailored application"


# ---------------------------------------------------------------------------
# glue used by the pipeline
# ---------------------------------------------------------------------------

def highlight_terms(description: str, items: list[dict]) -> list[dict]:
    """The exact words in the posting that name each skill, tagged have / related / missing — for highlighting."""
    out, seen = [], set()
    by_name = {i["name"]: i for i in items if i["status"] != "soft"}
    for canon, rx in tax._ALIAS_RE:
        it = by_name.get(canon)
        if not it:
            continue
        for m in rx.finditer(description or ""):
            t = m.group(0)
            key = t.lower()
            if key not in seen:
                seen.add(key)
                out.append({"text": t, "skill": canon, "status": it["status"]})
    return out


def compact(m: dict) -> str:
    """The subset persisted in jobs.match_json (drops verbose evidence text to keep rows small)."""
    slim = dict(m)
    slim["requirements"] = [{"text": r["text"][:160], "score": r["score"], "status": r["status"],
                             "evidence": (r["evidence"] or {}).get("label") if r["evidence"] else None} for r in m["requirements"]]
    return json.dumps(slim, separators=(",", ":"))


def apply_to_job(job: dict, ctx: dict) -> dict:
    """Score a job in place: blends fit_score, sets likelihood/interview_chance/work_mode/remote_scope/match_json."""
    m = evaluate(job, ctx)
    job["fit_score"] = m["fit"]
    if m["fit"] >= 65:
        job["tier"] = "Tier 1 — apply"
    elif m["fit"] >= 50:
        job["tier"] = "Tier 2 — strong maybe"
    elif m["fit"] >= 35:
        job["tier"] = "Maybe — skim it"
    else:
        job["tier"] = "Low"
    job["likelihood"] = m["likelihood"]
    job["interview_chance"] = m["interview_chance"]
    job["work_mode"] = m["job"]["work_mode"]
    job["remote_scope"] = m["job"]["remote_scope"]
    job["match_json"] = compact(m)
    have = [s["name"] for s in m["skills"]["matched"] if s["kind"] != "nice"][:4]
    bits = []
    if m["breakdown"]["title"] and m["breakdown"]["title"] >= 75:
        bits.append("title matches your targets")
    if have:
        bits.append("you have " + ", ".join(have))
    if m["skills"]["missing_required"]:
        bits.append("missing " + ", ".join(m["skills"]["missing_required"][:2]))
    job["why"] = "; ".join(bits) or job.get("why") or "limited overlap"
    # the keyword pass flags tech mentions without knowing your resume; the profile-derived skills/gaps replace those
    _tech_mentions = ("Mentions LLM evals", "Mentions a modern data stack", "Frontend framework mentioned", "Mentions Kubernetes")
    existing = [f for f in (job.get("flags") or "").split(" | ") if f and not f.startswith(_tech_mentions)]
    job["flags"] = " | ".join(dict.fromkeys(existing + m["blockers"]))
    return job


_CTX: dict = {"t": 0.0, "ctx": None, "key": None}


def get_context(cfg: dict | None = None, ttl: float = 5.0) -> dict | None:
    """Cached load_context() — scoring calls this once per job. None when no resume has been added."""
    import time
    now = time.time()
    key = id(cfg)
    if _CTX["t"] and now - _CTX["t"] < ttl and _CTX["key"] == key:
        return _CTX["ctx"]
    try:
        ctx = load_context(cfg)
    except Exception:  # noqa: BLE001  (db not ready, corrupt profile…) — fall back to keyword scoring
        ctx = None
    _CTX.update(t=now, ctx=ctx, key=key)
    return ctx


def current_context(deep_cfg: bool = True) -> dict | None:
    """The scoring context using the on-disk profile config (targets etc.). None if no resume has been added."""
    try:
        from src import config
        return get_context(config.load_profile())
    except Exception:  # noqa: BLE001
        return get_context(None)


def resume_text() -> str:
    """Full text of the active resume ('' if none)."""
    from src import profile_store
    p = profile_store.active_profile()
    return profile_store.get_resume_text(p["_resume_id"]) if p else ""


def reset_context() -> None:
    _CTX.update(t=0.0, ctx=None, key=None)
