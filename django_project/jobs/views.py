from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import Job, Scan, CoverLetter
from django.http import JsonResponse
import subprocess, threading, os, json, sys
from pathlib import Path
from datetime import date, datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent.parent / "jobhunt"
PYTHON = sys.executable

# keep track of running jobs (same as Flask)
_running = {"task": None, "logs": [], "returncode": None}
_lock = threading.Lock()
_letter = {"busy": False, "job_id": "", "text": "", "path": "", "backend": "", "error": "", "job": {}}

def _append(line: str):
    with _lock:
        _running["logs"].append(line.rstrip("\n"))
        if len(_running["logs"]) > 800:
            del _running["logs"][:-800]

def _run(task, cmd):
    _running["task"] = task
    _running["returncode"] = None
    _append(f"$ {' '.join(cmd[1:])}")
    scan_id = None
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        from src import db as _db
        scan_id = _db.create_scan()
    except Exception:
        _db = None
    try:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env={**os.environ, "PYTHONUNBUFFERED":"1"})
        for line in proc.stdout:
            _append(line)
        proc.wait()
        _running["returncode"] = proc.returncode
        _append(f"--- finished, exit code {proc.returncode} ---")
    except Exception as e:
        _running["returncode"] = -1
        _append(f"!!! failed: {e!r}")
    finally:
        if scan_id and _db is not None:
            import re
            kept = 0
            for line in _running["logs"]:
                m = re.search(r"Persisted (\d+) jobs", line)
                if m:
                    kept = int(m.group(1))
            status = "done" if _running["returncode"] == 0 else "error"
            err = "" if status == "done" else f"exit {_running['returncode']}"
            try:
                _db.finish_scan(scan_id, kept, kept, status, err)
            except Exception:
                pass
        _running["task"] = None

@api_view(["GET"])
def health(request):
    try:
        cnt = Job.objects.using("jobhunt").count()
        return Response({"ok": True, "jobs": cnt, "backend": "django+sqlite", "time": datetime.now().isoformat()})
    except Exception as e:
        return Response({"ok": False, "error": str(e)}, status=500)

@api_view(["GET"])
def stats(request):
    try:
        from django.db.models import Count
        qs = Job.objects.using("jobhunt")
        total = qs.count()
        tier1 = qs.filter(fit_score__gte=65).count()
        tier2 = qs.filter(fit_score__gte=50, fit_score__lt=65).count()
        by_src = {}
        for row in qs.values("source").annotate(n=Count("job_id")):
            key = row["source"].split(":")[0]
            by_src[key] = by_src.get(key, 0) + row["n"]
        local = qs.exclude(region="").count()
        return Response({"total": total, "tier1": tier1, "tier2": tier2, "by_source": by_src,
                         "local": local, "remote": qs.filter(remote=True).count()})
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
def job_list(request):
    """Paginated jobs. Filters: search, source, tier, min_score, remote, local, region, category, company,
    posted_within, closing_within, has_salary, status, starred, hide_blockers. Sort: fit|recent|new|closing|company|title.
    page_size (max 200)."""
    from rest_framework.pagination import PageNumberPagination
    from . import queries
    qs = queries.apply_sort(queries.apply_filters(queries.base_queryset(), request.GET), request.GET)
    paginator = PageNumberPagination()
    paginator.page_size = 50
    paginator.page_size_query_param = "page_size"
    paginator.max_page_size = 200
    try:
        page = paginator.paginate_queryset(qs, request)
    except Exception as e:  # e.g. missing table on a fresh install — always JSON
        return Response({"error": f"db error: {e}"}, status=500)
    return paginator.get_paginated_response([queries.serialize(j) for j in page])


@api_view(["GET"])
def job_export(request):
    """CSV download of the filtered job list (same filters as /api/jobs/)."""
    import csv
    from django.http import HttpResponse
    from . import queries
    qs = queries.apply_sort(queries.apply_filters(queries.base_queryset(), request.GET), request.GET)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="jobhunter-{datetime.now():%Y-%m-%d}.csv"'
    cols = ["fit_score", "tier", "title", "company", "region", "location", "category", "salary", "source",
            "posted_at", "expires_at", "app_status", "starred", "followup_date", "notes", "url", "job_id"]
    w = csv.DictWriter(resp, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for job in qs[:5000]:
        w.writerow(queries.serialize(job))
    return resp


@api_view(["POST"])
def bulk_status(request):
    """{"job_ids": [...], "status": "Applied"} — move many jobs at once."""
    from django.utils import timezone
    from .models import ApplicationStatus
    ids = request.data.get("job_ids")
    status_val = request.data.get("status")
    if not isinstance(ids, list) or not ids or not status_val:
        return Response({"error": "job_ids (list) and status required"}, status=400)
    if len(ids) > 500:
        return Response({"error": "max 500 jobs per request"}, status=400)
    now = timezone.now().isoformat()
    done = 0
    for job in Job.objects.using("jobhunt").filter(pk__in=ids):
        st = ApplicationStatus.objects.using("jobhunt").filter(pk=job.job_id).first()
        prev = (st.status if st else "New") or "New"
        ApplicationStatus.objects.using("jobhunt").update_or_create(
            job_id=job.job_id, defaults={"status": status_val, "updated_at": now})
        try:
            from core.models import StatusEvent
            StatusEvent.objects.create(job_id=job.job_id, title=job.title, company=job.company,
                                       from_status=prev, to_status=status_val, note="bulk update")
        except Exception:
            pass
        done += 1
    return Response({"ok": True, "updated": done, "status": status_val})


@api_view(["POST"])
def job_star(request, job_id):
    """Toggle (or set with {"starred": true|false}) the star on a job."""
    from django.utils import timezone
    from .models import ApplicationStatus
    if not Job.objects.using("jobhunt").filter(pk=job_id).exists():
        return Response({"error": "not found"}, status=404)
    want = request.data.get("starred") if isinstance(request.data, dict) else None
    st = ApplicationStatus.objects.using("jobhunt").filter(pk=job_id).first()
    if want is None:
        want = not (st.starred if st else False)
    ApplicationStatus.objects.using("jobhunt").update_or_create(
        job_id=job_id, defaults={"starred": bool(want), "updated_at": timezone.now().isoformat()})
    return Response({"ok": True, "job_id": job_id, "starred": bool(want)})


@api_view(["GET"])
def followups(request):
    """Jobs needing attention: overdue / upcoming follow-ups, and tracked jobs closing soon."""
    from . import queries
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=int(request.GET.get("days", 7) or 7))).isoformat()
    qs = queries.base_queryset()
    due = qs.exclude(applicationstatus__followup_date="").filter(applicationstatus__followup_date__lte=soon)
    tracked = qs.filter(Q(applicationstatus__starred=True) | Q(applicationstatus__status__in=["Shortlisted", "Applied", "Interviewing", "Interview", "Offer"]))   # positive match: jobs with no status row are not tracked
    closing = tracked.exclude(expires_at="").filter(expires_at__gte=today, expires_at__lte=soon)
    ser = queries.serialize
    overdue = [ser(j) for j in due.filter(applicationstatus__followup_date__lt=today).order_by("applicationstatus__followup_date")]
    upcoming = [ser(j) for j in due.filter(applicationstatus__followup_date__gte=today).order_by("applicationstatus__followup_date")]
    return Response({"overdue": overdue, "upcoming": upcoming, "closing_soon": [ser(j) for j in closing.order_by("expires_at")],
                     "counts": {"overdue": len(overdue), "upcoming": len(upcoming), "closing_soon": closing.count()}})


@api_view(["GET"])
def pipeline(request):
    """Application funnel: how many jobs sit in each status."""
    from django.db.models import Count
    from .models import ApplicationStatus
    order = ["New", "Shortlisted", "Applied", "Interviewing", "Offer", "Rejected", "Passed on it"]
    counts = {r["status"]: r["n"] for r in ApplicationStatus.objects.using("jobhunt").values("status").annotate(n=Count("status"))}
    stages = [{"status": s, "count": counts.pop(s, 0)} for s in order]
    stages += [{"status": s, "count": n} for s, n in sorted(counts.items())]
    applied = sum(s["count"] for s in stages if s["status"] in ("Applied", "Interview", "Offer", "Rejected"))
    interviews = sum(s["count"] for s in stages if s["status"] in ("Interviewing", "Interview", "Offer"))
    return Response({"stages": stages, "applied": applied, "interviews": interviews,
                     "interview_rate": round(interviews / applied * 100) if applied else 0,
                     "starred": ApplicationStatus.objects.using("jobhunt").filter(starred=True).count()})


@api_view(["GET"])
def job_detail(request, job_id):
    try:
        from . import queries
        job = queries.base_queryset().get(pk=job_id)
    except Job.DoesNotExist:
        return Response({"error": "not found"}, status=404)
    except Exception as e:
        # e.g. OperationalError no such table in test/empty DB — always JSON, never HTML
        return Response({"error": f"db error: {e}"}, status=500)
    # likelihood + details
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        from src import likelihood as _like, job_details as _jd, resume as _res
        prof = _res.parse().get("profile") or {}
        job_dict = queries.serialize(job)
        kw = queries.fit_keyword(job)
        rate_input = dict(job_dict, kw_fit=kw if kw is not None else job_dict["fit_score"])  # never re-blend a blended score
        like = _like.rate(rate_input, prof, deep=True)
        details = _jd.analyze(job_dict, prof)
        return Response({"job": job_dict, "likelihood": like, "details": details})
    except Exception as e:
        import traceback
        return Response({"error": str(e), "trace": traceback.format_exc()[:2000]}, status=500)

@api_view(["PUT"])
def job_status(request, job_id):
    data = request.data
    status_val = data.get("status")
    if not status_val:
        return Response({"error": "status required"}, status=400)
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        from src import db as _db
        from .models import ApplicationStatus, Job
        prev = "New"
        title = ""
        company = ""
        try:
            prev = ApplicationStatus.objects.using("jobhunt").get(pk=job_id).status or "New"
        except Exception:
            prev = "New"
        try:
            job = Job.objects.using("jobhunt").get(pk=job_id)
            title, company = job.title, job.company
        except Exception:
            pass
        _db.update_status(
            job_id,
            status=status_val,
            notes=data.get("notes"),
            applied_date=data.get("applied_date"),
            followup_date=data.get("followup_date"),
        )
        note = (data.get("notes") or "").strip()
        follow = data.get("followup_date")
        if follow:
            note = (note + f" Follow-up {follow}.").strip()
        try:
            from core.models import StatusEvent
            StatusEvent.objects.create(
                job_id=job_id,
                title=title,
                company=company,
                from_status=prev,
                to_status=status_val,
                note=note,
            )
        except Exception:
            pass
        return Response({"ok": True, "job_id": job_id, "status": status_val, "from_status": prev})
    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(["POST"])
def trigger_scan(request):
    if _running["task"]:
        return Response({"ok": False, "error": f"'{_running['task']}' already running"}, status=409)
    dry = request.data.get("dry_run", True) if isinstance(request.data, dict) else True
    cmd = [PYTHON, "-m", "src.run"]
    if dry:
        cmd.append("--dry-run")
    with _lock:
        _running["logs"].clear()
    threading.Thread(target=_run, args=("scan", cmd), daemon=True).start()
    return Response({"ok": True, "task": "scan"})

@api_view(["GET"])
def recent_scans(request):
    """Recent scanner runs, newest first."""
    try:
        rows = []
        for scan in Scan.objects.using("jobhunt").all()[:12]:
            rows.append({
                "id": scan.id,
                "started_at": scan.started_at,
                "finished_at": scan.finished_at,
                "total_fetched": scan.total_fetched,
                "total_kept": scan.total_kept,
                "status": scan.status,
                "error": scan.error or "",
            })
        return Response({"scans": rows})
    except Exception as e:
        return Response({"scans": [], "error": str(e)})


@api_view(["GET"])
def logs(request):
    since = int(request.GET.get("since", 0))
    with _lock:
        total = len(_running["logs"])
        chunk = _running["logs"][since:]
    return Response({"lines": chunk, "next": total, "busy": _running["task"] is not None, "returncode": _running["returncode"]})

def _lookup_job(job_id):
    import sys
    sys.path.insert(0, str(ROOT))
    from src import cover_letter as _cl
    try:
        j = Job.objects.using("jobhunt").get(pk=job_id)
        return {"job_id": j.job_id, "source": j.source, "title": j.title, "company": j.company, "location": j.location, "salary": j.salary, "url": j.url, "description": j.description, "posted_at": j.posted_at, "fit_score": j.fit_score, "tier": j.tier, "why": j.why, "flags": j.flags}
    except Job.DoesNotExist:
        return _cl.find_job(job_id)
    except Exception:
        return _cl.find_job(job_id)


def _draft_letter(job):
    import sys
    sys.path.insert(0, str(ROOT))
    from src import cover_letter as _cl
    try:
        text, path, backend = _cl.generate(job)
        with _lock:
            _letter.update(busy=False, text=text, path=str(path), backend=backend, error="", job={k: job.get(k) for k in ("title", "company", "url", "fit_score", "flags")})
    except Exception as e:
        with _lock:
            _letter.update(busy=False, error=str(e), text="")


@api_view(["GET", "POST"])
def cover_letter(request):
    if request.method == "GET":
        with _lock:
            return Response(dict(_letter))
    job_id = request.data.get("job_id")
    if not job_id:
        return Response({"ok": False, "error": "job_id required"}, status=400)
    with _lock:
        if _letter["busy"]:
            return Response({"ok": False, "error": "A letter is already being drafted"}, status=409)
    try:
        job = _lookup_job(job_id)
    except Exception as e:
        return Response({"ok": False, "error": str(e)}, status=500)
    if not job:
        return Response({"ok": False, "error": "not found"}, status=404)
    with _lock:
        _letter.update(busy=True, job_id=job_id, text="", path="", backend="", error="", job={k: job.get(k) for k in ("title", "company", "url", "fit_score", "flags")})
    threading.Thread(target=_draft_letter, args=(job,), daemon=True).start()
    return Response({"ok": True, "pending": True, "job_id": job_id, "job": _letter["job"]})


def _full_job(job) -> dict:
    """Everything the analysers need about a job (they read the active resume themselves)."""
    from . import queries
    d = queries.serialize(job)
    d["kw_fit"] = queries.fit_keyword(job) if queries.fit_keyword(job) is not None else job.fit_score
    return d


def _legacy(fn):
    """Common wrapper for the per-job analysis endpoints: scanner path, 404 for unknown ids, JSON errors."""
    import functools

    @functools.wraps(fn)
    def wrapper(request, job_id):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        try:
            job = Job.objects.using("jobhunt").get(pk=job_id)
        except Job.DoesNotExist:
            return Response({"error": "not found"}, status=404)
        try:
            return Response(fn(_full_job(job)))
        except Exception as e:
            import traceback
            return Response({"error": str(e), "trace": traceback.format_exc()[:2000]}, status=500)
    return wrapper


@api_view(["GET"])
@_legacy
def job_ats(job):
    from src import ats as _ats
    return _ats.score(job)


@api_view(["GET"])
@_legacy
def job_interview(job):
    from src import interview as _iv
    return _iv.prep(job)


@api_view(["GET"])
@_legacy
def job_salary(job):
    from src import salary as _sal
    b = _sal.benchmark(job)
    if not b:
        return {"has_salary": False, **_sal.context_for_missing(job)}
    return {"has_salary": True, **b}


@api_view(["GET"])
@_legacy
def job_ai_match(job):
    from src import ai_match as _am
    return _am.semantic_score(job)


@api_view(["GET"])
@_legacy
def job_tailor(job):
    from src import ai_resume as _ar
    return _ar.tailor(job)


# --- Flask compatibility layer (so old dashboard.html still works) ---
@api_view(["GET"])
def state(request):
    """Flask-compatible /api/state — returns jobs, generated, letters, busy, etc."""
    try:
        import json
        jobs = []
        # Prefer Django DB
        try:
            from . import queries
            jobs = [queries.serialize(j) for j in queries.base_queryset().order_by("-fit_score", "company")[:2000]]
        except Exception:
            pass
        # Fallback to JSON file if DB empty
        if not jobs:
            p = ROOT / "output" / "jobs_latest.json"
            if p.exists():
                jobs = json.loads(p.read_text())
        generated = None
        try:
            p = ROOT / "output" / "jobs_latest.json"
            if p.exists():
                generated = datetime.fromtimestamp(p.stat().st_mtime).isoformat()
            elif (ROOT / "output" / "jobhunt.db").exists():
                generated = datetime.fromtimestamp((ROOT / "output" / "jobhunt.db").stat().st_mtime).isoformat()
        except Exception:
            pass
        # Letters
        letters = []
        try:
            letters = sorted((p.name for p in (ROOT / "output").glob("cover_*.md")), reverse=True)
        except Exception:
            pass
        # Stats
        stats_data = {}
        try:
            qs = Job.objects.using("jobhunt")
            from collections import Counter
            stats_data = {"total": qs.count(), "tier1": qs.filter(fit_score__gte=65).count(), "tier2": qs.filter(fit_score__gte=50, fit_score__lt=65).count(), "local": qs.exclude(region="").count(), "by_source": dict(Counter(j["source"].split(":")[0] for j in jobs))}
        except Exception:
            pass
        # Backends
        try:
            import sys
            sys.path.insert(0, str(ROOT))
            from src import llm as _llm
            backends = _llm.describe()
        except Exception as e:
            backends = {"error": str(e)}
        # Provider
        provider = "auto"
        try:
            import yaml
            provider = (yaml.safe_load((ROOT / "config/profile.yaml").read_text()) or {}).get("cover_letter", {}).get("provider", "auto")
        except Exception:
            pass
        return Response({
            "jobs": jobs, "generated": generated, "letters": letters,
            "busy": _running["task"] is not None, "task": _running["task"], "returncode": _running["returncode"],
            "sheet_configured": bool(os.environ.get("SHEET_ID")), "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "sheet_id": os.environ.get("SHEET_ID", ""), "backends": backends, "provider": provider, "stats": stats_data,
        })
    except Exception as e:
        import traceback
        return Response({"error": str(e), "trace": traceback.format_exc()[:2000]}, status=500)


@api_view(["POST"])
def scan(request):
    """Flask-compatible POST /api/scan {dry_run: bool}"""
    if _running["task"]:
        return Response({"ok": False, "error": f"'{_running['task']}' already running"}, status=409)
    dry = request.data.get("dry_run", True) if isinstance(request.data, dict) else True
    cmd = [PYTHON, "-m", "src.run"]
    if dry:
        cmd.append("--dry-run")
    with _lock:
        _running["logs"].clear()
    threading.Thread(target=_run, args=("scan (dry run)" if dry else "scan + sync", cmd), daemon=True).start()
    return Response({"ok": True, "task": "scan"})


@api_view(["POST"])
def live_check(request):
    if _running["task"]:
        return Response({"ok": False, "error": f"'{_running['task']}' already running"}, status=409)
    with _lock:
        _running["logs"].clear()
    threading.Thread(target=_run, args=("live check", [PYTHON, "live_check.py"]), daemon=True).start()
    return Response({"ok": True, "task": "live check"})


@api_view(["POST"])
def run_tests(request):
    if _running["task"]:
        return Response({"ok": False, "error": f"'{_running['task']}' already running"}, status=409)
    with _lock:
        _running["logs"].clear()
    threading.Thread(target=_run, args=("tests", [PYTHON, "tests/test_pipeline.py"]), daemon=True).start()
    return Response({"ok": True, "task": "tests"})


@api_view(["POST"])
def set_provider(request):
    name = (request.data or {}).get("provider", "auto")
    if name not in ("auto","claude_code","ollama","anthropic","template"):
        return Response({"ok": False, "error": "unknown provider"}, status=400)
    import re
    path = ROOT / "config/profile.yaml"
    text = path.read_text()
    if re.search(r"^  provider: .*$", text, re.M):
        text = re.sub(r"^  provider: .*$", f"  provider: {name}", text, count=1, flags=re.M)
    else:
        text += f"\ncover_letter:\n  provider: {name}\n"
    path.write_text(text)
    return Response({"ok": True, "provider": name})


@api_view(["GET"])
def letter(request, name):
    from django.http import HttpResponse
    p = ROOT / "output" / name
    if not p.exists() or p.suffix != ".md":
        return Response({"error": "not found"}, status=404)
    return HttpResponse(p.read_text(), content_type="text/plain")


def _ics_escape(t: str) -> str:
    return (t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@api_view(["GET"])
def calendar_ics(request):
    """iCalendar feed: follow-up dates and closing dates of jobs you track or starred. Subscribe or import it."""
    from django.http import HttpResponse
    from . import queries
    today = date.today().isoformat()
    events = []
    for j in queries.base_queryset():
        try:
            st = j.applicationstatus
        except Exception:
            st = None
        tracked = bool(st and (st.starred or (st.status or "New") not in ("New", "Rejected", "Passed on it")))
        if st and st.followup_date:
            events.append((st.followup_date, f"Follow up: {j.title} @ {j.company}", f"Status: {st.status}. {st.notes or ''} {j.url}", f"fu-{j.job_id}"))
        if tracked and j.expires_at and j.expires_at >= today:
            events.append((j.expires_at, f"Closes: {j.title} @ {j.company}", f"Apply before this date. {j.url}", f"close-{j.job_id}"))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JobHunter//EN", "CALSCALE:GREGORIAN", "X-WR-CALNAME:JobHunter"]
    for day, summary, desc, uid in events:
        d = day[:10].replace("-", "")
        if len(d) != 8:
            continue
        lines += ["BEGIN:VEVENT", f"UID:{_ics_escape(uid)}@jobhunter", f"DTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}", f"DTSTART;VALUE=DATE:{d}",
                  f"SUMMARY:{_ics_escape(summary)}", f"DESCRIPTION:{_ics_escape(desc.strip())}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    resp = HttpResponse("\r\n".join(lines) + "\r\n", content_type="text/calendar; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="jobhunter.ics"'
    return resp


@api_view(["GET"])
def digest(request):
    """New listings worth your time. ?days=1&min_fit=50&fmt=md"""
    from django.http import HttpResponse
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src import digest as _dg
    try:
        from . import queries
        rows = []
        for j in queries.base_queryset():
            try:
                st = j.applicationstatus.status
            except Exception:
                st = "New"
            rows.append({**{f.attname: getattr(j, f.attname) for f in Job._meta.concrete_fields}, "app_status": st or "New"})
        d = _dg.build(int(request.GET.get("days", 1)), int(request.GET.get("min_fit", 50)), int(request.GET.get("limit", 15)), rows=rows)
    except ValueError:
        return Response({"error": "days, min_fit and limit must be numbers"}, status=400)
    if request.GET.get("fmt") == "md":
        return HttpResponse(_dg.to_markdown(d), content_type="text/markdown; charset=utf-8")
    return Response(d)
