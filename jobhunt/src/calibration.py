"""
calibration.py — turn the likelihood model's *priors* into your own observed rates.

The likelihood model starts from a generic prior for how often an application becomes an interview
(local ≈ 10%, remote ≈ 1.5%). As you record outcomes on the Pipeline, those priors are updated
(Bayesian shrinkage, so a handful of applications nudges them and dozens replace them):

  positive  = status Interviewing / Offer
  negative  = status Rejected, or Applied with no response for 21+ days
  pending   = Applied < 21 days ago  (ignored — no outcome yet)
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from src import db

DEFAULT = {"local": 0.10, "remote": 0.015}
STRENGTH = 15          # pseudo-applications the prior is worth
STALE_DAYS = 21
POSITIVE = ("Interviewing", "Interview", "Offer")


def _outcomes() -> dict[str, dict[str, int]]:
    c = db._conn()
    rows = c.execute("SELECT a.status, a.applied_date, a.updated_at, j.region, j.location, j.remote FROM app_status a "
                     "JOIN jobs j ON j.job_id = a.job_id WHERE a.status IN ('Applied','Interviewing','Interview','Offer','Rejected')").fetchall()
    c.close()
    out = {"local": {"pos": 0, "neg": 0, "pending": 0}, "remote": {"pos": 0, "neg": 0, "pending": 0}}
    for r in rows:
        local = bool(r["region"]) or "trinidad" in (r["location"] or "").lower()
        g = out["local" if local else "remote"]
        if r["status"] in POSITIVE:
            g["pos"] += 1
        elif r["status"] == "Rejected":
            g["neg"] += 1
        else:  # Applied
            when = (r["applied_date"] or r["updated_at"] or "")[:10]
            try:
                age = (date.today() - date.fromisoformat(when)).days
            except ValueError:
                age = 0
            g["neg" if age >= STALE_DAYS else "pending"] += 1
    return out


def priors(prefs: dict | None = None) -> dict:
    """{'local': {'p','source','n'}, 'remote': {...}} — prior interview probabilities, updated by your history."""
    try:
        oc = _outcomes()
    except Exception:  # noqa: BLE001  (no tables yet)
        oc = {"local": {"pos": 0, "neg": 0, "pending": 0}, "remote": {"pos": 0, "neg": 0, "pending": 0}}
    out = {}
    for kind in ("local", "remote"):
        g = oc[kind]
        n = g["pos"] + g["neg"]
        base = DEFAULT[kind]
        if n:
            p = (base * STRENGTH + g["pos"]) / (STRENGTH + n)
            out[kind] = {"p": round(min(max(p, 0.003), 0.6), 4), "n": n, "pending": g["pending"], "positives": g["pos"],
                         "source": f"your history ({n} decided applications)"}
        else:
            out[kind] = {"p": base, "n": 0, "pending": g["pending"], "positives": 0, "source": "default prior (no outcomes recorded yet)"}
    return out
