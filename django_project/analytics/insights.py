"""
insights.py — everything the Analytics page shows, computed from the stored jobs (+ their scan-time match) and
your application history. Pure functions over plain dicts so they are easy to test.

Input rows (see `rows_from_db`): the job columns plus `match` (parsed match_json or None), `status`, `starred`,
`applied_date`, `followup_date`, `status_updated`.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

STAGES = ["New", "Shortlisted", "Applied", "Interviewing", "Offer"]
RESPONDED = ("Interviewing", "Interview", "Offer", "Rejected")


def rows_from_db():
    from jobs.models import ApplicationStatus, Job
    sts = {s.job_id: s for s in ApplicationStatus.objects.using("jobhunt").all()}
    out = []
    for j in Job.objects.using("jobhunt").all():
        st = sts.get(j.job_id)
        m = None
        if j.match_json:
            try:
                m = json.loads(j.match_json)
            except ValueError:
                m = None
        out.append({
            "job_id": j.job_id, "title": j.title, "company": j.company, "source": (j.source or "").split(":")[0],
            "region": j.region, "category": j.category, "location": j.location, "remote": bool(j.remote),
            "fit": j.fit_score, "likelihood": j.likelihood, "chance": j.interview_chance, "work_mode": j.work_mode,
            "remote_scope": j.remote_scope, "posted_at": j.posted_at, "first_seen": j.first_seen, "expires_at": j.expires_at,
            "url": j.url, "match": m,
            "status": (st.status if st else "New") or "New", "starred": bool(st.starred) if st else False,
            "applied_date": (st.applied_date if st else "") or "", "followup_date": (st.followup_date if st else "") or "",
            "status_updated": (st.updated_at if st else "") or "", "dismiss_reason": (st.dismiss_reason if st else "") or "",
        })
    return out


def _local(r) -> bool:
    return bool(r["region"])


def _remote(r) -> bool:
    return not _local(r) and (r["work_mode"] == "remote" or (not r["work_mode"] and r["remote"]))


def _mode(r) -> str:
    return "local" if _local(r) else "remote" if _remote(r) else "abroad"


def _avg(xs, nd=0):
    xs = list(xs)
    return round(sum(xs) / len(xs), nd) if xs else 0


def _d(s: str):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def verdict(l: int) -> str:
    return "High" if l >= 65 else "Medium" if l >= 40 else "Low" if l >= 20 else "Long shot"


# ---------------------------------------------------------------------------

def market_skills(rows, limit=24):
    """Skill demand across all listings, and whether you have it."""
    demand = defaultdict(lambda: {"jobs": 0, "required": 0, "have": 0, "related": 0, "missing": 0, "category": "", "years": 0})
    for r in rows:
        m = r["match"]
        if not m:
            continue
        for it in (m.get("skills") or {}).get("items", []):
            if it["status"] == "soft":
                continue   # universal skills would drown out the technical picture
            d = demand[it["name"]]
            d["jobs"] += 1
            d["required"] += it["kind"] == "required"
            d[it["status"]] += 1
            d["category"] = it.get("category", "")
            if it["status"] == "have":
                d["years"] = max(d["years"], it.get("years", 0))
    out = []
    for name, d in demand.items():
        status = "have" if d["have"] >= max(d["missing"], d["related"]) and d["have"] else "related" if d["related"] and d["related"] >= d["missing"] else "missing"
        out.append({"skill": name, "jobs": d["jobs"], "required": d["required"], "status": status, "category": d["category"],
                    "have_share": round(100 * d["have"] / d["jobs"]), "years": d["years"]})
    out.sort(key=lambda x: (-x["jobs"], x["skill"]))
    return out[:limit]


def strengths(rows, limit=10):
    """Your skills ranked by how many listings ask for them."""
    c = Counter()
    yrs = {}
    for r in rows:
        for it in ((r["match"] or {}).get("skills") or {}).get("items", []):
            if it["status"] == "have" and it.get("category") != "Languages (spoken)":   # "English" is not a marketable technical skill
                c[it["name"]] += 1
                yrs[it["name"]] = max(yrs.get(it["name"], 0), it.get("years", 0))
    return [{"skill": k, "jobs": v, "years": yrs[k]} for k, v in c.most_common(limit)]


def focus_categories(profile) -> set[str]:
    """Skill areas you actually work in (2+ skills). Learning suggestions stay inside them."""
    c = Counter(m.get("category") for m in ((profile or {}).get("skills") or {}).values())
    return {k for k, v in c.items() if v >= 2 and k not in ("Domains", "Languages (spoken)")}


def gap_roi(rows, limit=12, focus=None):
    """Skills worth learning: how many listings ask for them as required, and how many they'd move from
    'nearly' to 'match' (the skill is the ONLY missing required skill). Only skills in your own skill areas."""
    agg = defaultdict(lambda: {"jobs": 0, "sole": 0, "local": 0, "remote": 0, "fit_sum": 0, "category": ""})
    for r in rows:
        m = r["match"]
        if not m or r["fit"] < 30:
            continue
        miss = (m.get("skills") or {}).get("missing_required") or []
        for name in miss:
            a = agg[name]
            a["jobs"] += 1
            a["sole"] += len(miss) == 1
            a["local" if _local(r) else "remote"] += 1
            a["fit_sum"] += r["fit"]
    cat = {it["name"]: it.get("category", "") for r in rows for it in ((r["match"] or {}).get("skills") or {}).get("items", [])}
    out = [{"skill": k, "jobs": v["jobs"], "sole_gap": v["sole"], "local": v["local"], "remote": v["remote"],
            "avg_fit": round(v["fit_sum"] / v["jobs"]), "category": cat.get(k, "")} for k, v in agg.items()
           if not focus or cat.get(k) in focus]
    out.sort(key=lambda x: (-x["sole_gap"], -x["jobs"], x["skill"]))
    return out[:limit]


def category_coverage(rows):
    """Radar data: for each skill category, the share of demanded skill-mentions you cover (have=1, related=.5)."""
    tot, got = Counter(), Counter()
    for r in rows:
        for it in ((r["match"] or {}).get("skills") or {}).get("items", []):
            if it["status"] == "soft":
                continue
            w = it["weight"]
            tot[it["category"]] += w
            got[it["category"]] += w * (1 if it["status"] == "have" else 0.5 if it["status"] == "related" else 0)
    cats = [c for c, t in tot.most_common(8)]
    return [{"category": c, "coverage": round(100 * got[c] / tot[c]), "demand": round(tot[c], 1)} for c in cats]


def fit_histogram(rows):
    bins = [{"label": f"{i}-{i + 9}" if i < 90 else "90+", "local": 0, "remote": 0, "abroad": 0} for i in range(0, 100, 10)]
    for r in rows:
        bins[min(9, r["fit"] // 10)][_mode(r)] += 1
    return bins


def mode_compare(rows):
    out = []
    for mode in ("local", "remote", "abroad"):
        g = [r for r in rows if _mode(r) == mode]
        if not g:
            continue
        out.append({"mode": mode, "count": len(g), "avg_fit": _avg(r["fit"] for r in g), "avg_odds": _avg(r["likelihood"] for r in g),
                    "avg_chance": _avg((r["chance"] for r in g), 1),
                    "good": sum(r["fit"] >= 50 for r in g), "medium_plus": sum(r["likelihood"] >= 40 for r in g),
                    "blocked": sum(bool(((r["match"] or {}).get("blockers"))) for r in g)})
    return out


def by_region(rows):
    g = defaultdict(list)
    for r in rows:
        if r["region"]:
            g[r["region"]].append(r)
    out = [{"region": k, "count": len(v), "avg_fit": _avg(x["fit"] for x in v), "best_fit": max(x["fit"] for x in v)} for k, v in g.items()]
    return sorted(out, key=lambda x: -x["count"])


def by_category(rows):
    g = defaultdict(list)
    for r in rows:
        g[r["category"] or "Other"].append(r)
    out = [{"category": k, "count": len(v), "avg_fit": _avg(x["fit"] for x in v), "good": sum(x["fit"] >= 50 for x in v)} for k, v in g.items()]
    return sorted(out, key=lambda x: -x["count"])[:12]


def by_source(rows):
    g = defaultdict(list)
    for r in rows:
        g[r["source"]].append(r)
    out = [{"source": k, "count": len(v), "avg_fit": _avg(x["fit"] for x in v), "avg_odds": _avg(x["likelihood"] for x in v),
            "good": sum(x["fit"] >= 50 for x in v)} for k, v in g.items()]
    return sorted(out, key=lambda x: (-x["good"], -x["avg_fit"]))


def timeline(rows, today, days=30):
    start = today - timedelta(days=days - 1)
    idx = {(start + timedelta(days=i)).isoformat(): i for i in range(days)}
    series = [{"date": d, "local": 0, "remote": 0, "good": 0} for d in idx]
    for r in rows:
        d = (r["posted_at"] or r["first_seen"] or "")[:10]   # when it was posted, not when we first saw it
        if d in idx:
            s = series[idx[d]]
            s["local" if _local(r) else "remote"] += 1
            s["good"] += r["fit"] >= 50
    return series


def closing(rows, today, days=14):
    series = [{"date": (today + timedelta(days=i)).isoformat(), "count": 0, "good": 0} for i in range(days)]
    idx = {s["date"]: s for s in series}
    for r in rows:
        s = idx.get(r["expires_at"][:10] if r["expires_at"] else "")
        if s:
            s["count"] += 1
            s["good"] += r["fit"] >= 50
    return series


def salary(rows, prefs):
    loc, rem = [], []
    for r in rows:
        pay = ((r["match"] or {}).get("job") or {}).get("pay")
        if not pay:
            continue
        (loc if _local(r) else rem).append(pay)

    def hist(vals, key, step, top):
        bins = [{"label": f"{i // 1000}-{(i + step) // 1000}k" if i < top else f"{top // 1000}k+", "count": 0} for i in range(0, top + step, step)][: top // step + 1]
        for v in vals:
            bins[min(len(bins) - 1, int(v // step))]["count"] += 1
        return bins
    return {
        "local": {"n": len(loc), "median": round(statistics.median(p["monthly_ttd_max"] for p in loc)) if loc else None,
                  "hist": hist([p["monthly_ttd_max"] for p in loc], "monthly_ttd_max", 4000, 24000), "unit": "TT$/mo"},
        "remote": {"n": len(rem), "median": round(statistics.median(p["monthly_usd_max"] for p in rem)) if rem else None,
                   "hist": hist([p["monthly_usd_max"] for p in rem], "monthly_usd_max", 2000, 16000), "unit": "US$/mo"},
        "floor_ttd": prefs.get("min_salary_monthly_ttd") or 0, "floor_usd": prefs.get("min_salary_monthly_usd") or 0,
        "disclosed_share": round(100 * (len(loc) + len(rem)) / len(rows)) if rows else 0,
    }


def remote_scopes(rows):
    c = Counter(r["remote_scope"] or "unknown" for r in rows if _remote(r))
    order = ["worldwide", "americas", "unknown", "us_only", "eu_only", "canada_only"]
    return [{"scope": k, "count": c[k]} for k in order if c[k]]


def funnel(rows, today):
    """Application funnel + the bottleneck. Counts a rejection as a response (it proves the application was seen)."""
    applied = [r for r in rows if r["status"] in ("Applied", "Interviewing", "Interview", "Offer", "Rejected") and r["status"] != "Shortlisted"]
    stage = Counter(r["status"] for r in rows)
    interviews = sum(r["status"] in ("Interviewing", "Interview", "Offer") for r in rows)
    offers = stage["Offer"]
    rejected = stage["Rejected"]
    stale = [r for r in rows if r["status"] == "Applied" and (d := _d(r["applied_date"] or r["status_updated"])) and (today - d).days >= 21]
    responded = interviews + rejected
    n_applied = len(applied)
    conv = {
        "applied_to_response": round(100 * responded / n_applied) if n_applied else None,
        "applied_to_interview": round(100 * interviews / n_applied) if n_applied else None,
        "interview_to_offer": round(100 * offers / interviews) if interviews else None,
    }
    hint = ""
    if n_applied < 8:
        hint = ("No applications recorded yet. Mark jobs Applied / Interviewing / Rejected on the Pipeline and this page starts measuring your funnel."
                if not n_applied else f"Only {n_applied} decided application{'s' if n_applied != 1 else ''} so far — conversion rates need 10+ applications to mean anything.")
    elif conv["applied_to_response"] is not None and conv["applied_to_response"] < 15:
        hint = "Few replies: the bottleneck is at the top — targeting or resume fit. Apply to higher-odds roles and tailor the bullets the Match tab suggests."
    elif interviews >= 3 and conv["interview_to_offer"] is not None and conv["interview_to_offer"] < 20:
        hint = "You get interviews but few offers: work on interview prep and negotiation, not the CV."
    else:
        hint = "Funnel looks healthy — keep the volume steady and follow up on stale applications."
    weeks = Counter()
    for r in applied:
        d = _d(r["applied_date"] or r["status_updated"])
        if d:
            weeks[(d - timedelta(days=d.weekday())).isoformat()] += 1
    return {
        "stages": [{"stage": s, "count": stage[s]} for s in STAGES] + [{"stage": "Rejected", "count": rejected}],
        "applied": n_applied, "interviews": interviews, "offers": offers, "rejected": rejected, "responded": responded,
        "stale_applied": len(stale), "conversion": conv, "hint": hint,
        "weekly": [{"week": k, "count": v} for k, v in sorted(weeks.items())][-10:],
    }


def passed_reasons(rows, limit=8):
    """Why you've dismissed roles ("Passed on it" + a reason). A pattern here is worth acting on:
    always "pay too low" for remote roles, say, or one skill showing up in "missing a must-have" again and again."""
    c = Counter(r["dismiss_reason"] for r in rows if r["status"] == "Passed on it" and r["dismiss_reason"])
    total = sum(r["status"] == "Passed on it" for r in rows)
    return {"total": total, "with_reason": sum(c.values()),
            "reasons": [{"reason": k, "count": v} for k, v in c.most_common(limit)]}


def top_opportunities(rows, limit=8):
    live = [r for r in rows if r["status"] in ("New", "Shortlisted") and not ((r["match"] or {}).get("blockers"))]
    live.sort(key=lambda r: -(r["fit"] * 0.5 + r["likelihood"] * 0.5))
    out = []
    for r in live[:limit]:
        m = r["match"] or {}
        out.append({"job_id": r["job_id"], "title": r["title"], "company": r["company"], "mode": _mode(r), "region": r["region"],
                    "fit": r["fit"], "likelihood": r["likelihood"], "chance": r["chance"], "verdict": verdict(r["likelihood"]),
                    "advice": m.get("advice", ""), "closes": r["expires_at"]})
    return out


def text_insights(rows, data, today):
    """Plain-English findings, most useful first."""
    out = []
    n = len(rows)
    if not n:
        return [{"kind": "info", "text": "No jobs yet. Run a scan."}]
    m = {x["mode"]: x for x in data["mode_compare"]}
    if "abroad" in m and m["abroad"]["good"]:
        out.append({"kind": "warn", "text": f"{m['abroad']['good']} good-fit listings are on-site or hybrid abroad: they look great on paper but would need relocation."})
    good = [r for r in rows if r["fit"] >= 50]
    out.append({"kind": "good" if good else "warn", "text": f"{len(good)} of {n} listings fit you (50+), {sum(r['likelihood'] >= 40 for r in rows)} with decent odds."})
    if "local" in m and "remote" in m and m["local"]["avg_chance"] and m["remote"]["avg_chance"]:
        ratio = m["local"]["avg_chance"] / m["remote"]["avg_chance"]
        if ratio >= 1.5:
            out.append({"kind": "info", "text": f"Local roles give you about {ratio:.1f}× the interview chance of remote ones on average ({m['local']['avg_chance']}% vs {m['remote']['avg_chance']}%). Remote is a volume game."})
    scopes = {s["scope"]: s["count"] for s in data["remote_scopes"]}
    closed = scopes.get("us_only", 0) + scopes.get("eu_only", 0) + scopes.get("canada_only", 0)
    total_remote = sum(scopes.values())
    if total_remote and closed:
        out.append({"kind": "warn", "text": f"{closed} of {total_remote} remote roles are restricted to US/EU/Canada residents — you can skip them."})
    roi = data["gap_roi"]
    if roi and roi[0]["sole_gap"]:
        g = roi[0]
        out.append({"kind": "action", "text": f"Learning {g['skill']} would turn {g['sole_gap']} near-miss listing{'s' if g['sole_gap'] != 1 else ''} into real matches ({g['jobs']} ask for it)."})
    strong = data["strengths"]
    if strong:
        out.append({"kind": "good", "text": f"Your most in-demand skills: {', '.join(s['skill'] for s in strong[:4])}."})
    src = data["sources"]
    if src and src[0]["good"]:
        out.append({"kind": "info", "text": f"{src[0]['source']} is your best source: {src[0]['good']} good-fit roles (avg fit {src[0]['avg_fit']})."})
    cl = [c for c in data["closing"][:7] if c["good"]]
    if cl:
        out.append({"kind": "warn", "text": f"{sum(c['good'] for c in cl)} good-fit roles close within a week."})
    f = data["funnel"]
    if f["stale_applied"]:
        out.append({"kind": "action", "text": f"{f['stale_applied']} application{'s' if f['stale_applied'] != 1 else ''} with no reply after 3 weeks — follow up or close them."})
    if f["hint"]:
        out.append({"kind": "info", "text": f["hint"]})
    thin = sum(1 for r in rows if (r["match"] or {}).get("confidence") == "low")
    if thin > n * 0.3:
        out.append({"kind": "info", "text": f"{thin} listings have thin descriptions, so their scores are less certain."})
    pr = data["passed_reasons"]
    if pr["reasons"] and pr["reasons"][0]["count"] >= 3:
        top = pr["reasons"][0]
        out.append({"kind": "info", "text": f"You've passed on {pr['total']} roles, most often for \"{top['reason']}\" ({top['count']} times) — worth tightening your filters for that."})
    return out


# ---------------------------------------------------------------------------
# analytics v2
# ---------------------------------------------------------------------------

def opportunity_map(rows, limit=400):
    """Fit (x) vs odds (y) for every listing that fits at all — the picture of where to spend effort."""
    pts = [{"job_id": r["job_id"], "title": r["title"][:60], "company": r["company"][:40], "fit": r["fit"], "odds": r["likelihood"],
            "mode": _mode(r), "blocked": bool(((r["match"] or {}).get("blockers")))} for r in rows if r["fit"] >= 30 and r["status"] in ("New", "Shortlisted")]
    pts.sort(key=lambda p: -(p["fit"] + p["odds"]))
    return pts[:limit]


def skill_bundles(rows, limit=10):
    """Pairs of skills that keep appearing together as requirements, and whether you have both."""
    from itertools import combinations
    pair, status = Counter(), {}
    for r in rows:
        items = [i for i in ((r["match"] or {}).get("skills") or {}).get("items", []) if i["status"] != "soft" and i["kind"] == "required"]
        for i in items:
            status[i["name"]] = i["status"]
        for a, b in combinations(sorted({i["name"] for i in items}), 2):
            pair[(a, b)] += 1
    out = []
    for (a, b), n in pair.most_common(limit * 3):
        sa, sb = status.get(a), status.get(b)
        out.append({"a": a, "b": b, "jobs": n, "have_both": sa == "have" and sb == "have",
                    "missing": [x for x, s in ((a, sa), (b, sb)) if s == "missing"]})
    return out[:limit]


def employers(rows, today, limit=12):
    """Employers with the most good-fit, unblocked roles, and how many they posted recently."""
    week = (today - timedelta(days=14)).isoformat()
    g = defaultdict(list)
    for r in rows:
        if r["company"] and r["company"] not in ("Unknown", "Confidential", "Employer Confidential"):
            g[r["company"]].append(r)
    out = []
    for name, rs in g.items():
        good = [r for r in rs if r["fit"] >= 50 and not ((r["match"] or {}).get("blockers"))]
        if good:
            out.append({"company": name, "roles": len(rs), "good": len(good), "avg_fit": _avg(r["fit"] for r in good),
                        "best_odds": max(r["likelihood"] for r in good), "recent": sum(((r["posted_at"] or r["first_seen"] or "")[:10]) >= week for r in rs),
                        "mode": _mode(good[0])})
    out.sort(key=lambda e: (-e["good"], -e["avg_fit"]))
    return out[:limit]


def salary_by_category(rows, min_n=3):
    """Median stated monthly pay per category: TT$ for local roles, US$ for remote."""
    g = defaultdict(list)
    for r in rows:
        pay = ((r["match"] or {}).get("job") or {}).get("pay")
        if pay:
            g[("local" if _local(r) else "remote", r["category"] or "Other")].append(pay["monthly_ttd_max"] if _local(r) else pay["monthly_usd_max"])
    out = {"local": [], "remote": []}
    for (kind, cat), vals in g.items():
        if len(vals) >= min_n:
            out[kind].append({"category": cat, "n": len(vals), "median": round(statistics.median(vals)), "top": max(vals)})
    for k in out:
        out[k].sort(key=lambda x: -x["median"])
    return out


def experience_asked(rows, years):
    """How many years listings ask for vs how many you have, and how senior the roles are."""
    bins = [{"label": l, "count": 0} for l in ("not stated", "0-1", "2-3", "4-5", "6-8", "9+")]
    levels = Counter()
    for r in rows:
        j = (r["match"] or {}).get("job") or {}
        y = j.get("min_years")
        i = 0 if y is None else 1 if y <= 1 else 2 if y <= 3 else 3 if y <= 5 else 4 if y <= 8 else 5
        bins[i]["count"] += 1
        lv = j.get("level")
        if lv is not None:
            levels["entry" if lv < 0.75 else "mid" if lv < 1.75 else "senior" if lv < 2.75 else "lead"] += 1
    return {"bins": bins, "your_years": years, "levels": [{"level": k, "count": levels[k]} for k in ("entry", "mid", "senior", "lead")]}


def time_open(rows):
    """Days between posting and closing (local boards state both): how long roles stay open."""
    days = []
    for r in rows:
        a, b = _d(r["posted_at"]), _d(r["expires_at"])
        if a and b and 0 <= (b - a).days <= 120:
            days.append((b - a).days)
    bins = [{"label": l, "count": 0} for l in ("≤7", "8-14", "15-21", "22-30", "31-45", "46+")]
    for d in days:
        bins[0 if d <= 7 else 1 if d <= 14 else 2 if d <= 21 else 3 if d <= 30 else 4 if d <= 45 else 5]["count"] += 1
    return {"bins": bins, "median": round(statistics.median(days)) if days else None, "n": len(days)}


def market_score(rows, profile):
    """One number for how well your resume covers what the market asks for, and the skills that would raise it most."""
    tot = got = 0.0
    lift = Counter()
    for r in rows:
        for it in ((r["match"] or {}).get("skills") or {}).get("items", []):
            if it["status"] == "soft":
                continue
            w = it["weight"]
            tot += w
            got += w * (1 if it["status"] == "have" else 0.5 if it["status"] == "related" else 0)
            if it["status"] == "missing":
                lift[it["name"]] += w
            elif it["status"] == "related":
                lift[it["name"]] += w * 0.5
    focus = focus_categories(profile)
    cat = {it["name"]: it.get("category") for r in rows for it in ((r["match"] or {}).get("skills") or {}).get("items", [])}
    best = [{"skill": k, "gain": round(100 * v / tot, 1)} for k, v in lift.most_common(40) if not focus or cat.get(k) in focus][:5] if tot else []
    return {"score": round(100 * got / tot) if tot else 0, "raise": best}


def history_from_db(limit=60):
    from jobs.models import Snapshot
    import json as _json
    return [{"day": s.day, "total": s.total, "good": s.good, "decent": s.decent, "local": s.local, "remote": s.remote, "avg_fit": s.avg_fit,
             "avg_odds": s.avg_odds, "coverage": s.coverage, "top_skills": _json.loads(s.top_skills or "[]")}
            for s in Snapshot.objects.using("jobhunt").order_by("-day")[:limit]][::-1]


def build(rows, prefs=None, today=None, profile=None):
    today = today or date.today()
    prefs = prefs or {}
    rows = list(rows)
    n = len(rows)
    week_ago = (today - timedelta(days=7)).isoformat()
    data = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "overview": {
            "total": n, "local": sum(_local(r) for r in rows), "remote": sum(_remote(r) for r in rows),
            "good_fit": sum(r["fit"] >= 50 for r in rows), "strong_fit": sum(r["fit"] >= 65 for r in rows),
            "medium_odds": sum(r["likelihood"] >= 40 for r in rows), "avg_fit": _avg(r["fit"] for r in rows),
            "avg_odds": _avg(r["likelihood"] for r in rows), "avg_chance": _avg((r["chance"] for r in rows), 1),
            "new_week": sum(((r["posted_at"] or r["first_seen"] or "")[:10]) >= week_ago for r in rows),
            "closing_week": sum(bool(r["expires_at"]) and today.isoformat() <= r["expires_at"] <= (today + timedelta(days=7)).isoformat() and r["fit"] >= 50 for r in rows),
            "starred": sum(r["starred"] for r in rows), "blocked": sum(bool(((r["match"] or {}).get("blockers"))) for r in rows),
            "scored": sum(bool(r["match"]) for r in rows),
        },
        "fit_hist": fit_histogram(rows),
        "verdicts": [{"verdict": v, "count": sum(verdict(r["likelihood"]) == v for r in rows)} for v in ("High", "Medium", "Low", "Long shot")],
        "market_skills": market_skills(rows), "strengths": strengths(rows), "gap_roi": gap_roi(rows, focus=focus_categories(profile)),
        "category_coverage": category_coverage(rows), "mode_compare": mode_compare(rows), "regions": by_region(rows),
        "categories": by_category(rows), "sources": by_source(rows), "timeline": timeline(rows, today), "closing": closing(rows, today),
        "salary": salary(rows, prefs), "remote_scopes": remote_scopes(rows), "funnel": funnel(rows, today),
        "top": top_opportunities(rows),
        "map": opportunity_map(rows), "bundles": skill_bundles(rows), "employers": employers(rows, today),
        "pay_by_category": salary_by_category(rows), "experience": experience_asked(rows, float((profile or {}).get("years_experience") or 0)),
        "time_open": time_open(rows), "market": market_score(rows, profile), "passed_reasons": passed_reasons(rows),
    }
    data["insights"] = text_insights(rows, data, today)
    return data


def scan_history(limit=12):
    """Recent scans and the latest outcome per board (for the 'Scan health' panel)."""
    from jobs.models import Scan, SourceRun
    scans = [{"id": s.id, "started_at": s.started_at, "kept": s.total_kept, "status": s.status}
             for s in Scan.objects.using("jobhunt").all()[:limit]][::-1]
    latest = {}
    for r in SourceRun.objects.using("jobhunt").all()[:300]:
        latest.setdefault(r.name, {"name": r.name, "label": r.label or r.name, "ok": bool(r.ok), "count": r.count, "ms": r.ms,
                                   "error": r.error, "ran_at": r.ran_at})
    return {"scans": scans, "boards": sorted(latest.values(), key=lambda b: (b["ok"], -b["count"]))}
