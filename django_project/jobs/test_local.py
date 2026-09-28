import json
from datetime import date, timedelta

from .testutil import ScannerDBTestCase

iso = lambda n: (date.today() + timedelta(days=n)).isoformat()  # noqa: E731


class JobFilterTests(ScannerDBTestCase):
    def setUp(self):
        self.make_job("a", title="Django Developer", region="Port of Spain", category="Technology", fit_score=80, expires_at=iso(2))
        self.make_job("b", title="Accountant", region="San Fernando", category="Finance & Accounting", fit_score=20, salary="TT$9,000", expires_at=iso(30))
        self.make_job("c", title="Remote Python", source="remotive", region="", category="", location="Remote", remote=True, fit_score=70, expires_at="")
        self.make_job("d", title="Expired Clerk", region="Arima / Sangre Grande", category="Admin & Clerical", fit_score=10, expires_at=iso(-3))

    def get(self, qs=""):
        r = self.client.get("/api/jobs/" + qs)
        self.assertEqual(r.status_code, 200, r.content[:200])
        return json.loads(r.content)

    def ids(self, qs=""):
        return [j["job_id"] for j in self.get(qs)["results"]]

    def test_local_flag_and_region(self):
        self.assertEqual(sorted(self.ids("?local=1")), ["a", "b", "d"])
        self.assertEqual(self.ids("?local=0"), ["c"])
        self.assertEqual(self.ids("?region=San+Fernando"), ["b"])
        self.assertEqual(sorted(self.ids("?region=San+Fernando,Port+of+Spain")), ["a", "b"])

    def test_category_search_salary(self):
        self.assertEqual(self.ids("?category=Technology"), ["a"])
        self.assertEqual(self.ids("?search=django+port"), ["a"])   # every word must match
        self.assertEqual(self.ids("?has_salary=1"), ["b"])

    def test_closing_within_and_sort(self):
        self.assertEqual(self.ids("?closing_within=7"), ["a"])
        order = self.ids("?sort=closing&local=1")
        self.assertEqual(order[0], "d")           # expired first (earliest date)
        self.assertEqual(self.ids("?sort=closing")[-1], "c")  # no expiry goes last

    def test_page_size_and_days_left(self):
        d = self.get("?page_size=2")
        self.assertEqual(len(d["results"]), 2)
        self.assertEqual(d["count"], 4)
        job = next(j for j in self.get()["results"] if j["job_id"] == "a")
        self.assertEqual(job["days_left"], 2)
        self.assertEqual(job["region"], "Port of Spain")

    def test_stats_counts_local(self):
        d = json.loads(self.client.get("/api/stats/").content)
        self.assertEqual(d["total"], 4)
        self.assertEqual(d["local"], 3)
        self.assertEqual(d["remote"], 1)

    def test_export_csv(self):
        r = self.client.get("/api/jobs/export/?local=1&sort=fit")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])
        body = r.content.decode()
        self.assertTrue(body.startswith("fit_score,tier,title"))
        self.assertIn("Django Developer", body)
        self.assertNotIn("Remote Python", body)


class TrackingTests(ScannerDBTestCase):
    def setUp(self):
        self.make_job("a", title="One", expires_at=iso(3))
        self.make_job("b", title="Two", expires_at=iso(3))

    def post(self, url, body):
        return self.client.post(url, data=json.dumps(body), content_type="application/json")

    def test_star_toggle_and_filter(self):
        r = json.loads(self.post("/api/jobs/a/star/", {}).content)
        self.assertTrue(r["starred"])
        listed = json.loads(self.client.get("/api/jobs/?starred=1").content)["results"]
        self.assertEqual([j["job_id"] for j in listed], ["a"])
        self.assertTrue(listed[0]["starred"])
        r = json.loads(self.post("/api/jobs/a/star", {}).content)   # no trailing slash works too
        self.assertFalse(r["starred"])
        self.assertEqual(self.post("/api/jobs/nope/star/", {}).status_code, 404)

    def test_bulk_status_and_pipeline(self):
        r = json.loads(self.post("/api/jobs/bulk-status/", {"job_ids": ["a", "b", "ghost"], "status": "Applied"}).content)
        self.assertEqual(r["updated"], 2)
        p = json.loads(self.client.get("/api/pipeline/").content)
        self.assertEqual(next(s["count"] for s in p["stages"] if s["status"] == "Applied"), 2)
        self.assertEqual(p["applied"], 2)
        by = json.loads(self.client.get("/api/jobs/?status=Applied").content)["results"]
        self.assertEqual(sorted(j["job_id"] for j in by), ["a", "b"])
        self.assertEqual(self.post("/api/jobs/bulk-status/", {"job_ids": [], "status": "x"}).status_code, 400)

    def test_followups_and_closing_soon(self):
        from jobs.models import ApplicationStatus
        ApplicationStatus.objects.using("jobhunt").create(job_id="a", status="Applied", followup_date=iso(-2), updated_at="n")
        self.post("/api/jobs/b/star/", {"starred": True})
        d = json.loads(self.client.get("/api/followups/").content)
        self.assertEqual([j["job_id"] for j in d["overdue"]], ["a"])
        self.assertEqual(sorted(j["job_id"] for j in d["closing_soon"]), ["a", "b"])  # tracked + starred, both close in 3d
        self.assertEqual(d["counts"]["overdue"], 1)


class CalendarAndDigestTests(ScannerDBTestCase):
    def setUp(self):
        from jobs.models import ApplicationStatus
        self.make_job("c1", title="Tracked, Role; One", company="Acme", expires_at=iso(5), first_seen=iso(0), fit_score=70, likelihood=50,
                      match_json=json.dumps({"verdict": "Medium", "advice": "Apply", "skills": {"matched": [{"name": "Python"}], "missing_required": ["Go"]}, "blockers": []}))
        self.make_job("c2", title="Untracked", expires_at=iso(6), first_seen=iso(0), fit_score=80)
        self.make_job("c3", title="Blocked", first_seen=iso(0), fit_score=75, match_json=json.dumps({"blockers": ["US only"], "skills": {}}))
        self.make_job("c4", title="Old", first_seen=iso(-30), fit_score=90)
        self.make_job("c5", title="Low fit", first_seen=iso(0), fit_score=20)
        ApplicationStatus.objects.using("jobhunt").create(job_id="c1", status="Applied", followup_date=iso(2), updated_at="n")

    def test_ics_has_followup_and_closing_for_tracked_only(self):
        r = self.client.get("/api/calendar.ics")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/calendar", r["Content-Type"])
        body = r.content.decode()
        self.assertTrue(body.startswith("BEGIN:VCALENDAR"))
        self.assertIn("SUMMARY:Follow up: Tracked\\, Role\\; One @ Acme", body)   # commas/semicolons escaped
        self.assertIn(f"DTSTART;VALUE=DATE:{iso(5).replace('-', '')}", body)
        self.assertNotIn("Untracked", body)               # not tracked: no closing reminder
        self.assertEqual(body.count("BEGIN:VEVENT"), 2)

    def test_digest_ranks_new_and_separates_blocked(self):
        d = json.loads(self.client.get("/api/digest/?days=1&min_fit=50").content)
        titles = [p["title"] for p in d["picks"]]
        self.assertIn("Untracked", titles)
        self.assertNotIn("Tracked, Role; One", titles)    # already applied to: not a suggestion
        self.assertNotIn("Old", titles)
        self.assertNotIn("Low fit", titles)
        self.assertEqual([b["title"] for b in d["blocked"]], ["Blocked"])
        md = self.client.get("/api/digest/?days=1&fmt=md").content.decode()
        self.assertIn("# Job digest", md)
        self.assertIn("good fit, but blocked", md.lower())
        self.assertEqual(self.client.get("/api/digest/?days=x").status_code, 400)
