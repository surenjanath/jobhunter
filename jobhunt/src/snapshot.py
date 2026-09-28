"""
snapshot.py — one row per day describing the market as your resume sees it, so Analytics can draw trends.

Recorded after every scan and every re-score (one row per day; later runs that day overwrite it):
  total / good-fit / decent-odds counts, local vs remote, average fit and odds, and **market coverage** — the share of the
  skills the listings ask for that your resume covers (have = 1, adjacent = 0.5). Coverage moving up is what a better resume
  or a newly learned skill looks like.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone

from src import db


def compute(rows: list[dict]) -> dict:
    tot = got = 0.0
    demand: Counter = Counter()
    for r in rows:
        try:
            m = json.loads(r.get("match_json") or "{}")
        except ValueError:
            continue
        for it in (m.get("skills") or {}).get("items", []):
            if it["status"] == "soft":
                continue
            w = it.get("weight", 1.0)
            tot += w
            got += w * (1 if it["status"] == "have" else 0.5 if it["status"] == "related" else 0)
            demand[(it["name"], it["status"])] += 1
    top = Counter()
    for (name, status), n in demand.items():
        top[name] += n
    have = {n for (n, s) in demand if s == "have"}
    n = len(rows) or 1
    return {
        "total": len(rows), "good": sum(r["fit_score"] >= 50 for r in rows), "decent": sum((r.get("likelihood") or 0) >= 40 for r in rows),
        "local": sum(bool(r.get("region")) for r in rows), "remote": sum((not r.get("region")) and r.get("work_mode") == "remote" for r in rows),
        "avg_fit": round(sum(r["fit_score"] for r in rows) / n, 1), "avg_odds": round(sum((r.get("likelihood") or 0) for r in rows) / n, 1),
        "coverage": round(100 * got / tot, 1) if tot else 0.0,
        "top_skills": [{"skill": k, "jobs": v, "have": k in have} for k, v in top.most_common(12)],
    }


def record(day: str | None = None) -> dict:
    """Compute from the stored jobs and upsert today's row."""
    c = db._conn()
    rows = [dict(r) for r in c.execute("SELECT fit_score, likelihood, region, work_mode, match_json FROM jobs")]
    c.close()
    m = compute(rows)
    day = day or date.today().isoformat()
    with db._lock:
        c = db._conn()
        c.execute("INSERT INTO snapshots(day,total,good,decent,local,remote,avg_fit,avg_odds,coverage,top_skills,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(day) DO UPDATE SET total=excluded.total, good=excluded.good, decent=excluded.decent, local=excluded.local, remote=excluded.remote, "
                  "avg_fit=excluded.avg_fit, avg_odds=excluded.avg_odds, coverage=excluded.coverage, top_skills=excluded.top_skills, created_at=excluded.created_at",
                  (day, m["total"], m["good"], m["decent"], m["local"], m["remote"], m["avg_fit"], m["avg_odds"], m["coverage"], json.dumps(m["top_skills"]),
                   datetime.now(timezone.utc).isoformat(timespec="seconds")))
        c.commit()
        c.close()
    return {**m, "day": day}


def history(limit: int = 90) -> list[dict]:
    c = db._conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM snapshots ORDER BY day DESC LIMIT ?", (limit,))]
    c.close()
    for r in rows:
        r["top_skills"] = json.loads(r["top_skills"] or "[]")
    return rows[::-1]
