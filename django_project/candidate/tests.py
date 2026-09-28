import io
import json
import zipfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile

from jobs.testutil import ScannerDBTestCase

RESUME = """# Jane Doe
**Backend Engineer**
jane@example.com

## EXPERIENCE
### Acme Insurance
**Senior Python Developer** · Jan 2019 – Present
- Built Django REST APIs and PostgreSQL ETL pipelines processing 50,000+ policies.
- Deployed Docker services on AWS with GitHub Actions CI/CD.
- Automated reporting with n8n saving 100 hours per month.

## SKILLS
Python, Django, PostgreSQL, Docker, AWS, n8n

## EDUCATION
BSc Computer Science — University of the West Indies · 2014 – 2018
"""


def docx_bytes(text):
    body = "".join(f"<w:p><w:r><w:t>{ln}</w:t></w:r></w:p>" for ln in text.split("\n"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


class ProfileApiTests(ScannerDBTestCase):
    def setUp(self):
        from src import db, matching, profile_store
        c = db._conn()
        for t in ("resume_chunks", "resume_versions"):
            c.execute(f"DELETE FROM {t}")
        c.commit(); c.close()
        profile_store.invalidate(); matching.reset_context()
        self.patch = mock.patch("src.retrieval.embedding_model", return_value="")
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def post(self, url, body=None, **kw):
        return self.client.post(url, data=json.dumps(body or {}), content_type="application/json", **kw)

    def test_upload_markdown_file_then_state(self):
        f = SimpleUploadedFile("jane.md", RESUME.encode(), content_type="text/markdown")
        r = self.client.post("/api/profile/resume/", {"file": f})
        self.assertEqual(r.status_code, 201, r.content[:300])
        d = json.loads(r.content)
        self.assertTrue(d["ok"])
        self.assertEqual(d["import"]["roles"], 1)
        names = {s["name"] for s in d["profile"]["skills"]}
        self.assertTrue({"Python", "Django", "PostgreSQL", "Docker"} <= names)
        self.assertGreater(d["profile"]["years_experience"], 7)
        self.assertEqual(d["status"]["has_resume"], True)
        self.assertEqual(d["status"]["semantic"], False)
        again = json.loads(self.client.get("/api/profile/").content)
        self.assertEqual(again["profile"]["contact"]["email"], "jane@example.com")
        self.assertEqual(again["calibration"]["local"]["n"], 0)

    def test_upload_docx_and_pasted_text(self):
        r = self.client.post("/api/profile/resume/", {"file": SimpleUploadedFile("cv.docx", docx_bytes(RESUME))})
        self.assertEqual(r.status_code, 201, r.content[:300])
        r = self.post("/api/profile/resume/", {"text": RESUME, "filename": "pasted.txt"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(json.loads(r.content)["versions"]), 2)

    def test_upload_errors_are_json_400(self):
        for payload in ({"text": ""}, {}):
            r = self.post("/api/profile/resume/", payload)
            self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/profile/resume/", {"file": SimpleUploadedFile("x.exe", b"MZ" * 200)})
        self.assertEqual(r.status_code, 400)
        self.assertIn("unsupported", json.loads(r.content)["error"])
        r = self.client.post("/api/profile/resume/", {"file": SimpleUploadedFile("tiny.md", b"hi")})
        self.assertEqual(r.status_code, 400)

    def test_overrides_and_versions(self):
        self.post("/api/profile/resume/", {"text": RESUME, "filename": "a.md"})
        d = json.loads(self.post("/api/profile/overrides/", {"add_skills": [{"name": "Kubernetes", "years": 2}], "remove_skills": ["n8n"]}).content)
        skills = {s["name"]: s for s in d["profile"]["skills"]}
        self.assertEqual(skills["Kubernetes"]["source"], "manual")
        self.assertNotIn("n8n", skills)
        vid = d["versions"][0]["id"]
        self.post("/api/profile/resume/", {"text": RESUME.replace("Jane", "Joan"), "filename": "b.md"})
        d = json.loads(self.post(f"/api/profile/versions/{vid}/activate/").content)
        self.assertEqual([v["id"] for v in d["versions"] if v["active"]], [vid])
        r = self.client.delete(f"/api/profile/versions/{vid}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.post("/api/profile/versions/999/activate/").status_code, 404)

    def test_overrides_without_resume_404(self):
        self.assertEqual(self.post("/api/profile/overrides/", {"remove_skills": ["x"]}).status_code, 404)

    def test_prefs_roundtrip_and_validation(self):
        if True:
            import tempfile, shutil, pathlib
            tmp = pathlib.Path(tempfile.mkdtemp()) / "profile.yaml"
            tmp.write_text("sources: {trinidad: true}\n")
            with mock.patch("src.profile_store.PROFILE_YAML", tmp):
                r = self.client.put("/api/profile/prefs/", data=json.dumps({"work_mode": "remote_first", "min_salary_monthly_usd": 4000, "preferred_regions": ["Port of Spain"]}), content_type="application/json")
                self.assertEqual(r.status_code, 200, r.content)
                got = json.loads(self.client.get("/api/profile/prefs/").content)["prefs"]
                self.assertEqual(got["work_mode"], "remote_first")
                self.assertEqual(got["preferred_regions"], ["Port of Spain"])
                self.assertIn("sources", tmp.read_text())
                bad = self.client.put("/api/profile/prefs/", data=json.dumps({"work_mode": "nope"}), content_type="application/json")
                self.assertEqual(bad.status_code, 400)
            shutil.rmtree(tmp.parent, ignore_errors=True)

    def test_match_requires_resume_then_explains(self):
        self.make_job("m1", title="Django Developer", region="", location="Remote", remote=True, work_mode="", fit_score=50,
                      description="Requirements\n- 3+ years of Python and Django\n- PostgreSQL experience\nOpen to candidates worldwide.")
        r = self.client.get("/api/jobs/m1/match/")
        self.assertEqual(r.status_code, 409)
        self.post("/api/profile/resume/", {"text": RESUME, "filename": "a.md"})
        r = self.client.get("/api/jobs/m1/match/")
        self.assertEqual(r.status_code, 200, r.content[:300])
        m = json.loads(r.content)["match"]
        self.assertGreater(m["fit"], 50)
        self.assertIn(m["verdict"], ("High", "Medium", "Low", "Long shot"))
        self.assertTrue(any(q["status"] == "met" for q in m["requirements"]))
        self.assertTrue(m["factors"])
        self.assertEqual(self.client.get("/api/jobs/ghost/match/").status_code, 404)

    def test_rescore_updates_job_rows_and_list_serialises_match(self):
        from jobs.models import Job
        self.post("/api/profile/resume/", {"text": RESUME, "filename": "a.md"})
        # the rescore thread/DB is the scanner db; put the job there too
        from src import db
        db.upsert_jobs([{"job_id": "r1", "source": "x", "title": "Python Django Developer", "company": "Acme", "url": "u", "remote": True,
                         "location": "Remote", "description": "Requirements\n- Python and Django\nWorldwide remote.", "fit_score": 40}])
        r = self.post("/api/rescore/", {"wait": True})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertGreaterEqual(json.loads(r.content)["rescored"], 1)
        row = db.get_job("r1")
        self.assertGreater(row["likelihood"], 0)
        self.assertEqual(row["work_mode"], "remote")
        self.assertTrue(json.loads(row["match_json"])["skills"]["matched"])
        st = json.loads(self.client.get("/api/rescore/").content)
        self.assertFalse(st["running"])

    def test_list_filters_by_mode_and_likelihood(self):
        self.make_job("l1", region="Port of Spain", work_mode="onsite", likelihood=60)
        self.make_job("r1", region="", location="Remote", remote=True, work_mode="remote", remote_scope="worldwide", likelihood=30)
        self.make_job("r2", region="", location="Remote", remote=True, work_mode="remote", remote_scope="us_only", likelihood=0)
        self.make_job("o1", region="", location="Berlin", work_mode="onsite", likelihood=1)
        ids = lambda q: sorted(j["job_id"] for j in json.loads(self.client.get("/api/jobs/" + q).content)["results"])  # noqa: E731
        self.assertEqual(ids("?mode=local"), ["l1"])
        self.assertEqual(ids("?mode=remote"), ["r1", "r2"])
        self.assertEqual(ids("?mode=onsite"), ["l1", "o1"])
        self.assertEqual(ids("?mode=abroad"), ["o1"])
        self.assertEqual(ids("?remote_scope=worldwide"), ["r1"])
        self.assertEqual(ids("?min_likelihood=25"), ["l1", "r1"])
        order = [j["job_id"] for j in json.loads(self.client.get("/api/jobs/?sort=likelihood").content)["results"]]
        self.assertEqual(order[:2], ["l1", "r1"])


class JobToolsTests(ScannerDBTestCase):
    """The per-job tabs (ATS, interview, salary, AI match, tailor, tech/needs) must come from the resume + posting, not canned text."""

    def setUp(self):
        from src import db, matching, profile_store
        c = db._conn()
        for t in ("resume_chunks", "resume_versions"):
            c.execute(f"DELETE FROM {t}")
        c.commit(); c.close()
        profile_store.invalidate(); matching.reset_context()
        p = mock.patch("src.retrieval.embedding_model", return_value="")
        p.start(); self.addCleanup(p.stop)
        self.client.post("/api/profile/resume/", data=json.dumps({"text": RESUME, "filename": "a.md"}), content_type="application/json")
        self.make_job("t1", title="Django Backend Engineer", company="Acme", region="", location="Remote", remote=True, work_mode="remote", fit_score=60,
                      description="Requirements\n- 3+ years building Django REST APIs and PostgreSQL pipelines\n- Experience with Kubernetes and Terraform\nRemote, open worldwide. Salary $90,000 - $110,000 per year.")
        self.make_job("t2", title="Accounts Clerk", company="Corp", region="Port of Spain", category="Finance & Accounting", location="Port of Spain, Trinidad & Tobago",
                      fit_score=30, description="Requirements\n- 2+ years of accounting and bookkeeping experience\n- Microsoft Excel")

    def get(self, job_id, tab):
        r = self.client.get(f"/api/jobs/{job_id}/{tab}/")
        self.assertEqual(r.status_code, 200, r.content[:300])
        return json.loads(r.content)

    def test_interview_is_specific_to_the_posting_and_resume(self):
        a, b = self.get("t1", "interview"), self.get("t2", "interview")
        qa, qb = " ".join(q["q"] for q in a["questions"]), " ".join(q["q"] for q in b["questions"])
        self.assertIn("Django", qa)
        self.assertIn("Kubernetes", qa)                       # a required skill missing from the resume gets its own honest question
        self.assertNotIn("Django", qb)
        self.assertNotEqual(qa, qb)
        self.assertTrue(any("50,000" in q["star"] for q in a["questions"]))   # STAR material is the user's own bullet
        self.assertIn("UTC-4", qa)                            # remote role -> time zone question
        self.assertNotIn("claims adjudication", qa + qb)      # nothing hard-coded about a particular person

    def test_ats_uses_the_real_resume_text(self):
        d = self.get("t1", "ats")
        self.assertIn("Django", d["have"])
        self.assertIn("Kubernetes", d["missing"])
        self.assertTrue(all("ok" in c for c in d["checks"]))
        self.assertGreater(d["breakdown"]["format"], 50)
        self.assertGreater(d["words"], 30)

    def test_tailor_leads_with_resume_bullets_and_refuses_to_invent(self):
        d = self.get("t1", "tailor")
        self.assertIn("Django REST APIs", d["lead_with"])
        self.assertTrue(any("Kubernetes" in i and "genuinely used" in i for i in d["injections"]))   # related (Docker), so: say so only if true
        self.assertIn("Acme", d["cover_open"])

    def test_ai_match_returns_evidence_passages(self):
        d = self.get("t1", "ai-match")
        self.assertGreater(d["score"], 30)
        self.assertEqual(d["method"], "bm25")
        self.assertTrue(d["passages"] and "passage" in d["passages"][0])
        self.assertIn("Django", d["top_terms"])

    def test_salary_with_and_without_pay(self):
        d = self.get("t1", "salary")
        self.assertTrue(d["has_salary"])
        self.assertEqual(d["currency"], "USD")
        self.assertEqual(d["monthly_usd_min"], 7500)
        n = self.get("t2", "salary")
        self.assertFalse(n["has_salary"])
        self.assertIn("peers", n)

    def test_tech_tab_marks_have_related_missing(self):
        d = json.loads(self.client.get("/api/jobs/t1/").content)["details"]
        st = {t["tech"]: t["status"] for lst in d["technologies_with_status"].values() for t in lst}
        self.assertEqual(st["Django"], "have")
        self.assertEqual(st["Kubernetes"], "related")   # Docker is on the resume
        self.assertEqual(st["Terraform"], "related")
        self.assertEqual(d["requirements"]["experience_raw"], "3+ years")

    def test_unknown_job_404_json(self):
        for tab in ("ats", "interview", "salary", "ai-match", "tailor"):
            r = self.client.get(f"/api/jobs/ghost/{tab}/")
            self.assertEqual(r.status_code, 404)
            self.assertIn("application/json", r["Content-Type"])

    def test_coach_brief_is_built_from_your_data(self):
        r = self.client.get("/api/coach/brief/")
        self.assertEqual(r.status_code, 200, r.content[:300])
        d = json.loads(r.content)
        self.assertEqual(d["source"], "rules")
        self.assertTrue(d["text"])
        self.assertNotIn("eval harness", d["text"])          # the old canned advice
        json.dumps(d)
