"""
test_coach.py — interview preparation beyond single mocks: voice baseline, story bank, drills, interview types,
prep plan, inbox classification, camera feedback, weekly report. Called from test_pipeline.main().
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run(check, cfg):
    print("\n12. INTERVIEW COACH (baseline, stories, drills, interview types, prep plan, inbox, camera, weekly)")
    from src import ai_features as ai
    from src import coach

    job = {"title": "Senior Python Developer", "company": "Acme Insurance",
           "description": "We are a leading insurer. Our mission is to make cover simple. We value ownership and collaboration. "
                          "Requirements: 5 years Python, Django and PostgreSQL. Remote within the Americas."}

    # ---- voice baseline -------------------------------------------------------------------------------------------
    check("baseline: too short -> None", coach.baseline_from({"duration_sec": 4, "pitch_mean_hz": 150}) is None)
    check("baseline: impossibly fast (stopped mid-passage) -> None, never a wrong baseline",
          coach.baseline_from({"duration_sec": 13, "pitch_mean_hz": 150, "pace_wpm": 292}) is None)
    base = coach.baseline_from({"duration_sec": 25, "pace_wpm": 175, "pitch_mean_hz": 120, "jitter": 0.035, "pitch_range_st": 6, "uptalk_ratio": 0.3})
    check("baseline: keeps the calm-voice numbers", base["pace_wpm"] == 175 and base["pitch_mean_hz"] == 120, base)
    t = coach.personal_thresholds(base)
    check("thresholds: a naturally fast talker isn't 'rushing' at their normal pace", t["rush_wpm"] > 200, t)
    check("thresholds: shakiness judged against your own voice", abs(t["jitter"] - 0.056) < 0.001, t)
    check("thresholds: without a baseline, generic and no raised-pitch cue", coach.personal_thresholds(None)["raised_pitch"] is None)
    fast_calm = {"duration_sec": 30, "pace_wpm": 190, "pitch_mean_hz": 122, "jitter": 0.04, "phrases": 8, "pitch_range_st": 6}
    generic, personal = ai.composure_feedback(fast_calm), ai.composure_feedback(fast_calm, baseline=base)
    check("composure: same voice, generic thresholds -> flagged as rushing and shaky",
          {s["cue"] for s in generic["signals"]} >= {"rush"}, generic["signals"])
    check("composure: same voice vs its own baseline -> calm (it's just how they talk)", personal["label"] == "Calm and confident" and personal["personal"], personal)
    raised = ai.composure_feedback({**fast_calm, "pace_wpm": 175, "pitch_mean_hz": 145}, baseline=base)
    check("composure: raised pitch vs your normal is a cue only a baseline can catch",
          any(s["cue"] == "raised" for s in raised["signals"]) and not any(s["cue"] == "raised" for s in ai.composure_feedback({**fast_calm, "pitch_mean_hz": 145})["signals"]), raised["signals"])
    check("composure: caveat says whether it's personal", "own calm-voice" in personal["caveat"] and "generic" in generic["caveat"])

    # ---- story bank -------------------------------------------------------------------------------------------------
    ans = ("When our claims team had a backlog I built a Django and PostgreSQL triage tool. I wrote the scoring myself. "
           "It cut the backlog by 40% in two months.")
    st = coach.story_from("Tell me about a time you improved a process", ans, 82)
    check("story: title from the first sentence, skills tagged, STAR read", st["title"].startswith("When our claims team")
          and {"Django", "PostgreSQL"} <= set(st["skills"]) and st["star"]["result"], st)
    cov = coach.story_coverage([{"text": "Experience building triage and scoring tools for claims"}], ["Django", "Kubernetes"], [dict(st, id=1)])
    check("coverage: skill with a story is covered, one without is a gap", cov["gaps"] == ["Kubernetes"] and cov["covered"] == 2, cov)
    rag = dict(coach.story_from("q", "I built a RAG assistant in Python that answered underwriting questions and cut lookups from 20 minutes to 2.", 80), id=2)
    cov2 = coach.story_coverage([], ["LLMs", "Python", "Terraform"], [rag])
    llm_row = next(r for r in cov2["rows"] if r["skill"] == "LLMs")
    check("coverage: a related-skill story counts as PARTIAL, labelled, not as full coverage",
          llm_row["partial"] == "RAG" and cov2["covered"] == 1 and cov2["partial"] == 1 and cov2["gaps"] == ["Terraform"], cov2)

    # ---- drills -------------------------------------------------------------------------------------------------------
    d0 = date(2026, 9, 1)
    check("drill: weak answer comes back tomorrow", coach.schedule(4, 40, d0)["next_due"] == "2026-09-02")
    good = coach.schedule(4, 90, d0)
    check("drill: strong answer spaced out (x2.5)", good["interval_days"] == 10 and good["next_due"] == "2026-09-11", good)
    check("drill: mastered after long intervals of strong answers", coach.schedule(10, 90, d0)["mastered"])
    check("drill: interval capped at 60 days", coach.schedule(50, 95, d0)["interval_days"] == 60)

    # ---- interview types ----------------------------------------------------------------------------------------------
    check("types: each kind has questions", all(coach.typed_questions(k, job, ["Python", "Django"], {"amount": 12000}) for k in ("screen", "technical", "negotiation", "reverse")))
    check("types: the offer is spoken naturally, not as 'US$/mo'", "US dollars a month" in coach.typed_questions("negotiation", job, [], {"amount": 4000, "unit": "US$/mo"})[0]["q"])
    check("types: negotiation opens with a concrete offer", "12,000" in coach.typed_questions("negotiation", job, [], {"amount": 12000, "unit": "TT$ a month"})[0]["q"])
    offer = {"amount": 12000}
    strong_neg = ("Thank you, I'm excited about the role. Based on similar roles in the market and the results I've delivered, "
                  "I was expecting closer to 14,500 a month. Is there flexibility there, and could we also talk about the bonus and leave?")
    weak_neg = "Oh that sounds great, I accept, thank you so much."
    sn, wn = coach.kind_feedback("negotiation", "q", strong_neg, job, offer), coach.kind_feedback("negotiation", "q", weak_neg, job, offer)
    check("negotiation: anchored counter + reasons + package -> high", sn["score"] >= 80, sn)
    check("negotiation: accepting on the spot -> low, with the honest warning", wn["score"] <= 40 and "hurt" in wn["honest"], wn)
    check("negotiation: a counter BELOW the offer isn't an anchor", not coach.kind_feedback("negotiation", "q", "Could we do 11,000 a month?", job, offer)["checks"]["anchored above the offer"])
    good_rev = "What does success look like in the first 90 days? And how does the team make decisions about the roadmap?"
    check("reverse: specific questions about the work -> high", coach.kind_feedback("reverse", "q", good_rev, job)["score"] >= 80)
    check("reverse: salary first / one question -> low", coach.kind_feedback("reverse", "q", "What's the salary?", job)["score"] < 50)
    tech = ("On a claims project we had slow reports, so I chose PostgreSQL materialized views instead of caching in Redis, because the data "
            "only changed nightly. The trade-off was staleness, which was fine. Report time dropped from 40 seconds to 2. " * 2)
    check("technical: trade-off + example + numbers + tools -> high", coach.kind_feedback("technical", "q", tech, job)["score"] >= 80)
    check("technical: vague -> low with trade-off tip", "Trade-offs" in " ".join(coach.kind_feedback("technical", "q", "I know it well, I have used it a lot at work.", job)["tips"]))
    check("screen: badmouthing an employer is flagged", not coach.kind_feedback("screen", "Why are you leaving?", "My boss is incompetent and the place is toxic, so I want out as soon as possible really.", job)["checks"]["no negativity about past employers"])
    check("screen: salary question needs a number", not coach.kind_feedback("screen", "What are your salary expectations?", "I'm open to whatever you think is fair for the role really.", job)["checks"]["gave a number or range"])
    fb = ai.interview_feedback(job, "What are your salary expectations?", "Based on my research I'm looking for 13,000 to 15,000 TT$ a month, depending on the full package.", kind="screen")
    check("interview_feedback kind=screen: uses the screen checks, no STAR follow-up", fb["checks"] and fb["follow_up"] is None and fb["kind"] == "screen", fb)
    check("interview_feedback: interrupted -> penalty + tip first", ai.interview_feedback(job, "q", ans, interrupted=True)["tips"][0].startswith("The interviewer had to cut you off"))
    check("offer_for: posted range low end, else peers' p25", coach.offer_for({"monthly_ttd_min": 12340}, None, True)["amount"] == 12300
          and coach.offer_for(None, {"p25": 4050, "unit": "US$/mo"}, False)["amount"] == 4000)

    # ---- prep plan + research -----------------------------------------------------------------------------------------
    rb = coach.research_brief(job, ["Python", "Django"])
    check("research brief: stack is technologies only (no 'English', 'Education')",
          not {"English", "Education"} & set(coach.research_brief({**job, "description": job["description"] + " Fluent English. Degree in Education."}, [])["stack"]))
    check("research brief: about lines, values, stack, questions", rb["about"] and "ownership" in rb["values"] and "Django" in rb["stack"] and len(rb["questions_to_ask"]) >= 3, rb)
    plan = coach.prep_plan(job, date(2026, 9, 10), "technical", today=date(2026, 9, 3), gaps=["Kubernetes"], has_baseline=False)
    keys = [t["key"] for t in plan["tasks"]]
    check("prep plan: a week out -> research, baseline, stories for gaps, two mocks, logistics, after-tasks",
          {"research", "baseline", "stories", "mock1", "mock2", "logistics", "log", "thanks"} <= set(keys) and plan["kind"] == "technical", keys)
    check("prep plan: tasks are in date order", [t["date"] for t in plan["tasks"]] == sorted(t["date"] for t in plan["tasks"]))
    tomorrow = coach.prep_plan(job, date(2026, 9, 4), "screen", today=date(2026, 9, 3), has_baseline=True, stories=5)
    check("prep plan: interview tomorrow -> everything compressed, nothing in the past", all(t["date"] >= "2026-09-03" for t in tomorrow["tasks"]) and "baseline" not in [t["key"] for t in tomorrow["tasks"]])

    # ---- real vs mock -----------------------------------------------------------------------------------------------
    rv = coach.real_vs_mock([{"felt": 2, "outcome": "rejected"}, {"felt": 2, "outcome": "advanced"}], [{"overall": 80}])
    check("real vs mock: real feels much harder -> practise tougher", "harder" in rv["read"] and rv["advance_rate"] == 50, rv)
    check("real vs mock: no data -> None", coach.real_vs_mock([], [{"overall": 70}]) is None)

    # ---- inbox ------------------------------------------------------------------------------------------------------
    inv = coach.classify_email("Interview invitation - Python Developer", "Hi, we'd like to schedule an interview. Are you free Tuesday, 8 October?", "jane@acme-insurance.com")
    check("inbox: invite -> Interviewing, date spotted", inv["kind"] == "invite" and inv["suggested_status"] == "Interviewing" and inv["mentions_date"], inv)
    rej = coach.classify_email("Your application", "Thank you for applying. Unfortunately we have decided to move forward with other candidates.", "")
    check("inbox: rejection wins over 'thank you for applying'", rej["kind"] == "rejection" and rej["suggested_status"] == "Rejected", rej)
    check("inbox: offer", coach.classify_email("Offer", "We are pleased to extend an offer of employment.", "")["kind"] == "offer")
    check("inbox: assessment", coach.classify_email("Next steps", "Please complete the HackerRank coding challenge within 5 days.", "")["kind"] in ("assessment", "invite"))
    check("inbox: unrelated -> other, no suggestion", coach.classify_email("Newsletter", "Our spring sale starts now.", "")["suggested_status"] is None)
    jobs = [{"job_id": "1", "title": "Python Developer", "company": "Acme Insurance Ltd"}, {"job_id": "2", "title": "Analyst", "company": "Globex"}]
    m = coach.match_email_to_jobs("Interview invitation - Python Developer", "from the Acme Insurance team", "jane@acmeinsurance.com", jobs)
    check("inbox: matched to the right job by company + domain", m and m[0]["job_id"] == "1", m)
    check("inbox: no company match -> no guess", coach.match_email_to_jobs("Hello", "generic text", "x@gmail.com", jobs) == [])

    # ---- camera -----------------------------------------------------------------------------------------------------
    check("camera: too few frames -> None", coach.camera_feedback({"frames": 5}) is None)
    cg = coach.camera_feedback({"frames": 200, "face_ratio": 0.98, "eye_contact_ratio": 0.7, "head_motion_deg": 4, "smile_ratio": 0.2})
    cb = coach.camera_feedback({"frames": 200, "face_ratio": 0.6, "eye_contact_ratio": 0.2, "head_motion_deg": 20, "smile_ratio": 0.0})
    check("camera: good framing/eye contact -> high, no tips", cg["score"] == 100 and not cg["tips"], cg)
    check("camera: out of frame, looking away, fidgeting, no smile -> four tips", cb["score"] <= 30 and len(cb["tips"]) == 4, cb)

    # ---- weekly report ----------------------------------------------------------------------------------------------
    wr = coach.weekly_report({"applied": 10, "responses": 0, "interviews": 1, "offers": 0, "rejections": 2, "mocks": 0, "mock_avg": None, "composure_avg": None, "drills": 0, "stories": 0},
                             {"applied": 4, "responses": 1, "interviews": 0, "offers": 0, "rejections": 0, "mocks": 2, "mock_avg": 60, "composure_avg": 70, "drills": 3, "stories": 1})
    check("weekly: low response rate and no practice before real interviews are called out",
          wr["response_rate"] == 0 and any("response" in r for r in wr["reads"]) and any("no mock practice" in r for r in wr["reads"]), wr["reads"])
    check("weekly: deltas", wr["deltas"]["applied"] == 6)

    # ---- matching precision ----------------------------------------------------------------------------------------
    from src import matching, skills_taxonomy as tax
    check("taxonomy: 'GIT' (Graduate In Training) isn't the Git tool", "Git" not in tax.find_skills("Field Service Engineer Graduate In Training (GIT)"))
    check("taxonomy: Git / git still found", tax.find_skills("We use Git and git-flow")["Git"] == 2)
    ctx = matching.load_context(profile={"skills": {"Python": {"category": "Languages", "years": 4}, "Django": {"category": "Web & Backend", "years": 4},
                                                   "PostgreSQL": {"category": "Data & Databases", "years": 3}, "SQL": {"category": "Languages"},
                                                   "Bash": {"category": "Languages"}, "Supply Chain": {"category": "Business & Operations"}},
                                        "titles": ["Backend Engineer"], "years_experience": 5, "seniority": "senior", "roles": []},
                                prefs={}, index=None, priors=None)
    if ctx:
        check("title: a main-area skill in the title is a match", matching.title_alignment("Python Developer", ctx)[0] >= 0.7)
        check("title: a side skill (Supply Chain) doesn't make 'Logistics Officer' a title match",
              matching.title_alignment("Logistics Officer", ctx)[0] < 0.3, matching.title_alignment("Logistics Officer", ctx))
        go = matching.evaluate({"title": "Senior Go Backend Engineer", "company": "X", "description": "Requirements: 5 years of Go. PostgreSQL. REST APIs.",
                                "location": "Remote", "remote": True}, ctx)
        check("fit: the title's core skill missing (Go) caps fit at 45 and says why",
              go["fit"] <= 45 and any("title names Go" in g for g in go["gaps"]), (go["fit"], go["gaps"][:2]))
        # "Software Engineer" in a title is a job family, not a skill that covers the title's named craft
        ctx["skills"]["Software Development"] = {"category": "Engineering practice", "years": 5}
        go2 = matching.evaluate({"title": "Senior Go Software Engineer", "company": "X", "description": "Requirements: 5 years of Go. PostgreSQL. REST APIs.",
                                 "location": "Remote", "remote": True}, ctx)
        check("fit: having 'Software Development' doesn't lift the Go title cap", go2["fit"] <= 45, go2["fit"])
        ctx["titles"].append(("data analyst", 1.0))
        check("title: sharing only the job-family word ('analyst') is a weak match",
              matching.title_alignment("Senior Lab Analyst", ctx)[0] < 0.3, matching.title_alignment("Senior Lab Analyst", ctx))
        ctx["skills"].update({k: {"category": "Engineering practice", "years": 2} for k in ("Testing", "Production Support")})
        check("title: a generic ask in the title ('QA') is not a title match",
              matching.title_alignment("QA/QC Inspector – Mechanical", ctx)[0] < 0.3, matching.title_alignment("QA/QC Inspector – Mechanical", ctx))
        check("title: the target itself still matches fully", matching.title_alignment("Audit Data Analyst", ctx)[0] == 1.0)
        # a developer posting that names no technology is read from the resume alone, not dragged down by keywords
        generic = {"title": "Systems Developer", "company": "X", "location": "Trinidad", "region": "Trinidad & Tobago", "kw_fit": 5,
                   "description": "Developing and maintaining software applications. Integrating applications, databases, APIs and third-party systems."}
        ctx["skills"]["Databases"] = {"category": "Data & Databases", "years": 3}
        gm = matching.evaluate(generic, ctx)
        check("fit: generic developer posting ignores a near-zero keyword score", gm["fit"] == gm["fit_profile"], (gm["fit"], gm["fit_profile"]))
        nf = matching.evaluate({"title": "Barista", "company": "X", "location": "Trinidad", "kw_fit": 5, "description": "Serve coffee. Entry level."}, ctx)
        check("fit: an out-of-field posting still blends the keyword score in", nf["fit"] < nf["fit_profile"], (nf["fit"], nf["fit_profile"]))
    from src import score as _score
    kcfg = {"scoring": {"strong_signals": {"agent": 8}, "context_signals": {"tobago": 14}, "score_divisor": 100}}
    human = _score.score_job({"title": "Reservations Agent", "description": "Our agents assist passengers. Agent duties in Tobago.", "location": "Tobago"}, kcfg)
    ai = _score.score_job({"title": "AI Engineer", "description": "Build LLM agent workflows. Agent evals.", "location": "Remote"}, kcfg)
    check("keywords: 'agent' in a non-AI posting is a person, not an AI-agent signal", human["fit_score"] <= 10 < ai["fit_score"], (human["fit_score"], ai["fit_score"]))
    from src import resume_parse
    rp = resume_parse.parse_resume("# A B\n\n## EXPERIENCE\n\n### Acme\n**Engineer** · Jan 2022 – Jan 2024\n\n- Built Django portals on PostgreSQL.\n\n"
                                   "### Globex\n**Engineer** · Jan 2020 – Jan 2022\n\n- Wrote Python scripts.\n\n## SKILLS\n\nPython, Django\n", today=date(2024, 6, 1))
    check("resume: a Django role counts toward Python years", rp["skills"]["Python"]["years"] >= 3.9, rp["skills"].get("Python"))
    long_cv = ("# A B\n\n## Work Experience\n\n### Acme Group (Acme Life · Acme N.V.) — 2021 – Present\n\nFive years with the same business.\n\n"
               "| Role | Dates |\n| --- | --- |\n| **Data Engineer**, Acme N.V. | Feb 2023 – Present |\n"
               "| **Project Assistant to the Managing Director**, Acme Life | 2021 – Feb 2023 |\n\n"
               "#### Group Projects: Project Assistant (2021 – Feb 2023), then Data Engineer (Feb 2023 – Present)\n\n"
               "- Built Django portals for policy administration with an audit trail.\n- Synced live inventory to the website.\n"
               "- Deployed with Docker.\n\n## Independent & Side Projects (2023 – 2030)\n\n- A teaching app in React.\n\n"
               "## Education\n\n**UWI:** BSc Actuarial Science, 2016 – 2021\n\n## Awards & Leadership\n\n- Head Prefect, Some Secondary School\n\n"
               "## Appendix: Full Project Catalogue\n\n| GuestHub | Contact master and guest lists |\n" + "Filler line about systems.\n" * 900)
    lp = resume_parse.parse_resume(long_cv, today=date(2024, 6, 1))
    check("resume: an employer line with overall dates is context, not a role; table rows and nested headings are roles",
          [r["title"] for r in lp["roles"]][:2] == ["Data Engineer", "Project Assistant to the Managing Director"]
          and all(r["company"] for r in lp["roles"]) and not any("Acme Group" in r["title"] for r in lp["roles"]), [(r["title"], r["company"]) for r in lp["roles"]])
    check("resume: side projects aren't employment and can't end in the future", lp["years_experience"] == 3.5, lp["years_experience"])
    check("resume: 'Assistant to the Managing Director' is not a director", lp["seniority"] != "lead", lp["seniority"])
    check("resume: education stops at the next section ('Contact master' in an appendix is not a master's)", lp["highest_education"] == "bachelor", lp["education"])
    check("resume: passing words in a long resume aren't skills (inventory, policy administration, audit trail, teaching)",
          not {"Supply Chain", "Administration", "Auditing", "Teaching"} & set(lp["skills"]), sorted(lp["skills"]))
    check("resume: frameworks imply Software Development and SQL", {"Software Development", "SQL", "Databases"} <= set(rp["skills"]), sorted(rp["skills"]))

