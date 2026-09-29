import json
from datetime import date

from django.test import TestCase

from analytics.station import build_brief
from core.models import StatusEvent


def _job(**kw):
    base = {
        "job_id": "j",
        "title": "Engineer",
        "company": "Acme",
        "fit_score": 60,
        "flags": "",
        "source": "ashby",
        "location": "Remote",
        "remote": True,
        "posted_at": "2026-09-20",
        "app_status": "New",
        "followup_date": "",
        "url": "https://example.com/job",
        "likelihood": {
            "likelihood": 60,
            "verdict": "Medium",
            "blockers": [],
            "gaps": [],
            "advice": "Tailor the resume.",
        },
    }
    base.update(kw)
    return base


class StationBriefTests(TestCase):
    def test_ranks_compare_and_hero_by_odds(self):
        jobs = [
            _job(job_id="low", company="Lab", title="ML", fit_score=70, flags="citizens only",
                 app_status="Applied", followup_date="2020-01-01", source="greenhouse",
                 likelihood={"likelihood": 40, "verdict": "Low", "blockers": ["citizens only"], "gaps": [], "advice": "Skip"}),
            _job(job_id="mid", company="Inato", title="Backend", fit_score=74, source="lever",
                 app_status="Shortlisted",
                 likelihood={"likelihood": 71, "verdict": "Medium", "blockers": [], "gaps": ["No formal LLM eval"], "advice": "Tailor"}),
            _job(job_id="hi", company="Sierra", title="Forward Deployed Engineer", fit_score=80,
                 likelihood={"likelihood": 82, "verdict": "High", "blockers": [], "gaps": ["No formal LLM eval"], "advice": "Apply this week"}),
        ]
        d = build_brief(jobs, letters=2, today=date(2026, 9, 27))
        self.assertFalse(d["empty"])
        self.assertEqual(d["hero"]["likelihood"], 82)
        self.assertEqual(d["hero"]["prior"], 71)
        self.assertEqual(d["hero"]["job"]["company"], "Sierra")
        self.assertEqual(d["hero"]["high_count"], 1)
        self.assertEqual([c["company"] for c in d["compare"]], ["Sierra", "Inato", "Lab"])
        self.assertEqual(d["warning"]["blocked"], 1)
        self.assertIn("LLM eval", d["warning"]["text"])
        self.assertEqual(d["pipeline"]["Applied"], 1)
        self.assertEqual(d["pipeline"]["Shortlisted"], 1)
        self.assertEqual(d["extended"]["due"], 1)
        self.assertEqual(d["extended"]["due_jobs"][0]["company"], "Lab")
        self.assertIn("Follow up with Lab", d["next_action"])
        self.assertEqual(d["conditions"][0]["value"], "3")
        self.assertEqual(d["conditions"][2]["value"], "80")

    def test_empty_scan_invites_a_run(self):
        d = build_brief([])
        self.assertTrue(d["empty"])
        self.assertTrue(d["warning"]["on"])
        self.assertIn("Run a scan", d["warning"]["text"])
        self.assertIsNone(d["hero"]["likelihood"])
        self.assertEqual(len(d["compare"]), 0)
        self.assertEqual(sum(d["pipeline"].values()), 0)

    def test_fit_score_fallback_when_odds_missing(self):
        d = build_brief([{"job_id": "x", "title": "Django", "company": "Local", "fit_score": 88, "flags": "", "source": "findworktt"}])
        self.assertEqual(d["hero"]["likelihood"], 88)
        self.assertEqual(d["hero"]["job"]["verdict"], "High")


class BriefEndpointTests(TestCase):
    databases = {"default", "jobhunt"}

    def test_brief_is_json(self):
        r = self.client.get("/api/brief/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/json", r["Content-Type"])
        d = json.loads(r.content)
        for key in ("conditions", "hero", "warning", "compare", "extended", "pipeline", "next_action"):
            self.assertIn(key, d)

    def test_brief_without_slash(self):
        r = self.client.get("/api/brief", follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/json", r["Content-Type"])

    def test_index_uses_station_layout(self):
        r = self.client.get("/")
        self.assertContains(r, "Cycle reports")
        self.assertContains(r, "Current conditions")
        self.assertContains(r, "Extended fit report")
        self.assertContains(r, 'href="/analytics/"')
        self.assertContains(r, 'id="live"')

    def test_scans_history_json(self):
        r = self.client.get("/api/scans/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/json", r["Content-Type"])
        self.assertIn("scans", json.loads(r.content))

    def test_cover_missing_job_is_json(self):
        r = self.client.post(
            "/api/cover/",
            data=json.dumps({"job_id": "missing-letter-job"}),
            content_type="application/json",
        )
        self.assertIn(r.status_code, [404, 500])
        self.assertIn("application/json", r["Content-Type"])


class ActivityTests(TestCase):
    databases = {"default", "jobhunt"}

    def tearDown(self):
        import sqlite3
        from pathlib import Path
        db = Path(__file__).resolve().parents[2] / "jobhunt" / "output" / "jobhunt.db"
        if not db.exists():
            return
        con = sqlite3.connect(db)
        con.execute("DELETE FROM app_status WHERE job_id=?", ("station-test-job",))
        con.commit()
        con.close()

    def test_activity_empty(self):
        r = self.client.get("/api/activity/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(json.loads(r.content)["events"], [])

    def test_status_write_records_event(self):
        r = self.client.put(
            "/api/jobs/station-test-job/status/",
            data=json.dumps({"status": "Shortlisted", "followup_date": "2026-10-01", "notes": "Sent note"}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(StatusEvent.objects.count(), 1)
        ev = StatusEvent.objects.get()
        self.assertEqual(ev.to_status, "Shortlisted")
        self.assertIn("2026-10-01", ev.note)
        listed = self.client.get("/api/activity", follow=True)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(json.loads(listed.content)["events"][0]["to_status"], "Shortlisted")


class GapAdviceTests(TestCase):
    """The Conditions page's 'next action' for the most common gap must be something the person can actually do."""
    def test_advice_depends_on_the_kind_of_gap(self):
        from analytics.station import gap_advice
        self.assertIn("add it to your resume", gap_advice("No Docker on your resume"))
        self.assertIn("learn next", gap_advice("No Docker on your resume"))
        self.assertIn("Profile", gap_advice("Asks for 7+ years; your resume shows 6.3"))
        self.assertIn("Settings", gap_advice("Title is outside your target roles"))
        self.assertNotIn("on the resume, then re-score", gap_advice("Title is outside your target roles"))
