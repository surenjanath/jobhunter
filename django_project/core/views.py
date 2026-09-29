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
    try:
        from jobs.models import Job
        cnt = Job.objects.using("jobhunt").count()
        return JsonResponse({"ok": True, "jobs": cnt, "backend": "django+sqlite"})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


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
