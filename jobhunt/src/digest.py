"""
digest.py — "what's new that's worth my time": new listings since a date, ranked by fit and odds, as Markdown or JSON.

    python -m src.digest                    # new in the last day, fit >= 50, printed
    python -m src.digest --days 7 --min-fit 40 --out output/digest.md

Also served at /api/digest/. Blockers (US-only remote, relocation-only…) are listed separately, not mixed in.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402


def load_rows(since: str) -> list[dict]:
    c = db._conn()
    rows = [dict(r) for r in c.execute(
        "SELECT j.*, COALESCE(a.status,'New') AS app_status FROM jobs j LEFT JOIN app_status a ON a.job_id=j.job_id "
        "WHERE j.first_seen >= ? ORDER BY j.fit_score DESC", (since,))]
    c.close()
    return rows


def build(days: int = 1, min_fit: int = 50, limit: int = 15, today: date | None = None, rows: list[dict] | None = None) -> dict:
    """`rows` (job columns + app_status) may be passed in; by default they are read from the scanner database."""
    today = today or date.today()
    since = (today - timedelta(days=days)).isoformat()
    rows = load_rows(since) if rows is None else [r for r in rows if (r.get("first_seen") or "") >= since]
    picks, blocked = [], []
    for r in rows:
        if r["app_status"] not in ("New", "Shortlisted"):
            continue
        m = {}
        try:
            m = json.loads(r["match_json"]) if r["match_json"] else {}
        except ValueError:
            pass
        item = {"job_id": r["job_id"], "title": r["title"], "company": r["company"], "url": r["url"], "fit": r["fit_score"],
                "odds": r["likelihood"], "chance": r["interview_chance"], "verdict": m.get("verdict", ""),
                "where": r["region"] or ("Remote" if r["work_mode"] == "remote" else r["location"]), "mode": "local" if r["region"] else r["work_mode"] or "",
                "scope": r["remote_scope"], "closes": r["expires_at"], "advice": m.get("advice", ""),
                "matched": [s["name"] for s in (m.get("skills") or {}).get("matched", [])][:5],
                "missing": (m.get("skills") or {}).get("missing_required", [])[:3], "blockers": m.get("blockers", [])}
        if r["fit_score"] < min_fit:
            continue
        (blocked if item["blockers"] else picks).append(item)
    picks.sort(key=lambda i: -(i["fit"] * 0.5 + i["odds"] * 0.5))
    return {"since": since, "days": days, "min_fit": min_fit, "total_new": len(rows), "picks": picks[:limit], "blocked": blocked[:10],
            "more": max(0, len(picks) - limit)}


def to_markdown(d: dict) -> str:
    out = [f"# Job digest — {d['total_new']} new since {d['since']}", ""]
    if not d["picks"]:
        out.append(f"Nothing new with fit ≥ {d['min_fit']} and no blockers.")
    for i in d["picks"]:
        out.append(f"### {i['title']} — {i['company']}")
        out.append(f"fit **{i['fit']}** · odds {i['odds']} ({i['verdict']}) · ~{i['chance']}% interview · {i['where'] or '—'}"
                   + (f" · closes {i['closes']}" if i["closes"] else ""))
        if i["matched"]:
            out.append("You have: " + ", ".join(i["matched"]) + (f" · missing: {', '.join(i['missing'])}" if i["missing"] else ""))
        if i["advice"]:
            out.append(f"_{i['advice']}_")
        out.append(i["url"])
        out.append("")
    if d["more"]:
        out.append(f"…and {d['more']} more.")
    if d["blocked"]:
        out += ["", "## Good fit, but blocked", ""]
        out += [f"- {b['title']} — {b['company']}: {b['blockers'][0]}" for b in d["blocked"]]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--min-fit", type=int, default=50)
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--out", help="write Markdown here instead of printing")
    args = ap.parse_args()
    md = to_markdown(build(args.days, args.min_fit, args.limit))
    if args.out:
        Path(args.out).write_text(md)
        print(f"wrote {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
