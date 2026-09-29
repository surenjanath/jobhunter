"""Station brief for the conditions report.

Pure function. Views attach likelihood, then this shapes the page.
"""

from __future__ import annotations

import re
from datetime import date, datetime


STAGES = (
    "New",
    "Shortlisted",
    "Applied",
    "Interviewing",
    "Offer",
    "Rejected",
    "Passed on it",
)

BLOCKER = (
    "clearance",
    "citizens only",
    "citizen",
    "permanent residency",
    "no sponsorship",
)


def gap_advice(gap: str) -> str:
    """What to actually do about the most common gap — it depends on the kind of gap."""
    m = re.match(r"No (.+?) on your resume", gap)
    if m:
        return (f"If you've used {m.group(1)}, add it to your resume and re-score; if you haven't, "
                f"it's the skill to learn next (Analytics shows how many roles it would unlock).")
    if gap.startswith("Asks for"):
        return "Check your years of experience are read correctly on the Profile page; if they are, favour roles at your level."
    if "target roles" in gap:
        return "Tighten your search terms in Settings, or add the titles you'd genuinely accept to your targets."
    if "relocation" in gap.lower() or "outside Trinidad" in gap:
        return "Filter to Local or Remote on the Ledger, or hide blockers, to focus on roles you can take."
    return f"Look at the best-fit roles with “{gap}” and decide whether it's fixable on your resume."


def _like(job: dict) -> dict:
    raw = job.get("likelihood") or {}
    if isinstance(raw, dict) and "likelihood" in raw:
        return raw
    score = int(job.get("fit_score") or 0)
    if score >= 75:
        verdict = "High"
    elif score >= 60:
        verdict = "Medium"
    elif score >= 45:
        verdict = "Low"
    else:
        verdict = "Long shot"
    return {
        "likelihood": score,
        "verdict": verdict,
        "blockers": [],
        "gaps": [],
        "advice": "",
    }


def _blocked(job: dict) -> bool:
    blob = f"{job.get('flags') or ''} {' '.join(_like(job).get('blockers') or [])}".lower()
    return any(k in blob for k in BLOCKER)


def _parse_day(value: str) -> date | None:
    text = (value or "").strip()[:10]
    if len(text) < 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _source(job: dict) -> str:
    return ((job.get("source") or "unknown").split(":")[0] or "unknown").strip()


def build_brief(jobs: list[dict] | None, *, letters: int = 0, generated: str | None = None, today: date | None = None) -> dict:
    """Shape a conditions report from job dicts.

    Each job may include likelihood, app_status, and followup_date.
    Missing likelihood falls back to fit_score so the page still renders.
    """
    today = today or date.today()
    rows = list(jobs or [])
    ranked = sorted(rows, key=lambda j: _like(j)["likelihood"], reverse=True)
    total = len(rows)
    tier1 = sum(1 for j in rows if int(j.get("fit_score") or 0) >= 65)
    blocked = [j for j in rows if _blocked(j)]
    highs = [j for j in ranked if _like(j)["verdict"] == "High"]
    lead = ranked[0] if ranked else None
    nxt = ranked[1] if len(ranked) > 1 else None
    likes = [_like(j)["likelihood"] for j in ranked]
    avg = round(sum(likes) / len(likes)) if likes else 0

    by_status = {name: 0 for name in STAGES}
    due = []
    for job in rows:
        status = job.get("app_status") or "New"
        if status not in by_status:
            status = "New"
        by_status[status] += 1
        day = _parse_day(job.get("followup_date") or "")
        if day and day <= today and status not in ("Rejected", "Passed on it", "Offer"):
            due.append(job)
    due.sort(key=lambda j: j.get("followup_date") or "")

    sources: dict[str, list[int]] = {}
    for job in rows:
        sources.setdefault(_source(job), []).append(int(job.get("fit_score") or 0))
    source_rows = []
    for name, scores in sources.items():
        source_rows.append({
            "source": name,
            "count": len(scores),
            "avg": round(sum(scores) / len(scores)) if scores else 0,
        })
    source_rows.sort(key=lambda r: (r["avg"], r["count"]), reverse=True)

    # count gaps only among roles worth pursuing: across every listing, "Title is outside your target roles" always
    # wins (most scraped jobs aren't yours) and says nothing about what to do next
    relevant = [j for j in ranked if int(j.get("fit_score") or 0) >= 50] or ranked
    gap_counts: dict[str, int] = {}
    for job in relevant:
        for gap in _like(job).get("gaps") or []:
            key = gap.split(" —")[0].split(" (")[0].strip()
            if key:
                gap_counts[key] = gap_counts.get(key, 0) + 1
    top_gap = max(gap_counts, key=gap_counts.get) if gap_counts else ""

    def _card(job: dict | None) -> dict | None:
        if not job:
            return None
        like = _like(job)
        return {
            "job_id": job.get("job_id") or "",
            "title": job.get("title") or "",
            "company": job.get("company") or "",
            "likelihood": like["likelihood"],
            "verdict": like["verdict"],
            "fit_score": int(job.get("fit_score") or 0),
            "advice": like.get("advice") or "",
            "gaps": list(like.get("gaps") or [])[:3],
            "blockers": list(like.get("blockers") or []),
            "status": job.get("app_status") or "New",
            "posted_at": job.get("posted_at") or "",
            "followup_date": job.get("followup_date") or "",
            "url": job.get("url") or "",
            "blocked": _blocked(job),
        }

    compare = [_card(j) for j in ranked[:3]]
    open_high = next((j for j in highs if (j.get("app_status") or "New") in ("New", "Shortlisted")), None)

    if not rows:
        warning = "No roles yet. Run a scan to fill this report."
        warning_on = True
        nxt_action = "Run a scan."
    elif blocked and len(blocked) >= max(3, total // 5):
        warning = f"{len(blocked)} postings ask for clearance, citizenship, or no sponsorship."
        warning_on = True
        nxt_action = "Hide blockers, then apply to the highest open role."
    elif top_gap:
        n_gap = gap_counts[top_gap]
        warning = f"Repeating gap in {n_gap} of your {len(relevant)} best-fit roles: {top_gap}."
        warning_on = True
        nxt_action = gap_advice(top_gap)
    else:
        warning = "No hard blockers in the current cut."
        warning_on = False
        nxt_action = "Shortlist the top three and draft the first letter."

    if due:
        first = due[0]
        nxt_action = f"Follow up with {first.get('company') or 'the oldest application'}."
    elif open_high:
        nxt_action = f"Apply to {open_high.get('title')} at {open_high.get('company')}."

    verdicts = ["High", "Medium", "Low", "Long shot"]
    mix = []
    for name in verdicts:
        count = sum(1 for j in ranked if _like(j)["verdict"] == name)
        mix.append({"label": name, "count": count, "pct": round(count / total * 100) if total else 0})

    in_motion = by_status["Applied"] + by_status["Interviewing"]
    lead_fit = int(lead.get("fit_score") or 0) if lead else 0

    return {
        "empty": total == 0,
        "generated": generated,
        "letters": letters,
        "conditions": [
            {"label": "Roles", "value": str(total)},
            {"label": "Tier 1", "value": str(tier1)},
            {"label": "Lead fit", "value": str(lead_fit) if lead else "—"},
            {
                "label": "Best odds",
                "value": f"{_like(lead)['likelihood']}%" if lead else "—",
                "detail": f"@ {len(highs)} high" if lead else "",
            },
        ],
        "hero": {
            "likelihood": _like(lead)["likelihood"] if lead else None,
            "prior": _like(nxt)["likelihood"] if nxt else None,
            "average": avg,
            "high_count": len(highs),
            "job": _card(lead),
        },
        "warning": {"on": warning_on, "text": warning, "blocked": len(blocked)},
        "compare": compare,
        "extended": {
            "mix": mix,
            "lead_fit": lead_fit,
            "due": len(due),
            "due_jobs": [_card(j) for j in due[:5]],
            "in_motion": in_motion,
            "letters": letters,
            "sources": source_rows[:5],
        },
        "pipeline": by_status,
        "top_gap": top_gap,
        "next_action": nxt_action,
        "odds": [
            {
                "job_id": job.get("job_id") or "",
                "likelihood": _like(job)["likelihood"],
                "verdict": _like(job)["verdict"],
                "advice": (_like(job).get("advice") or ""),
            }
            for job in rows
            if isinstance(job.get("likelihood"), dict)
        ],
    }
