import json

from django.contrib.auth.models import User
from rest_framework.test import APIClient

from candidate.tests import RESUME
from jobs.testutil import ScannerDBTestCase

SALES_RESUME = """# Alex Sales
**Business Development Manager**
alex@example.com

## EXPERIENCE
### Regional Traders Ltd
**Business Development Manager** · Jan 2018 – Present
- Grew territory revenue by negotiating distributor contracts across the Caribbean.
- Managed a team of 6 account managers and ran quarterly sales forecasting.
- Built relationships with retail chains, closing over TT$4M in annual contracts.

## SKILLS
Sales, Negotiation, Account Management, Forecasting, CRM

## EDUCATION
BSc Management Studies — University of the West Indies · 2010 – 2014
"""


class AccountAuthTests(ScannerDBTestCase):
    def setUp(self):
        self.c = APIClient(enforce_csrf_checks=False)

    def test_register_login_logout_me(self):
        self.assertEqual(self.c.get("/api/auth/me/").json(), {"authenticated": False})
        r = self.c.post("/api/auth/register/", {"email": "jane@example.com", "password": "correct-horse-battery-9"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["ok"])
        self.assertTrue(self.c.get("/api/auth/me/").json()["authenticated"])
        self.assertEqual(self.c.post("/api/auth/logout/").json(), {"ok": True})
        self.assertFalse(self.c.get("/api/auth/me/").json()["authenticated"])
        # wrong password rejected, correct password accepted
        self.assertEqual(self.c.post("/api/auth/login/", {"email": "jane@example.com", "password": "nope"}, format="json").status_code, 401)
        r = self.c.post("/api/auth/login/", {"email": "jane@example.com", "password": "correct-horse-battery-9"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.c.get("/api/auth/me/").json()["authenticated"])

    def test_register_validation(self):
        self.assertEqual(self.c.post("/api/auth/register/", {"email": "not-an-email", "password": "x"}, format="json").status_code, 400)
        self.assertEqual(self.c.post("/api/auth/register/", {"email": "a@b.com", "password": "123"}, format="json").status_code, 400)
        User.objects.create_user(username="dup@example.com", email="dup@example.com", password="correct-horse-battery-9")
        self.assertEqual(self.c.post("/api/auth/register/", {"email": "dup@example.com", "password": "correct-horse-battery-9"}, format="json").status_code, 409)


class AccountProfileTests(ScannerDBTestCase):
    def setUp(self):
        self.c = APIClient(enforce_csrf_checks=False)
        self.c.post("/api/auth/register/", {"email": "jane@example.com", "password": "correct-horse-battery-9", "keep_current_resume": "false"}, format="json")
        self.job = self.make_job("j1", title="Senior Python Developer",
                                 description="Requirements\n- 3+ years Python and Django\n- PostgreSQL\n- Docker",
                                 category="Technology", region="", location="Remote", remote=True)

    def upload(self, text):
        return self.c.post("/api/profile/resume/", {"text": text, "filename": "resume.md"}, format="json")

    def test_upload_becomes_own_profile_and_rescores(self):
        r = self.upload(RESUME)
        self.assertEqual(r.status_code, 201)
        d = r.json()
        self.assertTrue(d["own_profile"])
        self.assertEqual(d["rescored"], 1)
        prof = self.c.get("/api/profile/").json()
        self.assertTrue(prof["own_profile"])
        self.assertIn("Python", [s["name"] for s in prof["profile"]["skills"]])
        # status is a dict shaped like profile_store.status() — the frontend reads .filename/.chunks/.semantic
        self.assertEqual(prof["status"]["filename"], "resume.md")
        self.assertGreater(prof["status"]["chunks"], 0)
        self.assertIn("semantic", prof["status"])

    def test_two_accounts_get_different_fit_for_the_same_job(self):
        self.upload(RESUME)
        fit_dev = json.loads(self.c.get("/api/jobs/").content)["results"][0]["fit_score"]

        c2 = APIClient(enforce_csrf_checks=False)
        c2.post("/api/auth/register/", {"email": "alex@example.com", "password": "correct-horse-battery-9", "keep_current_resume": "false"}, format="json")
        c2.post("/api/profile/resume/", {"text": SALES_RESUME, "filename": "resume.md"}, format="json")
        fit_sales = json.loads(c2.get("/api/jobs/").content)["results"][0]["fit_score"]

        self.assertGreater(fit_dev, fit_sales)
        self.assertEqual(json.loads(c2.get("/api/jobs/").content)["results"][0]["job_id"], "j1")

    def test_pipeline_status_is_private_per_account(self):
        self.upload(RESUME)
        self.c.post("/api/jobs/j1/star/", {}, format="json")
        self.c.put("/api/jobs/j1/status/", json.dumps({"status": "Applied", "notes": "referred by a friend"}), content_type="application/json")

        c2 = APIClient(enforce_csrf_checks=False)
        c2.post("/api/auth/register/", {"email": "alex@example.com", "password": "correct-horse-battery-9", "keep_current_resume": "false"}, format="json")
        row2 = json.loads(c2.get("/api/jobs/").content)["results"][0]
        self.assertEqual(row2["app_status"], "New")
        self.assertFalse(row2["starred"])
        self.assertEqual(row2["notes"], "")

        guest = APIClient(enforce_csrf_checks=False)
        row_guest = json.loads(guest.get("/api/jobs/").content)["results"][0]
        self.assertEqual(row_guest["app_status"], "New")   # the shared app_status table, untouched by either account

        row1 = json.loads(self.c.get("/api/jobs/").content)["results"][0]
        self.assertEqual(row1["app_status"], "Applied")
        self.assertTrue(row1["starred"])
        self.assertEqual(row1["notes"], "referred by a friend")

    def test_state_endpoint_is_private_per_account(self):
        """/api/state/ is what the frontend actually loads JOBS from (core.js loadState()) — a regression test for
        a real bug: a brand new account's jobs briefly inherited the SHARED/guest app_status instead of showing
        New, because /api/state/'s serialize() calls weren't given the per-account overlay."""
        # a guest's single-job PUT status/ writes through the scanner db directly (src.db.update_status), a
        # different physical database from the Django ORM's 'jobhunt' test alias — bulk-status uses the ORM
        # (ApplicationStatus) like /api/state/ reads, so it's what actually proves the isolation here.
        guest = APIClient(enforce_csrf_checks=False)
        guest.post("/api/jobs/bulk-status/", {"job_ids": ["j1"], "status": "Passed on it", "dismiss_reason": "Pay too low"}, format="json")
        guest.post("/api/jobs/j1/star/", {}, format="json")

        self.upload(RESUME)
        row = next(j for j in self.c.get("/api/state/").json()["jobs"] if j["job_id"] == "j1")
        self.assertEqual(row["app_status"], "New")     # NOT "Passed on it" from the shared/guest table
        self.assertFalse(row["starred"])
        self.assertTrue(row["personalized"])
        self.assertEqual(row["fit_score"], json.loads(self.c.get("/api/jobs/").content)["results"][0]["fit_score"])

        row_guest = next(j for j in guest.get("/api/state/").json()["jobs"] if j["job_id"] == "j1")
        self.assertEqual(row_guest["app_status"], "Passed on it")   # the guest's own shared-table edit is untouched
        self.assertFalse(row_guest.get("personalized", False))

    def test_pipeline_counts_are_private_per_account(self):
        self.upload(RESUME)
        self.c.put("/api/jobs/j1/status/", json.dumps({"status": "Applied"}), content_type="application/json")
        p = self.c.get("/api/pipeline/").json()
        self.assertEqual(next(s["count"] for s in p["stages"] if s["status"] == "Applied"), 1)

        c2 = APIClient(enforce_csrf_checks=False)
        c2.post("/api/auth/register/", {"email": "alex@example.com", "password": "correct-horse-battery-9", "keep_current_resume": "false"}, format="json")
        p2 = c2.get("/api/pipeline/").json()
        self.assertEqual(next(s["count"] for s in p2["stages"] if s["status"] == "Applied"), 0)

    def test_register_migrates_the_currently_active_anonymous_profile(self):
        from src import profile_store
        profile_store.import_resume(RESUME, "anon.md", source="upload", embed=False)
        c3 = APIClient(enforce_csrf_checks=False)
        r = c3.post("/api/auth/register/", {"email": "carried@example.com", "password": "correct-horse-battery-9"}, format="json")
        d = r.json()
        self.assertTrue(d["migrated_current_resume"])
        self.assertTrue(d["has_profile"])
        prof = c3.get("/api/profile/").json()
        self.assertTrue(prof["own_profile"])
        self.assertIn("Python", [s["name"] for s in prof["profile"]["skills"]])
        # the migrated profile is immediately usable, not stuck showing shared/generic scores until a manual rescore
        row = json.loads(c3.get("/api/jobs/").content)["results"][0]
        self.assertTrue(row["personalized"])

    def test_job_match_caches_into_user_job_match(self):
        self.upload(RESUME)
        r = self.c.get("/api/jobs/j1/match/")
        self.assertEqual(r.status_code, 200)
        from accounts.models import UserJobMatch
        self.assertTrue(UserJobMatch.objects.filter(job_id="j1").exists())
        # the Ledger row now reflects that cached match without a separate rescore
        row = json.loads(self.c.get("/api/jobs/").content)["results"][0]
        self.assertEqual(row["fit_score"], r.json()["match"]["fit"])


from django.test import TestCase  # noqa: E402


class LoginThrottleTests(TestCase):
    """Password guessing is rate-limited per address and per account email."""
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        from django.contrib.auth.models import User
        User.objects.create_user(username="victim@example.com", email="victim@example.com", password="correct-horse-battery-9")

    def tearDown(self):
        from django.core.cache import cache
        cache.clear()

    def test_guessing_from_one_address_is_cut_off(self):
        from rest_framework.test import APIClient
        c = APIClient()
        codes = [c.post("/api/auth/login/", {"email": "victim@example.com", "password": f"guess{i}"}, format="json").status_code for i in range(12)]
        self.assertEqual(codes[:10], [401] * 10)
        self.assertEqual(codes[10:], [429, 429])
        # even the right password is refused while throttled: the limit isn't a password oracle
        self.assertEqual(c.post("/api/auth/login/", {"email": "victim@example.com", "password": "correct-horse-battery-9"}, format="json").status_code, 429)

    def test_guessing_one_account_from_many_addresses_is_cut_off(self):
        from rest_framework.test import APIClient
        codes = []
        for i in range(22):
            c = APIClient(REMOTE_ADDR=f"10.0.{i // 250}.{i % 250 + 1}")
            codes.append(c.post("/api/auth/login/", {"email": "victim@example.com", "password": f"guess{i}"}, format="json").status_code)
        self.assertEqual(codes[:20], [401] * 20)
        self.assertEqual(codes[20:], [429, 429])

    def test_normal_login_still_works(self):
        from rest_framework.test import APIClient
        r = APIClient().post("/api/auth/login/", {"email": "victim@example.com", "password": "correct-horse-battery-9"}, format="json")
        self.assertEqual(r.status_code, 200)
