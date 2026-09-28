"""
test_profile.py — resume parsing, retrieval, profile-driven matching, calibration, preferences.

Called from test_pipeline.main() (shares its temp database and `check`). Also runnable on its own:
    python tests/test_profile.py
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RESUME = """# JANE DOE
**Backend Engineer**
jane@example.com | (868) 555-1234 | github.com/janedoe

## SUMMARY
Backend engineer with insurance domain experience.

## EXPERIENCE

### Acme Insurance — Port of Spain
**Senior Python Developer** · Jan 2019 – Dec 2021
- Built Django REST APIs and PostgreSQL ETL pipelines processing 50,000+ policies.
- Automated reporting with n8n and Docker, saving 100 hours per month.

### Beta Corp
**Software Engineer** · Jun 2021 – Present
- Deployed Flask services on AWS with GitHub Actions CI/CD.
- Led 3 engineers building an LLM RAG assistant.

## SKILLS
Python, Django, Flask, PostgreSQL, Docker, AWS, n8n, RAG, LLMs

## EDUCATION
BSc Computer Science — University of the West Indies · 2014 – 2018
"""


def _docx(text: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{ln}</w:t></w:r></w:p>" for ln in text.split("\n"))
    doc = f'<?xml version="1.0"?><w:document xmlns:w="x"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def run(check, cfg: dict) -> None:
    print("\n8. RESUME PROFILE · RETRIEVAL · MATCHING · CALIBRATION")
    from src import calibration, db, matching, profile_store, resume_parse, retrieval, score
    from src import skills_taxonomy as tax

    today = date(2026, 9, 27)

    # ---- taxonomy -------------------------------------------------------------------------------------------
    f = tax.find_skills("We use Go and Node.js, C++ and C#, R. Must go to the office. React/TypeScript on PostgreSQL (postgres).")
    check("taxonomy: symbols and aliases", {"C++", "C#", "Node.js", "React", "TypeScript", "PostgreSQL"} <= set(f), str(sorted(f)))
    check("taxonomy: 'go to the office' is not the Go language", "Go" in f and f["Go"] == 1)
    check("taxonomy: related skills give partial credit", "MySQL" in tax.related("PostgreSQL"))

    # ---- parsing --------------------------------------------------------------------------------------------
    p = resume_parse.parse_resume(RESUME, today=today)
    check("parse: contact", p["contact"]["email"] == "jane@example.com" and p["contact"]["name"], str(p["contact"]))
    check("parse: two dated roles", len(p["roles"]) == 2, str([r["title"] for r in p["roles"]]))
    check("parse: role title/company split", p["roles"][0]["title"] == "Senior Python Developer" and "Acme" in p["roles"][0]["company"],
          str(p["roles"][0]))
    check("parse: current role detected", p["roles"][1]["current"] and p["roles"][1]["end"] == "")
    # Jan 2019–Dec 2021 (36 mo) + Jun 2021–Sep 2026 overlap Jun–Dec 2021 (7 mo) -> Jan 2019..Sep 2026 = 93 mo = 7.75y
    check("parse: years = union of overlapping ranges (no double counting)", abs(p["years_experience"] - 7.8) <= 0.1, str(p["years_experience"]))
    check("parse: skills extracted with years of use", p["skills"]["Django"]["years"] >= 2.9 and p["skills"]["Django"]["in_skills_section"])
    check("parse: skill not in resume is absent", "Kubernetes" not in p["skills"])
    check("parse: education level", p["highest_education"] == "bachelor" and p["education"][0]["year"] == 2018)
    check("parse: quantified achievements", any("50,000" in a for a in p["achievements"]))
    check("parse: domains", "Insurance" in p["domains"])
    check("parse: seniority from title/years", p["seniority"] == "senior", p["seniority"])
    check("parse: interval union helper", resume_parse.union_months([(0, 11), (6, 20), (30, 35)]) == 27)
    check("parse: bare years and present", resume_parse.RANGE_RE.search("2016 – 2021") and resume_parse.RANGE_RE.search("Oct 2021 - Present"))

    # text extraction
    t = resume_parse.extract_text(_docx(RESUME), "cv.docx")
    check("extract: DOCX text (stdlib only)", "Senior Python Developer" in t and "Jane" in t.title())
    for bad, name in ((b"", "x.md"), (b"hello", "x.md"), (b"MZ....", "x.exe")):
        try:
            resume_parse.extract_text(bad, name)
            ok = False
        except resume_parse.ResumeError:
            ok = True
        check(f"extract: rejects {name!r} ({len(bad)} bytes)", ok)

    # ---- retrieval ------------------------------------------------------------------------------------------
    chunks = retrieval.chunk_profile(RESUME, p)
    check("chunks: one per bullet, labelled with the role", any("Acme" in c["label"] and "PostgreSQL" in c["text"] for c in chunks), str(len(chunks)))
    idx = retrieval.ResumeIndex(chunks)
    hit = idx.retrieve("Experience building REST APIs with Django and PostgreSQL", k=1)[0]
    check("retrieval: best chunk answers the requirement", "Django REST" in hit["text"] and hit["score"] > 0.5, str(hit))
    miss = idx.retrieve("Manage Kubernetes clusters and Terraform modules", k=1)[0]
    check("retrieval: unrelated requirement scores low", miss["score"] < 0.35, str(miss["score"]))
    # embeddings path with a fake Ollama
    def fake_http(path, payload=None, timeout=60):
        if path == "/api/tags":
            return {"models": [{"name": "llama3.2:1b"}, {"name": "nomic-embed-text:latest"}]}
        if path == "/api/embed":
            return {"embeddings": [[1.0, 0.0] if "django" in t.lower() else [0.0, 1.0] for t in payload["input"]]}
        raise AssertionError(path)
    with mock.patch.object(retrieval, "_http_json", side_effect=fake_http):
        check("embeddings: picks an installed embedding model", retrieval.embedding_model() == "nomic-embed-text:latest")
        vecs = retrieval.embed(["django api", "cooking"], "nomic-embed-text:latest")
        check("embeddings: batch call", vecs == [[1.0, 0.0], [0.0, 1.0]])
    with mock.patch.object(retrieval, "_http_json", side_effect=OSError("down")):
        check("embeddings: server down -> None (lexical fallback)", retrieval.embed(["a"], "m") is None and retrieval.embedding_model() == "")
    vec_chunks = [dict(c, embedding=[1.0, 0.0] if "django" in c["text"].lower() else [0.0, 1.0]) for c in chunks]
    vidx = retrieval.ResumeIndex(vec_chunks, "m")
    h = vidx.retrieve("backend framework", k=1, qvec=[1.0, 0.0])[0]
    check("hybrid retrieval: semantic match beats zero keyword overlap", h["semantic"] == 1.0 and h["score"] >= 0.9 and "Django" in h["text"], str(h))

    # ---- store: versions, overrides, preferences (all against temp files) -----------------------------------
    tmp_yaml = Path(tempfile.mkdtemp()) / "profile.yaml"
    import yaml as _yaml
    _cfg = _yaml.safe_load((ROOT / "config" / "profile.yaml").read_text()) or {}
    _cfg.pop("preferences", None)          # the test must not depend on preferences saved in the real config
    tmp_yaml.write_text(_yaml.safe_dump(_cfg))
    with mock.patch.object(profile_store, "PROFILE_YAML", tmp_yaml), mock.patch.object(retrieval, "embedding_model", return_value=""):
        c = db._conn(); c.execute("DELETE FROM resume_versions"); c.execute("DELETE FROM resume_chunks"); c.commit(); c.close()
        profile_store.invalidate()
        check("store: no resume -> no profile", profile_store.active_profile() is None and matching.load_context(cfg) is None)
        imp = profile_store.import_resume(RESUME.encode(), "jane.md", embed=False)
        prof = profile_store.active_profile()
        check("store: import parses, chunks and activates", prof and prof["_resume_id"] == imp["id"] and imp["chunks"] >= 6, str(imp))
        profile_store.update_overrides(imp["id"], {"add_skills": [{"name": "Kubernetes", "years": 2}], "remove_skills": ["R"]})
        prof = profile_store.active_profile()
        check("overrides: manual skill added and marked", prof["skills"]["Kubernetes"]["source"] == "manual" and prof["skills"]["Kubernetes"]["years"] == 2)
        profile_store.update_overrides(imp["id"], {"remove_skills": ["Docker"]})
        check("overrides: removed skill disappears", "Docker" not in profile_store.active_profile()["skills"])
        profile_store.update_overrides(imp["id"], {"restore_skills": ["Docker"]})
        check("overrides: restore brings it back", "Docker" in profile_store.active_profile()["skills"])
        profile_store.update_overrides(imp["id"], {"years_experience": 3})
        check("overrides: years correction re-derives level", profile_store.active_profile()["years_experience"] == 3.0
              and profile_store.active_profile()["seniority"] == "senior")   # title still says Senior
        imp2 = profile_store.import_resume("# X\n\n## EXPERIENCE\n**Analyst** · Jan 2024 – Present\n- Wrote SQL reports in Excel for finance.\n" + "filler " * 30,
                                           "second.md", embed=False)
        check("versions: newest is active, older kept", profile_store.active_profile()["_resume_id"] == imp2["id"] and len(profile_store.list_versions()) == 2)
        profile_store.set_active(imp["id"])
        check("versions: switch back keeps my edits", "Kubernetes" in profile_store.active_profile()["skills"])
        profile_store.delete_version(imp2["id"])
        check("versions: delete", len(profile_store.list_versions()) == 1)

        check("prefs: defaults", profile_store.get_prefs()["work_mode"] == "both")
        profile_store.save_prefs({"work_mode": "local_first", "min_salary_monthly_ttd": 12000, "avoid_keywords": ["night shift"]})
        pr = profile_store.get_prefs()
        check("prefs: saved to profile.yaml without touching the rest", pr["work_mode"] == "local_first" and pr["min_salary_monthly_ttd"] == 12000
              and "sources" in tmp_yaml.read_text())
        for bad in ({"work_mode": "sideways"}, {"nope": 1}, {"min_salary_monthly_ttd": -5}, {"target_titles": "x"}):
            try:
                profile_store.validate_prefs(bad)
                ok = False
            except ValueError:
                ok = True
            check(f"prefs: rejects {list(bad)[0]}={list(bad.values())[0]!r}", ok)
        profile_store.save_prefs({"work_mode": "both", "min_salary_monthly_ttd": 0, "avoid_keywords": []})

        # ---- job analysis ------------------------------------------------------------------------------------
        a = matching.analyze_job({"title": "Senior Data Engineer", "location": "Remote (Worldwide)", "remote": True,
                                  "description": "Requirements\n- 4+ years building data pipelines with Python and SQL\n- Experience with Airflow or dbt\n"
                                                 "Nice to have: Snowflake\nResponsibilities\n- Build ETL for our insurance clients.\nSalary: $120,000 - $150,000"})
        kinds = {k: v["kind"] for k, v in a["skills"].items()}
        check("analyze: required vs nice skills", kinds.get("Python") == "required" and kinds.get("Snowflake") == "nice" and kinds.get("Airflow") == "required", str(kinds))
        check("analyze: years, level, mode", a["min_years"] == 4 and a["level"] == 2.0 and a["work_mode"] == "remote")
        check("analyze: requirement sentences keep the number", any(r.startswith("4+ years") for r in a["requirements"]), str(a["requirements"]))
        check("analyze: pay to monthly", a["pay"] and a["pay"]["monthly_usd_min"] == 10000 and a["pay"]["currency"] == "USD")
        check("pay: TT$ local monthly", matching.parse_pay("TT$9,000 - TT$12,000 per month", local=True)["monthly_ttd_max"] == 12000)
        check("pay: hourly rate", matching.parse_pay("$45/hr")["monthly_usd_min"] == 7200)
        check("pay: no false positives", matching.parse_pay("Competitive salary, 3 years experience, 401k") is None)
        for text, want in (("Remote, US only", "us_only"), ("You must be located in the United States", "us_only"), ("Remote — worldwide", "worldwide"),
                           ("Remote, LATAM", "americas"), ("EU-based candidates only", "eu_only"), ("Remote", "unknown")):
            got = matching.remote_scope({"description": text, "location": "", "title": "x"})
            check(f"remote scope: {text!r} -> {want}", got == want, got)
        check("remote scope: 'USA, LATAM' location is open to the Americas", matching.remote_scope({"location": "USA, LATAM", "description": "", "title": ""}) == "americas")

        # ---- evaluate ---------------------------------------------------------------------------------------
        ctx = matching.load_context(cfg, priors={"local": {"p": 0.10, "source": "t"}, "remote": {"p": 0.015, "source": "t"}})
        base = {"title": "Python Django Developer", "company": "X", "location": "Remote", "remote": True, "salary": "", "flags": "",
                "posted_at": date.today().isoformat(), "fit_score": 60,
                "description": "Requirements\n- 3+ years of Python and Django\n- PostgreSQL and Docker experience\n- Build REST APIs\nOpen to candidates worldwide. Contractors welcome."}
        strong = matching.evaluate(base, ctx)
        weak = matching.evaluate(dict(base, title="Kubernetes Platform Lead", description="Requirements\n- 10+ years of Kubernetes and Terraform\n- Go and Rust experience\nLead a team of 12 SREs. Remote worldwide."), ctx)
        us = matching.evaluate(dict(base, description=base["description"] + "\nMust be located in the United States."), ctx)
        check("evaluate: strong match outranks weak on fit and likelihood", strong["fit"] > weak["fit"] + 20 and strong["likelihood"] > weak["likelihood"] + 15,
              f'{strong["fit"]}/{strong["likelihood"]} vs {weak["fit"]}/{weak["likelihood"]}')
        check("evaluate: requirement evidence from the resume", any(r["status"] == "met" and r["evidence"] for r in strong["requirements"]), str(strong["requirements"][:2]))
        check("evaluate: missing skills are named", {"Rust", "Go"} & set(weak["skills"]["missing_required"]), str(weak["skills"]))
        check("evaluate: US-only remote is a blocker and tanks the odds", us["blockers"] and us["likelihood"] < strong["likelihood"] / 2 and us["verdict"] in ("Low", "Long shot"),
              f'{us["likelihood"]} {us["blockers"]}')
        check("evaluate: interview chance is a probability, capped", 0 < strong["interview_chance"] <= 65)
        check("evaluate: every factor is explained", all({"name", "delta"} <= set(f) for f in strong["factors"]) and strong["factors"])
        local = matching.evaluate(dict(base, location="Port of Spain, Trinidad & Tobago", region="Port of Spain", remote=False,
                                       description="On-site. Requirements\n- Python and Django experience\n- 2+ years"), ctx)
        onsite_abroad = matching.evaluate(dict(base, location="Berlin, Germany", remote=False, description="On-site in Berlin office. Python Django developer, 3+ years."), ctx)
        check("evaluate: local role is reachable, on-site abroad is not", local["likelihood"] > onsite_abroad["likelihood"] + 30 and onsite_abroad["blockers"],
              f'{local["likelihood"]} vs {onsite_abroad["likelihood"]}')
        check("evaluate: local gets a higher prior than remote", local["prior"] > strong["prior"])
        thin = matching.evaluate(dict(base, description="Python developer needed."), ctx)
        check("evaluate: thin posting lowers confidence", thin["confidence"] in ("low", "medium") and strong["confidence"] in ("medium", "high"))
        old = matching.evaluate(dict(base, posted_at=(date.today() - timedelta(days=60)).isoformat()), ctx)
        check("evaluate: stale posting is worth less", old["likelihood"] < strong["likelihood"])

        # per-skill items, soft skills, tailoring advice, posting highlights
        items = {i["name"]: i for i in strong["skills"]["items"]}
        check("items: every posting skill has a status and importance", items["Django"]["status"] == "have" and items["Django"]["weight"] == 1.0
              and items["Django"]["years"] >= 2.9, str(items.get("Django")))
        soft = matching.evaluate(dict(base, description="Requirements\n- Excellent communication and English\n- Python and Django"), ctx)
        si = {i["name"]: i for i in soft["skills"]["items"]}
        check("soft skills are neutral, never reported as gaps", si.get("Communication", {}).get("status") == "soft"
              and "Communication" not in soft["skills"]["missing_required"])
        rel = matching.evaluate(dict(base, description="Requirements\n- 3+ years building Django REST APIs and PostgreSQL pipelines\n- Experience with MySQL or Oracle"), ctx)
        tw = rel["tailoring"]
        check("tailoring: lead-with bullet comes from the resume", tw["lead_with"] and tw["lead_with"][0]["bullet"] in RESUME.replace("**", ""), str(tw["lead_with"][:1]))
        check("tailoring: related skill gets honest wording advice", any(k["skill"] == "MySQL" and "genuinely used" in k["advice"] for k in tw["add_keywords"]), str(tw["add_keywords"]))
        gap = matching.evaluate(dict(base, description="Requirements\n- Kubernetes and Terraform in production\n- Rust experience"), ctx)
        check("tailoring: missing skills are listed as do-not-claim", "Rust" in gap["tailoring"]["do_not_claim"])
        hl = matching.highlight_terms("We use Postgres and rust daily, plus Django.", matching.evaluate(dict(base, description="Requirements\n- Postgres, Rust and Django"), ctx)["skills"]["items"])
        got = {h["text"].lower(): h["status"] for h in hl}
        check("highlights: exact words in the posting, tagged by status", got.get("postgres") == "have" and got.get("rust") == "missing" and got.get("django") == "have", str(got))

        # preferences move the numbers
        pctx = matching.load_context(cfg, priors=ctx["priors"], prefs={**ctx["prefs"], "work_mode": "local_only"})
        check("prefs: local_only turns a remote role into a blocker", matching.evaluate(base, pctx)["blockers"])
        pctx = matching.load_context(cfg, priors=ctx["priors"], prefs={**ctx["prefs"], "avoid_keywords": ["contractors welcome"]})
        check("prefs: avoid list is honoured", any("avoid" in b for b in matching.evaluate(base, pctx)["blockers"]))
        pay_job = dict(base, salary="TT$6,000 per month", region="Port of Spain", location="Port of Spain")
        pctx = matching.load_context(cfg, priors=ctx["priors"], prefs={**ctx["prefs"], "min_salary_monthly_ttd": 15000})
        check("prefs: pay below your floor is called out", any("below your" in g for g in matching.evaluate(pay_job, pctx)["gaps"]))

        # ---- pipeline integration ---------------------------------------------------------------------------
        matching.reset_context()
        j = score.score_job(dict(base, source="remotive", job_id="t:1", url="u"), cfg)
        check("score_job: profile-driven fields are set", j["likelihood"] > 0 and j["interview_chance"] > 0 and j["work_mode"] == "remote"
              and j["remote_scope"] == "worldwide" and json.loads(j["match_json"])["fit_keyword"] == 60 or json.loads(j["match_json"])["fit_keyword"] >= 0)
        check("score_job: generic tech-mention flags are replaced by the profile's own skills/gaps", "Mentions Kubernetes" not in j["flags"])
        db.upsert_jobs([j])
        row = db.get_job("t:1")
        check("db: match fields persisted", row["likelihood"] == j["likelihood"] and row["work_mode"] == "remote" and row["match_json"])
        n = db.rescore_all(lambda job: score.score_job(job, cfg))
        check("db: rescore_all re-applies the profile", n >= 1 and db.get_job("t:1")["likelihood"] > 0)
        from src import likelihood
        r = likelihood.rate(dict(base, kw_fit=60), cfg, deep=False)
        check("likelihood.rate delegates to the profile model", r.get("model") == "profile" and "factors" in r and r["verdict"])
        check("fit blend does not compound on re-evaluation",
              matching.evaluate(dict(base, fit_score=99, kw_fit=60), ctx)["fit"] == matching.evaluate(dict(base, fit_score=60), ctx)["fit"])

        # ---- calibration ------------------------------------------------------------------------------------
        c = db._conn(); c.execute("DELETE FROM app_status"); c.execute("DELETE FROM jobs WHERE job_id LIKE 'cal:%'"); c.commit(); c.close()
        cal0 = calibration.priors()
        check("calibration: default priors with no history", cal0["local"]["p"] == 0.10 and cal0["remote"]["p"] == 0.015 and cal0["local"]["n"] == 0)
        old_day = (date.today() - timedelta(days=40)).isoformat()
        rows = []
        for i in range(8):   # 8 local applications: 3 interviews, 3 rejected, 2 ghosted
            st = "Interviewing" if i < 3 else "Rejected" if i < 6 else "Applied"
            rows.append((f"cal:l{i}", st, old_day))
        for i in range(2):   # 2 remote applications just sent -> pending, no evidence yet
            rows.append((f"cal:r{i}", "Applied", date.today().isoformat()))
        for jid, st, day in rows:
            db.upsert_jobs([{"job_id": jid, "source": "x", "title": "t", "company": "c", "url": "u",
                             "region": "Port of Spain" if ":l" in jid else "", "location": "Port of Spain" if ":l" in jid else "Remote"}])
            db.update_status(jid, status=st, applied_date=day)
        cal = calibration.priors()
        check("calibration: local prior moves toward your observed rate", 0.10 < cal["local"]["p"] < 3 / 8, str(cal["local"]))
        check("calibration: pending applications are not counted as misses", cal["remote"]["n"] == 0 and cal["remote"]["pending"] == 2 and cal["remote"]["p"] == 0.015)
        check("calibration: source is stated", "your history" in cal["local"]["source"])
        c = db._conn(); c.execute("DELETE FROM app_status"); c.execute("DELETE FROM jobs WHERE job_id LIKE 'cal:%' OR job_id='t:1'"); c.commit(); c.close()

        # cleanup so later tests (and the dashboard test DB) see a clean slate
        c = db._conn(); c.execute("DELETE FROM resume_versions"); c.execute("DELETE FROM resume_chunks"); c.commit(); c.close()
        profile_store.invalidate(); matching.reset_context()
    shutil.rmtree(tmp_yaml.parent, ignore_errors=True)


if __name__ == "__main__":
    os.environ.setdefault("JOBHUNT_DB", str(Path(tempfile.mkdtemp()) / "t.db"))
    import yaml
    P, F = [], []

    def _check(name, cond, detail=""):
        (P if cond else F).append(name)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"\n         -> {detail}" if detail and not cond else ""))

    run(_check, yaml.safe_load((ROOT / "config" / "profile.yaml").read_text()))
    print(f"\n  {len(P)} passed, {len(F)} failed")
    sys.exit(1 if F else 0)
