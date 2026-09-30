from unittest import mock

from rest_framework.test import APIClient

from candidate.tests import RESUME
from jobs.models import ApplicationStatus
from jobs.testutil import ScannerDBTestCase

DESC = """Senior Python Developer. We're a fast-paced family! You will wear many hats.
Requirements
- 3+ years of Python and Django
- PostgreSQL and Docker
Competitive salary. Contractors welcome."""


class AITests(ScannerDBTestCase):
    def setUp(self):
        self.c = APIClient()
        from src import profile_store
        profile_store.import_resume(RESUME.encode(), "jane.md", embed=False)
        self.j = self.make_job("a1", title="Senior Python Developer", description=DESC, region="", location="Remote", remote=True, category="Technology")
        self.make_job("a2", title="Python Backend Engineer", description=DESC.replace("Senior ", ""), region="", location="Remote", remote=True, category="Technology")
        self.make_job("a3", title="Payroll Clerk", description="Process payroll and invoices. 2 years accounting.", category="Finance & Accounting")

    def test_summary_flags_and_no_llm(self):
        with mock.patch("src.ai_features._ask_llm") as llm:
            r = self.c.get("/api/jobs/a1/summary/")
            llm.assert_not_called()          # nothing leaves the machine unless asked
        d = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertIn("Python", d["must_have"])
        self.assertTrue(any("many hats" in f["flag"] for f in d["red_flags"]))
        self.assertTrue(any("Contractors" in g for g in d["green_flags"]))
        self.assertEqual(d["provider"], "rules")

    def test_summary_with_ai_uses_llm(self):
        with mock.patch("src.ai_features._ask_llm", return_value=("A clear two sentence summary of the role and what it asks for.", "ollama")):
            d = self.c.post("/api/jobs/a1/summary/", {"ai": True}, format="json").json()
        self.assertEqual(d["provider"], "ollama")

    def test_unknown_job(self):
        self.assertEqual(self.c.get("/api/jobs/nope/summary/").status_code, 404)

    def test_rewrite_is_grounded(self):
        rules = self.c.post("/api/jobs/a1/rewrite/", {}, format="json").json()
        self.assertTrue(rules["bullets"])
        self.assertEqual(rules["provider"], "rules")
        orig = rules["bullets"][0]["original"]
        n = len(rules["bullets"])
        # a fabricated rewrite (adds a number and a tool) is rejected and the rules version kept
        fake = '[' + ",".join(['"%s Also led 40 engineers on Kubernetes."' % orig.rstrip(".")] * n) + ']'
        with mock.patch("src.ai_features._ask_llm", return_value=(fake, "ollama")):
            d = self.c.post("/api/jobs/a1/rewrite/", {"ai": True}, format="json").json()
        self.assertTrue(all(b["method"] == "rules" for b in d["bullets"]))
        self.assertTrue(any("rejected" in t for t in d["bullets"][0]["tips"]))
        from src import ai_features as ai
        self.assertFalse(ai.grounded("Built Django APIs for policies.", "Built Django APIs for 40 policies on Kubernetes."))
        self.assertTrue(ai.grounded("Built Django APIs for 50,000 policies.", "Delivered Django APIs for 50,000 policies."))

    def test_outreach_kinds_and_no_em_dash(self):
        for kind in ("follow_up", "thank_you", "recruiter_intro", "referral"):
            d = self.c.post("/api/jobs/a1/outreach/", {"kind": kind}, format="json").json()
            self.assertIn("Senior Python Developer", d["body"] + d["subject"])
            self.assertNotIn("—", d["body"])
        self.assertEqual(self.c.post("/api/jobs/a1/outreach/", {"kind": "x"}, format="json").status_code, 400)

    def test_interview_feedback(self):
        good = ("When our finance team at Acme had a reporting deadline I built a Django tool with n8n. My role was to cut the manual work, so I decided "
                "to automate the export and wrote the pipeline myself. It saved 100 hours a month and the team adopted it across three departments.")
        r = self.c.post("/api/jobs/a1/interview/feedback/", {"question": "Tell me about a time", "answer": good}, format="json").json()
        weak = self.c.post("/api/jobs/a1/interview/feedback/", {"question": "q", "answer": "I think we basically did stuff and it went well I guess."}, format="json").json()
        self.assertGreater(r["score"], weak["score"])
        self.assertTrue(weak["tips"])
        self.assertEqual(self.c.post("/api/jobs/a1/interview/feedback/", {"answer": "short"}, format="json").status_code, 400)

    def test_similar_and_recommendations(self):
        sim = self.c.get("/api/jobs/a1/similar/").json()["similar"]
        self.assertEqual(sim[0]["job_id"], "a2")                    # the near-duplicate, not the payroll clerk
        ApplicationStatus.objects.using("jobhunt").create(job_id="a1", status="Applied", updated_at="now")
        rec = self.c.get("/api/recommendations/").json()
        self.assertEqual(rec["basis"], "similar")
        self.assertEqual(rec["recommendations"][0]["job_id"], "a2")
        self.assertEqual(rec["recommendations"][0]["because"], "Senior Python Developer")

    def test_recommendations_without_signals_fall_back(self):
        self.assertEqual(self.c.get("/api/recommendations/").json()["basis"], "fit")

    def test_resume_review(self):
        d = self.c.get("/api/profile/review/").json()
        self.assertIn("score", d)
        self.assertTrue(d["wins"])

    def test_ask_parses_plain_english(self):
        p = self.c.post("/api/ai/ask/", {"q": "remote python roles worth applying"}, format="json").json()["params"]
        self.assertEqual((p["mode"], p["sort"], p["q"]), ("remote", "likelihood", "Python"))
        p = self.c.post("/api/ai/ask/", {"q": "finance jobs in Chaguanas closing soon"}, format="json").json()["params"]
        self.assertEqual((p["mode"], p["region"], p["closing"]), ("local", "Chaguanas / Caroni", "1"))
        self.assertEqual(self.c.post("/api/ai/ask/", {"q": " "}, format="json").status_code, 400)

    def test_roadmap(self):
        d = self.c.post("/api/ai/roadmap/", {"skill": "kubernetes", "jobs": 12, "sole_gap": 3}, format="json").json()
        self.assertEqual(d["skill"], "Kubernetes")
        self.assertIn("12", d["why"])
        self.assertTrue(d["steps"])
        self.assertEqual(self.c.post("/api/ai/roadmap/", {"skill": "zzz"}, format="json").status_code, 400)

    def test_status(self):
        self.assertIn("privacy", self.c.get("/api/ai/status/").json())

    def test_interview_summary_endpoint_and_voice_passthrough(self):
        ans = "When our finance team had a reporting deadline I built a Django tool. My goal was to cut manual work, so I decided to automate it. It saved 100 hours a month."
        voice = {"duration_sec": 30, "pace_wpm": 140, "pitch_mean_hz": 180, "pitch_stdev_hz": 35, "pause_ratio": 0.1, "long_pauses": 0, "volume_mean": 0.35, "volume_stdev": 0.08}
        r = self.c.post("/api/jobs/a1/interview/feedback/", {"question": "q", "answer": ans, "voice": voice}, format="json").json()
        self.assertIsNotNone(r["delivery"])
        s = self.c.post("/api/ai/interview/summary/", {"results": [dict(r, question="q")]}, format="json")
        self.assertEqual(s.status_code, 200)
        self.assertEqual(s.json()["n"], 1)
        self.assertEqual(self.c.post("/api/ai/interview/summary/", {"results": []}, format="json").status_code, 400)

    def test_interview_sessions_saved_listed_and_private_per_account(self):
        from django.contrib.auth.models import User
        ans = "When our finance team had a reporting deadline I built a Django tool. My goal was to cut manual work, so I decided to automate it. It saved 100 hours a month."
        r = dict(self.c.post("/api/jobs/a1/interview/feedback/", {"question": "q", "answer": ans}, format="json").json(), question="q", answer=ans)
        job = {"job_id": "a1", "title": "Senior Python Developer", "company": "Acme"}
        # not saved unless asked
        self.c.post("/api/ai/interview/summary/", {"results": [r]}, format="json")
        self.assertEqual(self.c.get("/api/ai/interview/sessions/").json()["sessions"], [])
        # guest save -> shows in the guest history
        sid = self.c.post("/api/ai/interview/summary/", {"results": [r], "save": True, "job": job}, format="json").json()["session_id"]
        rows = self.c.get("/api/ai/interview/sessions/").json()["sessions"]
        self.assertEqual([x["id"] for x in rows], [sid])
        self.assertEqual(rows[0]["job_title"], "Senior Python Developer")
        full = self.c.get(f"/api/ai/interview/sessions/{sid}/").json()
        self.assertEqual(full["results"][0]["answer"], ans)
        self.assertEqual(full["summary"]["n"], 1)
        # a signed-in account sees only its own, and can't open or delete the guest one
        u = User.objects.create_user(username="iv@example.com", password="correct-horse-battery-9")
        other = APIClient(); other.force_authenticate(u)
        self.assertEqual(other.get("/api/ai/interview/sessions/").json()["sessions"], [])
        self.assertEqual(other.get(f"/api/ai/interview/sessions/{sid}/").status_code, 404)
        self.assertEqual(other.delete(f"/api/ai/interview/sessions/{sid}/").status_code, 404)
        mine = other.post("/api/ai/interview/summary/", {"results": [r], "save": True, "job": job}, format="json").json()["session_id"]
        self.assertEqual([x["id"] for x in other.get("/api/ai/interview/sessions/").json()["sessions"]], [mine])
        self.assertEqual([x["id"] for x in self.c.get("/api/ai/interview/sessions/").json()["sessions"]], [sid])
        # delete
        self.assertEqual(self.c.delete(f"/api/ai/interview/sessions/{sid}/").status_code, 200)
        self.assertEqual(self.c.get("/api/ai/interview/sessions/").json()["sessions"], [])

    def test_interview_questions_endpoint_rules_and_ai(self):
        r = self.c.post("/api/jobs/a1/interview/questions/", {"n": 3}, format="json").json()
        self.assertEqual(r["provider"], "rules")
        self.assertTrue(1 <= len(r["questions"]) <= 3)
        with mock.patch("src.ai_features._ask_llm") as llm:
            self.c.post("/api/jobs/a1/interview/questions/", {"n": 3}, format="json")
            llm.assert_not_called()                      # no model unless asked
        reply = '{"questions":[{"q":"Walk me through your background.","why":"opener"},{"q":"Tell me about a Django project you shipped.","why":"b"},{"q":"How do you tune a slow PostgreSQL query?","why":"t"}]}'
        with mock.patch("src.ai_features._ask_llm", return_value=(reply, "ollama")):
            a = self.c.post("/api/jobs/a1/interview/questions/", {"n": 3, "ai": True, "persona": "tough"}, format="json").json()
        self.assertEqual(a["provider"], "ollama")
        self.assertEqual(len(a["questions"]), 3)
        self.assertEqual(self.c.post("/api/jobs/nope/interview/questions/", {}, format="json").status_code, 404)

    def test_feedback_persona_is_validated(self):
        ans = "We had a deadline and we built a tool and we shipped it together as a team, it went fine overall for everyone."
        r = self.c.post("/api/jobs/a1/interview/feedback/", {"question": "q", "answer": ans, "persona": "<script>"}, format="json")
        self.assertEqual(r.status_code, 200)       # unknown persona falls back to neutral, never errors

    def test_voice_status_reflects_whether_kokoro_is_installed(self):
        with mock.patch("src.voice._importable", return_value=False):
            d = self.c.get("/api/ai/voice/status/").json()
        self.assertFalse(d["available"])
        self.assertIsNone(d["backend"])
        self.assertEqual(d["voices"], [])
        self.assertIn("pip install kokoro-onnx", d["detail"])
        with mock.patch("src.voice.backend", return_value="onnx"):
            d = self.c.get("/api/ai/voice/status/").json()
        self.assertTrue(d["available"])
        self.assertIn({"id": "af_heart", "label": "Heart · American, warm"}, d["voices"])

    def test_speak_503s_with_json_when_kokoro_missing_not_a_500_html_page(self):
        with mock.patch("src.voice._importable", return_value=False):
            r = self.c.get("/api/ai/voice/speak/?text=Hello")
        self.assertEqual(r.status_code, 503)
        self.assertIn("application/json", r["Content-Type"])
        self.assertIn("kokoro", r.json()["error"].lower())

    def test_speak_requires_text(self):
        self.assertEqual(self.c.get("/api/ai/voice/speak/").status_code, 400)

    def test_speak_returns_audio_and_is_cached(self):
        with mock.patch("src.voice.synthesized_content_type", return_value=(b"fake-mp3-bytes", "audio/mpeg")) as m:
            r = self.c.get("/api/ai/voice/speak/?text=" + "Tell%20me%20about%20yourself")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "audio/mpeg")
        self.assertEqual(r.content, b"fake-mp3-bytes")
        self.assertIn("immutable", r["Cache-Control"])
        m.assert_called_once()
