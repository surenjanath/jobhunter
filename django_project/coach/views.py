"""Interview coach API: voice baseline, story bank, drills, real interviews + prep plans, inbox, weekly progress.
Logic lives in jobhunt/src/coach.py; this module is storage + scoping. Every query goes through _mine(): the
signed-in account's own rows, or the shared guest rows (user NULL) when nobody is signed in."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Drill, InboxSuggestion, RealInterview, Story, VoiceBaseline

ROOT = Path(__file__).resolve().parent.parent.parent / "jobhunt"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _coach():
    from src import coach
    return coach


def _owner(request):
    return request.user if request.user.is_authenticated else None


def _mine(request, model):
    return model.objects.filter(user=_owner(request)) if request.user.is_authenticated else model.objects.filter(user__isnull=True)


def _job_dict(job_id: str) -> dict | None:
    from ai.views import _job, as_dict
    j = _job(job_id)
    return as_dict(j) if j else None


def _want_ai(request) -> bool:
    from ai.views import _want_ai as w
    return w(request)


def _date(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def baseline_for(request) -> dict | None:
    b = _mine(request, VoiceBaseline).first()
    return b.metrics if b else None


def _requirements(request, job: dict) -> tuple[list[dict], list[str]]:
    """The posting's requirements and required skills, scored against this person's resume."""
    from accounts.context import matching_context
    from src import matching
    ctx = matching_context(request)
    if not ctx:
        return [], []
    m = matching.evaluate(dict(job), ctx)
    reqs = [{"text": r["text"]} for r in (m.get("requirements") or [])][:8]
    skills = [i["name"] for i in m["skills"]["items"] if i["kind"] == "required" and i["status"] != "soft"][:20]
    return reqs, skills


# ---------------------------------------------------------------------------
# voice baseline
# ---------------------------------------------------------------------------

@api_view(["GET", "POST", "DELETE"])
def baseline(request):
    if request.method == "POST":
        voice = request.data.get("voice") if isinstance(request.data.get("voice"), dict) else None
        metrics = _coach().baseline_from(voice)
        if not metrics:
            fast = voice and (voice.get("pace_wpm") or 0) > 240
            return Response({"error": "That was faster than anyone reads aloud: it looks like you stopped before the end. Read the whole passage at a relaxed pace, then click Done."
                             if fast else "Not enough clear speech to use as a baseline: read the whole passage aloud (at least 10 seconds)."}, status=400)
        _mine(request, VoiceBaseline).delete()
        VoiceBaseline.objects.create(user=_owner(request), metrics=metrics)
    elif request.method == "DELETE":
        _mine(request, VoiceBaseline).delete()
    b = _mine(request, VoiceBaseline).first()
    return Response({"baseline": b.metrics if b else None, "recorded_at": b.created_at if b else None, "passage": _coach().BASELINE_PASSAGE})


# ---------------------------------------------------------------------------
# story bank
# ---------------------------------------------------------------------------

def _story_out(s: Story) -> dict:
    return {"id": s.id, "title": s.title, "question": s.question, "text": s.text, "skills": s.skills, "star": s.star,
            "score": s.score, "job_id": s.job_id, "updated_at": s.updated_at}


@api_view(["GET", "POST"])
def stories(request):
    if request.method == "POST":
        text = str(request.data.get("text") or request.data.get("answer") or "").strip()[:6000]
        if len(text.split()) < 15:
            return Response({"error": "A story needs a few sentences: the situation, what you did, and the result."}, status=400)
        score = request.data.get("score")
        st = _coach().story_from(str(request.data.get("question") or ""), text, score if isinstance(score, int) else None)
        if request.data.get("title"):
            st["title"] = str(request.data["title"])[:200]
        s = Story.objects.create(user=_owner(request), title=st["title"][:200], question=st["question"][:2000], text=text,
                                 skills=st["skills"], star=st["star"], score=st["score"], job_id=str(request.data.get("job_id") or "")[:255])
        return Response(_story_out(s), status=201)
    return Response({"stories": [_story_out(s) for s in _mine(request, Story)[:200]]})


@api_view(["PUT", "DELETE"])
def story(request, sid):
    s = _mine(request, Story).filter(id=sid).first()
    if not s:
        return Response({"error": "not found"}, status=404)
    if request.method == "DELETE":
        s.delete()
        return Response({"ok": True})
    text = str(request.data.get("text") or s.text).strip()[:6000]
    st = _coach().story_from(s.question, text, s.score)
    s.text, s.skills, s.star = text, st["skills"], st["star"]
    s.title = str(request.data.get("title") or s.title)[:200]
    s.save()
    return Response(_story_out(s))


@api_view(["GET"])
def coverage(request, job_id):
    job = _job_dict(job_id)
    if not job:
        return Response({"error": "not found"}, status=404)
    reqs, skills = _requirements(request, job)
    rows = [{"id": s.id, "title": s.title, "text": s.text, "skills": s.skills, "score": s.score} for s in _mine(request, Story)]
    return Response(_coach().story_coverage(reqs, skills, rows))


# ---------------------------------------------------------------------------
# drills
# ---------------------------------------------------------------------------

def _drill_out(d: Drill) -> dict:
    return {"id": d.id, "question": d.question, "kind": d.kind, "job_id": d.job_id, "job_title": d.job_title, "source": d.source,
            "next_due": d.next_due, "interval_days": d.interval_days, "reps": d.reps, "last_score": d.last_score, "mastered": d.mastered}


def add_drill(owner, question: str, kind: str = "behavioural", job_id: str = "", job_title: str = "", score: int | None = None,
              source: str = "mock") -> Drill | None:
    """Add a question to practise, or refresh it if it's already there (same owner + question text)."""
    question = (question or "").strip()[:2000]
    if not question:
        return None
    qs = Drill.objects.filter(user=owner) if owner else Drill.objects.filter(user__isnull=True)
    d = qs.filter(question=question).first()
    due = timezone.localdate() + timedelta(days=1)
    if d:
        if score is not None:
            d.last_score = score
        d.mastered = False
        d.next_due = min(d.next_due, due)
        d.save()
        return d
    return Drill.objects.create(user=owner, question=question, kind=kind, job_id=job_id[:255], job_title=job_title[:300],
                                source=source, next_due=due, last_score=score)


@api_view(["GET", "POST"])
def drills(request):
    if request.method == "POST":
        d = add_drill(_owner(request), str(request.data.get("question") or ""), str(request.data.get("kind") or "behavioural"),
                      str(request.data.get("job_id") or ""), str(request.data.get("job_title") or ""), source="manual")
        if not d:
            return Response({"error": "question required"}, status=400)
        return Response(_drill_out(d), status=201)
    today = timezone.localdate()
    rows = list(_mine(request, Drill))
    return Response({"due": [_drill_out(d) for d in rows if d.next_due <= today and not d.mastered],
                     "upcoming": [_drill_out(d) for d in rows if d.next_due > today and not d.mastered][:50],
                     "mastered": [_drill_out(d) for d in rows if d.mastered][:50]})


@api_view(["POST", "DELETE"])
def drill(request, did):
    d = _mine(request, Drill).filter(id=did).first()
    if not d:
        return Response({"error": "not found"}, status=404)
    if request.method == "DELETE":
        d.delete()
        return Response({"ok": True})
    try:
        score = int(request.data.get("score"))
    except (TypeError, ValueError):
        return Response({"error": "score required"}, status=400)
    nxt = _coach().schedule(d.interval_days, score, timezone.localdate())
    d.interval_days, d.next_due, d.mastered = nxt["interval_days"], date.fromisoformat(nxt["next_due"]), nxt["mastered"]
    d.reps += 1
    d.last_score = score
    d.last_reviewed = timezone.now()
    d.save()
    return Response(_drill_out(d))


# ---------------------------------------------------------------------------
# real interviews: prep plan before, log after
# ---------------------------------------------------------------------------

def _ri_out(r: RealInterview) -> dict:
    return {"id": r.id, "job_id": r.job_id, "job_title": r.job_title, "company": r.company, "scheduled_on": r.scheduled_on,
            "stage": r.stage, "done_tasks": r.done_tasks, "logged": r.logged, "questions": r.questions, "felt": r.felt,
            "outcome": r.outcome, "notes": r.notes, "days_left": (r.scheduled_on - timezone.localdate()).days}


@api_view(["GET", "POST"])
def real_interviews(request):
    if request.method == "POST":
        job = _job_dict(str(request.data.get("job_id") or ""))
        when = _date(request.data.get("scheduled_on"))
        if not job or not when:
            return Response({"error": "job_id and scheduled_on (YYYY-MM-DD) required"}, status=400)
        stage = str(request.data.get("stage") or "screen")
        stage = stage if stage in dict(RealInterview.STAGES) else "screen"
        r = RealInterview.objects.create(user=_owner(request), job_id=job["job_id"], job_title=job["title"], company=job["company"],
                                         scheduled_on=when, stage=stage)
        return Response(_ri_out(r), status=201)
    rows = list(_mine(request, RealInterview))
    today = timezone.localdate()
    from accounts.models import InterviewSession
    mocks = [{"overall": s.overall} for s in (InterviewSession.objects.filter(user=_owner(request)) if request.user.is_authenticated
                                               else InterviewSession.objects.filter(user__isnull=True))[:30]]
    return Response({"upcoming": [_ri_out(r) for r in rows if r.scheduled_on >= today and not r.logged],
                     "past": [_ri_out(r) for r in reversed(rows) if r.scheduled_on < today or r.logged],
                     "real_vs_mock": _coach().real_vs_mock([{"felt": r.felt, "outcome": r.outcome} for r in rows if r.logged], mocks)})


@api_view(["GET", "PUT", "DELETE"])
def real_interview(request, rid):
    r = _mine(request, RealInterview).filter(id=rid).first()
    if not r:
        return Response({"error": "not found"}, status=404)
    if request.method == "DELETE":
        r.delete()
        return Response({"ok": True})
    if request.method == "PUT":
        d = request.data
        if _date(d.get("scheduled_on")):
            r.scheduled_on = _date(d["scheduled_on"])
        if d.get("stage") in dict(RealInterview.STAGES):
            r.stage = d["stage"]
        if isinstance(d.get("done_tasks"), list):
            r.done_tasks = [str(x)[:40] for x in d["done_tasks"]][:40]
        if "log" in d and isinstance(d["log"], dict):
            log = d["log"]
            qs = [str(q).strip()[:500] for q in (log.get("questions") or []) if str(q).strip()][:30]
            r.questions, r.logged = qs, True
            r.felt = int(log["felt"]) if str(log.get("felt") or "").isdigit() and 1 <= int(log["felt"]) <= 5 else None
            r.outcome = str(log.get("outcome") or "waiting")[:20]
            r.notes = str(log.get("notes") or "")[:4000]
            for q in qs:   # what they actually asked becomes practice for next time
                add_drill(_owner(request), q, "behavioural", r.job_id, f"{r.job_title} @ {r.company}", source="real")
        r.save()
    return Response(_ri_out(r))


@api_view(["GET"])
def plan(request, rid):
    r = _mine(request, RealInterview).filter(id=rid).first()
    if not r:
        return Response({"error": "not found"}, status=404)
    job = _job_dict(r.job_id) or {"job_id": r.job_id, "title": r.job_title, "company": r.company, "description": ""}
    reqs, skills = _requirements(request, job)
    stories_ = [{"id": s.id, "title": s.title, "text": s.text, "skills": s.skills, "score": s.score} for s in _mine(request, Story)]
    cov = _coach().story_coverage(reqs, skills, stories_)
    p = _coach().prep_plan(job, r.scheduled_on, r.stage, timezone.localdate(), gaps=cov["gaps"],
                           has_baseline=bool(baseline_for(request)), stories=len(stories_))
    for t in p["tasks"]:
        t["done"] = t["key"] in r.done_tasks
        t["overdue"] = not t["done"] and t["date"] < timezone.localdate().isoformat()
    brief = _coach().research_brief(job, skills)
    if _want_ai(request):
        brief.update(_ai_brief(job, skills))
    return Response({"interview": _ri_out(r), "plan": p, "brief": brief, "coverage": cov})


def _ai_brief(job: dict, skills: list[str]) -> dict:
    from ai.views import _cfg
    from src import ai_features as ai
    text, backend = ai._ask_llm(
        "You help a candidate prepare for an interview. From the job posting only, reply with JSON: "
        '{"summary": "two sentences on what this company/team does and what the role is really for", '
        '"likely_questions": ["five questions this interviewer will probably ask"], '
        '"angles": ["three things the candidate should emphasise"]}. Never invent facts about the company that are not in the posting.',
        f"Role: {job.get('title')} at {job.get('company')}\nKey skills: {', '.join(skills)}\n\nPosting:\n{(job.get('description') or '')[:4000]}", _cfg())
    data = ai._json_from(text)
    if not isinstance(data, dict):
        return {}
    out = {"ai_provider": backend}
    if isinstance(data.get("summary"), str):
        out["ai_summary"] = data["summary"].strip()
    for k in ("likely_questions", "angles"):
        if isinstance(data.get(k), list):
            out["ai_" + k] = [str(x).strip() for x in data[k] if str(x).strip()][:6]
    return out


# ---------------------------------------------------------------------------
# inbox: paste an email, or suggestions from `manage.py check_inbox`
# ---------------------------------------------------------------------------

def tracked_jobs(owner) -> list[dict]:
    """Jobs this person is actually tracking (anything past New), with title and company — what an email can match."""
    from jobs.models import ApplicationStatus, Job
    if owner:
        from accounts.models import UserJobStatus
        st = {s.job_id: s.status for s in UserJobStatus.objects.filter(user=owner).exclude(status__in=["New", "Passed on it"])}
    else:
        st = {s.job_id: s.status for s in ApplicationStatus.objects.using("jobhunt").exclude(status__in=["New", "Passed on it"])}
    rows = Job.objects.using("jobhunt").filter(job_id__in=list(st))
    return [{"job_id": j.job_id, "title": j.title, "company": j.company, "status": st[j.job_id]} for j in rows]


def suggest_from_email(owner, subject: str, body: str, sender: str, message_id: str = "", received_at=None) -> dict:
    c = _coach()
    cls = c.classify_email(subject, body, sender)
    matches = c.match_email_to_jobs(subject, body, sender, tracked_jobs(owner))
    out = {**cls, "matches": matches}
    if cls["suggested_status"] and matches:
        m = matches[0]
        qs = InboxSuggestion.objects.filter(user=owner) if owner else InboxSuggestion.objects.filter(user__isnull=True)
        if not message_id or not qs.filter(message_id=message_id).exists():
            s = InboxSuggestion.objects.create(
                user=owner, message_id=message_id[:500], subject=subject[:500], sender=sender[:300], received_at=received_at,
                kind=cls["kind"], suggested_status=cls["suggested_status"], job_id=m["job_id"], job_title=m["title"],
                company=m["company"], snippet=body.strip()[:400], mentions_date=(cls["mentions_date"] or "")[:80])
            out["suggestion_id"] = s.id
    return out


@api_view(["POST"])
def inbox_parse(request):
    body = str(request.data.get("body") or "")[:20000]
    if not body.strip():
        return Response({"error": "paste the email text"}, status=400)
    return Response(suggest_from_email(_owner(request), str(request.data.get("subject") or "")[:500], body, str(request.data.get("sender") or "")[:300]))


@api_view(["GET"])
def inbox(request):
    rows = _mine(request, InboxSuggestion).filter(state="new")[:50]
    return Response({"suggestions": [{"id": s.id, "subject": s.subject, "sender": s.sender, "kind": s.kind, "suggested_status": s.suggested_status,
                                      "job_id": s.job_id, "job_title": s.job_title, "company": s.company, "snippet": s.snippet,
                                      "mentions_date": s.mentions_date, "received_at": s.received_at} for s in rows]})


@api_view(["POST"])
def inbox_resolve(request, sid):
    s = _mine(request, InboxSuggestion).filter(id=sid).first()
    if not s:
        return Response({"error": "not found"}, status=404)
    action = request.data.get("action")
    if action not in ("applied", "dismissed"):
        return Response({"error": "action must be applied or dismissed"}, status=400)
    s.state = action
    s.save()
    return Response({"ok": True})


# ---------------------------------------------------------------------------
# weekly progress
# ---------------------------------------------------------------------------

def _week_stats(request, start: datetime, end: datetime) -> dict:
    from accounts.models import InterviewSession
    owner = _owner(request)
    responded = ("Interviewing", "Interview", "Offer", "Rejected")
    if owner:
        from accounts.models import UserJobStatus
        rows = UserJobStatus.objects.filter(user=owner, updated_at__gte=start, updated_at__lt=end)
        applied = UserJobStatus.objects.filter(user=owner, applied_date__gte=start.date().isoformat(), applied_date__lt=end.date().isoformat()).count()
        responses = rows.filter(status__in=responded).count()
        offers = rows.filter(status="Offer").count()
        rejections = rows.filter(status="Rejected").count()
    else:
        from core.models import StatusEvent
        ev = StatusEvent.objects.filter(created_at__gte=start, created_at__lt=end)
        applied = ev.filter(to_status="Applied").values("job_id").distinct().count()
        responses = ev.filter(to_status__in=responded).values("job_id").distinct().count()
        offers = ev.filter(to_status="Offer").values("job_id").distinct().count()
        rejections = ev.filter(to_status="Rejected").values("job_id").distinct().count()
    sess = (InterviewSession.objects.filter(user=owner) if owner else InterviewSession.objects.filter(user__isnull=True)).filter(created_at__gte=start, created_at__lt=end)
    comp = [s.summary.get("composure_avg") for s in sess if isinstance(s.summary, dict) and s.summary.get("composure_avg") is not None]
    return {"applied": applied, "responses": responses, "offers": offers, "rejections": rejections,
            "interviews": _mine(request, RealInterview).filter(scheduled_on__gte=start.date(), scheduled_on__lt=end.date()).count(),
            "mocks": sess.count(), "mock_avg": round(sum(s.overall for s in sess) / len(sess)) if sess else None,
            "composure_avg": round(sum(comp) / len(comp)) if comp else None,
            "drills": _mine(request, Drill).filter(last_reviewed__gte=start, last_reviewed__lt=end).count(),
            "stories": _mine(request, Story).filter(created_at__gte=start, created_at__lt=end).count()}


@api_view(["GET"])
def weekly(request):
    now = timezone.now()
    this_start = now - timedelta(days=7)
    rep = _coach().weekly_report(_week_stats(request, this_start, now + timedelta(seconds=1)), _week_stats(request, this_start - timedelta(days=7), this_start))
    rep["due_drills"] = _mine(request, Drill).filter(next_due__lte=timezone.localdate(), mastered=False).count()
    nxt = _mine(request, RealInterview).filter(scheduled_on__gte=timezone.localdate(), logged=False).first()
    rep["next_interview"] = _ri_out(nxt) if nxt else None
    return Response(rep)
