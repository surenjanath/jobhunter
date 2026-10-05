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

def health_payload() -> dict:
    """Up whenever the app can serve requests. A missing jobs table is normal on a brand-new or wiped disk (the first
    scan creates it), so it's reported, not treated as down: a hosting platform would otherwise fail the deploy."""
    try:
        from jobs.models import Job
        return {"ok": True, "jobs": Job.objects.using("jobhunt").count(), "backend": "django+sqlite"}
    except Exception as e:  # noqa: BLE001
        return {"ok": True, "jobs": 0, "backend": "django+sqlite", "note": f"no jobs yet ({type(e).__name__})"}


def health(request):
    return JsonResponse(health_payload())


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
        from . import site
        data = request.data
        if isinstance(data, dict) and "cover_letter" in data and not site.can_edit(request.user):
            data = {k: v for k, v in data.items() if k != "cover_letter"}   # the site-wide provider is the admin's; see /api/llm/
        return Response(update_settings(data))
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except Exception as e:
        import traceback
        return Response({"error": str(e), "trace": traceback.format_exc()[:1000]}, status=500)


def _llm_scope(request):
    """Whose AI settings a request means, and whether it may change them: (scope, can_edit, account settings | None).

    "account": the signed-in person's own keys and choices (theirs alone to change). "site": the site-wide ones every
    account and guest falls back to, changed only by an admin (see core.site). Signed-in people get their account
    unless they ask for ?scope=site; guests only ever see the site."""
    from . import site
    user = request.user
    data = request.data if isinstance(getattr(request, "data", None), dict) else {}
    want = request.GET.get("scope") or data.get("scope")
    if user.is_authenticated and want != "site":
        from accounts.models import UserProfile
        prof, _ = UserProfile.objects.get_or_create(user=user)
        return "account", True, prof
    return "site", site.can_edit(user), None


@api_view(["GET", "PUT"])
def llm_view(request):
    """AI providers for the Settings page. GET lists them (with options and, for admins, usage counts); PUT {provider?,
    options?, providers: {name: {api_key?, model?, base_url?}}} saves. Signed in, this is your own account's settings
    (?scope=site for the site-wide ones, admin only). Keys are write-only: a GET shows at most the last 4 characters
    of your own."""
    from . import site
    from .settings_store import get_llm, update_llm
    scope, can_edit, prof = _llm_scope(request)
    admin = site.can_edit(request.user)
    if request.method == "PUT":
        if not can_edit:
            return Response({"error": "only an admin account can change the site-wide AI providers"}, status=403)
        try:
            body = {k: v for k, v in request.data.items() if k != "scope"}
            if prof is None:
                update_llm(body)
            else:
                prof.llm = update_llm(body, prof.llm or {}, allow_private_urls=admin)
                prof.save(update_fields=["llm", "updated_at"])
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
    own = None if prof is None else (prof.llm or {"keys": {}, "cfg": {}})
    return Response({**get_llm(own, show_keys=can_edit, show_usage=admin), "scope": scope, "can_edit": can_edit,
                     "signed_in": request.user.is_authenticated, "can_edit_site": admin})


@api_view(["POST"])
def llm_check(request, action):
    """POST /api/llm/test/ {provider} sends one tiny prompt; /api/llm/models/ lists what the provider offers (both run
    with the settings of the scope being edited); /api/llm/reset-usage/ clears the usage counts (admin)."""
    import time
    from . import site
    from src import llm
    if action not in ("test", "models", "reset-usage"):
        return Response({"error": f"no such API endpoint: {request.path}"}, status=404)
    scope, can_edit, prof = _llm_scope(request)
    if action == "reset-usage":
        if not site.can_edit(request.user):
            return Response({"error": "only an admin account can reset the usage counts"}, status=403)
        llm.reset_usage()
        return Response({"ok": True})
    if not can_edit:
        return Response({"error": "sign in to test AI providers"}, status=403)
    name = str((request.data or {}).get("provider") or "")
    if name not in llm.ORDER:
        return Response({"error": "unknown provider"}, status=400)
    t0 = time.time()
    with llm.scoped(None if prof is None else prof.llm):
        cfg = llm.effective()
        try:
            if action == "models":
                return Response({"ok": True, "models": llm.list_models(name, cfg)})
            if name in llm.OPENAI_COMPAT:   # short replies are fine here; the other backends insist on a full paragraph
                text = llm.call(name, "You are a connection test.", "Reply with the single word: ready", cfg, timeout=40, max_tokens=200)
            else:
                text = llm.call(name, "You are a connection test.", "In two or three sentences, say that the connection "
                                "works and name one thing a good cover letter does.", cfg)
            return Response({"ok": True, "reply": text[:200], "ms": int((time.time() - t0) * 1000)})
        except llm.LLMUnavailable as e:
            return Response({"ok": False, "error": str(e)})


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
    if fmt == "json":
        return JsonResponse(r)
    body = tr.to_markdown(r) if fmt == "md" else tr.to_text(r)
    slug = re.sub(r"[^a-z0-9]+", "-", f"{r['name']} {r['for_job']['company']}".lower()).strip("-")[:60] or "resume"
    resp = HttpResponse(body, content_type="text/markdown; charset=utf-8" if fmt == "md" else "text/plain; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{slug}-resume.{fmt}"'
    return resp


@api_view(["GET", "POST"])
def alerts_view(request):
    """GET: which alert channels are configured, and a preview of what the next alert would say.
    POST {"action": "test"} sends a short test message; {"action": "send"} sends the real alert now. Admin only."""
    from src import alerts
    from . import alerts_service, site
    user = request.user if request.user.is_authenticated else None
    if request.method == "GET":
        preview = alerts_service.run(user or alerts_service.owner_user(), dry_run=True)
        return Response({"channels": alerts.channels(), "preview": preview.get("message"), "counts": preview.get("counts"),
                         "can_send": site.can_edit(request.user)})
    if not site.can_edit(request.user):
        return Response({"error": "only an admin account can send alerts"}, status=403)
    if not any(alerts.channels().values()):
        return Response({"error": "no alert channel configured: see docs/ALERTS.md"}, status=400)
    if (request.data or {}).get("action") == "test":
        return Response({"channels": alerts.send({"subject": "JobHunter: test alert",
                                                   "text": "Alerts are set up. You'll get new good-fit roles, follow-ups due and closing dates here.\n"})})
    return Response(alerts_service.run(user or alerts_service.owner_user()))


@api_view(["POST"])
def job_import(request):
    """Add a job you found yourself. {url} alone with preview=true reads the page and returns the fields to check;
    {ld_json, url} comes from the browser button; saving takes {title, company, description, location, url, …}.
    The job is scored exactly like a scanned one and lands in the ledger."""
    from src import job_import as ji
    d = request.data if isinstance(request.data, dict) else {}
    url = str(d.get("url") or "").strip()[:2000]
    if d.get("preview"):
        if d.get("ld_json"):
            got = ji.from_ld_json(str(d["ld_json"])[:200000], url)
            if got:
                return Response(got)
        if not url:
            return Response({"error": "paste a link"}, status=400)
        got = ji.fetch(url)
        return Response(got, status=400 if got.get("error") else 200)
    fields = {k: str(d.get(k) or "") for k in ("title", "company", "location", "description", "url", "salary", "posted_at", "expires_at")}
    if len(fields["title"].strip()) < 3:
        return Response({"error": "a job title is needed"}, status=400)
    if len(fields["description"].strip()) < 80:
        return Response({"error": "paste the job description too (at least a few sentences): it's what the match is based on"}, status=400)
    from src import db, run, score
    job = score.score_job(ji.build_job(fields), run.load_config())
    db.upsert_jobs([job])
    return Response({"job_id": job["job_id"], "fit_score": job.get("fit_score"), "tier": job.get("tier"), "why": job.get("why"),
                     "title": job["title"], "company": job["company"]}, status=201)


@ensure_csrf_cookie
def add_job_page(request):
    return render(request, "pages/add_job.html", {"page": "jobs", "page_title": "Add a job"})
