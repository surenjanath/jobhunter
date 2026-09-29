"""
Resolves which resume/preferences/pipeline a request should use: a signed-in account's own private data, or the
shared/anonymous data every earlier version of this app used — unchanged for anyone who never signs up.

Deliberately NOT reusing src.matching's get_context()/current_context() cache for accounts: that cache is one
module-level dict keyed loosely by id(cfg), fine for a single shared profile but unsafe for several accounts'
contexts racing through the same process. Account contexts are built fresh via matching.load_context() each time
they're needed instead (cheap — no network, no embeddings by default).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from django.utils import timezone

ROOT = Path(__file__).resolve().parent.parent.parent / "jobhunt"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_CTX_CACHE: dict[int, tuple[float, dict | None]] = {}
_CTX_TTL = 5.0


def has_profile(user) -> bool:
    return bool(getattr(user, "is_authenticated", False)) and hasattr(user, "profile") and bool(user.profile.data)


def build_context(user) -> dict | None:
    """The full matching context for this account's own resume (cached briefly per user id — a rescore or a
    Ledger page load touches many jobs in one request). None if they haven't uploaded a resume."""
    if not has_profile(user):
        return None
    now = time.time()
    hit = _CTX_CACHE.get(user.id)
    if hit and now - hit[0] < _CTX_TTL:
        return hit[1]
    from src import matching, retrieval
    up = user.profile
    prefs = {**DEFAULT_PREFS(), **(up.preferences or {})}
    chunks = retrieval.chunk_profile(up.resume_text or "", up.data) if up.resume_text else []
    index = retrieval.ResumeIndex(chunks, "")   # keyword (BM25) retrieval only for account profiles — no embeddings
    ctx = matching.load_context(profile=up.data, prefs=prefs, index=index, priors=priors_for_user(user, prefs))
    _CTX_CACHE[user.id] = (now, ctx)
    return ctx


def invalidate(user) -> None:
    _CTX_CACHE.pop(getattr(user, "id", None), None)


def DEFAULT_PREFS() -> dict:
    from src import profile_store
    return dict(profile_store.DEFAULT_PREFS)


def matching_context(request):
    """What every view should score jobs against: the signed-in account's own resume if it has one, else the
    shared instance-wide profile (identical to today's behaviour when nobody is signed in)."""
    from src import matching
    user = getattr(request, "user", None)
    if user is not None and has_profile(user):
        return build_context(user)
    return matching.current_context()


# ---------------------------------------------------------------------------
# per-account calibration — the same idea as src.calibration.priors(), sourced from this account's own
# UserJobStatus rows instead of the shared scanner database's app_status table.
# ---------------------------------------------------------------------------

def priors_for_user(user, prefs: dict | None = None) -> dict:
    from datetime import date
    from src import calibration
    from jobs.models import Job
    from .models import UserJobStatus

    rows = list(UserJobStatus.objects.filter(
        user=user, status__in=("Applied", "Interviewing", "Interview", "Offer", "Rejected")))
    out = {"local": {"pos": 0, "neg": 0, "pending": 0}, "remote": {"pos": 0, "neg": 0, "pending": 0}}
    if rows:
        job_ids = [r.job_id for r in rows]
        regions = {}
        for jid, region, location in Job.objects.using("jobhunt").filter(job_id__in=job_ids).values_list("job_id", "region", "location"):
            regions[jid] = bool(region) or "trinidad" in (location or "").lower()
        for r in rows:
            local = regions.get(r.job_id, False)
            g = out["local" if local else "remote"]
            if r.status in calibration.POSITIVE:
                g["pos"] += 1
            elif r.status == "Rejected":
                g["neg"] += 1
            else:
                when = (r.applied_date or "")[:10]
                try:
                    age = (date.today() - date.fromisoformat(when)).days if when else 0
                except ValueError:
                    age = 0
                g["neg" if age >= calibration.STALE_DAYS else "pending"] += 1
    result = {}
    for kind in ("local", "remote"):
        g = out[kind]
        n = g["pos"] + g["neg"]
        base = calibration.DEFAULT[kind]
        if n:
            p = (base * calibration.STRENGTH + g["pos"]) / (calibration.STRENGTH + n)
            result[kind] = {"p": round(min(max(p, 0.003), 0.6), 4), "n": n, "pending": g["pending"],
                           "positives": g["pos"], "source": f"your history ({n} decided applications)"}
        else:
            result[kind] = {"p": base, "n": 0, "pending": g["pending"], "positives": 0, "source": "default prior (no outcomes recorded yet)"}
    return result


# ---------------------------------------------------------------------------
# per-account rescore — mirrors /api/rescore/ (src.matching.apply_to_job over every stored job), but writes to
# UserJobMatch instead of the shared jobs table, and reads jobs via the Django ORM rather than the scanner db API.
# ---------------------------------------------------------------------------

def rescore_user(user) -> int:
    """Score every stored job against this account's own resume. Returns how many jobs were scored (0 if the
    account has no resume yet)."""
    invalidate(user)
    ctx = build_context(user)
    if not ctx:
        return 0
    from src import matching
    from jobs.models import Job
    from .models import UserJobMatch

    import json as _json
    now = timezone.now()
    rows = []
    for job in Job.objects.using("jobhunt").all().iterator(chunk_size=200):
        try:
            kw_fit = _json.loads(job.match_json).get("fit_keyword", job.fit_score) if job.match_json else job.fit_score
        except ValueError:
            kw_fit = job.fit_score
        d = {"job_id": job.job_id, "title": job.title, "company": job.company, "location": job.location,
            "remote": bool(job.remote), "salary": job.salary, "description": job.description,
            "region": job.region, "posted_at": job.posted_at, "first_seen": job.first_seen, "flags": job.flags,
            "fit_score": job.fit_score, "kw_fit": kw_fit}
        try:
            m = matching.evaluate(d, ctx)
        except Exception:  # noqa: BLE001 — one bad row must not sink the whole rescore
            continue
        rows.append(UserJobMatch(user=user, job_id=job.job_id, fit_score=m["fit"], likelihood=m["likelihood"],
                                 interview_chance=m["interview_chance"], match_json=matching.compact(m), updated_at=now))
    UserJobMatch.objects.filter(user=user).delete()
    UserJobMatch.objects.bulk_create(rows, batch_size=500)
    return len(rows)


# ---------------------------------------------------------------------------
# pipeline overlay — used by jobs/views.py + jobs/queries.serialize() to show/store each account's own status,
# star, notes and fit/odds instead of the one shared table every view used before accounts existed.
# ---------------------------------------------------------------------------

class _GuestMap(dict):
    """.get(anything) -> jobs.queries.UNSET, always — so a guest's serialize(job, *status_map.get(...)) calls
    fall back to the shared scanner-db data exactly as if no override had been passed at all, rather than a
    plain {}.get() returning None (which serialize() would read as "signed in, but nothing for this job")."""
    def get(self, key, default=None):
        from jobs.queries import UNSET
        return UNSET


def overlay_for(request, job_ids: list[str]) -> tuple[dict, dict]:
    """(status_by_job_id, match_by_job_id) for this account and these jobs — pass straight through to
    jobs.queries.serialize(job, status_map.get(job.job_id), match_map.get(job.job_id)); guest requests get maps
    that always report UNSET, so a guest's own code path never changes."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return _GuestMap(), _GuestMap()
    if not job_ids:
        return {}, {}
    from .models import UserJobMatch, UserJobStatus
    status = {s.job_id: s for s in UserJobStatus.objects.filter(user=user, job_id__in=job_ids)}
    match = {m.job_id: m for m in UserJobMatch.objects.filter(user=user, job_id__in=job_ids)}
    return status, match


def set_status(user, job_id: str, **fields) -> "UserJobStatus":  # noqa: F821 (quoted forward ref)
    """Write one job's status/star/notes/etc. for this account. `dismiss_reason` clears itself automatically
    when `status` moves away from "Passed on it" and no explicit reason is given — same rule as the shared
    app_status table (src.db.update_status)."""
    from .models import UserJobStatus
    if "status" in fields and fields["status"] != "Passed on it" and "dismiss_reason" not in fields:
        fields["dismiss_reason"] = ""
    row, _ = UserJobStatus.objects.update_or_create(user=user, job_id=job_id, defaults=fields)
    return row
