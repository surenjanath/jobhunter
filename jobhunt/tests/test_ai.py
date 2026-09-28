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
