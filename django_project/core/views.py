import re
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import StatusEvent

def _page(template, key, title):
    """One view per page. Each page is its own template under templates/pages/ (shell in layout.html).
    ensure_csrf_cookie: no template here renders a form, so nothing would otherwise trigger Django to set the
    csrftoken cookie — jfetch (core.js) needs it on hand before the first POST, for whoever ends up signed in."""
    @ensure_csrf_cookie
    def view(request):
        return render(request, template, {"page": key, "page_title": title})
    view.__name__ = f"page_{key}"
    return view


index = home = _page("pages/home.html", "home", "Conditions")
ledger = _page("pages/ledger.html", "jobs", "Ledger")
pipeline = _page("pages/pipeline.html", "pipeline", "Pipeline")
analytics_page = _page("pages/analytics.html", "analytics", "Analytics")
profile_page = _page("pages/profile.html", "profile", "Profile")
@ensure_csrf_cookie
def login_page(request):
    """The sign-in page for private mode (JOBHUNTER_PRIVATE=1). Standalone: no shell, nothing that needs sign-in."""
    from . import site
    nxt = request.GET.get("next") or "/"
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"   # only same-site redirects after sign-in
    return render(request, "pages/login.html", {"next": nxt, "page_title": "Sign in", "signup": site.get()["allow_signup"]})


interview_page = _page("pages/interview.html", "interview", "Interview")
trinidad_page = _page("pages/trinidad.html", "trinidad", "Trinidad")
settings_page = _page("pages/settings.html", "settings", "Settings")


@api_view(["GET"])
def activity(request):
    try:
        limit = int(request.GET.get("limit", 20))
    except ValueError:
        limit = 20
    limit = max(1, min(limit, 100))
    rows = []
    try:
        events = list(StatusEvent.objects.all()[:limit])
    except Exception:  # noqa: BLE001  (django db not migrated yet: run `python manage.py migrate`)
        events = []
    for ev in events:
        rows.append({
            "job_id": ev.job_id,
            "title": ev.title,
            "company": ev.company,
            "from_status": ev.from_status,
            "to_status": ev.to_status,
            "note": ev.note,
            "created_at": ev.created_at.isoformat(),
        })
    return Response({"events": rows})

def health(request):
    """200 whenever the app can serve requests. A missing jobs table is normal on a brand-new or wiped disk (the first
    scan creates it), so it's reported, not treated as down: a hosting platform would otherwise fail the deploy."""
    try:
        from jobs.models import Job
        cnt = Job.objects.using("jobhunt").count()
        return JsonResponse({"ok": True, "jobs": cnt, "backend": "django+sqlite"})
    except Exception as e:  # noqa: BLE001
        return JsonResponse({"ok": True, "jobs": 0, "backend": "django+sqlite", "note": f"no jobs yet ({type(e).__name__})"})


@api_view(["GET", "PUT"])
def settings_view(request):
    """GET returns merged settings, PUT applies partial updates.

    Body example:
    {
      "preferences": {"show_remote": false, "show_links": true},
      "sources": {"remotive": false},
      "filters": {"min_score_to_include": 40, "max_age_days": 21},
      "cover_letter": {"provider": "ollama"}
    }
    """
    from .settings_store import get_settings, update_settings
    if request.method == "GET":
        try:
            return Response(get_settings())
        except Exception as e:
            return Response({"error": str(e)}, status=500)
    # PUT
    try:
        return Response(update_settings(request.data))
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except Exception as e:
        import traceback
        return Response({"error": str(e), "trace": traceback.format_exc()[:1000]}, status=500)


def api_not_found(request):
    return JsonResponse({"error": f"no such API endpoint: {request.path}"}, status=404)


@api_view(["GET", "PUT"])
def site_view(request):
    """Site access switches for the Settings page. PUT {allow_signup?, require_signin?} (admin only, see core.site)."""
    from . import site
    from .models import SiteConfig
    user = request.user
    if request.method == "PUT":
        if not site.can_edit(user):
            return Response({"error": "only an admin account can change site access"}, status=403)
        d = request.data if isinstance(request.data, dict) else {}
        row, _ = SiteConfig.objects.get_or_create(pk=1)
        if "allow_signup" in d:
            row.allow_signup = bool(d["allow_signup"])
        if "require_signin" in d:
            want = bool(d["require_signin"])
            if want and not user.is_authenticated:
                return Response({"error": "sign in first: turning this on while signed out would lock you out"}, status=400)
            row.require_signin = want
        row.updated_by = user.email if user.is_authenticated else "guest"
        row.save()
        if user.is_authenticated and not user.is_staff:   # the first person to set this up becomes the admin
            user.is_staff = True
            user.save(update_fields=["is_staff"])
        site.invalidate()
    return Response({**site.get(), "can_edit": site.can_edit(user), "signed_in": user.is_authenticated,
                     "is_admin": bool(user.is_authenticated and user.is_staff)})


def _tailored(job_id):
    from ai.views import _job, as_dict
    job = _job(job_id)
    if not job:
        return None, None
    from src import tailored_resume
    return tailored_resume, tailored_resume.build(as_dict(job))


def tailored_resume_page(request, job_id):
    """Your resume arranged for one posting, laid out for printing (browser Print → Save as PDF)."""
    tr, r = _tailored(job_id)
    if r is None:
        from django.http import Http404
        raise Http404("no such job")
    return render(request, "pages/resume.html", {"r": r, "job_id": job_id, "page_title": "Tailored resume"})


def tailored_resume_download(request, job_id, fmt):
    from django.http import HttpResponse
    tr, r = _tailored(job_id)
    if r is None or r.get("error"):
        return JsonResponse({"error": (r or {}).get("error") or "no such job"}, status=404 if r is None else 409)
    body = tr.to_markdown(r) if fmt == "md" else tr.to_text(r)
    slug = re.sub(r"[^a-z0-9]+", "-", f"{r['name']} {r['for_job']['company']}".lower()).strip("-")[:60] or "resume"
    resp = HttpResponse(body, content_type="text/markdown; charset=utf-8" if fmt == "md" else "text/plain; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{slug}-resume.{fmt}"'
    return resp
