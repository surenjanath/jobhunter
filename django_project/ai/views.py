"""AI features (see jobhunt/src/ai_features.py). Everything works without a model; `ai: true` adds an LLM pass.

Privacy: nothing is sent to a language model unless the request explicitly sets `ai` — and Ollama keeps it on this machine."""
import sys
from pathlib import Path

from rest_framework.decorators import api_view
from rest_framework.response import Response

from jobs.models import ApplicationStatus, Job

ROOT = Path(__file__).resolve().parent.parent.parent / "jobhunt"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _feat():
    from src import ai_features
    return ai_features


def _voice():
    from src import voice
    return voice


def _cfg() -> dict:
    from core.settings_store import _load_yaml
    return _load_yaml().get("cover_letter") or {}


def _want_ai(request) -> bool:
    v = request.data.get("ai") if hasattr(request, "data") and request.method == "POST" else request.GET.get("ai")
    return str(v).lower() in ("1", "true", "yes")


def as_dict(job: Job, status: str = "") -> dict:
    return {"job_id": job.job_id, "title": job.title, "company": job.company, "location": job.location, "remote": bool(job.remote),
            "salary": job.salary, "description": job.description, "region": job.region, "posted_at": job.posted_at,
            "first_seen": job.first_seen, "flags": job.flags, "fit_score": job.fit_score, "app_status": status or "New",
            "blocked": bool(job.likelihood and job.likelihood < 5 and job.match_json and '"blockers": [' in job.match_json and '"blockers": []' not in job.match_json)}


def _job(job_id):
    try:
        return Job.objects.using("jobhunt").get(pk=job_id)
    except Job.DoesNotExist:
        return None


def _corpus(limit: int = 1500) -> list[dict]:
    status = {s.job_id: s for s in ApplicationStatus.objects.using("jobhunt").all()}
    out = []
    for j in Job.objects.using("jobhunt").order_by("-fit_score")[:limit]:
        st = status.get(j.job_id)
        d = as_dict(j, st.status if st else "")
        d["starred"] = bool(st and st.starred)
        out.append(d)
    return out


@api_view(["GET"])
def status(request):
    return Response(_feat().llm_status(_cfg()))


def _with_job(fn):
    def view(request, job_id):
        job = _job(job_id)
        if not job:
            return Response({"error": "not found"}, status=404)
        return fn(request, job, as_dict(job))
    view.__name__ = fn.__name__
    return view


@api_view(["GET", "POST"])
@_with_job
def summary(request, job, d):
    return Response(_feat().posting_summary(d, use_llm=_want_ai(request), cfg=_cfg()))


@api_view(["POST"])
@_with_job
def rewrite(request, job, d):
    out = _feat().rewrite_bullets(d, use_llm=_want_ai(request), cfg=_cfg())
    return Response(out, status=409 if out.get("error") else 200)


@api_view(["POST"])
@_with_job
def outreach(request, job, d):
    out = _feat().outreach(d, kind=str(request.data.get("kind") or "follow_up"), use_llm=_want_ai(request), cfg=_cfg())
    return Response(out, status=400 if out.get("error") else 200)


@api_view(["POST"])
@_with_job
def interview_feedback(request, job, d):
    voice = request.data.get("voice") if isinstance(request.data.get("voice"), dict) else None
    persona = str(request.data.get("persona") or "neutral")
    out = _feat().interview_feedback(d, str(request.data.get("question") or ""), str(request.data.get("answer") or ""),
                                     use_llm=_want_ai(request), cfg=_cfg(), voice=voice,
                                     persona=persona if persona in _feat().PERSONAS else "neutral")
    return Response(out, status=400 if out.get("error") else 200)


@api_view(["POST"])
@_with_job
def interview_questions(request, job, d):
    """{n, persona, ai} -> questions for the mock interview: written by the model when ai is on, else the rule-built set."""
    try:
        n = max(1, min(12, int(request.data.get("n") or 5)))
    except (TypeError, ValueError):
        n = 5
    persona = str(request.data.get("persona") or "neutral")
    if not _want_ai(request):
        from src import interview as _iv
        return Response({"questions": (_iv.questions(d).get("questions") or [])[:n], "provider": "rules"})
    return Response(_feat().ai_questions(d, n=n, persona=persona if persona in _feat().PERSONAS else "neutral", cfg=_cfg()))


@api_view(["POST"])
def interview_summary(request):
    """{results, ai?, save?, job?: {job_id, title, company}} -> the wrap-up. save=true also stores the session
    (the signed-in account's, or the shared guest history) so the Interview page can show progress over time."""
    results = request.data.get("results")
    results = [r for r in results if isinstance(r, dict)][:30] if isinstance(results, list) else []
    out = _feat().session_summary(results, use_llm=_want_ai(request), cfg=_cfg())
    if out.get("error"):
        return Response(out, status=400)
    if str(request.data.get("save")).lower() in ("1", "true"):
        from accounts.models import InterviewSession
        job = request.data.get("job") if isinstance(request.data.get("job"), dict) else {}
        for r in results:                               # keep stored rows bounded: an answer is a minute or two of speech
            if isinstance(r.get("answer"), str):
                r["answer"] = r["answer"][:5000]
        s = InterviewSession.objects.create(
            user=request.user if request.user.is_authenticated else None,
            job_id=str(job.get("job_id") or "")[:255], job_title=str(job.get("title") or "")[:300], company=str(job.get("company") or "")[:300],
            overall=out["overall_avg"], content=out["content_avg"], delivery=out["delivery_avg"], n=out["n"], summary=out, results=results)
        out["session_id"] = s.id
    return Response(out)


def _sessions(request):
    from accounts.models import InterviewSession
    qs = InterviewSession.objects.all()
    return qs.filter(user=request.user) if request.user.is_authenticated else qs.filter(user__isnull=True)


@api_view(["GET"])
def interview_sessions(request):
    rows = [{"id": s.id, "job_id": s.job_id, "job_title": s.job_title, "company": s.company, "overall": s.overall, "content": s.content,
             "delivery": s.delivery, "composure": (s.summary or {}).get("composure_avg"), "n": s.n, "created_at": s.created_at}
            for s in _sessions(request)[:50]]
    return Response({"sessions": rows})


@api_view(["GET", "DELETE"])
def interview_session(request, sid):
    s = _sessions(request).filter(id=sid).first()
    if not s:
        return Response({"error": "not found"}, status=404)
    if request.method == "DELETE":
        s.delete()
        return Response({"ok": True})
    return Response({"id": s.id, "job": {"job_id": s.job_id, "title": s.job_title, "company": s.company},
                     "summary": s.summary, "results": s.results, "created_at": s.created_at})


@api_view(["GET"])
@_with_job
def similar(request, job, d):
    return Response({"similar": _feat().similar_jobs(d, _corpus(), k=6)})


@api_view(["GET"])
def recommendations(request):
    corpus = _corpus()
    liked = [j for j in corpus if j.get("starred") or j["app_status"] in ("Applied", "Interviewing", "Interview", "Offer", "Shortlisted")]
    recs = _feat().recommendations(corpus, liked, k=8)
    if not recs:  # no signals yet: your best untouched matches
        recs = [{"job_id": j["job_id"], "title": j["title"], "company": j["company"], "similarity": 0, "because": "", "fit": j["fit_score"]}
                for j in corpus if j["app_status"] == "New"][:8]
        return Response({"recommendations": recs, "basis": "fit", "liked": 0})
    return Response({"recommendations": recs, "basis": "similar", "liked": len(liked)})


@api_view(["GET", "POST"])
def resume_review(request):
    out = _feat().resume_review()
    return Response(out, status=409 if out.get("error") else 200)


@api_view(["POST"])
def ask(request):
    out = _feat().ask(str(request.data.get("q") or ""))
    return Response(out, status=400 if out.get("error") else 200)


@api_view(["POST"])
def roadmap(request):
    """`jobs` / `sole_gap` (from the Learn-next table) are optional context for the 'why'."""
    def num(k):
        try:
            return int(request.data.get(k) or 0)
        except (TypeError, ValueError):
            return 0
    demand = {"jobs": num("jobs"), "sole_gap": num("sole_gap")} if num("jobs") else None
    out = _feat().roadmap(str(request.data.get("skill") or ""), demand, use_llm=_want_ai(request), cfg=_cfg())
    return Response(out, status=400 if out.get("error") else 200)


# ---------------------------------------------------------------------------
# voice — the mock interview read aloud (Kokoro, optional; see jobhunt/src/voice.py). Text scoring
# (interview_feedback, above) always works without this; these two endpoints add the spoken half.
# ---------------------------------------------------------------------------

@api_view(["GET"])
def voice_status(request):
    return Response(_voice().status())


@api_view(["GET"])
def speak(request):
    """?text=...  ->  audio/mpeg (or audio/wav if this machine has no ffmpeg). Cached on disk by the exact text,
    voice and speed, so the same question or result is only ever synthesized once."""
    from django.http import HttpResponse
    text = (request.GET.get("text") or "").strip()
    if not text:
        return Response({"error": "text required"}, status=400)
    v = _voice()
    voice_name = request.GET.get("voice") or v.DEFAULT_VOICE
    try:
        speed = float(request.GET.get("speed") or 1.05)
    except ValueError:
        speed = 1.05
    try:
        data, content_type = v.synthesized_content_type(text, voice_name, speed)
    except v.VoiceUnavailable as e:
        return Response({"error": str(e)}, status=503)
    except Exception as e:  # noqa: BLE001 — a synthesis failure must stay text-first-friendly, never a 500 HTML page
        return Response({"error": f"could not synthesize speech: {e}"}, status=500)
    resp = HttpResponse(data, content_type=content_type)
    resp["Cache-Control"] = "public, max-age=31536000, immutable"   # content-addressed by (text, voice, speed) — safe to cache hard
    return resp
