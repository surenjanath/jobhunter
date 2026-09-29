"""
test_ai.py — the AI features' deterministic core and their guardrails. No model is called: the LLM path is exercised with a stub.
Called from test_pipeline.main(); runnable alone via test_pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run(check, cfg):
    print("\n10. AI FEATURES (rules first, LLM optional and fenced)")
    from src import ai_features as ai

    job = {"job_id": "x", "title": "Senior Python Developer", "company": "Acme", "posted_at": "2020-01-01", "location": "Remote", "remote": True,
           "description": "We're a family. Fast-paced. Wear many hats.\nRequirements\n- 3+ years of Python and Django\nCompetitive salary. Remote worldwide, contractors welcome."}
    rf = {f["flag"] for f in ai.red_flags(job)}
    check("red flags: many hats, family, old posting, pay not stated", {"“Wear many hats”", "“We're a family”", "Old posting", "Pay not stated"} <= rf, str(rf))
    check("red flags ordered by severity", [f["severity"] for f in ai.red_flags(job)] == sorted((f["severity"] for f in ai.red_flags(job)), reverse=True))
    check("commission-only is the top severity", ai.red_flags({"title": "Sales", "description": "Commission only role"})[0]["severity"] == 3)

    check("grounded rejects a new number", not ai.grounded("Built APIs for policies.", "Built APIs for 40 policies."))
    check("grounded rejects a new tool", not ai.grounded("Built APIs.", "Built APIs on Kubernetes."))
    check("grounded accepts a re-wording", ai.grounded("Worked on Django APIs for 50,000 policies.", "Delivered Django APIs for 50,000 policies."))

    good = ("When our finance team had a reporting deadline I built a Django tool. My goal was to cut manual work, so I decided to automate it and wrote the pipeline myself. "
            "It saved 100 hours a month and the team adopted it across three departments.")
    weak = "I think we basically did some stuff and it went well I guess."
    g, w = ai.interview_feedback(job, "q", good), ai.interview_feedback(job, "q", weak)
    check("interview feedback scores a structured answer higher", g["score"] > w["score"] and all(g["star"].values()), f"{g['score']} vs {w['score']}")
    check("interview feedback refuses a one-liner", "error" in ai.interview_feedback(job, "q", "yes"))

    p = ai.ask("remote python roles worth applying")["params"]
    check("ask: remote + odds sort + skill", (p["mode"], p["sort"], p["q"]) == ("remote", "likelihood", "Python"), str(p))
    p = ai.ask("finance jobs in Chaguanas closing soon")["params"]
    check("ask: region implies local, closing sorts", (p["mode"], p["region"], p["closing"], p["category"]) == ("local", "Chaguanas / Caroni", "1", "Finance & Accounting"), str(p))
    check("ask: empty query is an error", "error" in ai.ask("  "))

    corpus = [{"job_id": "1", "title": "Python Django Developer", "description": "Python Django PostgreSQL APIs", "fit_score": 60},
              {"job_id": "2", "title": "Python Backend Developer", "description": "Python Django REST APIs", "fit_score": 55},
              {"job_id": "3", "title": "Payroll Clerk", "description": "payroll invoices accounting", "fit_score": 20}]
    sim = ai.similar_jobs(corpus[0], corpus)
    check("similar jobs: the sibling ranks first, itself and unrelated excluded", sim and sim[0]["job_id"] == "2" and all(s["job_id"] != "1" for s in sim))
    rec = ai.recommendations(corpus, [corpus[0]])
    check("recommendations follow what you liked", rec and rec[0]["job_id"] == "2" and rec[0]["because"] == "Python Django Developer")
    check("no liked jobs, no recommendations", ai.recommendations(corpus, []) == [])

    r = ai.roadmap("docker", {"jobs": 9, "sole_gap": 2})
    check("roadmap: canonical name, why mentions demand", r.get("skill") == "Docker" and "9" in r["why"] and r["steps"])
    check("roadmap: unknown skill is an error", "error" in ai.roadmap("not-a-skill-zzz"))

    with mock.patch.object(ai, "_ask_llm", return_value=("A short, clear summary of the role for you.", "stub")) as m:
        ai.posting_summary(job)
        check("no LLM call unless asked", not m.called)
        s = ai.posting_summary(job, use_llm=True)
        check("LLM summary is used when asked", s["provider"] == "stub" and s["tldr"].startswith("A short"))
    with mock.patch.object(ai, "_ask_llm", return_value=(None, "unavailable: x")):
        s = ai.posting_summary(job, use_llm=True)
        check("LLM unavailable falls back to the rules text", s["provider"] == "rules" and "Senior Python Developer" in s["tldr"])

    # voice delivery — computed client-side (pace, pitch variety, pauses, volume), scored server-side
    check("delivery_feedback: no data -> None (never fabricated)", ai.delivery_feedback(None) is None)
    check("delivery_feedback: empty dict -> None", ai.delivery_feedback({}) is None)
    good_voice = {"duration_sec": 30, "pace_wpm": 140, "pitch_mean_hz": 180, "pitch_stdev_hz": 35,
                 "pause_ratio": 0.1, "long_pauses": 0, "volume_mean": 0.35, "volume_stdev": 0.08}
    gd = ai.delivery_feedback(good_voice)
    check("delivery_feedback: solid delivery scores high with no tips", gd["score"] >= 90 and not gd["tips"], gd)
    bad_voice = {"duration_sec": 40, "pace_wpm": 90, "pitch_mean_hz": 170, "pitch_stdev_hz": 5,
                "pause_ratio": 0.5, "long_pauses": 4, "volume_mean": 0.05, "volume_stdev": 0.09}
    bd = ai.delivery_feedback(bad_voice)
    check("delivery_feedback: flags slow pace, flat tone, long pauses, low volume", bd["score"] < 70 and len(bd["tips"]) == 4, bd["tips"])
    check("delivery_feedback: fast pace flagged too", ai.delivery_feedback({**good_voice, "pace_wpm": 200})["tips"], "expected a pace tip")

    good = ("When our finance team had a reporting deadline I built a Django tool. My goal was to cut manual work, "
            "so I decided to automate it and wrote the pipeline myself. It saved 100 hours a month and three departments adopted it.")
    plain = ai.interview_feedback(job, "q", good)
    check("interview_feedback without voice: unchanged shape, no delivery", plain["delivery"] is None and plain["overall_score"] == plain["score"])
    with_voice = ai.interview_feedback(job, "q", good, voice=bad_voice)
    check("interview_feedback with poor delivery: overall_score drops below content score", with_voice["overall_score"] < with_voice["score"], with_voice)
    check("interview_feedback: verdict matches the spoken overall_score, not the content-only score",
         (with_voice["overall_score"] >= 75) == (with_voice["verdict"] == "Strong"))
    check("interview_feedback: content score itself is untouched by voice", with_voice["score"] == plain["score"])

    # whole-session wrap-up
    check("session_summary: no scored answers -> error", "error" in ai.session_summary([]))
    r1 = dict(ai.interview_feedback(job, "Q1", good), question="Q1")
    weak_ans = "I think we basically did some stuff and it went well I guess honestly you know."
    r2 = dict(ai.interview_feedback(job, "Q2", weak_ans), question="Q2")
    sess = ai.session_summary([r1, r2])
    check("session_summary: averages both questions", sess["n"] == 2 and sess["content_avg"] == round((r1["score"] + r2["score"]) / 2), sess)
    check("session_summary: finds the best and worst question by name", sess["best"]["question"] == "Q1" and sess["worst"]["question"] == "Q2", sess)
    check("session_summary: a garbage/non-dict item in results is ignored, not a crash", ai.session_summary([r1, "not a result", None])["n"] == 1)
    check("session_summary: speech mentions the overall score", str(sess["overall_avg"]) in sess["speech"])
