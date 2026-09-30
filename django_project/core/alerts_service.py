"""Build and send the alert for one pipeline (an account's, or the shared guest one). Used by `manage.py send_alerts`
and the Settings page's 'Send a test alert' / 'Send now' buttons. Delivery itself is jobhunt/src/alerts.py."""
from __future__ import annotations

import os
from datetime import date, timedelta

CLOSED = ("Rejected", "Passed on it", "Offer")


class _Req:
    """Just enough of a request for accounts.context.pipeline_statuses()."""
    def __init__(self, user):
        from django.contrib.auth.models import AnonymousUser
        self.user = user or AnonymousUser()


def gather(user=None, days: int = 2, min_fit: int | None = None, limit: int = 10) -> dict:
    from accounts.context import pipeline_statuses
    from jobs import queries
    from jobs.models import Job
    from src import digest
    from .models import AlertSent
    min_fit = min_fit if min_fit is not None else int(os.environ.get("JOBHUNTER_ALERT_MIN_FIT") or 55)
    pipe = pipeline_statuses(_Req(user))
    jobs = list(queries.base_queryset())
    rows = [{**{f.attname: getattr(j, f.attname) for f in Job._meta.concrete_fields},
             "app_status": (pipe[j.job_id].status if j.job_id in pipe else "New")} for j in jobs]
    sent = set(AlertSent.objects.values_list("job_id", flat=True))
    d = digest.build(days, min_fit, 50, rows=rows)
    picks = [p for p in d.get("picks") or [] if p["job_id"] not in sent][:limit]
    today = date.today().isoformat()
    by_id = {j.job_id: j for j in jobs}
    followups = [{"title": by_id[k].title, "company": by_id[k].company, "followup_date": v.followup_date}
                 for k, v in pipe.items() if k in by_id and v.followup_date and v.followup_date <= today and v.status not in CLOSED]
    soon = (date.today() + timedelta(days=3)).isoformat()
    closing = [{"title": j.title, "company": j.company, "expires_at": j.expires_at} for j in jobs
               if j.job_id in pipe and (pipe[j.job_id].starred or pipe[j.job_id].status not in ("New",) + CLOSED)
               and j.expires_at and today <= j.expires_at <= soon]
    return {"picks": picks, "followups": followups, "closing": closing}


def run(user=None, dry_run: bool = False) -> dict:
    from src import alerts
    from .models import AlertSent
    g = gather(user)
    site = f"https://{os.environ['RENDER_EXTERNAL_HOSTNAME']}/" if os.environ.get("RENDER_EXTERNAL_HOSTNAME") else os.environ.get("JOBHUNTER_SITE_URL", "")
    msg = alerts.compose(g["picks"], g["followups"], g["closing"], site)
    if not msg:
        return {"sent": False, "reason": "nothing new", "counts": {k: len(v) for k, v in g.items()}}
    if dry_run:
        return {"sent": False, "reason": "dry run", "message": msg, "counts": {k: len(v) for k, v in g.items()}}
    if not any(alerts.channels().values()):
        return {"sent": False, "reason": "no alert channel configured (see docs/ALERTS.md)", "message": msg}
    result = alerts.send(msg)
    if any(v == "sent" for v in result.values()):
        for p in g["picks"]:
            AlertSent.objects.get_or_create(job_id=p["job_id"])
    return {"sent": any(v == "sent" for v in result.values()), "channels": result, "counts": {k: len(v) for k, v in g.items()}}


def owner_user():
    """On a hosted copy the alerts follow the owner's account; locally (no owner set) the shared pipeline."""
    email = os.environ.get("JOBHUNTER_OWNER_EMAIL", "").strip().lower()
    if not email:
        return None
    from django.contrib.auth.models import User
    return User.objects.filter(username=email).first()
