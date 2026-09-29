"""
test_ai.py — the AI features' deterministic core and their guardrails. No model is called: the LLM path is exercised with a stub.
Called from test_pipeline.main(); runnable alone via test_pipeline.
"""

from __future__ import annotations

import json
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

    # follow-up probes and filler words
    check("follow_up: a complete STAR answer with numbers gets no probe", plain["follow_up"] is None, plain["follow_up"])
    no_result = ("When our finance team had a reporting deadline I built a Django tool. My goal was to cut manual work, "
                 "so I decided to automate it and I wrote the pipeline myself over a couple of weeks.")
    fr = ai.interview_feedback(job, "q", no_result)
    check("follow_up: missing a measurable result -> asks for one", fr["follow_up"] and "number" in fr["follow_up"], fr["follow_up"])
    we = ai.interview_feedback(job, "q", "We had a deadline and we built a tool, we tested it and we shipped it and we were happy with it, the team saved 10 hours.")
    check("follow_up: mostly 'we' -> asks about your own part", we["follow_up"] and "own part" in we["follow_up"], we["follow_up"])
    wk = ai.interview_feedback(job, "q", weak_ans)
    check("filler: counted and listed", wk["filler_count"] >= 3 and "basically" in wk["filler"], wk["filler"])
    s2 = ai.session_summary([dict(wk, question="Q"), dict(plain, question="Q2")])
    check("session_summary: filler totals and rate", s2["filler_total"] == wk["filler_count"] and s2["filler_per_100"] > 0 and s2["top_fillers"], s2)

    # composure — nerves read from vocal cues, stated honestly with evidence
    calm_v = {"duration_sec": 30, "pace_wpm": 140, "jitter": 0.01, "pitch_drift_st": 0.2, "uptalk_ratio": 0.1, "trail_off_ratio": 0.1,
              "phrases": 10, "start_latency_sec": 0.8, "pitch_range_st": 5}
    nerv_v = {"duration_sec": 30, "pace_wpm": 195, "jitter": 0.08, "pitch_drift_st": 3, "uptalk_ratio": 0.7, "trail_off_ratio": 0.6,
              "phrases": 10, "start_latency_sec": 6, "pitch_range_st": 4}
    cc, cn = ai.composure_feedback(calm_v), ai.composure_feedback(nerv_v, filler_per_100=8)
    check("composure: calm voice -> 'Calm and confident', no fixes", cc["label"] == "Calm and confident" and not cc["fixes"], cc)
    check("composure: nervous voice -> 'Noticeably nervous' and says so plainly", cn["label"] == "Noticeably nervous" and "nervous" in cn["honest"], cn)
    check("composure: every cue it cites is evidence, with a fix", len(cn["signals"]) >= 5 and cn["fixes"] and cn["caveat"], cn["signals"])
    check("composure: too short or missing -> None", ai.composure_feedback({"duration_sec": 3}) is None and ai.composure_feedback(None) is None)
    check("composure: missing cues are skipped, not guessed", ai.composure_feedback({"duration_sec": 20})["score"] == 100)
    nv = ai.interview_feedback(job, "q", good, voice=nerv_v)
    cv = ai.interview_feedback(job, "q", good, voice=calm_v)
    shaky = ai.delivery_feedback({**nerv_v, "pitch_mean_hz": 180, "pitch_stdev_hz": 40})
    check("delivery: a shaky voice is never praised as 'natural variation in tone'", not any("variation" in n for n in shaky["notes"]), shaky["notes"])
    check("interview_feedback: nerves pull delivery (and overall) down", nv["overall_score"] < cv["overall_score"] and nv["composure"]["score"] < cv["composure"]["score"])
    check("interview_feedback: the spoken result mentions nerves when present", "nervous" in nv["speech"].lower(), nv["speech"])
    check("honest take on every answer", plain["honest"].startswith("Honest take") and ai.interview_feedback(job, "q", weak_ans)["honest"] != plain["honest"])
    check("persona tough: pushes back even on a decent answer", ai.interview_feedback(job, "q", good, persona="tough")["follow_up"] or plain["overall_score"] >= 80)
    sn = ai.session_summary([dict(nv, question="A"), dict(cv, question="B")])
    check("session_summary: composure trend -> 'settled in'", sn["composure_avg"] is not None and "settled" in (sn["nerves"] or ""), sn)
    check("session_summary: honest readiness line", sn["readiness"].split(":")[0] in ("Ready", "Borderline", "Not ready yet"), sn["readiness"])

    # AI: one call per answer -> coach + follow-up + stronger version, and a rewrite that invents facts is dropped
    reply = json.dumps({"coach": ["Lead with the result", "Say what YOU did"], "follow_up": "You said three departments adopted it. How did you get the first one on board?",
                        "stronger": "When our finance team faced a reporting deadline, I built a Django tool to cut manual work. I wrote the pipeline myself; it saved 100 hours a month and three departments adopted it."})
    with mock.patch.object(ai, "_ask_llm", return_value=(reply, "ollama")):
        ar = ai.interview_feedback(job, "q", good, use_llm=True)
    check("AI review: tailored follow-up replaces the rules one", ar["follow_up"].startswith("You said three") and ar["follow_up_by"] == "ollama", ar.get("follow_up"))
    check("AI review: grounded stronger answer is shown", "100 hours" in ar.get("stronger", ""), ar)
    check("AI review: coach notes as bullets", ar["coach"].startswith("•") and ar["provider"] == "ollama")
    bad = json.dumps({"coach": ["x"], "follow_up": "", "stronger": "I built a Kubernetes platform in Go that saved 5,000 hours a year for 40 teams across the company."})
    with mock.patch.object(ai, "_ask_llm", return_value=(bad, "ollama")):
        br = ai.interview_feedback(job, "q", good, use_llm=True)
    check("AI review: a rewrite that adds facts is dropped, not shown", "stronger" not in br and br.get("stronger_dropped"), br)
    check("AI review: empty follow-up from the model means no probe", br["follow_up"] is None)
    src_ans = "At my last job the finance team was spending days on month-end reports, so I built a Python and Django tool. I wrote the ETL part myself and we rolled it out."
    check("no_new_claims: a job title lifted from the question is caught",
          not ai._no_new_claims(src_ans, "As Project Assistant, I built a Python and Django tool for month-end reports and wrote the ETL part myself."))
    check("no_new_claims: 'helped/built' upgraded to 'led/owned' is caught",
          not ai._no_new_claims(src_ans, "I led the month-end reporting work and built a Python and Django tool, writing the ETL part myself."))
    check("no_new_claims: a faithful rewrite passes",
          ai._no_new_claims(src_ans, "Working on month-end reports at my last job, I built a Python and Django tool and wrote the ETL part myself. We rolled it out."))
    check("spoken result starts each sentence with a capital", ". this" not in ai.interview_feedback(job, "q", weak_ans)["speech"])
    with mock.patch.object(ai, "_ask_llm", return_value=("Just be more specific.", "ollama")):
        pr = ai.interview_feedback(job, "q", good, use_llm=True)
    check("AI review: plain-text reply still becomes coach notes", pr["coach"] == "Just be more specific.")
    trailing = '{"coach": ["Lead with the number",], "follow_up": "Which metric moved first, and by how much?", "stronger": "",}'
    with mock.patch.object(ai, "_ask_llm", return_value=(trailing, "ollama")):
        tr = ai.interview_feedback(job, "q", good, use_llm=True)
    check("AI review: JSON with trailing commas still parses", tr.get("follow_up") == "Which metric moved first, and by how much?" and tr["coach"].startswith("•"), tr)
    with mock.patch.object(ai, "_ask_llm", return_value=('{"coach": ["a" "b"] broken', "ollama")):
        jr = ai.interview_feedback(job, "q", good, use_llm=True)
    check("AI review: unparseable JSON is never shown as coach notes", "coach" not in jr)
    with mock.patch.object(ai, "_ask_llm", return_value=(None, "unavailable: x")):
        ur = ai.interview_feedback(job, "q", good, use_llm=True)
    check("AI review: model down -> rules result unchanged", ur["provider"] == "rules" and "coach" not in ur)

    qs_reply = json.dumps({"questions": [{"q": "Walk me through your background and why this role.", "why": "opener"},
                                         {"q": "Tell me about a time you automated a painful manual process.", "why": "behavioural"},
                                         {"q": "How would you design retries for a flaky upstream API?", "why": "technical"}]})
    with mock.patch.object(ai, "_ask_llm", return_value=(qs_reply, "ollama")):
        aq = ai.ai_questions(job, n=3)
    check("ai_questions: model-written questions returned and tagged", len(aq["questions"]) == 3 and aq["provider"] == "ollama" and aq["questions"][1]["by"] == "ollama", aq)
    with mock.patch.object(ai, "_ask_llm", return_value=("sorry, I can't", "ollama")):
        fq = ai.ai_questions(job, n=3)
    check("ai_questions: unusable reply -> built-in questions, with a note", fq["provider"] == "rules" and fq["questions"] and fq.get("note"), fq)

    # the privacy label must name the provider a request will REALLY use
    from src import llm as _llm
    both = {"claude_code": {"available": True}, "ollama": {"available": True}, "template": {"available": True}}
    with mock.patch.object(_llm, "describe", return_value=both):
        check("llm_status: auto -> first available in ORDER", ai.llm_status({"provider": "auto"})["active"] == _llm.ORDER[0])
        check("llm_status: pinned provider wins over ORDER", ai.llm_status({"provider": "ollama"})["active"] == "ollama")
        check("llm_status: pinned to template -> no AI", ai.llm_status({"provider": "template"})["any"] is False)
    with mock.patch.object(_llm, "describe", return_value={"claude_code": {"available": True}, "ollama": {"available": False}}):
        st_ = ai.llm_status({"provider": "ollama"})
        check("llm_status: pinned but unavailable -> no AI (never silently another provider)", st_["active"] is None and st_["any"] is False, st_)
