"""Regression tests for trailing-slash + HTML-instead-of-JSON bugs + settings.

Bug 1: OperationalError no such table: django_session -> fixed via migrate
Bug 2: PUT /api/jobs/<id>/status (no slash) -> RuntimeError 500 HTML page
        -> frontend r.json() fails with: Unexpected token '<', "<!DOCTYPE "...
Bug 3: GET without trailing slash returns 301 HTML redirect.

These tests run WITHOUT real jobhunt.db data (use fake IDs) and verify
endpoints ALWAYS return JSON (never HTML), both with and without slash.
"""
import json
from django.test import TestCase
from core.settings_store import get_settings, update_settings, DEFAULT_UI


class TrailingSlashNoDbTests(TestCase):
    databases = {"default", "jobhunt"}
    def assertIsJSON(self, response, url):
        ct = response.get("Content-Type", "")
        self.assertIn(
            "application/json", ct,
            f"{url} returned Content-Type {ct!r} (likely HTML). "
            f"Body: {response.content[:200]!r}.",
        )

    def test_settings_both_slashes(self):
        for u in ["/api/settings/", "/api/settings"]:
            r = self.client.get(u, follow=True)
            self.assertEqual(r.status_code, 200, f"GET {u}")
            self.assertIsJSON(r, u)
            d = json.loads(r.content)
            self.assertIn("preferences", d)
            self.assertIn("sources", d)
            self.assertIn("links", d)

    def test_health_stats_json(self):
        for u in ["/health/", "/health", "/api/stats/", "/api/stats"]:
            r = self.client.get(u, follow=True)
            # stats may 500 if jobhunt.db missing tables in test DB, but must still be JSON
            self.assertIn(r.status_code, [200, 500], f"GET {u}")
            self.assertIsJSON(r, u)

    def test_put_status_fake_id_never_500_html(self):
        """PUT without slash on fake ID must be 404 JSON, never 500 RuntimeError HTML."""
        for u in ["/api/jobs/fake-id-123/status/", "/api/jobs/fake-id-123/status"]:
            r = self.client.put(
                u, data=json.dumps({"status": "New"}),
                content_type="application/json",
            )
            self.assertNotEqual(
                r.status_code, 500,
                f"PUT {u} returned 500 (RuntimeError APPEND_SLASH -> HTML).",
            )
            self.assertIsJSON(r, u)

    def test_job_detail_fake_id_json_404(self):
        for u in ["/api/jobs/fake-id-123/", "/api/jobs/fake-id-123"]:
            r = self.client.get(u, follow=True)
            # real DB: 404 JSON; empty test DB (no jobs table): 500 JSON — both must be JSON, never HTML
            self.assertIn(r.status_code, [404, 500], f"GET {u}")
            self.assertIsJSON(r, u)


class SettingsStoreTests(TestCase):
    databases = {"default", "jobhunt"}
    def test_get_settings_shape(self):
        s = get_settings()
        for key in ("preferences", "sources", "filters", "cover_letter",
                    "candidate", "search_terms", "targets", "links"):
            self.assertIn(key, s, f"missing {key}")
        for k in DEFAULT_UI:
            self.assertIn(k, s["preferences"], f"missing pref {k}")

    def test_update_preferences_roundtrip(self):
        orig = get_settings()["preferences"]
        try:
            s = update_settings({"preferences": {"show_remote": False, "show_links": False}})
            self.assertFalse(s["preferences"]["show_remote"])
            self.assertFalse(s["preferences"]["show_links"])
        finally:
            update_settings({"preferences": {"show_remote": orig["show_remote"],
                                             "show_links": orig["show_links"]}})

    def test_update_rejects_bad(self):
        with self.assertRaises(ValueError):
            update_settings({"preferences": {"nope": 1}})
        with self.assertRaises(ValueError):
            update_settings({"filters": {"min_score_to_include": 999}})
        with self.assertRaises(ValueError):
            update_settings({"cover_letter": {"provider": "nope"}})

    def test_put_settings_endpoint(self):
        r = self.client.put(
            "/api/settings/",
            data=json.dumps({"preferences": {"show_remote": True}}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/json", r.get("Content-Type", ""))


from jobs.testutil import ScannerDBTestCase  # noqa: E402


class StatePayloadTests(ScannerDBTestCase):
    """/api/state/ is loaded by every page and polled every 20s: keep it light, compressed and cacheable."""
    def test_state_leaves_out_descriptions_unless_asked(self):
        self.make_job("s1", title="Payroll Clerk", description="Long posting text " * 200)
        light = self.client.get("/api/state/").json()["jobs"][0]
        self.assertNotIn("description", light)
        self.assertEqual(light["title"], "Payroll Clerk")
        full = self.client.get("/api/state/?full=1").json()["jobs"][0]
        self.assertTrue(full["description"].startswith("Long posting text"))
        # the job dialog still gets the full text from the detail endpoint
        self.assertIn("Long posting text", self.client.get("/api/jobs/s1/").json()["job"]["description"])

    def test_state_is_gzipped_and_supports_304(self):
        self.make_job("s2", title="Analyst", description="x" * 5000)
        r = self.client.get("/api/state/", HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(r["Content-Encoding"], "gzip")
        etag = r["ETag"]
        again = self.client.get("/api/state/", HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(again.status_code, 304)
