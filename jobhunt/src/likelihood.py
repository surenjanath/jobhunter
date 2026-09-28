"""
likelihood.py — estimate the chance you actually get this job.

Unlike fit_score (keyword triage), this is calibrated to your real resume
and the Role Fit Map. It answers: "If you apply, what are your odds?"

It reads:
  - config/profile.yaml (targets, scoring weights)
  - config/fact_bank.md (honest gaps)
  - the active resume (profile_store)
  - the job dict itself

Output per job:
  likelihood  0-100
  verdict     "High" / "Medium" / "Low" / "Long shot"
  breakdown   dict of 0-100 sub-scores
  strengths   [str]  why you have an edge
  gaps        [str]  what you'd need to learn / what's missing
  blockers    [str]  hard dealbreakers
  advice      str    one-line next step
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "config" / "profile.yaml"
FACT_BANK = ROOT / "config" / "fact_bank.md"


def _load_profile() -> dict:
    try:
        return yaml.safe_load(PROFILE.read_text()) or {}
    except Exception:
        return {}


def _skill_set(profile: dict) -> dict[str, int]:
    """Merged strong+context signals as a quick skill inventory."""
    out: dict[str, int] = {}
    for k, v in (profile.get("scoring", {}).get("strong_signals") or {}).items():
        out[k.lower()] = v
    for k, v in (profile.get("scoring", {}).get("context_signals") or {}).items():
        out[k.lower()] = v
    return out


# Canonical gaps from fact_bank / Role Fit Map
KNOWN_GAPS = {
    "evals": {"keywords": ["eval", "observability", "tracing", "langsmith", "langfuse"], "msg": "No formal LLM eval / observability harness (your #1 gap for AI roles)", "penalty": 18},
    "modern_data": {"keywords": ["dbt", "airflow", "dagster", "snowflake", "databricks", "spark"], "msg": "No modern data stack (dbt/Airflow/Snowflake) — you use n8n/pandas/GH Actions", "penalty": 15},
    "frontend": {"keywords": ["react", "typescript", "next.js", "vue", "frontend"], "msg": "No TypeScript/React depth — Django templates only", "penalty": 12},
    "k8s": {"keywords": ["kubernetes", "k8s", "terraform", " Helm"], "msg": "No K8s/Terraform at scale — you run servers directly (nginx/Docker)", "penalty": 10},
    "team": {"keywords": ["mentoring", "led a team", "managed engineers", "staff engineer", "tech lead"], "msg": "Never worked on an engineering team — no code review / mentoring history", "penalty": 8},
}

# Tier calibration from Role Fit Map
TIER1_TITLES = [
    "forward deployed", "solutions engineer", "solutions architect",
    "implementation engineer", "automation engineer", "founding engineer",
    "product engineer", "backend engineer python", "django developer", "internal tools"
]
TIER2_TITLES = ["ai engineer", "llm engineer", "machine learning", "data engineer", "analytics engineer", "platform engineer"]

DOMAIN_BONUS = ["insurance", "insurtech", "fintech", "healthtech", "claims", "underwriting", "actuarial", "risk", "compliance"]


def _contains_any(blob: str, keywords: list[str]) -> bool:
    b = blob.lower()
    return any(k.lower() in b for k in keywords)


def _experience_years_required(blob: str) -> int | None:
    # look for "5+ years", "3-5 years", etc.
    m = re.search(r"(\d+)\s*\+?\s*years", blob.lower())
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def rate(job: dict, profile: dict | None = None, deep: bool = False) -> dict:
    """Return likelihood dict for a single job.

    With a resume on file this is the profile-driven model in matching.py (evidence per requirement, remote
    eligibility, your preferences and outcome history). The heuristic below is only the no-resume fallback.
    """
    try:
        from src import matching
        ctx = matching.get_context(profile if isinstance(profile, dict) and "targets" in profile else None)
        if ctx:
            m = matching.evaluate(job, ctx, deep=deep)
            m["model"] = "profile"
            return m
    except Exception:  # noqa: BLE001
        pass
    profile = profile or _load_profile()
    blob = f"{job.get('title','')} {job.get('description','')} {job.get('location','')}".lower()
    title = (job.get("title") or "").lower()

    # Start from fit_score if present, else compute a quick proxy
    base = int(job.get("fit_score", 50))

    breakdown: dict[str, int] = {}
    strengths: list[str] = []
    gaps: list[str] = []
    blockers: list[str] = []

    # 1. Skill match (0-100) — strong signals vs negative
    strong_hits = []
    for phrase, weight in (profile.get("scoring", {}).get("strong_signals") or {}).items():
        if phrase.lower() in blob:
            strong_hits.append(phrase)
    neg_hits = []
    for phrase, weight in (profile.get("scoring", {}).get("negative_signals") or {}).items():
        if phrase.lower() in blob:
            neg_hits.append(phrase)
    skill = 60
    skill += min(len(strong_hits) * 7, 30)
    skill -= min(len(neg_hits) * 6, 35)
    # bonus for python/django core which you definitely have
    if "python" in blob and "django" in blob:
        skill += 8
        strengths.append("Python/Django core — strong keyword overlap with your profile")
    if "insurance" in blob or "insurtech" in blob:
        skill += 10
        strengths.append("Domain overlap with your profile's bonus domains")
    if "llm" in blob or "rag" in blob or "agent" in blob:
        # you have this but with gaps
        skill += 5
        strengths.append("Multi-agent RAG claims system (LLM advises, rules engine decides) — in testing")
    skill = max(0, min(100, skill))
    breakdown["skill_match"] = skill

    # 2. Experience fit
    yrs_req = _experience_years_required(blob)
    have = int(profile.get("candidate", {}).get("years_experience", 5))
    exp = 70
    if yrs_req is not None:
        if yrs_req <= have:
            exp = 85
            strengths.append(f"Experience bar {yrs_req}+ yrs — you have {have} yrs")
        elif yrs_req <= have + 2:
            exp = 60
            gaps.append(f"Asks {yrs_req}+ yrs — a stretch from your {have} yrs (but ownership helps)")
        else:
            exp = 30
            blockers.append(f"Asks {yrs_req}+ yrs — likely auto-screened")
            gaps.append(f"Seniority gap ({yrs_req}+ yrs required)")
    else:
        exp = 75
    # penalize "senior" that really means 8+
    if "senior" in title and yrs_req is None:
        exp = min(exp, 70)
    breakdown["experience"] = exp

    # 3. Domain advantage
    domain = 50
    dom_hit = next((d for d in DOMAIN_BONUS if d.lower() in blob), None)
    if dom_hit:
        domain = 85
        strengths.append(f"Domain match: {dom_hit} — your insurance depth is rare")
    elif "fintech" in blob or "healthtech" in blob:
        domain = 70
    # tech domain with no insurance = neutral
    breakdown["domain"] = domain

    # 4. Title tier (Role Fit Map calibration)
    tier = 50
    if any(t in title for t in TIER1_TITLES):
        tier = 88
        strengths.append("Tier-1 title for you (FDE / Solutions / Automation / Founding — per Role Fit Map)")
    elif any(t in title for t in TIER2_TITLES):
        tier = 62
        gaps.append("Tier-2 title — reachable in 3-9 mo with targeted proof (ship eval harness / dbt)")
    else:
        tier = 45
        if "engineer" not in title and "developer" not in title:
            tier = 30
            gaps.append("Title not in your target lanes — likely poor fit")
    breakdown["title_fit"] = tier

    # 5. Geography / work authorization
    geo = 60
    loc = blob
    source = (job.get("source") or "").lower()
    is_trinidad = bool(job.get("region")) or any(x in source for x in ["findworktt","jobstt","trinidadjob","caribbeanjobs","employtt","islandjobhunt","caribbeanjobsonline","evecaribbean","digicel"]) or any(x in loc for x in ["trinidad","tobago","port of spain","san fernando","chaguanas","couva","point lisas","arima"])
    if is_trinidad:
        geo = 92
        strengths.append("Local T&T job — no visa, no relocation, you're already there (best geography)")
        # Local salary will be lower, but geography is perfect
        if "tt$" in loc or "ttd" in loc:
            gaps.append("Local T&T salary in TTD — expect 70-80% below US remote contractor rates")
    elif any(x in loc for x in ["remote", "anywhere", "distributed", "work from home", "latam", "eor", "employer of record", "utc-4", "eastern"]):
        geo = 85
        strengths.append("Remote / EOR / LATAM-friendly — your UTC-4 overlap is an asset")
    if "us citizen" in loc or "citizen only" in loc or "security clearance" in loc:
        geo = 10
        blockers.append("US-citizen / clearance required — hard blocker from T&T")
    elif not is_trinidad and ("onsite" in loc or "hybrid" in loc):
        geo = 40
        gaps.append("On-site / hybrid — likely requires relocation from T&T")
    elif "visa sponsorship" in loc:
        geo = 75
        strengths.append("Mentions visa sponsorship (good signal)")
    breakdown["geography"] = geo

    # 6. Gaps scan
    for key, info in KNOWN_GAPS.items():
        if _contains_any(blob, info["keywords"]):
            gaps.append(info["msg"])
            # penalize skill and overall
            skill = max(0, skill - 4)
            breakdown["skill_match"] = skill

    # 7. Hard blockers (from score.py HARD_BLOCKERS)
    if "phd required" in blob:
        blockers.append("PhD required")
    if re.search(r"\b(1[0-9]|[2-9][0-9])\+?\s*years", blob) and yrs_req and yrs_req >= 10:
        blockers.append("Asks 10+ years — likely filtered")
    if "no sponsorship" in blob or "no visa" in blob:
        blockers.append("Explicitly no sponsorship — hard blocker")

    # Overall likelihood — weighted blend calibrated to Role Fit Map
    # Weights: skill 30%, title 25%, geography 20%, experience 15%, domain 10%
    # Then apply blocker penalty and gap penalties
    overall = (
        skill * 0.30 +
        tier * 0.25 +
        geo * 0.20 +
        exp * 0.15 +
        domain * 0.10
    )
    # Blend with base fit_score slightly so keyword signal still matters
    overall = overall * 0.85 + base * 0.15

    # Penalties
    for b in blockers:
        if "citizen" in b.lower() or "clearance" in b.lower() or "no sponsorship" in b.lower():
            overall = min(overall, 15)
        elif "10+" in b:
            overall = min(overall, 25)
    if len([g for g in gaps if "No modern data" in g or "No LLM eval" in g]) >= 2:
        overall -= 8
    if is_non_eng_title(title):
        overall = min(overall, 15)

    overall = max(0, min(100, int(round(overall))))

    # Verdict
    if blockers and overall <= 20:
        verdict = "Long shot"
    elif overall >= 70:
        verdict = "High"
    elif overall >= 50:
        verdict = "Medium"
    elif overall >= 35:
        verdict = "Low"
    else:
        verdict = "Long shot"

    # Advice
    if verdict == "High":
        advice = "Apply now — you're competitive. Tailor 1st paragraph to the most relevant build (FDE → ownership, insurtech → domain)."
    elif verdict == "Medium":
        advice = "Apply selectively — you can win with a strong, specific letter that acknowledges one gap honestly."
    elif verdict == "Low":
        if any("eval" in g.lower() for g in gaps):
            advice = "Low today — ship an eval harness for the claims agents and re-apply in 3-4 weeks."
        elif any("modern data" in g.lower() for g in gaps):
            advice = "Low — build one public project that uses the missing skills and link it from your resume."
        else:
            advice = "Low — likely filtered on title/stack. Focus on Tier-1 lanes instead."
    else:
        advice = "Long shot — hard blocker (citizenship/clearance/10+ yrs). Skip unless posting is mis-tagged."

    # Deduplicate
    strengths = list(dict.fromkeys(strengths))[:4]
    gaps = list(dict.fromkeys(gaps))[:5]
    blockers = list(dict.fromkeys(blockers))[:3]

    return {
        "likelihood": overall,
        "verdict": verdict,
        "breakdown": breakdown,
        "strengths": strengths,
        "gaps": gaps,
        "blockers": blockers,
        "advice": advice,
        "yrs_req": yrs_req,
    }


def is_non_eng_title(title: str) -> bool:
    non = ("human resources", "people operations", "talent", "recruiter", "people & culture", "people and culture")
    t = title.lower()
    return any(p in t for p in non) and "engineer" not in t and "developer" not in t


def stored(job: dict) -> dict | None:
    """The likelihood dict saved with the job at scan time (jobs.match_json), or None if it was never profile-scored."""
    raw = job.get("match_json")
    if not raw:
        return None
    try:
        import json
        m = json.loads(raw)
    except ValueError:
        return None
    m["likelihood"] = int(job.get("likelihood") or m.get("likelihood") or 0)
    m["interview_chance"] = int(job.get("interview_chance") or m.get("interview_chance") or 0)
    m["model"] = "profile"
    return m


def batch(jobs: list[dict], profile: dict | None = None) -> list[dict]:
    """Attach likelihood to each job dict (mutates). Uses the scan-time result when there is one — recomputing
    the profile model for hundreds of jobs on every dashboard request is far too slow."""
    prof = profile or _load_profile()
    for j in jobs:
        j["likelihood"] = stored(j) or rate(j, prof)
    # sort by likelihood desc
    jobs.sort(key=lambda x: x["likelihood"]["likelihood"], reverse=True)
    return jobs
