"""Shared job querying: filters, sorting and row serialisation used by the list, export and summary endpoints."""
import json
from datetime import date, timedelta

from django.db.models import Case, IntegerField, Q, Value, When

from .models import Job

DB = "jobhunt"

SORTS = {
    "fit": ("-fit_score", "company"),
    "likelihood": ("-likelihood", "-fit_score"),
    "chance": ("-interview_chance", "-fit_score"),
    "recent": ("-posted_at", "-first_seen"),
    "new": ("-first_seen", "-fit_score"),
    "closing": ("expires_at", "-fit_score"),   # empties sorted last in apply_filters
    "company": ("company", "-fit_score"),
    "title": ("title", "company"),
}

TRUTHY = ("1", "true", "yes", "on", "only")
FALSY = ("0", "false", "no", "off", "hide")


def base_queryset():
    return Job.objects.using(DB).select_related("applicationstatus")


def _multi(params, key):
    """?region=a&region=b and ?region=a,b both work."""
    vals = []
    for v in params.getlist(key) if hasattr(params, "getlist") else [params.get(key, "")]:
        vals += [x.strip() for x in (v or "").split(",") if x.strip()]
    return vals


def _iso_days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def apply_filters(qs, params):
    """Apply the standard job filters from a QueryDict-like `params`."""
    search = (params.get("search") or "").strip()
    if search:
        q = Q()
        for word in search.split():  # every word must match somewhere
            q &= (Q(title__icontains=word) | Q(company__icontains=word) | Q(location__icontains=word)
                  | Q(description__icontains=word) | Q(region__icontains=word) | Q(category__icontains=word))
        qs = qs.filter(q)

    sources = _multi(params, "source")
    if sources:
        q = Q()
        for s in sources:
            q |= Q(source__startswith=s)
        qs = qs.filter(q)

    tier = (params.get("tier") or "").strip()
    if tier in ("65", "50"):
        qs = qs.filter(fit_score__gte=int(tier))
    min_score = params.get("min_score")
    if min_score:
        try:
            qs = qs.filter(fit_score__gte=int(min_score))
        except ValueError:
            pass

    # Work-mode switch: local (Trinidad & Tobago) | remote | hybrid | onsite | all
    mode = (params.get("mode") or "").strip().lower()
    if mode == "local":
        qs = qs.exclude(region="")
    elif mode == "remote":
        qs = qs.filter(region="").filter(Q(work_mode="remote") | Q(remote=True))
    elif mode in ("hybrid", "onsite"):
        qs = qs.filter(work_mode=mode)
    elif mode == "abroad":   # on-site / hybrid roles outside Trinidad & Tobago
        qs = qs.filter(region="", work_mode__in=["onsite", "hybrid"])
    scope = _multi(params, "remote_scope")
    if scope:
        qs = qs.filter(remote_scope__in=scope)
    min_lik = params.get("min_likelihood")
    if min_lik:
        try:
            qs = qs.filter(likelihood__gte=int(min_lik))
        except ValueError:
            pass

    remote = (params.get("remote") or "all").strip().lower()
    if remote in ("only", "true", "1", "remote"):
        qs = qs.filter(remote=True)
    elif remote in ("hide", "false", "0", "no"):
        qs = qs.filter(remote=False)

    # Trinidad & Tobago local postings are the ones with a region.
    local = (params.get("local") or "").strip().lower()
    if local in TRUTHY:
        qs = qs.exclude(region="")
    elif local in FALSY:
        qs = qs.filter(region="")

    regions = _multi(params, "region")
    if regions:
        qs = qs.filter(region__in=regions)
    cats = _multi(params, "category")
    if cats:
        qs = qs.filter(category__in=cats)
    company = (params.get("company") or "").strip()
    if company:
        qs = qs.filter(company__iexact=company)

    posted_within = params.get("posted_within")
    if posted_within:
        try:
            qs = qs.filter(Q(posted_at__gte=_iso_days_ago(int(posted_within))) | Q(first_seen__gte=_iso_days_ago(int(posted_within))))
        except ValueError:
            pass

    closing = params.get("closing_within")
    if closing:
        try:
            qs = qs.filter(expires_at__gte=date.today().isoformat(),
                           expires_at__lte=(date.today() + timedelta(days=int(closing))).isoformat())
        except ValueError:
            pass

    has_salary = (params.get("has_salary") or "").lower()
    if has_salary in TRUTHY:
        qs = qs.exclude(salary="")

    status = _multi(params, "status")
    if status:
        q = Q(applicationstatus__status__in=[s for s in status if s != "New"])
        if "New" in status:
            q |= Q(applicationstatus__isnull=True) | Q(applicationstatus__status="New")
        qs = qs.filter(q)
    if (params.get("starred") or "").lower() in TRUTHY:
        qs = qs.filter(applicationstatus__starred=True)
    if (params.get("hide_blockers") or "").lower() in TRUTHY:
        qs = qs.filter(Q(flags="") | ~Q(flags__icontains="citizen"))

    return qs


def apply_sort(qs, params):
    key = (params.get("sort") or "fit").strip().lower()
    order = SORTS.get(key, SORTS["fit"])
    if key == "closing":  # jobs with no expiry go last
        qs = qs.annotate(_no_expiry=Case(When(expires_at="", then=Value(1)), default=Value(0),
                                         output_field=IntegerField()))
        return qs.order_by("_no_expiry", *order)
    return qs.order_by(*order)


def days_left(expires_at: str):
    if not expires_at:
        return None
    try:
        return (date.fromisoformat(expires_at) - date.today()).days
    except ValueError:
        return None


def verdict(likelihood: int) -> str:
    return "High" if likelihood >= 65 else "Medium" if likelihood >= 40 else "Low" if likelihood >= 20 else "Long shot"


def fit_keyword(job: Job):
    """The keyword-only fit stored inside match_json (jobs.fit_score is the blended value)."""
    if not job.match_json:
        return None
    try:
        return json.loads(job.match_json).get("fit_keyword")
    except ValueError:
        return None


def _likelihood(job: Job):
    """{likelihood, verdict, interview_chance, advice, blockers…} from the stored profile match (None if never scored)."""
    if not job.match_json:
        return None
    try:
        m = json.loads(job.match_json)
    except ValueError:
        return None
    return {"likelihood": job.likelihood, "verdict": m.get("verdict") or verdict(job.likelihood),
            "interview_chance": job.interview_chance, "advice": m.get("advice", ""), "blockers": m.get("blockers", []),
            "confidence": m.get("confidence", ""), "fit_profile": m.get("fit_profile"), "fit_keyword": m.get("fit_keyword")}


def serialize(job: Job) -> dict:
    try:
        st = job.applicationstatus
    except Exception:
        st = None
    return {
        "job_id": job.job_id, "source": job.source, "title": job.title, "company": job.company,
        "location": job.location, "remote": bool(job.remote), "salary": job.salary, "url": job.url,
        "description": job.description, "posted_at": job.posted_at, "fit_score": job.fit_score,
        "tier": job.tier, "why": job.why, "flags": job.flags, "alt_urls": job.alt_urls,
        "seen_on": job.seen_on, "first_seen": job.first_seen,
        "region": job.region, "category": job.category, "expires_at": job.expires_at,
        "likelihood": _likelihood(job), "likelihood_score": job.likelihood, "interview_chance": job.interview_chance,
        "work_mode": job.work_mode, "remote_scope": job.remote_scope, "has_match": bool(job.match_json),
        "days_left": days_left(job.expires_at),
        "app_status": (st.status if st else "New") or "New",
        "starred": bool(st.starred) if st else False,
        "followup_date": (st.followup_date if st else "") or "",
        "notes": (st.notes if st else "") or "",
        "applied_date": (st.applied_date if st else "") or "",
    }
