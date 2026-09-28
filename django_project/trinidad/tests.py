import json
from datetime import date
from unittest import mock

from jobs.testutil import ScannerDBTestCase


class LocalMarketTests(ScannerDBTestCase):
    def setUp(self):
        self.make_job("a", company="RBC", region="Port of Spain", category="Finance & Accounting", fit_score=60)
        self.make_job("b", company="RBC", region="Chaguanas / Caroni", category="Sales & Marketing", source="caribbeanjobs")
        self.make_job("c", company="Remote Co", source="remotive", region="", category="")

    def test_local_summary(self):
        d = json.loads(self.client.get("/api/local/").content)
        self.assertEqual(d["total"], 2)
        self.assertEqual({r["region"] for r in d["by_region"]}, {"Port of Spain", "Chaguanas / Caroni"})
        self.assertEqual(d["top_employers"][0], {"company": "RBC", "count": 2, "best_fit": 60})
        self.assertEqual(d["relevant"], 1)
        self.assertEqual(d["new_today"], 2)

    def test_employers(self):
        d = json.loads(self.client.get("/api/local/employers/?q=rb").content)
        self.assertEqual(d["employers"][0]["company"], "RBC")
        self.assertEqual(d["employers"][0]["open_roles"], 2)


class SourceRegistryTests(ScannerDBTestCase):
    def test_registry_lists_every_builtin_board_with_health(self):
        from jobs.models import SourceRun
        SourceRun.objects.using("jobhunt").create(name="jobstt", label="JobsTT", ok=True, count=12, ms=900, ran_at="2026-09-27T10:00:00")
        SourceRun.objects.using("jobhunt").create(name="trinidadjob", label="TrinidadJob", ok=False, count=0, ms=50, error="HTTP 503", ran_at="2026-09-27T10:00:00")
        d = json.loads(self.client.get("/api/sources/").content)
        rows = {r["name"]: r for r in d["sources"]}
        for name in ("caribbeanjobs", "jobstt", "trinidadjob", "employtt", "findworktt", "islandjobhunt",
                     "caribbeanjobsonline", "evecaribbean", "digicel"):
            self.assertIn(name, rows)
        self.assertEqual(rows["jobstt"]["status"], "healthy")
        self.assertEqual(rows["trinidadjob"]["status"], "error")
        self.assertEqual(rows["trinidadjob"]["error"], "HTTP 503")
        self.assertEqual(rows["employtt"]["status"], "never run")
        self.assertEqual(d["summary"]["failing"], 1)

    def test_test_endpoint_runs_fetcher_without_saving(self):
        from src import trinidad as tt
        fake = [{"title": "T", "company": "C", "location": "L", "region": "R", "category": "X", "posted_at": "",
                 "expires_at": "", "salary": "", "url": "u", "source": "jobstt"}]
        with mock.patch.dict(tt.TT_SOURCES["jobstt"].__dict__, {"fn": lambda limit: fake}):
            r = self.client.post("/api/sources/jobstt/test/", data=json.dumps({"limit": 1}), content_type="application/json")
        d = json.loads(r.content)
        self.assertTrue(d["ok"])
        self.assertEqual(d["count"], 1)
        self.assertEqual(self.client.post("/api/sources/nope/test/").status_code, 404)

    def test_detect_falls_back_to_generic_scrape_when_no_known_ats(self):
        from src import ats_sources, trinidad as tt
        list_page = ('<html><body><a href="/careers/senior-accountant-123">Senior Accountant</a>'
                    '<a href="/careers/warehouse-lead-456">Warehouse Lead</a></body></html>')
        detail = "<html><body>plain prose, no structured data</body></html>"

        def fake_fetch(u, p=None, **k):
            return list_page if u == "https://acme.tt/careers" else detail

        with mock.patch.object(ats_sources, "detect", return_value=[]), mock.patch.object(tt, "fetch", side_effect=fake_fetch):
            r = self.client.post("/api/sources/detect/", data=json.dumps({"url": "https://acme.tt/careers"}), content_type="application/json")
        d = json.loads(r.content)
        self.assertEqual(d["candidates"], [])
        self.assertTrue(d["generic"]["ok"])
        self.assertEqual(d["generic"]["count"], 2)
        self.assertIn("Senior Accountant", d["generic"]["sample"])
        self.assertEqual(d["hint"], "")

    def test_detect_generic_fallback_reports_nothing_found(self):
        from src import ats_sources, trinidad as tt
        with mock.patch.object(ats_sources, "detect", return_value=[]), mock.patch.object(tt, "fetch", return_value="<html><body>no links here</body></html>"):
            r = self.client.post("/api/sources/detect/", data=json.dumps({"url": "https://acme.tt/"}), content_type="application/json")
        d = json.loads(r.content)
        self.assertFalse(d["generic"]["ok"])
        self.assertTrue(d["hint"])

    def test_custom_site_validation(self):
        def post(body):
            return self.client.post("/api/sources/custom/test/", data=json.dumps(body), content_type="application/json")
        self.assertEqual(post({"name": "x"}).status_code, 400)                                  # bad name
        self.assertEqual(post({"name": "acme"}).status_code, 400)                               # no sitemap/list_url
        self.assertEqual(post({"name": "acme", "sitemap": "ftp://x"}).status_code, 400)         # not http(s)
        self.assertEqual(post({"name": "jobstt", "sitemap": "https://x.tt/s.xml"}).status_code, 400)  # built-in name
        self.assertEqual(post({"name": "acme", "sitemap": "https://x.tt/s.xml", "url_pattern": "("}).status_code, 400)  # bad regex
