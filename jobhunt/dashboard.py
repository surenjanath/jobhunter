#!/usr/bin/env python3
"""
dashboard.py — local control panel for the whole system.

    pip install flask
    python dashboard.py
    open http://127.0.0.1:5111

Runs the scan, tails the log live, browses and filters results, drafts cover
letters, and pushes to Google Sheets. Everything the CLI does, with buttons.

Binds to 127.0.0.1 only. Nothing is exposed to your network.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
PYTHON = sys.executable

app = Flask(__name__, static_folder=None)

# ---- actual backend DB (new) ----
try:
    from src import db as _db
    _has_db = True
except Exception:
    _db = None
    _has_db = False

# ---------------------------------------------------------------------------
# background job runner — one at a time, with a live log tail
# ---------------------------------------------------------------------------

_log_lines: list[str] = []
_log_lock = threading.Lock()
_current: dict = {"task": None, "started": None, "returncode": None}


def _append(line: str) -> None:
    with _log_lock:
        _log_lines.append(line.rstrip("\n"))
        if len(_log_lines) > 800:
            del _log_lines[:-800]


def _run(task: str, cmd: list[str]) -> None:
    _current.update(task=task, started=datetime.now().isoformat(), returncode=None)
    _append(f"$ {' '.join(cmd[1:])}")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        for line in proc.stdout:  # type: ignore[union-attr]
            _append(line)
        proc.wait()
        _current["returncode"] = proc.returncode
        _append(f"--- finished, exit code {proc.returncode} ---")
    except Exception as exc:  # noqa: BLE001
        _current["returncode"] = -1
        _append(f"!!! failed to start: {exc!r}")
    finally:
        _current["task"] = None


def _busy() -> bool:
    return _current["task"] is not None


def _start(task: str, cmd: list[str]):
    if _busy():
        return jsonify({"ok": False, "error": f"'{_current['task']}' is already running"}), 409
    with _log_lock:
        _log_lines.clear()
    threading.Thread(target=_run, args=(task, cmd), daemon=True).start()
    return jsonify({"ok": True, "task": task})


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    if _has_db:
        try:
            cnt = _db.count_jobs()
            return jsonify({"ok": True, "jobs": cnt, "backend": "sqlite", "time": datetime.now().isoformat()})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": repr(exc)}), 500
    return jsonify({"ok": True, "backend": "json", "time": datetime.now().isoformat()})


@app.get("/api/stats")
def stats():
    if _has_db:
        try:
            s = _db.stats()
            return jsonify(s)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": repr(exc)}), 500
    # fallback: compute from JSON
    jobs = []
    p = OUTPUT / "jobs_latest.json"
    if p.exists():
        try:
            jobs = json.loads(p.read_text())
        except Exception:
            pass
    return jsonify({
        "total": len(jobs),
        "tier1": len([j for j in jobs if j.get("fit_score", 0) >= 65]),
        "tier2": len([j for j in jobs if 50 <= j.get("fit_score", 0) < 65]),
        "by_source": {},
    })


@app.get("/api/jobs")
def api_jobs():
    if _has_db:
        try:
            limit = min(int(request.args.get("limit", 50)), 200)
            offset = int(request.args.get("offset", 0))
            min_score = int(request.args.get("min_score", 0))
            source = request.args.get("source", "")
            search = request.args.get("search", "")
            tier = request.args.get("tier", "")
            jobs = _db.get_jobs(limit=limit, offset=offset, min_score=min_score, source=source, search=search, tier=tier)
            total = _db.count_jobs()
            return jsonify({"jobs": jobs, "total": total, "limit": limit, "offset": offset})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": repr(exc)}), 500
    return jsonify({"error": "db not available"}), 500


@app.get("/api/jobs/<path:job_id>/details")
def api_job_details(job_id: str):
    # Detailed analysis: tech, requirements, likelihood
    job = None
    if _has_db:
        job = _db.get_job(job_id)
    if not job:
        from src import cover_letter
        job = cover_letter.find_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    try:
        from src import job_details as _jd
        from src import likelihood as _like
        from src import resume as _res
        prof = _res.parse().get("profile") or {}
        # attach likelihood if not present
        if "likelihood" not in job:
            job["likelihood"] = _like.rate(job, prof)
        details = _jd.analyze(job, prof)
        # also include analytics for context
        return jsonify({
            "job": job,
            "details": details,
            "likelihood": job["likelihood"],
        })
    except Exception as exc:  # noqa: BLE001
        import traceback
        return jsonify({"error": repr(exc), "trace": traceback.format_exc()[:2000]}), 500


@app.get("/api/analytics")
def api_analytics():
    try:
        from src import analytics as _an
        return jsonify(_an.full_dashboard())
    except Exception as exc:  # noqa: BLE001
        import traceback
        return jsonify({"error": repr(exc), "trace": traceback.format_exc()[:2000]}), 500


@app.get("/api/resume")
def api_resume():
    try:
        from src import resume as _res
        return jsonify(_res.parse())
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": repr(exc)}), 500


@app.get("/api/kanban")
def api_kanban():
    try:
        if not _has_db:
            return jsonify({"error": "db not available"}), 500
        # Group jobs by app_status
        cols = ["New","Shortlisted","Applied","Interviewing","Offer","Rejected","Passed on it"]
        out = {}
        for status in cols:
            jobs = _db.get_jobs(limit=50, offset=0)
            # Filter in Python since get_jobs doesn't filter by status
            filtered = [j for j in jobs if (j.get("app_status") or "New") == status]
            out[status] = filtered[:10]
        # Also get counts per status
        counts = {}
        for status in cols:
            counts[status] = len([j for j in _db.get_jobs(limit=5000) if (j.get("app_status") or "New") == status])
        return jsonify({"columns": out, "counts": counts, "statuses": cols})
    except Exception as exc:  # noqa: BLE001
        import traceback
        return jsonify({"error": repr(exc), "trace": traceback.format_exc()[:2000]}), 500


@app.get("/api/jobs/<path:job_id>/ats")
def api_ats(job_id: str):
    job = None
    if _has_db:
        job = _db.get_job(job_id)
    if not job:
        from src import cover_letter
        job = cover_letter.find_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    try:
        from src import ats as _ats
        from src import matching
        return jsonify(_ats.score(job, matching.resume_text()))
    except Exception as exc:  # noqa: BLE001
        import traceback
        return jsonify({"error": repr(exc), "trace": traceback.format_exc()[:2000]}), 500


@app.get("/api/jobs/<path:job_id>/interview")
def api_interview(job_id: str):
    job = None
    if _has_db:
        job = _db.get_job(job_id)
    if not job:
        from src import cover_letter
        job = cover_letter.find_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    try:
        from src import interview as _iv
        return jsonify(_iv.prep(job))
    except Exception as exc:  # noqa: BLE001
        import traceback
        return jsonify({"error": repr(exc), "trace": traceback.format_exc()[:2000]}), 500


@app.get("/api/jobs/<path:job_id>/salary")
def api_salary(job_id: str):
    job = None
    if _has_db:
        job = _db.get_job(job_id)
    if not job:
        from src import cover_letter
        job = cover_letter.find_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    try:
        from src import salary as _sal
        b = _sal.benchmark(job)
        if not b:
            return jsonify({"has_salary": False, "message": "No salary disclosed"})
        return jsonify({"has_salary": True, **b})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": repr(exc)}), 500


@app.get("/api/jobs/<path:job_id>/company")
def api_company(job_id: str):
    job = None
    if _has_db:
        job = _db.get_job(job_id)
    if not job:
        from src import cover_letter
        job = cover_letter.find_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    try:
        from src import company as _co
        return jsonify(_co.research(job))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": repr(exc)}), 500


@app.get("/api/jobs/<path:job_id>/ai-match")
def api_ai_match(job_id: str):
    job = None
    if _has_db:
        job = _db.get_job(job_id)
    if not job:
        from src import cover_letter
        job = cover_letter.find_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    try:
        from src import ai_match as _am
        return jsonify(_am.semantic_score(job))
    except Exception as exc:  # noqa: BLE001
        import traceback
        return jsonify({"error": repr(exc), "trace": traceback.format_exc()[:2000]}), 500


@app.get("/api/jobs/<path:job_id>/tailor")
def api_tailor(job_id: str):
    job = None
    if _has_db:
        job = _db.get_job(job_id)
    if not job:
        from src import cover_letter
        job = cover_letter.find_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    try:
        from src import ai_resume as _ar
        return jsonify(_ar.tailor(job))
    except Exception as exc:  # noqa: BLE001
        import traceback
        return jsonify({"error": repr(exc), "trace": traceback.format_exc()[:2000]}), 500


@app.get("/api/coach/brief")
def api_coach_brief():
    try:
        from src import ai_coach as _coach
        jobs = _db.export_jobs_json() if _has_db else []
        return jsonify(_coach.daily_brief(jobs[:5]))
    except Exception as exc:  # noqa: BLE001
        import traceback
        return jsonify({"error": repr(exc), "trace": traceback.format_exc()[:2000]}), 500


@app.get("/api/coach/actions")
def api_coach_actions():
    try:
        from src import ai_coach as _coach
        jobs = _db.export_jobs_json() if _has_db else []
        return jsonify(_coach.priority_actions(jobs))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": repr(exc)}), 500


@app.put("/api/jobs/<path:job_id>/status")
def api_update_status(job_id: str):
    if not _has_db:
        return jsonify({"error": "db not available"}), 500
    data = request.get_json(force=True) or {}
    ok = _db.update_status(job_id, status=data.get("status"), notes=data.get("notes"),
                            applied_date=data.get("applied_date"), followup_date=data.get("followup_date"))
    if not ok:
        return jsonify({"error": "no fields"}), 400
    return jsonify({"ok": True, "job_id": job_id})


@app.get("/")
def index():
    return send_from_directory(ROOT, "dashboard.html")


@app.get("/api/state")
def state():
    jobs = []
    generated = None
    stats = None
    # Prefer DB if available, else JSON
    if _has_db:
        try:
            jobs = _db.export_jobs_json()
            stats = _db.stats()
        except Exception:
            pass
    if not jobs:
        path = OUTPUT / "jobs_latest.json"
        if path.exists():
            try:
                jobs = json.loads(path.read_text(encoding="utf-8"))
                generated = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
            except json.JSONDecodeError:
                jobs = []
            # also try to get generated from DB file mtime if json missing
        if _has_db and not generated:
            try:
                if (OUTPUT / "jobhunt.db").exists():
                    generated = datetime.fromtimestamp((OUTPUT / "jobhunt.db").stat().st_mtime).isoformat(timespec="seconds")
            except Exception:
                pass
    else:
        # DB jobs, get generated from DB mtime
        try:
            if (OUTPUT / "jobhunt.db").exists():
                generated = datetime.fromtimestamp((OUTPUT / "jobhunt.db").stat().st_mtime).isoformat(timespec="seconds")
            elif (OUTPUT / "jobs_latest.json").exists():
                generated = datetime.fromtimestamp((OUTPUT / "jobs_latest.json").stat().st_mtime).isoformat(timespec="seconds")
        except Exception:
            pass

    letters = sorted(
        (p.name for p in OUTPUT.glob("cover_*.md")), reverse=True
    )

    return jsonify(
        {
            "jobs": jobs,
            "generated": generated,
            "letters": letters,
            "busy": _busy(),
            "task": _current["task"],
            "returncode": _current["returncode"],
            "sheet_configured": bool(os.environ.get("SHEET_ID")),
            "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "sheet_id": os.environ.get("SHEET_ID", ""),
            "backends": _backends(),
            "provider": _provider(),
            "stats": stats,
        }
    )


def _backends() -> dict:
    sys.path.insert(0, str(ROOT))
    try:
        from src import llm
        return llm.describe()
    except Exception as exc:  # noqa: BLE001
        return {"error": {"available": False, "detail": repr(exc)}}


def _provider() -> str:
    import yaml
    try:
        with open(ROOT / "config" / "profile.yaml", encoding="utf-8") as fh:
            return ((yaml.safe_load(fh) or {}).get("cover_letter") or {}).get(
                "provider", "auto"
            )
    except Exception:  # noqa: BLE001
        return "auto"


@app.post("/api/provider")
def set_provider():
    """Pin the cover-letter backend by rewriting the one line in profile.yaml."""
    import re as _re
    from src import llm
    name = (request.get_json(force=True) or {}).get("provider", "auto")
    if name not in llm.PROVIDERS:
        return jsonify({"ok": False, "error": "unknown provider"}), 400
    path = ROOT / "config" / "profile.yaml"
    text = path.read_text(encoding="utf-8")
    if _re.search(r"^  provider: .*$", text, _re.M):
        text = _re.sub(r"^  provider: .*$", f"  provider: {name}", text, count=1, flags=_re.M)
    else:
        text += f"\ncover_letter:\n  provider: {name}\n"
    path.write_text(text, encoding="utf-8")
    return jsonify({"ok": True, "provider": name})


@app.get("/api/logs")
def logs():
    since = request.args.get("since", type=int, default=0)
    with _log_lock:
        total = len(_log_lines)
        chunk = _log_lines[since:]
    return jsonify({"lines": chunk, "next": total, "busy": _busy(),
                    "returncode": _current["returncode"]})


@app.post("/api/scan")
def scan():
    dry = request.json.get("dry_run", True) if request.is_json else True
    cmd = [PYTHON, "-m", "src.run"]
    if dry:
        cmd.append("--dry-run")
    return _start("scan (dry run)" if dry else "scan + sheet sync", cmd)


@app.post("/api/live-check")
def live_check():
    return _start("live endpoint check", [PYTHON, "live_check.py"])


@app.post("/api/tests")
def tests():
    return _start("offline test suite", [PYTHON, "tests/test_pipeline.py"])


@app.post("/api/cover")
def cover():
    data = request.get_json(force=True)
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"ok": False, "error": "job_id required"}), 400

    sys.path.insert(0, str(ROOT))
    from src import cover_letter

    job = None
    if _has_db:
        job = _db.get_job(job_id)
    if not job:
        job = cover_letter.find_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not in the latest results"}), 404

    try:
        text, path, backend = cover_letter.generate(job)
        if _has_db:
            try:
                _db.save_cover_letter(job_id, job.get("company",""), job.get("title",""), backend, text, str(path))
            except Exception:
                pass
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": repr(exc)}), 500

    return jsonify(
        {
            "ok": True,
            "text": text,
            "path": str(path.relative_to(ROOT)),
            "backend": backend,
            "job": {k: job.get(k) for k in ("title", "company", "url", "fit_score", "flags")},
        }
    )


@app.get("/api/letter/<path:name>")
def letter(name: str):
    p = OUTPUT / name
    if not p.exists() or p.suffix != ".md":
        return jsonify({"error": "not found"}), 404
    return Response(p.read_text(encoding="utf-8"), mimetype="text/plain")


if __name__ == "__main__":
    OUTPUT.mkdir(exist_ok=True)
    port = int(os.environ.get("PORT", 5111))
    print(f"\n  Control panel:  http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
