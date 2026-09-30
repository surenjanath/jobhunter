import json
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(["GET"])
def dashboard(request):
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "jobhunt"))
        from src import analytics as _an
        return Response(_an.full_dashboard())
    except Exception as e:
        import traceback
        return Response({"error": str(e), "trace": traceback.format_exc()[:2000]}, status=500)

@api_view(["GET"])
def resume(request):
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "jobhunt"))
        from src import resume as _res
        return Response(_res.parse())
    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(["GET"])
def brief(request):
    """Conditions report: odds, blockers, compare list, pipeline, follow-ups."""
    from .station import build_brief
    try:
        import sys
        from pathlib import Path
        from datetime import datetime
        root = Path(__file__).resolve().parent.parent.parent / "jobhunt"
        sys.path.insert(0, str(root))
        from jobs.models import Job, ApplicationStatus

        jobs = []
        qs_rows = []
        statuses = {}
        try:
            from accounts.context import pipeline_statuses
            statuses = pipeline_statuses(request)    # this account's own follow-ups / statuses when signed in
        except Exception:
            statuses = {}
        try:
            qs = list(Job.objects.using("jobhunt").all().order_by("-fit_score")[:400])
            qs_rows = qs
            for job in qs:
                st = statuses.get(job.job_id)
                jobs.append({
                    "job_id": job.job_id,
                    "source": job.source,
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "remote": bool(job.remote),
                    "salary": job.salary,
                    "url": job.url,
                    "posted_at": job.posted_at,
                    "fit_score": job.fit_score,
                    "kw_fit": (json.loads(job.match_json).get("fit_keyword") if job.match_json else None),
                    "tier": job.tier,
                    "why": job.why,
                    "flags": job.flags,
                    "app_status": st.status if st else "New",
                    "followup_date": st.followup_date if st else "",
                })
        except Exception:
            jobs = []

        # Odds: use what the scan stored (profile-driven, computed with the full description). Only jobs that were
        # never matched get the on-the-fly estimate.
        pending = []
        for j, job in zip(jobs, qs_rows):
            stored = None
            if job.match_json:
                try:
                    stored = json.loads(job.match_json)
                except ValueError:
                    stored = None
            if stored:
                j["likelihood"] = {"likelihood": job.likelihood, "verdict": stored.get("verdict", ""), "interview_chance": job.interview_chance,
                                   "blockers": stored.get("blockers", []), "gaps": stored.get("gaps", []), "advice": stored.get("advice", ""),
                                   "breakdown": stored.get("breakdown", {})}
            elif len(pending) < 24:
                pending.append(j)
        if pending:
            try:
                from src import likelihood as _like
                from src import resume as _res
                prof = (_res.parse() or {}).get("profile") or {}
                for j in pending:
                    j["description"] = next((r.description for r in qs_rows if r.job_id == j["job_id"]), "")
                _like.batch(pending, prof)
            except Exception:
                pass

        letters = 0
        generated = None
        try:
            out = root / "output"
            letters = len(list(out.glob("cover_*.md")))
            stamp = out / "jobs_latest.json"
            if stamp.exists():
                generated = datetime.fromtimestamp(stamp.stat().st_mtime).isoformat()
        except Exception:
            pass
        return Response(build_brief(jobs, letters=letters, generated=generated))
    except Exception as e:
        return Response(build_brief([], generated=None) | {"error": str(e)})


@api_view(["GET"])
def coach_brief(request):
    """Daily brief from your own insights. ?ai=1 lets the configured model phrase it (facts only, no resume text)."""
    try:
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent / "jobhunt"
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from src import ai_coach, profile_store
        from core.settings_store import _load_yaml
        from . import insights as ins
        data = ins.build(ins.rows_from_db(), profile_store.get_prefs(), profile=profile_store.active_profile())
        return Response(ai_coach.daily_brief(data, use_llm=request.GET.get("ai") == "1", cfg=_load_yaml().get("cover_letter") or {}))
    except Exception as e:
        import traceback
        return Response({"error": str(e), "trace": traceback.format_exc()[:2000]}, status=500)


@api_view(["GET"])
def insights(request):
    """Everything the Analytics page needs in one call (see analytics/insights.py)."""
    try:
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent / "jobhunt"
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from src import profile_store
        from . import insights as ins
        data = ins.build(ins.rows_from_db(), profile_store.get_prefs(), profile=profile_store.active_profile())
        data.update(ins.scan_history())
        data["history"] = ins.history_from_db()
        return Response(data)
    except Exception as e:
        import traceback
        return Response({"error": str(e), "trace": traceback.format_exc()[:1500]}, status=500)
