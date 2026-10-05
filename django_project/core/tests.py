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


from jobs.testutil import ScannerDBTestCase  # noqa: E402


class TailoredResumeTests(ScannerDBTestCase):
    def setUp(self):
        from candidate.tests import RESUME
        from src import profile_store
        self.resume = RESUME
        profile_store.import_resume(RESUME.encode(), "jane.md", embed=False)
        self.make_job("tr1", title="Senior Python Developer", company="Initech",
                      description="Requirements\n- 3+ years Python and Django\n- Docker and AWS\n- n8n automation")

    def test_only_reorders_and_selects_never_invents(self):
        from src import profile_store, tailored_resume
        from ai.views import _job, as_dict
        r = tailored_resume.build(as_dict(_job("tr1")))
        prof = profile_store.active_profile()
        originals = {b for role in prof["roles"] for b in role["bullets"]}
        self.assertTrue(r["roles"] and r["roles"][0]["bullets"])
        for role in r["roles"]:
            for b in role["bullets"]:
                self.assertIn(b, originals)                       # word for word from the resume
        self.assertEqual(r["summary"], prof.get("summary") or "")
        self.assertLessEqual(set(r["skills"]), set(prof["skills"]))   # no skill you don't have
        self.assertEqual(r["skills"][: len(r["skills_matched"])], r["skills_matched"])   # posting's skills first
        self.assertIn("Django", r["skills_matched"])

    def test_page_and_downloads(self):
        page = self.client.get("/resume/tr1/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Tailored for")
        txt = self.client.get("/api/jobs/tr1/resume.txt")
        self.assertEqual(txt.status_code, 200)
        self.assertIn("attachment;", txt["Content-Disposition"])
        body = txt.content.decode()
        self.assertIn("EXPERIENCE", body)
        self.assertNotIn("**", body)
        md = self.client.get("/api/jobs/tr1/resume.md").content.decode()
        self.assertIn("## Experience", md)
        self.assertEqual(self.client.get("/resume/nope/").status_code, 404)

    def test_no_resume_says_so(self):
        from src import profile_store, tailored_resume
        from unittest import mock
        with mock.patch("src.matching.current_context", return_value=None):
            self.assertIn("error", tailored_resume.build({"title": "x"}))


class AlertTests(ScannerDBTestCase):
    def setUp(self):
        from datetime import date, timedelta
        from candidate.tests import RESUME
        from src import profile_store
        profile_store.import_resume(RESUME.encode(), "jane.md", embed=False)
        today = date.today()
        self.make_job("al1", title="Senior Python Developer", company="Initech", fit_score=80, likelihood=60,
                      description="Python Django PostgreSQL Docker AWS", region="", location="Remote", remote=True, first_seen=today.isoformat())
        self.make_job("al2", title="Analyst", company="Globex", fit_score=60, expires_at=(today + timedelta(days=2)).isoformat())
        self.client.post("/api/jobs/bulk-status/", {"job_ids": ["al2"], "status": "Applied"}, content_type="application/json")

    def test_compose_is_empty_when_nothing_to_say(self):
        from src import alerts
        self.assertIsNone(alerts.compose([], [], []))
        m = alerts.compose([{"title": "Dev", "company": "X", "fit": 70, "verdict": "High", "where": "Remote", "url": "https://x/y"}],
                           [{"title": "A", "company": "B", "followup_date": "2026-01-01"}], [], "https://me.onrender.com/")
        self.assertEqual(m["subject"], "JobHunter: 1 new role, 1 follow-up due")
        self.assertIn("FOLLOW UP TODAY", m["text"])
        self.assertIn("https://me.onrender.com/", m["text"])

    def test_nothing_is_sent_without_a_channel(self):
        from unittest import mock
        from core import alerts_service
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch("src.alerts.send") as send:
            out = alerts_service.run(None)
        send.assert_not_called()
        self.assertIn("no alert channel", out.get("reason", ""))

    def test_sends_once_per_job_and_includes_closing_tracked_roles(self):
        from unittest import mock
        from core import alerts_service
        from core.models import AlertSent
        env = {"JOBHUNTER_TELEGRAM_TOKEN": "t", "JOBHUNTER_TELEGRAM_CHAT_ID": "1"}
        with mock.patch.dict("os.environ", env), mock.patch("src.alerts.send", return_value={"telegram": "sent"}) as send:
            first = alerts_service.run(None)
            msg = send.call_args[0][0]
            second = alerts_service.run(None)
        self.assertTrue(first["sent"])
        self.assertIn("Initech", msg["text"])
        self.assertIn("CLOSING SOON", msg["text"])            # the applied role that closes in 2 days
        self.assertIn("al1", set(AlertSent.objects.values_list("job_id", flat=True)))
        self.assertEqual(second["counts"]["picks"], 0)         # never announced twice

    def test_api_needs_admin_to_send(self):
        from django.contrib.auth.models import User
        from rest_framework.test import APIClient
        from unittest import mock
        User.objects.create_user(username="boss@example.com", password="correct-horse-battery-9", is_staff=True)
        guest = APIClient()
        self.assertIn("channels", guest.get("/api/alerts/").json())
        with mock.patch.dict("os.environ", {"JOBHUNTER_TELEGRAM_TOKEN": "t", "JOBHUNTER_TELEGRAM_CHAT_ID": "1"}):
            self.assertEqual(guest.post("/api/alerts/", {"action": "test"}, format="json").status_code, 403)


class HealthProbeTests(TestCase):
    """A platform's internal probe (odd Host header, plain HTTP) must get 200, even with production settings."""
    def test_health_ignores_host_and_https_redirect(self):
        from django.test import override_settings
        with override_settings(ALLOWED_HOSTS=["jobhunter.onrender.com"], SECURE_SSL_REDIRECT=True, DEBUG=False):
            r = self.client.get("/health/", HTTP_HOST="10.201.3.7:10000")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["ok"])
            self.assertEqual(self.client.get("/ledger/", HTTP_HOST="10.201.3.7:10000").status_code, 400)   # everything else still checked


class ResumeJsonTests(TailoredResumeTests):
    def test_resume_json_for_the_apply_tab(self):
        d = self.client.get("/api/jobs/tr1/resume.json").json()
        self.assertIn("Django", d["skills_matched"])
        self.assertIn("missing_required", d["notes"])


class JobImportTests(ScannerDBTestCase):
    LD_PAGE = ('<html><head><title>x</title><script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",'
               '"title":"Senior Python Developer","hiringOrganization":{"@type":"Organization","name":"Initech"},'
               '"jobLocation":{"@type":"Place","address":{"addressLocality":"Port of Spain","addressCountry":"TT"}},'
               '"description":"<p>Build Django REST APIs with PostgreSQL and Docker. 3+ years Python.</p>","datePosted":"2026-09-20"}</script></head></html>')

    def setUp(self):
        from candidate.tests import RESUME
        from src import profile_store
        profile_store.import_resume(RESUME.encode(), "jane.md", embed=False)

    def test_parse_jobposting_and_private_addresses_blocked(self):
        from src import job_import as ji
        f = ji.parse_page(self.LD_PAGE, "https://jobs.example.com/1")
        self.assertEqual((f["title"], f["company"]), ("Senior Python Developer", "Initech"))
        self.assertIn("Port of Spain", f["location"])
        self.assertIn("Django REST APIs", f["description"])
        for bad in ("http://127.0.0.1:8000/api/state/", "http://localhost/", "http://192.168.1.1/", "file:///etc/passwd", "http://169.254.169.254/latest/"):
            self.assertIn("error", ji.fetch(bad), bad)

    def test_preview_from_link_and_from_the_browser_button(self):
        from unittest import mock
        from src import job_import as ji
        fake = mock.Mock(status_code=200, text=self.LD_PAGE, url="https://jobs.example.com/1")
        with mock.patch.object(ji, "_public_url", return_value=True), mock.patch("requests.get", return_value=fake):
            r = self.client.post("/api/jobs/import/", {"url": "https://jobs.example.com/1", "preview": True}, content_type="application/json").json()
        self.assertEqual(r["company"], "Initech")
        ld = self.LD_PAGE.split('ld+json">')[1].split("</script>")[0]
        b = self.client.post("/api/jobs/import/", {"preview": True, "ld_json": ld, "url": "https://www.linkedin.com/jobs/view/1"}, content_type="application/json").json()
        self.assertEqual(b["title"], "Senior Python Developer")

    def test_save_scores_it_and_it_shows_in_the_ledger(self):
        bad = self.client.post("/api/jobs/import/", {"title": "Dev", "description": "short"}, content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        body = {"title": "Senior Python Developer", "company": "Initech", "location": "Port of Spain, Trinidad",
                "url": "https://www.linkedin.com/jobs/view/123", "description": "We need a backend engineer to build Django REST APIs with PostgreSQL "
                "and Docker on AWS. 3+ years of Python. You'll automate reporting pipelines and work with our insurance team."}
        r = self.client.post("/api/jobs/import/", body, content_type="application/json")
        self.assertEqual(r.status_code, 201)
        d = r.json()
        self.assertTrue(d["job_id"].startswith("manual:"))
        self.assertGreater(d["fit_score"], 40)
        again = self.client.post("/api/jobs/import/", body, content_type="application/json").json()
        self.assertEqual(again["job_id"], d["job_id"])        # same link -> same job, not a duplicate
        from src import db   # imports write through the scanner's own module (in tests: its throwaway database)
        c = db._conn()
        row = c.execute("SELECT source, company, fit_score FROM jobs WHERE job_id=?", (d["job_id"],)).fetchone()
        c.close()
        self.assertEqual((row[0], row[1]), ("manual", "Initech"))
        self.assertEqual(self.client.get("/add-job/").status_code, 200)


class LLMProviderTests(TestCase):
    """Settings → AI providers: keys are write-only, only an editor may change them, and a custom endpoint really gets called."""
    databases = {"default", "jobhunt"}

    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from core import settings_store
        from src import llm
        tmp = Path(tempfile.mkdtemp())
        (tmp / "profile.yaml").write_text("cover_letter:\n  provider: auto\n")
        for target, name, value in ((settings_store, "PROFILE", tmp / "profile.yaml"), (llm, "PROFILE_FILE", tmp / "profile.yaml"),
                                    (llm, "KEYS_FILE", tmp / "llm_keys.json"), (llm, "USAGE_FILE", tmp / "llm_usage.json")):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict("os.environ", {k: "" for k in list(llm.KEY_ENV.values()) + ["LLM_BASE_URL", "LLM_MODEL"]})
        env.start()
        self.addCleanup(env.stop)
        self.tmp, self.llm = tmp, llm

    def put(self, body):
        return self.client.put("/api/llm/", body, content_type="application/json")

    def row(self, data, name):
        return next(p for p in data["providers"] if p["name"] == name)

    def test_key_is_saved_but_never_returned(self):
        r = self.put({"provider": "openai", "providers": {"openai": {"api_key": "sk-test-1234567890abcd", "model": "gpt-x"}}})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        o = self.row(d, "openai")
        self.assertTrue(o["available"] and o["has_key"])
        self.assertEqual((o["key_source"], o["key_hint"], o["model"], d["provider"], d["active"]), ("saved", "abcd", "gpt-x", "openai", "openai"))
        self.assertNotIn("sk-test-1234567890abcd", r.content.decode())
        self.assertNotIn("sk-test", self.client.get("/api/settings/").content.decode())
        self.assertNotIn("sk-test", (self.tmp / "profile.yaml").read_text())          # keys stay out of the profile
        self.assertEqual(self.llm.api_key("openai"), ("sk-test-1234567890abcd", "saved"))
        self.assertEqual((self.tmp / "llm_keys.json").stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.row(self.put({"providers": {"openai": {"api_key": ""}}}).json(), "openai")["has_key"])

    def test_bad_input_is_refused(self):
        self.assertEqual(self.put({"provider": "skynet"}).status_code, 400)
        self.assertEqual(self.put({"providers": {"custom": {"base_url": "file:///etc/passwd"}}}).status_code, 400)
        self.assertEqual(self.put({"providers": {"openai": {"base_url": "http://evil.example"}}}).status_code, 400)
        self.assertEqual(self.put({"providers": {"ollama": {"api_key": "x"}}}).status_code, 400)

    def test_only_an_admin_may_change_or_test_once_one_exists(self):
        from django.contrib.auth.models import User
        User.objects.create_user("boss", "boss@example.com", "pw-12345678", is_staff=True)
        self.assertEqual(self.put({"provider": "openai"}).status_code, 403)
        self.assertEqual(self.client.post("/api/llm/test/", {"provider": "openai"}, content_type="application/json").status_code, 403)
        d = self.client.get("/api/llm/").json()
        self.assertFalse(d["can_edit"])
        self.assertEqual(self.row(d, "openai")["key_hint"], "")

    def test_custom_endpoint_is_called_tested_and_listed(self):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        seen = {}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body):
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._send({"data": [{"id": "big-model"}, {"id": "small-model"}]})

            def do_POST(self):
                seen["auth"] = self.headers.get("Authorization")
                seen["path"] = self.path
                seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self._send({"choices": [{"message": {"content": "<think>hmm</think>ready"}}],
                            "usage": {"prompt_tokens": 7, "completion_tokens": 3}})

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        base = f"http://127.0.0.1:{srv.server_port}/v1"
        d = self.put({"provider": "custom", "providers": {"custom": {"base_url": base + "/chat/completions/", "model": "small-model",
                                                                    "api_key": "local-key-000000001"}}}).json()
        c = self.row(d, "custom")
        self.assertEqual((c["base_url"], c["available"], c["privacy"], d["active"]), (base, True, "stays on this machine", "custom"))
        t = self.client.post("/api/llm/test/", {"provider": "custom"}, content_type="application/json").json()
        self.assertEqual((t["ok"], t["reply"]), (True, "ready"), t)
        self.assertEqual((seen["auth"], seen["path"], seen["body"]["model"]), ("Bearer local-key-000000001", "/v1/chat/completions", "small-model"))
        m = self.client.post("/api/llm/models/", {"provider": "custom"}, content_type="application/json").json()
        self.assertEqual(m["models"], ["big-model", "small-model"])
        self.assertEqual(self.llm.generate("s", "u")[1], "custom")                    # every AI feature now goes there
        self.assertEqual(self.client.get("/api/ai/status/").json()["active"], "custom")
        u = self.row(self.client.get("/api/llm/").json(), "custom")["usage"]           # counts only, kept per provider
        self.assertEqual((u["calls"], u["failures"], u["tokens_in"], u["tokens_out"]), (2, 0, 14, 6), u)
        srv.shutdown()
        srv.server_close()                                                            # now nothing is listening there
        t = self.client.post("/api/llm/test/", {"provider": "custom"}, content_type="application/json").json()
        self.assertFalse(t["ok"])
        self.assertNotIn("local-key", t["error"])
        u = self.row(self.client.get("/api/llm/").json(), "custom")["usage"]
        self.assertEqual(u["failures"], 1)
        self.assertTrue(u["last_error"])
        self.client.post("/api/llm/reset-usage/", {}, content_type="application/json")
        self.assertIsNone(self.row(self.client.get("/api/llm/").json(), "custom")["usage"])

    def test_options_are_validated_and_reach_the_request(self):
        from unittest import mock
        self.assertEqual(self.put({"options": {"temperature": 9}}).status_code, 400)
        self.assertEqual(self.put({"options": {"max_tokens": "lots"}}).status_code, 400)
        d = self.put({"provider": "groq", "options": {"temperature": 0.1, "max_tokens": 900, "timeout": 30},
                      "providers": {"groq": {"api_key": "gsk-test-000000000001"}}}).json()
        self.assertEqual(d["options"], {"temperature": 0.1, "max_tokens": 900, "timeout": 30, "fallback": False})
        reply = {"choices": [{"message": {"content": "hello"}}]}
        with mock.patch.object(self.llm, "_http_json", return_value=reply) as http:
            self.assertEqual(self.llm.generate("s", "u"), ("hello", "groq"))
        url, key, body, timeout = http.call_args.args
        self.assertEqual((url, body["temperature"], body["max_tokens"], timeout),
                         ("https://api.groq.com/openai/v1/chat/completions", 0.1, 900, 30))

    def test_fallback_moves_on_only_when_switched_on(self):
        from unittest import mock
        self.put({"provider": "groq", "providers": {"groq": {"api_key": "gsk-test-000000000001"}, "mistral": {"api_key": "ms-test-0000000000001"}}})

        def http(url, *a, **k):
            if "groq" in url:
                raise self.llm._HTTPFailure(429, '{"error": {"message": "slow down"}}')
            return {"choices": [{"message": {"content": "from the second one"}}]}

        with mock.patch.object(self.llm, "_http_json", side_effect=http), \
             mock.patch.object(self.llm, "claude_code_available", return_value=False), \
             mock.patch.object(self.llm, "ollama_models", return_value=[]), \
             mock.patch.object(self.llm, "generate_ollama", side_effect=self.llm.LLMNotSetUp("off")):
            with self.assertRaises(self.llm.LLMUnavailable) as err:
                self.llm.generate("s", "u")                                  # pinned and failing: say so, don't wander
            self.assertIn("rate limited", str(err.exception))
            d = self.put({"options": {"fallback": True}}).json()
            self.assertEqual(d["active"], "groq")
            self.assertEqual(self.llm.generate("s", "u"), ("from the second one", "mistral"))
        self.assertEqual(self.llm.usage()["groq"]["failures"], 2)


class AccountLLMTests(LLMProviderTests):
    """Keys belong to the account that typed them; the admin's site-wide key is what everyone else falls back to."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import User
        from django.test import Client
        self.boss = User.objects.create_user("boss", "boss@example.com", "pw-12345678", is_staff=True)
        self.jane = User.objects.create_user("jane", "jane@example.com", "pw-12345678")
        self.sam = User.objects.create_user("sam", "sam@example.com", "pw-12345678")
        self.cb, self.cj, self.cs, self.client = Client(), Client(), Client(), Client()
        self.cb.force_login(self.boss)
        self.cj.force_login(self.jane)
        self.cs.force_login(self.sam)

    def put_as(self, client, body, scope=""):
        return client.put("/api/llm/" + (f"?scope={scope}" if scope else ""), body, content_type="application/json")

    def get_as(self, client, scope=""):
        return client.get("/api/llm/" + (f"?scope={scope}" if scope else "")).json()

    # the inherited single-site tests assume a copy with no accounts at all
    test_key_is_saved_but_never_returned = test_bad_input_is_refused = test_custom_endpoint_is_called_tested_and_listed = None
    test_only_an_admin_may_change_or_test_once_one_exists = test_options_are_validated_and_reach_the_request = None
    test_fallback_moves_on_only_when_switched_on = None

    def test_own_key_is_private_and_site_key_is_shared(self):
        self.assertEqual(self.put_as(self.cj, {"providers": {"groq": {"api_key": "x"}}}, "site").status_code, 403)   # not hers to set
        self.assertEqual(self.put_as(self.client, {"provider": "groq"}).status_code, 403)                              # guests: nothing
        r = self.put_as(self.cb, {"provider": "groq", "providers": {"groq": {"api_key": "gsk-site-00000000SITE"}}}, "site")
        self.assertEqual((r.status_code, r.json()["scope"]), (200, "site"))
        r = self.put_as(self.cj, {"provider": "mistral", "providers": {"mistral": {"api_key": "ms-jane-00000000JANE", "model": "mistral-tiny"}}})
        d = r.json()
        self.assertEqual((d["scope"], d["provider"], d["active"]), ("account", "mistral", "mistral"))
        m = self.row(d, "mistral")
        self.assertEqual((m["key_source"], m["key_hint"], m["model"]), ("account", "JANE", "mistral-tiny"))
        g = self.row(d, "groq")                                    # she may use the site key, but sees nothing of it
        self.assertEqual((g["available"], g["key_source"], g["key_hint"]), (True, "saved", ""))
        self.assertNotIn("JANE", r.content.decode().replace('"key_hint":"JANE"', ""))
        self.assertNotIn("ms-jane", (self.tmp / "profile.yaml").read_text())
        self.assertFalse((self.tmp / "llm_keys.json").read_text().count("ms-jane"))

        sam = self.get_as(self.cs)                                 # another account: no trace of Jane's key or choices
        self.assertEqual((sam["provider"], sam["active"], sam["own_provider"]), ("groq", "groq", ""))
        self.assertFalse(self.row(sam, "mistral")["has_key"])
        for who in (self.cb, self.cs, self.client):
            self.assertNotIn("JANE", who.get("/api/llm/?scope=site").content.decode())
        self.assertFalse(self.row(self.get_as(self.cb, "site"), "mistral")["has_key"])
        self.assertEqual(self.row(self.get_as(self.cb, "site"), "groq")["key_hint"], "SITE")
        self.assertIsNone(self.row(sam, "groq")["usage"])           # usage counts are the admin's to see

    def test_each_request_is_sent_with_that_accounts_key(self):
        from unittest import mock
        self.put_as(self.cb, {"provider": "groq", "providers": {"groq": {"api_key": "gsk-site-00000000SITE"}}}, "site")
        self.put_as(self.cj, {"provider": "mistral", "providers": {"mistral": {"api_key": "ms-jane-00000000JANE"}}})
        seen = []

        def http(url, key="", payload=None, timeout=0, headers=None):
            seen.append((url.split("/")[2], key))
            return {"choices": [{"message": {"content": "ready"}}]}

        with mock.patch.object(self.llm, "_http_json", side_effect=http):
            for client, name in ((self.cj, "mistral"), (self.cs, "groq"), (self.cj, "groq")):
                r = client.post("/api/llm/test/", {"provider": name}, content_type="application/json").json()
                self.assertTrue(r["ok"], r)
            self.assertEqual(self.cj.get("/api/ai/status/").json()["active"], "mistral")
            self.assertEqual(self.cs.get("/api/ai/status/").json()["active"], "groq")
            self.assertEqual(self.client.get("/api/ai/status/").json()["active"], "groq")
            with self.llm.scoped(self.jane.__class__.objects.get(pk=self.jane.pk).profile.llm):
                self.assertEqual(self.llm.carry(self.llm.generate)("s", "u")[1], "mistral")     # also in a worker thread
            self.assertEqual(self.llm.generate("s", "u")[1], "groq")                               # outside any account
        self.assertEqual(seen[:3], [("api.mistral.ai", "ms-jane-00000000JANE"), ("api.groq.com", "gsk-site-00000000SITE"),
                                    ("api.groq.com", "gsk-site-00000000SITE")])
        self.assertEqual(self.client.post("/api/llm/test/", {"provider": "groq"}, content_type="application/json").status_code, 403)

    def test_account_can_go_back_to_the_site_default_and_cannot_reach_private_addresses(self):
        self.put_as(self.cb, {"provider": "groq", "providers": {"groq": {"api_key": "gsk-site-00000000SITE"}}}, "site")
        self.put_as(self.cj, {"provider": "template", "options": {"temperature": 1.0}, "providers": {"groq": {"api_key": "gsk-jane-00000000JANE"}}})
        d = self.get_as(self.cj)
        self.assertEqual((d["provider"], d["active"], d["options"]["temperature"]), ("template", None, 1.0))
        self.assertEqual(self.get_as(self.cs)["options"]["temperature"], 0.4)
        d = self.put_as(self.cj, {"provider": "", "providers": {"groq": {"api_key": ""}}}).json()
        self.assertEqual((d["provider"], d["own_provider"], self.row(d, "groq")["key_source"]), ("groq", "", "saved"))
        for url in ("http://127.0.0.1:9/v1", "http://169.254.169.254/v1", "http://10.0.0.5/v1"):
            self.assertEqual(self.put_as(self.cj, {"providers": {"custom": {"base_url": url}}}).status_code, 400, url)
        self.assertEqual(self.put_as(self.cb, {"providers": {"custom": {"base_url": "http://127.0.0.1:9/v1"}}}).status_code, 200)
        self.assertEqual(self.cj.post("/api/provider/", {"provider": "ollama"}, content_type="application/json").status_code, 403)
        self.cj.put("/api/settings/", {"cover_letter": {"provider": "ollama"}}, content_type="application/json")
        self.assertEqual(self.get_as(self.cb, "site")["provider"], "groq")          # the old routes can't move the site default either
