import re

from django.test import TestCase


class PageRouteTests(TestCase):
    """Every screen is its own URL and template; the nav marks the current one; a page holds only its own content."""
    databases = {"default", "jobhunt"}
    PAGES = {
        "/": ("home", "Conditions", "sheetConditions", "todayBlock"),
        "/ledger/": ("jobs", "Ledger", "jobsCard", "tableWrap"),
        "/pipeline/": ("pipeline", "Pipeline", "sheetPipeline", "pipelineBody"),
        "/analytics/": ("analytics", "Analytics", "analyticsCard", "anRoot"),
        "/profile/": ("profile", "Profile", "resumeCard", "resumeBody"),
        "/interview/": ("interview", "Interview", "interviewCard", "ivBody"),
        "/trinidad/": ("trinidad", "Trinidad", "trinidadCard", "trinidadBody"),
        "/settings/": ("settings", "Settings", "settingsCard", "settingsSave"),
    }
    OWN = {"sheetConditions", "jobsCard", "sheetPipeline", "analyticsCard", "resumeCard", "interviewCard", "trinidadCard", "settingsCard"}

    def test_each_page_renders_with_its_own_content_only(self):
        for url, (key, label, section, marker) in self.PAGES.items():
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            html = r.content.decode()
            self.assertIn(f"<title>{label} · JobHunter</title>", html, url)
            self.assertIn(f'<body data-page="{key}">', html, url)
            self.assertIn(f'id="{section}"', html, url)
            self.assertIn(f'id="{marker}"', html, url)
            present = {s for s in self.OWN if f'id="{s}"' in html}
            self.assertEqual(present, {section}, f"{url} contains other pages' sections: {present}")

    def test_nav_links_are_real_urls_and_current_page_is_marked(self):
        for url, (key, label, *_rest) in self.PAGES.items():
            html = self.client.get(url).content.decode()
            links = re.findall(r'<a href="([^"]+)"( class="active" aria-current="page")?>([^<]+)</a>', html.split('id="mainNav"')[1].split("</nav>")[0])
            self.assertEqual([l[0] for l in links], list(self.PAGES), url)           # all 8 pages, in order
            self.assertEqual([l[2].strip() for l in links if l[1]], [label], url)     # exactly the current one is active
            self.assertNotIn('href="#"', html.split('id="mainNav"')[1].split("</nav>")[0])

    def test_shell_pieces_present_on_every_page_but_page_tools_only_where_used(self):
        for url in self.PAGES:
            html = self.client.get(url).content.decode()
            for needed in ('id="bScan"', 'id="jobDlg"', 'id="palDlg"', "window.URLS=", "js/core.js", "js/boot.js"):
                self.assertIn(needed, html, f"{url} missing {needed}")
        self.assertIn('id="bulkBar"', self.client.get("/ledger/").content.decode())
        self.assertNotIn('id="bulkBar"', self.client.get("/analytics/").content.decode())
        self.assertIn('id="warnRail"', self.client.get("/").content.decode())
        self.assertNotIn('id="warnRail"', self.client.get("/ledger/").content.decode())

    def test_only_the_pages_own_script_is_loaded(self):
        html = self.client.get("/analytics/").content.decode()
        self.assertIn("js/analytics.js", html)
        for other in ("js/ledger.js", "js/home.js", "js/profile.js", "js/settings.js", "js/pipeline.js", "js/trinidad.js"):
            self.assertNotIn(other, html)

    def test_api_paths_are_untouched_by_page_routes(self):
        for u in ("/api/profile/", "/api/settings/", "/health/"):
            self.assertIn("application/json", self.client.get(u)["Content-Type"])


class VoiceCueContractTests(TestCase):
    """Every cue the browser's startMetrics() emits must have a merge rule in interview.js's mergeVoice(), or it is
    silently dropped whenever an answer has a follow-up (this happened: the nerves never reached the server)."""
    def test_every_emitted_voice_cue_has_a_merge_rule(self):
        from pathlib import Path
        js = Path(__file__).resolve().parent.parent / "static" / "js"
        ai, iv = (js / "ai.js").read_text(), (js / "interview.js").read_text()
        emitted = set(re.findall(r"(?:\bv|\bout)\.([a-z_]+)=", ai))
        for block in re.findall(r"const v=\{([^}]*)\}", ai):
            emitted |= set(re.findall(r"([a-z_]+):", block))
        merge = iv[iv.index("const MERGE="):iv.index("function mergeVoice")]
        ruled = set(re.findall(r"'([a-z_]+)'", merge))
        self.assertGreater(len(emitted), 10)
        self.assertEqual(emitted - ruled, set())


class ApiNotFoundTests(TestCase):
    def test_unknown_api_path_is_json_404(self):
        r = self.client.get("/api/definitely-not-a-thing/")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r["Content-Type"], "application/json")
        self.assertIn("no such API endpoint", r.json()["error"])

    def test_pages_have_an_icon(self):
        self.assertIn('rel="icon"', self.client.get("/ledger/").content.decode())


class SiteAccessTests(TestCase):
    """The Settings page's 'Allow new accounts' / 'Require sign-in' switches, and who may flip them."""
    def setUp(self):
        from django.core.cache import cache
        from core import site
        cache.clear()
        site.invalidate()

    def tearDown(self):
        from core import site
        site.invalidate()

    def _client(self, email=None, staff=False):
        from django.contrib.auth.models import User
        from rest_framework.test import APIClient
        c = APIClient()
        if email:
            u = User.objects.create_user(username=email, email=email, password="correct-horse-battery-9", is_staff=staff)
            c.force_authenticate(u)
            c.force_login(u)
        return c

    def test_defaults_are_open_locally(self):
        d = self._client().get("/api/site/").json()
        self.assertTrue(d["allow_signup"])
        self.assertFalse(d["require_signin"])
        self.assertTrue(d["can_edit"])          # no admin yet: a fresh local copy can be set up

    def test_guest_cannot_lock_the_site(self):
        r = self._client().put("/api/site/", {"require_signin": True}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("sign in first", r.json()["error"])

    def test_first_signed_in_editor_becomes_admin_and_others_are_locked_out(self):
        from django.contrib.auth.models import User
        me = self._client("me@example.com")
        self.assertEqual(me.put("/api/site/", {"allow_signup": False}, format="json").status_code, 200)
        self.assertTrue(User.objects.get(username="me@example.com").is_staff)
        other = self._client("other@example.com")
        self.assertEqual(other.put("/api/site/", {"allow_signup": True}, format="json").status_code, 403)
        self.assertFalse(other.get("/api/site/").json()["can_edit"])
        # and sign-ups really are off
        from rest_framework.test import APIClient
        r = APIClient().post("/api/auth/register/", {"email": "new@example.com", "password": "correct-horse-battery-9"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_require_signin_locks_pages_and_api_but_not_sign_in(self):
        admin = self._client("admin@example.com", staff=True)
        admin.put("/api/site/", {"require_signin": True}, format="json")
        guest = self.client
        r = guest.get("/ledger/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/login/?next=/ledger/"))
        self.assertEqual(guest.get("/api/state/").status_code, 401)
        self.assertEqual(guest.get("/login/").status_code, 200)
        self.assertEqual(guest.get("/health/").status_code, 200)
        self.assertEqual(guest.get("/api/auth/me/").json()["private"], True)
        # signing in gets you in
        ok = guest.post("/api/auth/login/", {"email": "admin@example.com", "password": "correct-horse-battery-9"}, content_type="application/json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(guest.get("/ledger/").status_code, 200)

    def test_login_page_only_redirects_within_the_site(self):
        html = self.client.get("/login/?next=//evil.example.com/").content.decode()
        self.assertIn("const next='/'", html)
