"""
db.py — SQLite persistence for the actual backend.

Tables:
  jobs          — latest ranked jobs (upsert by job_id)
  scans         — history of each run
  cover_letters — generated letters
  app_status    — user-tracked status per job (joins to jobs)

No external deps; uses stdlib sqlite3.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("JOBHUNT_DB", str(ROOT / "output" / "jobhunt.db")))

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    location    TEXT DEFAULT '',
    remote      INTEGER DEFAULT 0,
    salary      TEXT DEFAULT '',
    url         TEXT NOT NULL,
    description TEXT DEFAULT '',
    posted_at   TEXT DEFAULT '',
    fit_score   INTEGER DEFAULT 0,
    tier        TEXT DEFAULT '',
    why         TEXT DEFAULT '',
    flags       TEXT DEFAULT '',
    alt_urls    TEXT DEFAULT '',
    seen_on     TEXT DEFAULT '',
    first_seen  TEXT DEFAULT '',
    updated_at  TEXT NOT NULL,
    expires_at  TEXT DEFAULT '',
    last_seen   TEXT DEFAULT '',
    region      TEXT DEFAULT '',
    category    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS source_runs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    label    TEXT DEFAULT '',
    ok       INTEGER DEFAULT 1,
    count    INTEGER DEFAULT 0,
    ms       INTEGER DEFAULT 0,
    error    TEXT DEFAULT '',
    ran_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resume_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT DEFAULT '',
    source        TEXT DEFAULT 'upload',
    text          TEXT NOT NULL,
    profile_json  TEXT NOT NULL,
    overrides_json TEXT DEFAULT '{}',
    active        INTEGER DEFAULT 0,
    embed_model   TEXT DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resume_chunks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id INTEGER NOT NULL,
    ord       INTEGER DEFAULT 0,
    section   TEXT DEFAULT '',
    label     TEXT DEFAULT '',
    text      TEXT NOT NULL,
    embedding TEXT DEFAULT '',
    FOREIGN KEY(resume_id) REFERENCES resume_versions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_resume_chunks_rid ON resume_chunks(resume_id);
CREATE TABLE IF NOT EXISTS snapshots (
    day        TEXT PRIMARY KEY,
    total      INTEGER DEFAULT 0,
    good       INTEGER DEFAULT 0,
    decent     INTEGER DEFAULT 0,
    local      INTEGER DEFAULT 0,
    remote     INTEGER DEFAULT 0,
    avg_fit    REAL DEFAULT 0,
    avg_odds   REAL DEFAULT 0,
    coverage   REAL DEFAULT 0,
    top_skills TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_runs_name ON source_runs(name, id DESC);
CREATE TABLE IF NOT EXISTS scans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    total_fetched INTEGER DEFAULT 0,
    total_kept    INTEGER DEFAULT 0,
    status        TEXT DEFAULT 'running',
    error         TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cover_letters (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL,
    company    TEXT DEFAULT '',
    title      TEXT DEFAULT '',
    backend    TEXT DEFAULT '',
    text       TEXT NOT NULL,
    path       TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
);
CREATE TABLE IF NOT EXISTS app_status (
    job_id       TEXT PRIMARY KEY,
    status       TEXT DEFAULT 'New',
    applied_date TEXT DEFAULT '',
    followup_date TEXT DEFAULT '',
    notes        TEXT DEFAULT '',
    updated_at   TEXT NOT NULL,
    starred      INTEGER DEFAULT 0,
    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(fit_score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
"""

# Columns added after the first release. Existing databases are upgraded in place.
_MIGRATIONS = {
    "jobs": {"expires_at": "TEXT DEFAULT ''", "last_seen": "TEXT DEFAULT ''",
             "region": "TEXT DEFAULT ''", "category": "TEXT DEFAULT ''",
             "likelihood": "INTEGER DEFAULT 0", "interview_chance": "INTEGER DEFAULT 0",
             "work_mode": "TEXT DEFAULT ''", "remote_scope": "TEXT DEFAULT ''", "match_json": "TEXT DEFAULT ''"},
    "app_status": {"starred": "INTEGER DEFAULT 0", "dismiss_reason": "TEXT DEFAULT ''"},
}


def _migrate(c: sqlite3.Connection) -> None:
    for table, cols in _MIGRATIONS.items():
        have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        for name, ddl in cols.items():
            if name not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    # indexes on migrated columns must come after the ALTERs
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_region ON jobs(region)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_expires ON jobs(expires_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_likelihood ON jobs(likelihood DESC)")
    c.commit()


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")
    return c


_conn_once = _conn()
_conn_once.executescript(_SCHEMA)
_conn_once.commit()
_migrate(_conn_once)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_jobs(jobs: list[dict]) -> int:
    """Insert/update jobs, preserving first_seen. Returns count."""
    if not jobs:
        return 0
    with _lock:
        c = _conn()
        # Load existing first_seen
        existing = {r["job_id"]: r["first_seen"] for r in c.execute("SELECT job_id, first_seen FROM jobs")}
        now = _now()
        today = datetime.now().date().isoformat()
        rows = []
        for j in jobs:
            jid = j.get("job_id", "")
            if not jid:
                continue
            fs = existing.get(jid) or today
            rows.append((
                jid, j.get("source",""), j.get("title","")[:300], j.get("company","")[:150],
                j.get("location","")[:150], 1 if j.get("remote") else 0, j.get("salary","")[:120],
                j.get("url",""), j.get("description","")[:12000], j.get("posted_at",""),
                int(j.get("fit_score",0)), j.get("tier",""), j.get("why","")[:600],
                j.get("flags","")[:600], j.get("alt_urls","")[:800], j.get("seen_on","")[:200],
                fs, now, j.get("expires_at","") or "", today, j.get("region","") or "", j.get("category","") or "",
                int(j.get("likelihood", 0) or 0), int(j.get("interview_chance", 0) or 0), j.get("work_mode","") or "",
                j.get("remote_scope","") or "", j.get("match_json","") or ""
            ))
        c.executemany("""
            INSERT INTO jobs(job_id,source,title,company,location,remote,salary,url,description,posted_at,fit_score,tier,why,flags,alt_urls,seen_on,first_seen,updated_at,expires_at,last_seen,region,category,likelihood,interview_chance,work_mode,remote_scope,match_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
                source=excluded.source, title=excluded.title, company=excluded.company,
                location=excluded.location, remote=excluded.remote, salary=excluded.salary,
                url=excluded.url, description=excluded.description, posted_at=excluded.posted_at,
                fit_score=excluded.fit_score, tier=excluded.tier, why=excluded.why,
                flags=excluded.flags, alt_urls=excluded.alt_urls, seen_on=excluded.seen_on,
                updated_at=excluded.updated_at, expires_at=excluded.expires_at,
                last_seen=excluded.last_seen, region=excluded.region, category=excluded.category,
                likelihood=excluded.likelihood, interview_chance=excluded.interview_chance, work_mode=excluded.work_mode,
                remote_scope=excluded.remote_scope, match_json=excluded.match_json
        """, rows)
        c.commit()
        # Ensure app_status rows exist for new jobs
        for j in jobs:
            jid = j.get("job_id")
            if jid:
                c.execute("INSERT OR IGNORE INTO app_status(job_id,status,updated_at) VALUES(?,?,?)", (jid, "New", now))
        c.commit()
        c.close()
        return len(rows)


def get_jobs(limit: int = 100, offset: int = 0, min_score: int = 0, source: str = "", search: str = "", tier: str = "") -> list[dict]:
    c = _conn()
    q = "SELECT j.*, a.status as app_status FROM jobs j LEFT JOIN app_status a ON j.job_id=a.job_id WHERE 1=1"
    params: list[Any] = []
    if min_score:
        q += " AND j.fit_score >= ?"
        params.append(min_score)
    if source:
        q += " AND j.source LIKE ?"
        params.append(f"{source}%")
    if tier:
        if tier == "65":
            q += " AND j.fit_score >= 65"
        elif tier == "50":
            q += " AND j.fit_score >= 50"
    if search:
        q += " AND (j.title LIKE ? OR j.company LIKE ? OR j.location LIKE ? OR j.description LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like, like])
    q += " ORDER BY j.fit_score DESC, j.company ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = [dict(r) for r in c.execute(q, params)]
    c.close()
    # Normalize remote bool
    for r in rows:
        r["remote"] = bool(r["remote"])
    return rows


def get_job(job_id: str) -> dict | None:
    c = _conn()
    row = c.execute("SELECT j.*, a.status as app_status FROM jobs j LEFT JOIN app_status a ON j.job_id=a.job_id WHERE j.job_id=?", (job_id,)).fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    d["remote"] = bool(d["remote"])
    return d


def count_jobs() -> int:
    c = _conn()
    n = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    c.close()
    return n


def stats() -> dict:
    c = _conn()
    total = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    t1 = c.execute("SELECT COUNT(*) FROM jobs WHERE fit_score >=65").fetchone()[0]
    t2 = c.execute("SELECT COUNT(*) FROM jobs WHERE fit_score >=50 AND fit_score <65").fetchone()[0]
    # group by the part of `source` before ":" (e.g. greenhouse:acme -> greenhouse)
    by_src2 = {}
    for r in c.execute("SELECT source, COUNT(*) as c FROM jobs GROUP BY source"):
        src = r["source"].split(":")[0]
        by_src2[src] = by_src2.get(src, 0) + r["c"]
    c.close()
    return {"total": total, "tier1": t1, "tier2": t2, "by_source": by_src2}


def update_status(job_id: str, status: str = None, notes: str = None, applied_date: str = None, followup_date: str = None,
                  dismiss_reason: str = None) -> bool:
    fields = []
    params: list[Any] = []
    if status is not None:
        fields.append("status=?")
        params.append(status)
        if dismiss_reason is None and status != "Passed on it":
            # leaving "Passed on it" (re-opening the role) clears a stale reason from the last time it was dismissed
            fields.append("dismiss_reason=?")
            params.append("")
    if dismiss_reason is not None:
        fields.append("dismiss_reason=?")
        params.append(dismiss_reason)
    if notes is not None:
        fields.append("notes=?")
        params.append(notes)
    if applied_date is not None:
        fields.append("applied_date=?")
        params.append(applied_date)
    if followup_date is not None:
        fields.append("followup_date=?")
        params.append(followup_date)
    if not fields:
        return False
    fields.append("updated_at=?")
    params.append(_now())
    params.append(job_id)
    with _lock:
        c = _conn()
        cur = c.execute(f"UPDATE app_status SET {', '.join(fields)} WHERE job_id=?", params)
        changed = cur.rowcount
        if changed == 0:
            c.execute("INSERT OR IGNORE INTO app_status(job_id,status,updated_at) VALUES(?,?,?)", (job_id, status or "New", _now()))
            # then update again with provided fields if insert happened
            if c.execute("SELECT changes()").fetchone()[0] == 1 and len(fields) > 1:
                # Re-apply updates (already handled by insert, but ensure notes etc)
                c.execute(f"UPDATE app_status SET {', '.join(fields)} WHERE job_id=?", params)
        c.commit()
        c.close()
    return True


def record_source_runs(runs: list[dict]) -> None:
    """Persist per-source health from one scan (trinidad.HEALTH values)."""
    if not runs:
        return
    with _lock:
        c = _conn()
        c.executemany(
            "INSERT INTO source_runs(name,label,ok,count,ms,error,ran_at) VALUES(?,?,?,?,?,?,?)",
            [(r["name"], r.get("label", ""), 1 if r.get("ok", True) else 0, int(r.get("count", 0)),
              int(r.get("ms", 0)), (r.get("error") or "")[:300], r.get("ran_at") or _now()) for r in runs])
        # keep the table small: 30 runs per source
        c.execute("DELETE FROM source_runs WHERE id NOT IN (SELECT id FROM source_runs r2 WHERE r2.name=source_runs.name ORDER BY id DESC LIMIT 30)")
        c.commit()
        c.close()


def source_health() -> dict[str, dict]:
    """Latest run per source plus its last success."""
    c = _conn()
    out: dict[str, dict] = {}
    for r in c.execute("SELECT * FROM source_runs ORDER BY id DESC"):
        d = out.setdefault(r["name"], {"name": r["name"], "label": r["label"], "ok": bool(r["ok"]),
                                       "count": r["count"], "ms": r["ms"], "error": r["error"],
                                       "ran_at": r["ran_at"], "last_success": ""})
        if r["ok"] and not d["last_success"]:
            d["last_success"] = r["ran_at"]
    c.close()
    return out


def purge_expired(today: str | None = None) -> int:
    """Delete closed postings nobody is tracking. Tracked jobs (status != New or starred) are kept."""
    today = today or datetime.now().date().isoformat()
    with _lock:
        c = _conn()
        cur = c.execute("""DELETE FROM jobs WHERE expires_at != '' AND expires_at < ?
                           AND job_id NOT IN (SELECT job_id FROM app_status WHERE status != 'New' OR starred = 1)""", (today,))
        n = cur.rowcount
        c.execute("DELETE FROM app_status WHERE job_id NOT IN (SELECT job_id FROM jobs) AND status='New' AND starred=0")
        c.commit()
        c.close()
        return n


def purge_legacy_trinidad(sources: list[str]) -> int:
    """Remove rows written by the pre-2026-09 Trinidad fetchers (unstable hash() ids, homepage urls)."""
    if not sources:
        return 0
    marks = ",".join("?" * len(sources))
    with _lock:
        c = _conn()
        cur = c.execute(f"""DELETE FROM jobs WHERE source IN ({marks}) AND region = ''
                            AND job_id NOT IN (SELECT job_id FROM app_status WHERE status != 'New' OR starred = 1)""", sources)
        n = cur.rowcount
        c.execute("DELETE FROM app_status WHERE job_id NOT IN (SELECT job_id FROM jobs) AND status='New' AND starred=0")
        c.commit()
        c.close()
        return n


def rescore_all(score_fn) -> int:
    """Re-run scoring over every stored job (no network). `score_fn(job_dict) -> job_dict`."""
    with _lock:
        c = _conn()
        rows = [dict(r) for r in c.execute("SELECT * FROM jobs")]
        upd = []
        for r in rows:
            r["remote"] = bool(r["remote"])
            n = score_fn(dict(r))
            upd.append((int(n["fit_score"]), n["tier"], n["why"][:600], n["flags"][:600],
                        int(n.get("likelihood", 0) or 0), int(n.get("interview_chance", 0) or 0), n.get("work_mode", "") or "",
                        n.get("remote_scope", "") or "", n.get("match_json", "") or "", r["job_id"]))
        c.executemany("UPDATE jobs SET fit_score=?, tier=?, why=?, flags=?, likelihood=?, interview_chance=?, work_mode=?, remote_scope=?, match_json=? WHERE job_id=?", upd)
        c.commit()
        c.close()
        return len(upd)


def set_starred(job_id: str, starred: bool) -> None:
    with _lock:
        c = _conn()
        c.execute("INSERT OR IGNORE INTO app_status(job_id,status,updated_at) VALUES(?,?,?)", (job_id, "New", _now()))
        c.execute("UPDATE app_status SET starred=?, updated_at=? WHERE job_id=?", (1 if starred else 0, _now(), job_id))
        c.commit()
        c.close()


def create_scan() -> int:
    with _lock:
        c = _conn()
        cur = c.execute("INSERT INTO scans(started_at,status) VALUES(?,?)", (_now(), "running"))
        sid = cur.lastrowid
        c.commit()
        c.close()
        return sid


def finish_scan(scan_id: int, total_fetched: int, total_kept: int, status: str = "done", error: str = ""):
    with _lock:
        c = _conn()
        c.execute("UPDATE scans SET finished_at=?, total_fetched=?, total_kept=?, status=?, error=? WHERE id=?",
                  (_now(), total_fetched, total_kept, status, error[:2000], scan_id))
        c.commit()
        c.close()


def list_scans(limit: int = 10) -> list[dict]:
    c = _conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,))]
    c.close()
    return rows


def save_cover_letter(job_id: str, company: str, title: str, backend: str, text: str, path: str) -> int:
    with _lock:
        c = _conn()
        cur = c.execute("INSERT INTO cover_letters(job_id,company,title,backend,text,path,created_at) VALUES(?,?,?,?,?,?,?)",
                        (job_id, company, title, backend, text, path, _now()))
        lid = cur.lastrowid
        c.commit()
        c.close()
        return lid


def list_letters(limit: int = 20) -> list[dict]:
    c = _conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM cover_letters ORDER BY id DESC LIMIT ?", (limit,))]
    c.close()
    return rows


def export_jobs_json() -> list[dict]:
    """For dashboard compat: return all jobs sorted."""
    return get_jobs(limit=5000, offset=0)
