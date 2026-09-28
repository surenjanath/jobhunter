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
        "/trinidad/": ("trinidad", "Trinidad", "trinidadCard", "trinidadBody"),
        "/settings/": ("settings", "Settings", "settingsCard", "settingsSave"),
    }
    OWN = {"sheetConditions", "jobsCard", "sheetPipeline", "analyticsCard", "resumeCard", "trinidadCard", "settingsCard"}

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
            self.assertEqual([l[0] for l in links], list(self.PAGES), url)           # all 7 pages, in order
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
