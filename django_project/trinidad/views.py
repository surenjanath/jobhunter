"""Trinidad & Tobago local-market endpoints: summary, employers, board registry/health, custom sites."""
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from django.db.models import Avg, Count, Max, Q
from rest_framework.decorators import api_view
from rest_framework.response import Response

from jobs.models import Job, SourceRun

ROOT = Path(__file__).resolve().parent.parent.parent / "jobhunt"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB = "jobhunt"
SLUG = re.compile(r"^[a-z0-9_]{2,30}$")


def _local():
    return Job.objects.using(DB).exclude(region="")


def _profile():
    from core.settings_store import _load_yaml
    return _load_yaml()


@api_view(["GET"])
def local_summary(request):
    """Snapshot of the whole local market: totals, regions, categories, employers, freshness."""
    try:
        qs = _local()
        today = date.today()
        iso = lambda d: d.isoformat()  # noqa: E731
        total = qs.count()
        by_region = list(qs.values("region").annotate(n=Count("job_id"), avg_fit=Avg("fit_score")).order_by("-n"))
        by_category = list(qs.values("category").annotate(n=Count("job_id")).order_by("-n"))
        by_source = list(qs.values("source").annotate(n=Count("job_id")).order_by("-n"))
        employers = list(qs.exclude(company__in=["Unknown", "Confidential", "Employer Confidential"])
                         .values("company").annotate(n=Count("job_id"), best=Max("fit_score")).order_by("-n")[:15])
        return Response({
            "total": total,
            "new_7d": qs.filter(first_seen__gte=iso(today - timedelta(days=7))).count(),
            "new_today": qs.filter(first_seen=iso(today)).count(),
            "closing_7d": qs.filter(expires_at__gte=iso(today), expires_at__lte=iso(today + timedelta(days=7))).count(),
            "with_salary": qs.exclude(salary="").count(),
            "relevant": qs.filter(fit_score__gte=50).count(),
            "by_region": [{"region": r["region"], "count": r["n"], "avg_fit": round(r["avg_fit"] or 0)} for r in by_region],
            "by_category": [{"category": r["category"] or "Other", "count": r["n"]} for r in by_category],
            "by_source": [{"source": r["source"], "count": r["n"]} for r in by_source],
            "top_employers": [{"company": r["company"], "count": r["n"], "best_fit": r["best"]} for r in employers],
        })
    except Exception as e:
        return Response({"error": str(e), "total": 0, "by_region": [], "by_category": [], "by_source": [],
                         "top_employers": []}, status=500)


@api_view(["GET"])
def employers(request):
    """Local employers ranked by open roles. ?q= filters by name."""
    q = (request.GET.get("q") or "").strip()
    qs = _local().exclude(company="Unknown")
    if q:
        qs = qs.filter(company__icontains=q)
    rows = qs.values("company").annotate(n=Count("job_id"), best=Max("fit_score"),
                                         regions=Count("region", distinct=True)).order_by("-n", "company")[:100]
    return Response({"employers": [{"company": r["company"], "open_roles": r["n"], "best_fit": r["best"],
                                    "regions": r["regions"]} for r in rows]})


def _registry():
    """All known boards (built-in + custom) with enabled flag, latest health and stored job counts."""
    from src import trinidad as tt
    prof = _profile()
    flags = prof.get("sources", {}) or {}
    master = flags.get("trinidad", True)
    runs = {}
    for r in SourceRun.objects.using(DB).all()[:400]:
        d = runs.setdefault(r.name, {"latest": r, "last_success": None})
        if r.ok and d["last_success"] is None:
            d["last_success"] = r.ran_at
    counts = {r["source"]: r["n"] for r in _local().values("source").annotate(n=Count("job_id"))}
    out = []

    def row(name, label, url, kind, enabled, custom=False):
        run = runs.get(name)
        latest = run["latest"] if run else None
        return {
            "name": name, "label": label, "url": url, "kind": kind, "custom": custom,
            "enabled": bool(enabled and master),
            "jobs": counts.get(name, 0),
            "last_run": latest.ran_at if latest else "",
            "ok": latest.ok if latest else None,
            "last_count": latest.count if latest else None,
            "ms": latest.ms if latest else None,
            "error": latest.error if latest else "",
            "last_success": run["last_success"] if run else "",
            "status": ("never run" if not latest else "error" if not latest.ok
                       else "empty" if latest.count == 0 else "healthy"),
        }

    for s in tt.TT_SOURCES.values():
        out.append(row(s.name, s.label, s.url, s.kind, flags.get(s.config_key, True)))
    for site in tt.custom_sites(prof):
        nm = re.sub(r"[^a-z0-9_]+", "", site["name"].lower())
        out.append(row(nm, site.get("label") or site["name"], site.get("sitemap") or site.get("list_url") or (f"{site['ats']}: {site.get('slug') or site.get('tenant')}" if site.get("ats") else ""),
                       "custom", True, custom=True))
    return out, master


@api_view(["GET"])
def sources(request):
    """Trinidad job boards: enabled flag, last scan outcome, stored job counts. Toggle via PUT /api/settings/."""
    try:
        rows, master = _registry()
        healthy = sum(1 for r in rows if r["enabled"] and r["status"] == "healthy")
        return Response({"enabled": master, "sources": rows,
                         "summary": {"total": len(rows), "enabled": sum(1 for r in rows if r["enabled"]),
                                     "healthy": healthy,
                                     "failing": sum(1 for r in rows if r["enabled"] and r["status"] == "error")}})
    except Exception as e:
        return Response({"error": str(e), "sources": []}, status=500)


@api_view(["POST"])
def test_source(request, name):
    """Run one board's fetcher live (small sample) and report what it found. Does not write to the database."""
    from src import trinidad as tt
    src = tt.TT_SOURCES.get(name)
    site = None
    if not src:
        site = next((s for s in tt.custom_sites(_profile()) if re.sub(r"[^a-z0-9_]+", "", s["name"].lower()) == name), None)
        if not site:
            return Response({"error": f"unknown source {name!r}"}, status=404)
    limit = 5
    try:
        limit = max(1, min(int(request.data.get("limit", 5)), 15))
    except (TypeError, ValueError):
        pass
    fn = (lambda: src.fn(limit)) if src else (lambda: tt.fetch_custom_site(site, limit))
    rows = tt.run_source(name, fn, src.label if src else name)
    h = tt.HEALTH[name]
    return Response({"ok": h["ok"], "count": h["count"], "ms": h["ms"], "error": h["error"],
                     "sample": [{k: r[k] for k in ("title", "company", "location", "region", "category", "posted_at",
                                                    "expires_at", "salary", "url")} for r in rows[:limit]]})


def _validate_site(data):
    name = re.sub(r"[^a-z0-9_]+", "", str(data.get("name", "")).lower())
    if not SLUG.match(name):
        raise ValueError("name must be 2-30 letters/digits")
    from src import trinidad as tt
    if name in tt.TT_SOURCES:
        raise ValueError(f"{name!r} is a built-in board")
    site = {"name": name, "label": str(data.get("label") or data.get("name") or name)[:60]}
    ats = str(data.get("ats") or "").lower()
    if ats:
        from src import ats_sources
        if ats not in ats_sources.KINDS:
            raise ValueError(f"ats must be one of {', '.join(ats_sources.KINDS)}")
        site["ats"] = ats
        need = ("tenant", "site") if ats == "workday" else ("slug",)
        for k in need:
            v = str(data.get(k) or "").strip()
            if not re.match(r"^[A-Za-z0-9_.-]{1,80}$", v):
                raise ValueError(f"{ats} needs a valid {k}")
            site[k] = v
        if ats == "workday":
            site["wd"] = int(data.get("wd") or 1)
            if data.get("search"):
                site["search"] = str(data["search"])[:60]
        if data.get("all_locations"):
            site["all_locations"] = True
        if data.get("company"):
            site["company"] = str(data["company"])[:100]
        return site
    for key in ("sitemap", "list_url"):
        v = str(data.get(key) or "").strip()
        if v:
            if not re.match(r"^https?://[^\s]+$", v):
                raise ValueError(f"{key} must be an http(s) url")
            site[key] = v
    if not (site.get("sitemap") or site.get("list_url")):
        raise ValueError("provide a sitemap or list_url")
    pat = str(data.get("url_pattern") or "/jobs?/").strip()
    try:
        re.compile(pat)
    except re.error as exc:
        raise ValueError(f"url_pattern is not a valid regex: {exc}")
    site["url_pattern"] = pat
    if data.get("company"):
        site["company"] = str(data["company"])[:100]
    return site


@api_view(["POST"])
def detect_site(request):
    """Paste an employer's careers URL: find which applicant-tracking system it uses (and how many T&T jobs it has)."""
    from src import ats_sources
    url = str((request.data or {}).get("url") or "").strip()
    if not url or len(url) > 300:
        return Response({"error": "give the employer's careers page URL"}, status=400)
    found = ats_sources.detect(url)
    for c in found:
        if c.get("ats"):
            try:
                c["sample"] = len(ats_sources.fetch({**c, "name": "probe"}, 50))
            except Exception as e:  # noqa: BLE001
                c["sample"] = 0
                c["error"] = str(e)[:160]
    return Response({"url": url, "candidates": found,
                     "hint": "" if found else "No known applicant-tracking system found on that page. Try the employer's jobs/careers page, or add its job sitemap manually."})


@api_view(["POST"])
def test_custom_site(request):
    """Dry-run a candidate custom site definition without saving it."""
    from src import trinidad as tt
    try:
        site = _validate_site(request.data or {})
    except ValueError as e:
        return Response({"ok": False, "error": str(e)}, status=400)
    rows = tt.run_source(site["name"], lambda: tt.fetch_custom_site(site, 5), site["label"])
    h = tt.HEALTH[site["name"]]
    return Response({"ok": h["ok"] and h["count"] > 0, "count": h["count"], "error": h["error"] or ("" if h["count"] else "no JobPosting data found"),
                     "sample": [{k: r[k] for k in ("title", "company", "location", "region", "url")} for r in rows[:5]]})


@api_view(["GET", "POST", "DELETE"])
def custom_sites(request):
    """List / add / remove user-defined Trinidad sites (any site publishing schema.org JobPosting data)."""
    from core.settings_store import _load_yaml, _save_yaml
    from src import trinidad as tt
    prof = _load_yaml()
    sites = list(prof.get("trinidad_custom_sites") or [])
    if request.method == "GET":
        return Response({"sites": sites})
    if request.method == "POST":
        try:
            site = _validate_site(request.data or {})
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        if any(s.get("name") == site["name"] for s in sites):
            return Response({"error": f"{site['name']!r} already exists"}, status=409)
        rows = tt.run_source(site["name"], lambda: tt.fetch_custom_site(site, 3), site["label"])
        if not rows and not (request.data or {}).get("force"):
            h = tt.HEALTH[site["name"]]
            return Response({"error": h["error"] or "no JobPosting data found on that site (send force=true to save anyway)",
                             "tested": True}, status=422)
        sites.append(site)
        prof["trinidad_custom_sites"] = sites
        _save_yaml(prof)
        return Response({"ok": True, "site": site, "sample_count": len(rows)}, status=201)
    name = str((request.data or {}).get("name") or request.GET.get("name") or "").lower()
    keep = [s for s in sites if s.get("name") != name]
    if len(keep) == len(sites):
        return Response({"error": "not found"}, status=404)
    prof["trinidad_custom_sites"] = keep
    _save_yaml(prof)
    return Response({"ok": True, "removed": name})
