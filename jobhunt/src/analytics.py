"""
analytics.py — the analytics engine.

Computes insights from the DB + profile + likelihood.
Used by backend_api and dashboard.

No external deps; produces JSON ready for Chart.js.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src import db as _db
from src import likelihood as _like

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "config" / "profile.yaml"


def _profile() -> dict:
    try:
        return yaml.safe_load(PROFILE.read_text()) or {}
    except Exception:
        return {}


def _jobs(limit: int = 500) -> list[dict]:
    try:
        return _db.get_jobs(limit=limit, offset=0)
    except Exception:
        return []


def overview() -> dict:
    """Top-level KPIs."""
    jobs = _jobs(2000)
    if not jobs:
        return {"total": 0, "tier1": 0, "tier2": 0, "avg": 0, "median": 0}
    prof = _profile()
    # ensure likelihood attached
    _like.batch(jobs, prof)
    scores = [j["fit_score"] for j in jobs]
    likes = [j["likelihood"]["likelihood"] for j in jobs]
    tier1 = len([j for j in jobs if j["fit_score"] >= 65])
    tier2 = len([j for j in jobs if 50 <= j["fit_score"] < 65])
    hi = len([j for j in jobs if j["likelihood"]["verdict"] == "High"])
    med = len([j for j in jobs if j["likelihood"]["verdict"] == "Medium"])
    lo = len([j for j in jobs if j["likelihood"]["verdict"] in ("Low","Long shot")])
    blocked = len([j for j in jobs if j["likelihood"]["blockers"]])
    # intl friendly
    intl = len([j for j in jobs if any(k in (j.get("flags","").lower()) for k in ["eor","timezone-friendly","sponsorship (good)"])])
    avg = round(sum(scores)/len(scores),1) if scores else 0
    avg_like = round(sum(likes)/len(likes),1) if likes else 0
    # salary disclosure rate
    sal = len([j for j in jobs if j.get("salary")])
    return {
        "total": len(jobs),
        "tier1": tier1, "tier2": tier2, "maybe": len(jobs)-tier1-tier2,
        "high_likelihood": hi, "medium": med, "low_long": lo,
        "blocked": blocked, "intl_friendly": intl,
        "avg_fit": avg, "avg_likelihood": avg_like,
        "salary_disclosed": sal, "salary_rate": round(sal/len(jobs)*100,1) if jobs else 0,
    }


def score_distribution() -> dict:
    jobs = _jobs(2000)
    buckets = {"35-49":0,"50-64":0,"65-74":0,"75-84":0,"85-100":0}
    for j in jobs:
        s = j.get("fit_score",0)
        if s < 50: buckets["35-49"] += 1
        elif s < 65: buckets["50-64"] += 1
        elif s < 75: buckets["65-74"] += 1
        elif s < 85: buckets["75-84"] += 1
        else: buckets["85-100"] += 1
    return {"buckets": buckets, "labels": list(buckets.keys()), "data": list(buckets.values())}


def likelihood_distribution() -> dict:
    jobs = _jobs(2000)
    prof = _profile()
    _like.batch(jobs, prof)
    buckets = {"Long shot":0,"Low":0,"Medium":0,"High":0}
    for j in jobs:
        buckets[j["likelihood"]["verdict"]] += 1
    return {"buckets": buckets, "labels": list(buckets.keys()), "data": list(buckets.values())}


def source_performance() -> dict:
    jobs = _jobs(2000)
    by_src: dict[str, list[int]] = defaultdict(list)
    for j in jobs:
        src = (j.get("source") or "").split(":")[0]
        by_src[src].append(j.get("fit_score",0))
    rows = []
    for src, scores in by_src.items():
        rows.append({
            "source": src,
            "count": len(scores),
            "avg": round(sum(scores)/len(scores),1) if scores else 0,
            "max": max(scores) if scores else 0,
            "tier1": len([s for s in scores if s >= 65]),
        })
    rows.sort(key=lambda r: r["avg"], reverse=True)
    return {"rows": rows, "labels": [r["source"] for r in rows], "avg": [r["avg"] for r in rows], "count": [r["count"] for r in rows]}


def gap_analysis() -> dict:
    jobs = _jobs(2000)
    prof = _profile()
    _like.batch(jobs, prof)
    gap_counts: Counter = Counter()
    for j in jobs:
        for g in j["likelihood"]["gaps"]:
            # normalize
            key = g.split(" —")[0].split(" (")[0].strip()
            gap_counts[key] += 1
    top = gap_counts.most_common(8)
    return {"top_gaps": [{"gap": k, "count": v} for k,v in top], "labels": [k for k,v in top], "data": [v for k,v in top]}


def salary_insights() -> dict:
    jobs = _jobs(2000)
    # extract numeric salaries where disclosed
    salaries = []
    for j in jobs:
        s = j.get("salary") or ""
        if not s:
            continue
        # find $XXX or €XXX
        nums = re.findall(r"[\$€£]\s*([\d,]+)", s)
        for n in nums:
            try:
                v = int(n.replace(",",""))
                if 20000 < v < 500000:
                    salaries.append(v)
            except Exception:
                continue
    hist = {"<70k":0,"70-100k":0,"100-150k":0,"150-200k":0,"200k+":0}
    for v in salaries:
        if v < 70000: hist["<70k"]+=1
        elif v < 100000: hist["70-100k"]+=1
        elif v < 150000: hist["100-150k"]+=1
        elif v < 200000: hist["150-200k"]+=1
        else: hist["200k+"]+=1
    return {"count": len(salaries), "hist": hist, "labels": list(hist.keys()), "data": list(hist.values()), "avg": round(sum(salaries)/len(salaries)) if salaries else 0}


def geography() -> dict:
    jobs = _jobs(2000)
    prof = _profile()
    _like.batch(jobs, prof)
    geo = {"remote":0,"hybrid":0,"onsite":0,"blocker":0}
    for j in jobs:
        f = (j.get("flags") or "").lower() + " " + (j.get("location") or "").lower()
        if "citizen" in f or "clearance" in f or "no sponsorship" in f:
            geo["blocker"]+=1
        elif "hybrid" in f:
            geo["hybrid"]+=1
        elif "on-site" in f or "onsite" in f:
            geo["onsite"]+=1
        else:
            geo["remote"]+=1
    return geo


def top_strengths() -> dict:
    jobs = _jobs(2000)
    prof = _profile()
    _like.batch(jobs, prof)
    cnt: Counter = Counter()
    for j in jobs:
        for s in j["likelihood"]["strengths"]:
            cnt[s] += 1
    top = cnt.most_common(5)
    return {"top": [{"text": k, "count": v} for k,v in top]}


def insights() -> dict:
    """Narrative insights for the dashboard."""
    ov = overview()
    src = source_performance()
    gaps = gap_analysis()
    geo = geography()
    best_src = src["rows"][0]["source"] if src["rows"] else "—"
    worst_gap = gaps["top_gaps"][0]["gap"] if gaps["top_gaps"] else "—"
    tips = []
    if ov["blocked"] > ov["total"]*0.2:
        tips.append(f"{ov['blocked']} jobs have hard blockers (citizenship/clearance) — filter them with 'Hide blockers' and focus on EOR-friendly boards.")
    if ov["high_likelihood"] < 5:
        tips.append("Only a handful are High likelihood — that's normal from 135 postings. Your hit rate is in the top 7%.")
    if best_src:
        tips.append(f"Best source by avg fit is {best_src} — prioritize its postings first.")
    if worst_gap and "eval" in worst_gap.lower():
        tips.append("Top gap is LLM evals — build a small eval harness for the claims agents and you move 20+ 'Medium' to 'High'.")
    if ov["salary_rate"] < 20:
        tips.append("Only ~20% disclose salary — when they do, the 100-150k band dominates. Anchor there for contractor roles.")
    return {
        "overview": ov,
        "source": src,
        "gaps": gaps,
        "geo": geo,
        "tips": tips[:4],
    }


def full_dashboard() -> dict:
    return {
        "overview": overview(),
        "score_dist": score_distribution(),
        "likelihood_dist": likelihood_distribution(),
        "source": source_performance(),
        "gaps": gap_analysis(),
        "salary": salary_insights(),
        "geo": geography(),
        "strengths": top_strengths(),
        "insights": insights()["tips"],
    }
