"""
backend_api.py — the actual backend.

A proper REST API with SQLite persistence, background scans, and health checks.
This is what `dashboard.py` was pretending to be — now it's real.

Run:
    python -m src.backend_api        # -> http://127.0.0.1:5112
    or via dashboard.py which now proxies to it.

Endpoints:
    GET  /health                     -> liveness
    GET  /api/jobs?...               -> list with filters
    GET  /api/jobs/<job_id>          -> single
    PUT  /api/jobs/<job_id>/status   -> update Status/Notes
    GET  /api/stats                  -> aggregate
    POST /api/scans                  -> trigger scan (dry_run)
    GET  /api/scans                  -> history
    POST /api/cover                   -> draft letter
    GET  /api/letters                -> list letters
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("backend")

app = Flask(__name__)

# Import db lazily so tests that mock it still work
from src import db as _db
from src import cover_letter as _cl
from src import llm as _llm


@app.get("/health")
def health():
    try:
        cnt = _db.count_jobs()
        return jsonify({"ok": True, "jobs": cnt, "time": datetime.now().isoformat()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": repr(exc)}), 500


@app.get("/api/jobs")
def list_jobs():
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
        log.exception("list_jobs failed")
        return jsonify({"error": repr(exc)}), 500


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    job = _db.get_job(job_id)
    if not job:
        # fallback to JSON cache for backwards compat
        job = _cl.find_job(job_id)
        if not job:
            return jsonify({"error": "not found"}), 404
    return jsonify(job)


@app.get("/api/jobs/<path:job_id>/details")
def job_details(job_id: str):
    job = _db.get_job(job_id) or _cl.find_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    try:
        from src import job_details as _jd
        from src import likelihood as _like
        from src import resume as _res
        prof = _res.parse().get("profile") or {}
        if "likelihood" not in job:
            job["likelihood"] = _like.rate(job, prof)
        details = _jd.analyze(job, prof)
        return jsonify({"job": job, "details": details, "likelihood": job["likelihood"]})
    except Exception as exc:  # noqa: BLE001
        import traceback
        return jsonify({"error": repr(exc), "trace": traceback.format_exc()[:2000]}), 500


@app.put("/api/jobs/<job_id>/status")
def update_job_status(job_id: str):
    data = request.get_json(force=True) or {}
    ok = _db.update_status(
        job_id,
        status=data.get("status"),
        notes=data.get("notes"),
        applied_date=data.get("applied_date"),
        followup_date=data.get("followup_date"),
    )
    if not ok:
        return jsonify({"error": "no fields to update"}), 400
    return jsonify({"ok": True, "job_id": job_id})


@app.get("/api/stats")
def stats():
    try:
        s = _db.stats()
        # also include scan history
        scans = _db.list_scans(limit=1)
        s["last_scan"] = scans[0] if scans else None
        s["backends"] = _llm.describe()
        # load provider
        try:
            with open(ROOT / "config" / "profile.yaml") as fh:
                cfg = yaml.safe_load(fh) or {}
                s["provider"] = (cfg.get("cover_letter") or {}).get("provider", "auto")
        except Exception:
            s["provider"] = "auto"
        return jsonify(s)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": repr(exc)}), 500


@app.get("/api/scans")
def list_scans():
    return jsonify(_db.list_scans(limit=20))


# Background scan runner — one at a time
_scan_lock = threading.Lock()
_scan_state: dict = {"running": False, "last_id": None}


def _run_scan_async(dry_run: bool, scan_id: int):
    try:
        from src import score as scoring
        from src import sources
        cfg = _load_cfg()
        raw = sources.fetch_all(cfg)
        total_fetched = len(raw)
        jobs = scoring.rank(raw, cfg)
        # persist
        from src.run import save_local
        save_local(jobs)
        _db.upsert_jobs(jobs)
        _db.finish_scan(scan_id, total_fetched=total_fetched, total_kept=len(jobs), status="done")
        log.info("Scan %s done: %s fetched -> %s kept", scan_id, total_fetched, len(jobs))
        # optional sheets sync
        if not dry_run:
            sheet_id = os.environ.get("SHEET_ID")
            if sheet_id:
                try:
                    from src import sheets
                    sheets.sync(jobs, sheet_id)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Sheets sync failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("Scan %s failed", scan_id)
        _db.finish_scan(scan_id, total_fetched=0, total_kept=0, status="failed", error=repr(exc))
    finally:
        _scan_state["running"] = False


def _load_cfg() -> dict:
    with open(ROOT / "config" / "profile.yaml") as fh:
        return yaml.safe_load(fh) or {}


@app.post("/api/scans")
def trigger_scan():
    if _scan_state["running"]:
        return jsonify({"ok": False, "error": "scan already running"}), 409
    data = request.get_json(force=True) or {} if request.is_json else {}
    dry_run = data.get("dry_run", True) if isinstance(data, dict) else True
    scan_id = _db.create_scan()
    _scan_state["running"] = True
    _scan_state["last_id"] = scan_id
    threading.Thread(target=_run_scan_async, args=(dry_run, scan_id), daemon=True).start()
    return jsonify({"ok": True, "scan_id": scan_id, "dry_run": dry_run})


@app.get("/api/scans/<int:scan_id>")
def get_scan(scan_id: int):
    scans = _db.list_scans(limit=100)
    for s in scans:
        if s["id"] == scan_id:
            return jsonify(s)
    return jsonify({"error": "not found"}), 404


@app.post("/api/cover")
def cover():
    data = request.get_json(force=True) or {}
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"ok": False, "error": "job_id required"}), 400
    job = _db.get_job(job_id) or _cl.find_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not in store"}), 404
    try:
        text, path, backend = _cl.generate(job)
        _db.save_cover_letter(job_id, job.get("company",""), job.get("title",""), backend, text, str(path))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": repr(exc)}), 500
    return jsonify({"ok": True, "text": text, "path": str(path.relative_to(ROOT)) if path else "", "backend": backend,
                    "job": {k: job.get(k) for k in ("title","company","url","fit_score","flags")}})


@app.get("/api/letters")
def list_letters():
    return jsonify(_db.list_letters(limit=30))


@app.get("/api/state")
def compat_state():
    """Backwards compat for old dashboard.html that hits /api/state"""
    jobs = _db.export_jobs_json()
    # fallback to JSON file if DB empty (first run)
    if not jobs:
        p = OUTPUT / "jobs_latest.json"
        if p.exists():
            try:
                jobs = json.loads(p.read_text())
            except Exception:
                jobs = []
    generated = None
    if (OUTPUT / "jobs_latest.json").exists():
        try:
            generated = datetime.fromtimestamp((OUTPUT / "jobs_latest.json").stat().st_mtime).isoformat(timespec="seconds")
        except Exception:
            pass
    letters = sorted((p.name for p in OUTPUT.glob("cover_*.md")), reverse=True)
    # also from DB
    db_letters = _db.list_letters(limit=50)
    return jsonify({
        "jobs": jobs,
        "generated": generated,
        "letters": letters,
        "db_letters": db_letters,
        "busy": _scan_state["running"],
        "task": "scan" if _scan_state["running"] else None,
        "returncode": None,
        "sheet_configured": bool(os.environ.get("SHEET_ID")),
        "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "sheet_id": os.environ.get("SHEET_ID",""),
        "backends": _llm.describe(),
        "provider": _load_cfg().get("cover_letter",{}).get("provider","auto"),
        "stats": _db.stats(),
    })


if __name__ == "__main__":
    OUTPUT.mkdir(exist_ok=True)
    # ensure DB migrated and seeded from existing JSON if empty
    if _db.count_jobs() == 0 and (OUTPUT / "jobs_latest.json").exists():
        try:
            jobs = json.loads((OUTPUT / "jobs_latest.json").read_text())
            _db.upsert_jobs(jobs)
            log.info("Seeded DB with %s jobs from jobs_latest.json", len(jobs))
        except Exception as exc:
            log.warning("DB seed failed: %s", exc)
    port = int(os.environ.get("PORT", 5112))
    print(f"\n  Backend API: http://127.0.0.1:{port}\n  Health: http://127.0.0.1:{port}/health\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
