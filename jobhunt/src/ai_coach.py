"""
ai_coach.py — the daily brief and next actions, computed from your own data (Analytics insights).

The default brief is rule-based and instant: it names your best open roles, the one skill worth learning, follow-ups
that are due, and whether local or remote is working better for you. Pass use_llm=True to have a configured model
(Ollama / Claude / API) rewrite those same facts as prose — it is given only the computed facts, never the resume.
"""

from __future__ import annotations

from datetime import datetime


def facts(ins: dict | None) -> dict:
    """The handful of numbers the brief is built from."""
    ins = ins or {}
    ov = ins.get("overview", {})
    top = ins.get("top", [])
    roi = ins.get("gap_roi", [])
    mc = {m["mode"]: m for m in ins.get("mode_compare", [])}
    f = ins.get("funnel", {})
    return {"total": ov.get("total", 0), "good": ov.get("good_fit", 0), "decent": ov.get("medium_odds", 0), "top": top[:3],
            "learn": roi[0] if roi else None, "stale": f.get("stale_applied", 0), "applied": f.get("applied", 0),
            "closing_week": ov.get("closing_week", 0), "local": mc.get("local"), "remote": mc.get("remote"),
            "blocked": ov.get("blocked", 0)}


def priority_actions(ins: dict | None) -> list[dict]:
    f = facts(ins)
    acts: list[dict] = []
    if f["top"]:
        t = f["top"][0]
        acts.append({"title": f"Apply to {t['title']} at {t['company']}",
                     "why": f"Best open role right now: fit {t['fit']}, {t['verdict'].lower()} odds (~{t['chance']}% interview). {t['advice']}",
                     "effort": "1 hour", "impact": "High", "job_id": t["job_id"]})
    if f["learn"]:
        g = f["learn"]
        acts.append({"title": f"Learn {g['skill']}", "why": f"Asked for by {g['jobs']} of your listings; the only thing missing in {g['sole_gap']} of them.",
                     "effort": "1-2 weeks", "impact": "Medium" if g["sole_gap"] < 5 else "High"})
    if f["stale"]:
        acts.append({"title": f"Follow up on {f['stale']} silent application{'s' if f['stale'] != 1 else ''}", "why": "No reply after 3 weeks — a short nudge or closing them keeps the funnel honest.",
                     "effort": "20 minutes", "impact": "Medium"})
    if f["closing_week"]:
        acts.append({"title": f"{f['closing_week']} good-fit role{'s' if f['closing_week'] != 1 else ''} close this week", "why": "Filter the Ledger to 'Closing ≤ 7d' and decide today.",
                     "effort": "30 minutes", "impact": "High"})
    return acts[:4]


def rules_text(ins: dict | None) -> str:
    f = facts(ins)
    if not f["total"]:
        return "No listings yet. Run a scan, then this brief will name your best roles."
    bits = []
    if f["top"]:
        t = f["top"][0]
        bits.append(f"Best open role: {t['title']} at {t['company']} (fit {t['fit']}, {t['verdict'].lower()} odds). "
                    f"{f['good']} of {f['total']} listings fit you and {f['decent']} have decent odds.")
    else:
        bits.append(f"{f['good']} of {f['total']} listings fit you, but none are open and unblocked right now — check the Ledger's Local view or relax your preferences.")
    if f["learn"]:
        bits.append(f"Closing one gap would help most: {f['learn']['skill']} blocks {f['learn']['jobs']} listings.")
    l, r = f["local"], f["remote"]
    if l and r and l["avg_chance"] and r["avg_chance"]:
        better = "local" if l["avg_chance"] >= r["avg_chance"] else "remote"
        bits.append(f"{better.title()} roles are converting better for you ({l['avg_chance']}% local vs {r['avg_chance']}% remote interview chance).")
    if f["stale"]:
        bits.append(f"{f['stale']} application{'s' if f['stale'] != 1 else ''} awaiting a reply for 3+ weeks.")
    return " ".join(bits)


def daily_brief(ins: dict | None = None, use_llm: bool = False, cfg: dict | None = None) -> dict:
    text, source = rules_text(ins), "rules"
    if use_llm:
        try:
            from src import llm
            out, backend = llm.generate(
                "You are a pragmatic job-search coach. Rewrite the facts as a 3-sentence daily brief. No hype, no invented facts.",
                "Facts:\n" + text + "\nActions:\n" + "\n".join(f"- {a['title']}: {a['why']}" for a in priority_actions(ins)), cfg or {})
            if len(out) > 40:
                text, source = out.strip(), backend
        except Exception:  # noqa: BLE001
            pass
    return {"text": text, "source": source, "actions": priority_actions(ins), "generated": datetime.now().isoformat()}
