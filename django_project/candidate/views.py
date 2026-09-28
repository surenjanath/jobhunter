"""Resume profile, preferences, calibration and profile-driven matching endpoints."""
import json
import sys
import threading
from pathlib import Path

from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from jobs.models import Job

ROOT = Path(__file__).resolve().parent.parent.parent / "jobhunt"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _imports():
    from src import calibration, matching, profile_store, resume_parse, retrieval
    return calibration, matching, profile_store, resume_parse, retrieval


def _public_profile(p: dict) -> dict:
    """The effective profile as the UI needs it (no private fields, skills grouped and sorted)."""
    skills = [{"name": n, **{k: v for k, v in m.items()}} for n, m in p.get("skills", {}).items()]
    skills.sort(key=lambda s: (-s.get("years", 0), -s.get("mentions", 0), s["name"]))
    return {
        "contact": p.get("contact", {}), "headline": p.get("headline", ""), "summary": p.get("summary", ""),
        "years_experience": p.get("years_experience"), "seniority": p.get("seniority", ""),
        "roles": p.get("roles", []), "titles": p.get("titles", []), "education": p.get("education", []),
        "highest_education": p.get("highest_education", ""), "skills": skills, "domains": p.get("domains", []),
        "certifications": p.get("certifications", []), "projects": p.get("projects", []),
        "achievements": p.get("achievements", []), "target_titles": p.get("target_titles", []),
        "llm": p.get("llm"), "overrides": p.get("overrides", {}), "sections_found": p.get("sections_found", []),
    }


def _state() -> dict:
    calibration, matching, profile_store, resume_parse, retrieval = _imports()
    prof = profile_store.active_profile()
    from src import llm
    try:
        providers = {k: v.get("available", False) for k, v in llm.describe().items()}
    except Exception:
        providers = {}
    return {
        "status": profile_store.status(),
        "profile": _public_profile(prof) if prof else None,
        "prefs": profile_store.get_prefs(),
        "work_modes": list(profile_store.WORK_MODES),
        "calibration": calibration.priors(),
        "versions": profile_store.list_versions(),
        "llm_providers": providers,
    }


@api_view(["GET"])
def profile(request):
    try:
        _, _, profile_store, *_ = _imports()
        profile_store.bootstrap_if_empty()
        return Response(_state())
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def upload_resume(request):
    """Upload a resume: multipart `file` (PDF/DOCX/MD/TXT) or JSON {"text": "...", "filename": "cv.md"}."""
    calibration, matching, profile_store, resume_parse, retrieval = _imports()
    try:
        f = request.FILES.get("file")
        if f:
            if f.size > resume_parse.MAX_BYTES:
                return Response({"error": "file is larger than 8 MB"}, status=400)
            data, name = f.read(), f.name
        else:
            text = (request.data.get("text") or "").strip()
            if not text:
                return Response({"error": "send a file, or JSON with text"}, status=400)
            data, name = text, str(request.data.get("filename") or "pasted-resume.txt")
        summary = profile_store.import_resume(data, name, source="upload", embed=request.data.get("embed", "true") != "false")
        matching.reset_context()
        return Response({"ok": True, "import": summary, **_state()}, status=201)
    except resume_parse.ResumeError as e:
        return Response({"error": str(e)}, status=400)
    except Exception as e:
        return Response({"error": f"could not import resume: {e}"}, status=500)


@api_view(["POST", "PUT", "PATCH"])
def overrides(request):
    """Correct the extracted profile. Body: {add_skills:[{name,years}], remove_skills:[name], restore_skills:[name],
    skill_years:{name:years}, years_experience, target_titles:[...]}"""
    calibration, matching, profile_store, *_ = _imports()
    prof = profile_store.active_profile()
    if not prof:
        return Response({"error": "no resume yet"}, status=404)
    try:
        profile_store.update_overrides(prof["_resume_id"], request.data or {})
        matching.reset_context()
        return Response({"ok": True, **_state()})
    except (ValueError, TypeError) as e:
        return Response({"error": str(e)}, status=400)


@api_view(["GET", "PUT", "PATCH"])
def prefs(request):
    """Search preferences: work_mode (both|local_first|remote_first|local_only|remote_only), salary floors, regions…"""
    calibration, matching, profile_store, *_ = _imports()
    if request.method == "GET":
        return Response({"prefs": profile_store.get_prefs(), "work_modes": list(profile_store.WORK_MODES)})
    try:
        out = profile_store.save_prefs(request.data or {})
        matching.reset_context()
        return Response({"ok": True, "prefs": out})
    except (ValueError, TypeError) as e:
        return Response({"error": str(e)}, status=400)


@api_view(["POST"])
def reindex(request):
    """Recompute embeddings (after `ollama pull nomic-embed-text`)."""
    calibration, matching, profile_store, *_ = _imports()
    try:
        out = profile_store.reindex()
        matching.reset_context()
        return Response({"ok": True, **out, **_state()})
    except KeyError:
        return Response({"error": "no resume yet"}, status=404)


@api_view(["POST"])
def enrich(request):
    """Opt-in: ask the configured LLM for a headline / target titles / honest strengths & gaps.
    The resume text is sent to that provider — Ollama stays local, Claude/API do not."""
    calibration, matching, profile_store, resume_parse, retrieval = _imports()
    prof = profile_store.active_profile()
    if not prof:
        return Response({"error": "no resume yet"}, status=404)
    from src import llm
    from core.settings_store import _load_yaml
    cfg = (_load_yaml().get("cover_letter") or {})
    provider = (request.data or {}).get("provider")
    if provider:
        cfg = {**cfg, "provider": provider}
    try:
        text = profile_store.get_resume_text(prof["_resume_id"])
        out = resume_parse.enrich_with_llm(text, {}, cfg)
        profile_store.set_llm_enrichment(prof["_resume_id"], out["llm"])
        matching.reset_context()
        return Response({"ok": True, **_state()})
    except llm.LLMUnavailable as e:
        return Response({"error": f"no AI provider available: {e}"}, status=503)
    except (resume_parse.ResumeError, ValueError) as e:
        return Response({"error": str(e)}, status=502)


@api_view(["POST"])
def activate_version(request, rid):
    calibration, matching, profile_store, *_ = _imports()
    try:
        profile_store.set_active(rid)
        matching.reset_context()
    except KeyError:
        return Response({"error": "not found"}, status=404)
    return Response({"ok": True, **_state()})


@api_view(["DELETE"])
def delete_version(request, rid):
    calibration, matching, profile_store, *_ = _imports()
    profile_store.delete_version(rid)
    matching.reset_context()
    return Response({"ok": True, **_state()})


# --- rescoring: re-run every stored job against the current resume + preferences --------------------------------
_rescore = {"running": False, "done": 0, "total": 0, "error": "", "finished": None}
_rescore_lock = threading.Lock()


def _run_rescore():
    from core.settings_store import _load_yaml
    from src import db, matching, score
    try:
        cfg = _load_yaml()
        matching.reset_context()
        n = db.rescore_all(lambda j: score.score_job(j, cfg))
        with _rescore_lock:
            _rescore.update(done=n, total=n, error="")
    except Exception as e:  # noqa: BLE001
        with _rescore_lock:
            _rescore.update(error=str(e))
    finally:
        from datetime import datetime
        with _rescore_lock:
            _rescore.update(running=False, finished=datetime.now().isoformat(timespec="seconds"))


@api_view(["GET", "POST"])
def rescore(request):
    """POST starts a background re-score of every stored job (add {"wait": true} to block); GET reports progress."""
    if request.method == "GET":
        with _rescore_lock:
            return Response(dict(_rescore))
    with _rescore_lock:
        if _rescore["running"]:
            return Response({"ok": True, "already_running": True, **_rescore}, status=202)
        total = Job.objects.using("jobhunt").count()
        _rescore.update(running=True, done=0, total=total, error="", finished=None)
    if (request.data or {}).get("wait"):
        _run_rescore()
        with _rescore_lock:
            return Response({"ok": not _rescore["error"], "rescored": _rescore["done"], **_rescore})
    threading.Thread(target=_run_rescore, daemon=True).start()
    return Response({"ok": True, "started": True, "total": total}, status=202)


@api_view(["GET"])
def job_match(request, job_id):
    """Deep, explainable match for one job: per-requirement resume evidence (semantic when an embedding model
    is installed), skills matched/missing, every factor behind the likelihood."""
    calibration, matching, profile_store, *_ = _imports()
    try:
        job = Job.objects.using("jobhunt").get(pk=job_id)
    except Job.DoesNotExist:
        return Response({"error": "not found"}, status=404)
    ctx = matching.get_context({"targets": _targets()})
    if not ctx:
        return Response({"error": "add a resume first (Profile tab)"}, status=409)
    stored = {}
    try:
        stored = json.loads(job.match_json) if job.match_json else {}
    except ValueError:
        pass
    d = {"job_id": job.job_id, "title": job.title, "company": job.company, "location": job.location, "remote": bool(job.remote),
         "salary": job.salary, "description": job.description, "region": job.region, "posted_at": job.posted_at,
         "first_seen": job.first_seen, "flags": job.flags,
         "fit_score": job.fit_score, "kw_fit": stored.get("fit_keyword", job.fit_score)}   # keyword pass, not the blended score
    m = matching.evaluate(d, ctx, deep=True)
    return Response({"ok": True, "match": m, "profile_years": ctx["years"], "resume": ctx["profile"].get("_filename", ""),
                     "rank": _rank(job, m), "pool": _pool(),
                     "highlights": matching.highlight_terms(job.description, m["skills"]["items"])})


def _rank(job, m):
    """Where this job sits among all stored listings (and among the same kind: local / remote)."""
    qs = Job.objects.using("jobhunt")
    total = qs.count() or 1
    kind = qs.exclude(region="") if job.region else qs.filter(region="")
    kt = kind.count() or 1
    return {"total": total, "fit_pct": round(100 * qs.filter(fit_score__lt=m["fit"]).count() / total),
            "odds_pct": round(100 * qs.filter(likelihood__lt=m["likelihood"]).count() / total),
            "kind": "local" if job.region else "remote / other", "kind_total": kt,
            "kind_fit_pct": round(100 * kind.filter(fit_score__lt=m["fit"]).count() / kt)}


def _pool(n=25):
    """Average fit breakdown of your best listings — the yardstick the radar compares a job against."""
    rows = list(Job.objects.using("jobhunt").exclude(match_json="").order_by("-fit_score")[:n])
    keys = ("skills", "evidence", "title", "experience", "domain", "preferences")
    acc = {k: [] for k in keys}
    for r in rows:
        try:
            b = json.loads(r.match_json).get("breakdown", {})
        except ValueError:
            continue
        for k in keys:
            if b.get(k) is not None:
                acc[k].append(b[k])
    return {"n": len(rows), "breakdown": {k: (round(sum(v) / len(v)) if v else None) for k, v in acc.items()}}


def _targets():
    from core.settings_store import _load_yaml
    return _load_yaml().get("targets") or {}
