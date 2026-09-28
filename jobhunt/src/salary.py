"""
salary.py — what a posting pays, against YOUR floor and against similar listings you have collected.

No invented "market bands": the comparison is your own preferences (profile_store prefs) and the pay actually stated by
comparable listings in your database (same kind of work, local vs remote). Amounts are normalised to monthly TT$ and US$.
"""

from __future__ import annotations

import json
import statistics

from src import matching

DEFAULT_FX = 6.78


def _prefs() -> dict:
    try:
        from src import profile_store
        return profile_store.get_prefs()
    except Exception:  # noqa: BLE001
        return {}


def parse_salary(s: str, local: bool = False) -> dict | None:
    return matching.parse_pay(s or "", local=local)


def peers(job: dict, limit: int = 400) -> dict:
    """Stated pay of comparable listings: same local/remote kind, and the same category when there are enough."""
    try:
        from src import db
        c = db._conn()
        rows = c.execute("SELECT job_id, category, region, match_json FROM jobs WHERE match_json != '' LIMIT ?", (limit,)).fetchall()
        c.close()
    except Exception:  # noqa: BLE001
        return {"n": 0}
    local = bool(job.get("region"))
    cat = job.get("category") or ""
    same_kind, same_cat = [], []
    for r in rows:
        if r["job_id"] == job.get("job_id"):
            continue
        try:
            pay = ((json.loads(r["match_json"]).get("job") or {}).get("pay"))
        except ValueError:
            continue
        if not pay or bool(r["region"]) != local:
            continue
        v = pay["monthly_ttd_max"] if local else pay["monthly_usd_max"]
        same_kind.append(v)
        if cat and r["category"] == cat:
            same_cat.append(v)
    vals, basis = (same_cat, f"{cat} roles") if len(same_cat) >= 5 else (same_kind, "local roles" if local else "remote roles")
    if not vals:
        return {"n": 0}
    vals = sorted(vals)
    q = lambda p: vals[min(len(vals) - 1, int(p * (len(vals) - 1)))]  # noqa: E731
    return {"n": len(vals), "median": round(statistics.median(vals)), "p25": q(0.25), "p75": q(0.75), "basis": basis,
            "unit": "TT$/mo" if local else "US$/mo"}


def benchmark(job: dict) -> dict | None:
    """Pay details for a job that states pay, else None. Keys: currency, period, monthly ttd/usd, vs_floor, peers."""
    local = bool(job.get("region")) or "trinidad" in (job.get("location") or "").lower()
    pay = matching.parse_pay(f"{job.get('salary') or ''}\n{(job.get('description') or '')[:3000]}", local=local)
    if not pay:
        return None
    prefs = _prefs()
    fx = float(prefs.get("fx_ttd_per_usd") or DEFAULT_FX)
    floor_ttd = prefs.get("min_salary_monthly_ttd") or (prefs.get("min_salary_monthly_usd") or 0) * fx
    top = pay["monthly_ttd_max"]
    vs = None
    if floor_ttd:
        vs = "meets" if top >= floor_ttd * 1.0 else "below"
        if pay["monthly_ttd_min"] >= floor_ttd:
            vs = "above"
    pr = peers(dict(job, region=job.get("region") or ("x" if local else "")))
    pos = None
    if pr.get("n"):
        mine = pay["monthly_ttd_max"] if local else pay["monthly_usd_max"]
        pos = "above the median" if mine > pr["median"] * 1.1 else "below the median" if mine < pr["median"] * 0.9 else "around the median"
    return {**{k: v for k, v in pay.items() if not k.startswith("_")}, "floor_ttd": int(floor_ttd or 0), "vs_floor": vs, "peers": pr, "position": pos, "fx": fx}


def context_for_missing(job: dict) -> dict:
    """When a posting states no pay: what similar listings pay, and your floor."""
    prefs = _prefs()
    fx = float(prefs.get("fx_ttd_per_usd") or DEFAULT_FX)
    return {"peers": peers(job), "floor_ttd": int(prefs.get("min_salary_monthly_ttd") or (prefs.get("min_salary_monthly_usd") or 0) * fx), "fx": fx}


def insights(jobs: list[dict]) -> dict:
    parsed = [b for b in (benchmark(j) for j in jobs) if b]
    if not parsed:
        return {"count": 0, "avg_usd": 0, "avg_ttd": 0}
    avg = round(sum(p["monthly_usd_max"] for p in parsed) / len(parsed))
    return {"count": len(parsed), "avg_usd": avg, "avg_ttd": round(avg * DEFAULT_FX)}
