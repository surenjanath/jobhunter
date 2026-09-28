"""
score.py — rank postings against the profile.

The score is deliberately blunt. It is a triage tool, not a judgement: its only
job is to float the 15 jobs worth reading to the top of a list of 800.

Output per job:
    fit_score   0-100
    tier        Tier 1 / Tier 2 / Maybe / Low
    why         short human-readable rationale
    flags       dealbreakers or things to check before applying
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# Phrases that should stop you applying, or at least make you read carefully.
HARD_BLOCKERS = [
    (r"security clearance|ts/sci|top secret", "Requires security clearance"),
    (r"must be (a )?(us|u\.s\.) citizen|citizens only", "US citizens only"),
    (r"green card|permanent resident only", "Requires US permanent residency"),
    (r"\b(1[0-9]|[2-9][0-9])\+? years", "Asks for 10+ years experience"),
    (r"phd required|ph\.d\. required", "PhD required"),
    (r"no (visa )?sponsorship", "Explicitly no sponsorship"),
]

SOFT_FLAGS = [
    (r"\bhybrid\b", "Hybrid — check if remote is negotiable"),
    (r"\bon-?site\b", "Mentions on-site"),
    (r"\brelocat", "Mentions relocation"),
    (r"visa sponsor", "Mentions visa sponsorship (good)"),
    (r"employer of record|\beor\b|deel|remote\.com|oyster", "Hires internationally via EOR (good)"),
    (r"latam|latin america|caribbean|americas time ?zone|utc-[3-6]", "Timezone-friendly (good)"),
    (r"\bevals?\b|evaluation harness|observability|tracing", "Mentions LLM evals / observability (check the Match tab)"),
    (r"\bdbt\b|airflow|dagster|snowflake|databricks", "Mentions a modern data stack (dbt, Airflow, Snowflake…)"),
    (r"typescript|react\b|next\.js", "Frontend framework mentioned (TypeScript / React)"),
    (r"kubernetes|\bk8s\b|terraform", "Mentions Kubernetes / Terraform"),
]


LOCAL_PLACE_SIGNALS = {
    "caribbean", "trinidad", "tobago", "trinidad and tobago", "port of spain", "san fernando",
    "chaguanas", "couva", "point lisas", "arima",
}


_HUMAN_AGENT = re.compile(
    r"\b(sales|customer|guest relations|insurance|travel|real estate|call cent\w*|support|service|"
    r"direct sales|shipping|booking|ticket\w*|field|estate|talent|leasing)\s+agents?\b")


def _count(text: str, phrase: str) -> int:
    """Whole-word-ish occurrence count, capped so one spammy word can't dominate."""
    pattern = r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"
    return min(len(re.findall(pattern, text)), 3)


def score_job(job: dict, cfg: dict) -> dict:
    """Attach fit_score / tier / why / flags to a job dict. Returns the job."""
    scoring = cfg.get("scoring", {})
    blob = f"{job.get('title','')} {job.get('description','')} {job.get('location','')}".lower()
    title = (job.get("title") or "").lower()

    # Quick title relevance guard: if the title is clearly non-engineering
    # (e.g. HR, People, Recruiter) then cap the score early. This prevents
    # HR roles that mention "remote" etc from floating into Tier 1.
    non_eng_titles = ("human resources", "people operations", "talent", "recruiter", "hr ", "hr,", "people & culture", "people and culture")
    is_non_eng = any(p in title for p in non_eng_titles) and "engineer" not in title and "developer" not in title

    raw = 0
    geo_raw = 0
    skill_raw = 0  # positive evidence the role matches the candidate (skills / work-style), not geography
    hits: list[str] = []

    # "agent" is an AI-agent signal; human job titles ("sales agent", "guest relations agent") are not.
    ai_blob = _HUMAN_AGENT.sub(" ", blob)

    for group in ("strong_signals", "context_signals"):
        for phrase, weight in (scoring.get(group) or {}).items():
            n = _count(ai_blob if phrase.lower() in ("agent", "agents") else blob, phrase.lower())
            if n:
                # Place names only say "it's local", not "it fits me". They are held back and only
                # count when the role also matches a skill / title / domain (see below).
                if group == "context_signals" and phrase.lower() in LOCAL_PLACE_SIGNALS:
                    geo_raw += weight * n
                    continue
                raw += weight * n
                if group == "strong_signals":
                    skill_raw += max(weight, 0) * n
                if weight >= 7:
                    hits.append(phrase)

    for phrase, weight in (scoring.get("negative_signals") or {}).items():
        n = _count(blob, phrase.lower())
        if n:
            raw += weight * n  # weights are already negative

    mods = scoring.get("modifiers", {})
    targets = cfg.get("targets", {})

    tier_1_hit = any(t.lower() in title for t in targets.get("tier_1", []))
    tier_2_hit = any(t.lower() in title for t in targets.get("tier_2", []))
    if tier_1_hit:
        raw += mods.get("tier_1_title_match", 0)
    elif tier_2_hit:
        raw += mods.get("tier_2_title_match", 0)

    domain_hit = next(
        (d for d in cfg.get("bonus_domains", []) if _count(blob, d.lower())), None
    )
    if domain_hit:
        raw += mods.get("bonus_domain_match", 0)
        hits.append(f"domain:{domain_hit}")

    if job.get("salary"):
        raw += mods.get("salary_disclosed", 0)

    # A local role that matches nothing about the candidate must not ride to 80+ on geography alone.
    if skill_raw >= 8 or tier_1_hit or tier_2_hit:
        raw += geo_raw
    elif geo_raw:
        raw += min(geo_raw, 10)

    # Squash into 0-100. The divisor sets how hard a 100 is to reach; raise it
    # if too many jobs land in Tier 1, lower it if the sheet looks empty.
    divisor = scoring.get("score_divisor", 165)
    fit = max(0, min(100, round(raw / divisor * 100)))

    flags = [msg for pat, msg in HARD_BLOCKERS if re.search(pat, blob)]
    blocked = bool(flags)
    flags += [msg for pat, msg in SOFT_FLAGS if re.search(pat, blob)]

    if is_non_eng:
        flags.append("Non-engineering title — likely false positive")
        fit = min(fit, 20)

    if blocked:
        fit = min(fit, 25)

    if fit >= 65:
        tier = "Tier 1 — apply"
    elif fit >= 50:
        tier = "Tier 2 — strong maybe"
    elif fit >= 35:
        tier = "Maybe — skim it"
    else:
        tier = "Low"

    why_bits = []
    if tier_1_hit:
        why_bits.append("Tier-1 title")
    elif tier_2_hit:
        why_bits.append("Tier-2 title")
    if domain_hit:
        why_bits.append(f"{domain_hit} domain")
    uniq = list(dict.fromkeys(h for h in hits if not h.startswith("domain:")))[:6]
    if uniq:
        why_bits.append("matches: " + ", ".join(uniq))

    job["fit_score"] = fit
    job["tier"] = tier
    job["why"] = "; ".join(why_bits) or "keyword overlap only"
    job["flags"] = " | ".join(dict.fromkeys(flags))

    # With a resume on file, replace the keyword-only picture with the profile-driven one (skills you actually
    # have, requirement evidence, remote eligibility, preferences). Without one, the keyword score stands.
    try:
        from src import matching
        ctx = matching.get_context(cfg)
        if ctx:
            matching.apply_to_job(job, ctx)
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("profile matching failed for %s: %r", job.get("job_id"), exc)
    return job


# How much to trust a source's URL. Higher wins when the same role appears
# on several boards.
#
# This matters more than it looks. Aggregators pad descriptions with company
# boilerplate, so "keep the longest description" reliably picked the aggregator
# copy and threw away the company's own application link. Aggregator listing
# pages go stale fast: once a role is filled the link 404s or bounces to a
# generic search page, which is exactly the "wrong link" symptom.
SOURCE_TRUST = {
    "greenhouse": 100,   # company's own ATS, direct apply URL
    "lever": 100,
    "ashby": 100,
    "hn_whoishiring": 60,  # links to the comment, which is genuinely the source
    "himalayas": 40,
    "weworkremotely": 35,
    "jobicy": 35,
    "workingnomads": 30,
    "getonboard": 35,
    "jooble": 60,
    "arbeitnow": 35,
    "remotive": 30,
    "remoteok": 30,
    # Trinidad & Tobago local — direct local apply, high trust for local roles
    "findworktt": 90,
    "jobstt": 85,
    "trinidadjob": 85,
    "caribbeanjobs": 80,
    "employtt": 95,
    "digicel": 100,        # employer's own careers site
    "evecaribbean": 85,
    "islandjobhunt": 75,
    "caribbeanjobsonline": 70,
}


def _trust(job: dict) -> int:
    src = (job.get("source") or "").split(":")[0]
    if src in SOURCE_TRUST:
        return SOURCE_TRUST[src]
    return 70 if job.get("region") else 20  # custom Trinidad sites carry a region


def dedupe(jobs: list[dict]) -> list[dict]:
    """
    Collapse the same role appearing on several boards.

    Merges rather than picking a winner: the URL comes from the most trusted
    source (the company's own ATS if it's there), while the description comes
    from whichever copy is longest, since that's what scoring reads. Any other
    listings are kept in `alt_urls` as a fallback.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for job in jobs:
        company = re.sub(r"[^a-z0-9]", "", (job.get("company") or "").lower())
        title = re.sub(r"[^a-z0-9]", "", (job.get("title") or "").lower())
        if not title:
            continue
        groups.setdefault((company, title), []).append(job)

    merged: list[dict] = []
    for copies in groups.values():
        # Most trusted source wins the link; ties broken by richer description.
        canonical = max(copies, key=lambda j: (_trust(j), len(j.get("description") or "")))
        richest = max(copies, key=lambda j: len(j.get("description") or ""))

        job = dict(canonical)
        if len(richest.get("description") or "") > len(job.get("description") or ""):
            job["description"] = richest["description"]
        if not job.get("salary"):
            job["salary"] = next((c.get("salary") for c in copies if c.get("salary")), "")
        if not job.get("posted_at"):
            job["posted_at"] = next((c.get("posted_at") for c in copies if c.get("posted_at")), "")

        others = [c["url"] for c in copies if c.get("url") and c["url"] != job.get("url")]
        job["alt_urls"] = " | ".join(dict.fromkeys(others))
        job["seen_on"] = ", ".join(
            dict.fromkeys((c.get("source") or "").split(":")[0] for c in copies)
        )
        merged.append(job)

    return merged


def _too_old(job: dict, max_age_days: int) -> bool:
    posted = job.get("posted_at")
    if not posted:
        return False  # unknown date — keep it, don't guess
    try:
        dt = datetime.fromisoformat(posted).replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return dt < datetime.now(timezone.utc) - timedelta(days=max_age_days)


def rank(jobs: list[dict], cfg: dict) -> list[dict]:
    """Dedupe, score, filter, sort. This is the whole pipeline in one call."""
    min_score = cfg.get("min_score_to_include", 35)
    max_age = cfg.get("max_age_days", 30)

    # Local (Trinidad) postings are kept regardless of fit so the whole local market is browsable;
    # they still rank by fit_score. Set keep_all_trinidad: false to filter them like everything else.
    keep_local = cfg.get("keep_all_trinidad", True)
    scored = [score_job(j, cfg) for j in dedupe(jobs)]
    kept = [
        j
        for j in scored
        if (j["fit_score"] >= min_score or (keep_local and j.get("region")))
        and j.get("url") and not _too_old(j, max_age)
    ]
    kept.sort(key=lambda j: (-j["fit_score"], j.get("company", "")))
    return kept
