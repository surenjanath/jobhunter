from datetime import date, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from candidate.tests import RESUME
from jobs.testutil import ScannerDBTestCase

from .models import Drill, InboxSuggestion, RealInterview, Story

DESC = """We are a leading insurer. Our mission is simple cover. We value ownership.
Requirements
- 3+ years of Python and Django
- PostgreSQL and Docker
Salary: TT$12,000 - TT$16,000 per month."""
STORY = ("When our claims team had a backlog I built a Django and PostgreSQL triage tool. My goal was to clear it before audit, "
         "so I wrote the scoring rules myself. It cut the backlog by 40% in two months and the team adopted it.")
CALM = {"duration_sec": 25, "pace_wpm": 175, "pitch_mean_hz": 120, "jitter": 0.035, "pitch_range_st": 6, "uptalk_ratio": 0.3}


class CoachAPITests(ScannerDBTestCase):
    def setUp(self):
        self.c = APIClient()
        from src import profile_store
        profile_store.import_resume(RESUME.encode(), "jane.md", embed=False)
        self.make_job("c1", title="Python Developer", company="Acme Insurance", description=DESC, region="North", location="Port of Spain, Trinidad")
        self.make_job("c2", title="Data Analyst", company="Globex", description="SQL and Excel.")

    def other(self):
        u = User.objects.filter(username="o@example.com").first() or User.objects.create_user(
            username="o@example.com", email="o@example.com", password="correct-horse-battery-9")
        c = APIClient()
        c.force_authenticate(u)
        return c

    # ---- baseline -----------------------------------------------------------------------------------------------------
    def test_baseline_record_and_it_changes_composure(self):
        self.assertIsNone(self.c.get("/api/coach/baseline/").json()["baseline"])
        self.assertIn("passage", self.c.get("/api/coach/baseline/").json())
        self.assertEqual(self.c.post("/api/coach/baseline/", {"voice": {"duration_sec": 4}}, format="json").status_code, 400)
        self.assertEqual(self.c.post("/api/coach/baseline/", {"voice": CALM}, format="json").json()["baseline"]["pace_wpm"], 175)
        # a fast, calm talker: generic thresholds say "rushing"; against their own baseline they're calm
        fast = {"duration_sec": 30, "pace_wpm": 190, "pitch_mean_hz": 122, "jitter": 0.04, "phrases": 8, "pitch_range_st": 6}
        r = self.c.post("/api/jobs/c1/interview/feedback/", {"question": "q", "answer": STORY, "voice": fast}, format="json").json()
        self.assertTrue(r["composure"]["personal"])
        self.assertEqual(r["composure"]["label"], "Calm and confident")
        other = self.other()   # another account has no baseline: generic judgement
        r2 = other.post("/api/jobs/c1/interview/feedback/", {"question": "q", "answer": STORY, "voice": fast}, format="json").json()
        self.assertFalse(r2["composure"]["personal"])
        self.c.delete("/api/coach/baseline/")
        self.assertIsNone(self.c.get("/api/coach/baseline/").json()["baseline"])

    # ---- stories + coverage -------------------------------------------------------------------------------------------
    def test_story_bank_and_coverage(self):
        self.assertEqual(self.c.post("/api/coach/stories/", {"text": "too short"}, format="json").status_code, 400)
        s = self.c.post("/api/coach/stories/", {"question": "Tell me about a process you improved", "answer": STORY, "score": 84}, format="json").json()
        self.assertIn("Django", s["skills"])
        self.assertTrue(s["star"]["result"])
        cov = self.c.get("/api/coach/coverage/c1/").json()
        self.assertGreater(cov["covered"], 0)
        self.assertIn("Docker", cov["gaps"])          # required, no story mentions it
        upd = self.c.put(f"/api/coach/stories/{s['id']}/", {"text": STORY + " I containerised it with Docker."}, format="json").json()
        self.assertIn("Docker", upd["skills"])
        self.assertEqual(self.other().get("/api/coach/stories/").json()["stories"], [])   # private to the guest pipeline
        self.assertEqual(self.other().delete(f"/api/coach/stories/{s['id']}/").status_code, 404)
        self.assertEqual(self.c.delete(f"/api/coach/stories/{s['id']}/").status_code, 200)

    # ---- drills -------------------------------------------------------------------------------------------------------
    def test_weak_answers_become_drills_and_review_reschedules(self):
        weak = self.c.post("/api/jobs/c1/interview/feedback/", {"question": "Why this role?", "answer": "I think it is basically a good job and stuff, you know, I guess."}, format="json").json()
        good = self.c.post("/api/jobs/c1/interview/feedback/", {"question": "A process you improved?", "answer": STORY}, format="json").json()
        out = self.c.post("/api/ai/interview/summary/", {"results": [dict(weak, question="Why this role?"), dict(good, question="A process you improved?")],
                                                         "save": True, "job": {"job_id": "c1", "title": "Python Developer", "company": "Acme Insurance"}}, format="json").json()
        self.assertEqual(out["drills_added"], 1)
        d = Drill.objects.get()
        self.assertEqual(d.question, "Why this role?")
        self.assertEqual(self.c.get("/api/coach/drills/").json()["due"], [])   # due tomorrow, not today
        Drill.objects.update(next_due=timezone.localdate())
        self.assertEqual(len(self.c.get("/api/coach/drills/").json()["due"]), 1)
        r = self.c.post(f"/api/coach/drills/{d.id}/", {"score": 90}, format="json").json()
        self.assertGreater(r["interval_days"], 1)
        self.assertEqual(r["reps"], 1)
        self.assertEqual(self.c.get("/api/coach/drills/").json()["due"], [])
        # saving the same weak question again doesn't duplicate it
        self.c.post("/api/ai/interview/summary/", {"results": [dict(weak, question="Why this role?")], "save": True, "job": {"job_id": "c1"}}, format="json")
        self.assertEqual(Drill.objects.count(), 1)

    # ---- interview types ----------------------------------------------------------------------------------------------
    def test_typed_questions_and_negotiation_offer(self):
        for kind in ("screen", "technical", "negotiation", "reverse"):
            r = self.c.post("/api/jobs/c1/interview/questions/", {"kind": kind, "n": 5}, format="json").json()
            self.assertEqual(r["kind"], kind)
            self.assertTrue(r["questions"], kind)
        neg = self.c.post("/api/jobs/c1/interview/questions/", {"kind": "negotiation"}, format="json").json()
        self.assertEqual(neg["offer"]["amount"], 12000)     # low end of the posted TT$12,000-16,000
        self.assertIn("12,000", neg["questions"][0]["q"])
        fb = self.c.post("/api/jobs/c1/interview/feedback/", {"kind": "negotiation", "question": neg["questions"][0]["q"], "offer": neg["offer"],
                                                            "answer": "Thanks, I'm excited. Based on similar roles in the market and my results I'd be looking for 14,500 a month. Could we also discuss the bonus?"},
                         format="json").json()
        self.assertTrue(fb["checks"]["anchored above the offer"])
        self.assertIsNone(fb["follow_up"])

    # ---- real interviews, plan, log ------------------------------------------------------------------------------------
    def test_real_interview_plan_and_log(self):
        when = (timezone.localdate() + timedelta(days=5)).isoformat()
        self.assertEqual(self.c.post("/api/coach/interviews/", {"job_id": "nope", "scheduled_on": when}, format="json").status_code, 400)
        ri = self.c.post("/api/coach/interviews/", {"job_id": "c1", "scheduled_on": when, "stage": "technical"}, format="json").json()
        self.assertEqual(ri["days_left"], 5)
        p = self.c.get(f"/api/coach/interviews/{ri['id']}/plan/").json()
        keys = [t["key"] for t in p["plan"]["tasks"]]
        self.assertIn("baseline", keys)                     # none recorded yet
        self.assertEqual(p["plan"]["kind"], "technical")
        self.assertIn("Django", p["brief"]["stack"])
        self.assertTrue(p["coverage"]["gaps"])
        with mock.patch("src.ai_features._ask_llm") as llm:
            self.c.get(f"/api/coach/interviews/{ri['id']}/plan/")
            llm.assert_not_called()
        self.c.put(f"/api/coach/interviews/{ri['id']}/", {"done_tasks": ["research"]}, format="json")
        self.assertTrue(next(t for t in self.c.get(f"/api/coach/interviews/{ri['id']}/plan/").json()["plan"]["tasks"] if t["key"] == "research")["done"])
        # the calendar feed carries the interview and its mock days
        ics = self.c.get("/api/calendar.ics").content.decode()
        self.assertIn("Interview (Technical): Python Developer @ Acme Insurance", ics)
        self.assertIn("Mock interview: Acme Insurance", ics)
        # log it afterwards: the questions they asked become drills
        log = self.c.put(f"/api/coach/interviews/{ri['id']}/", {"log": {"questions": ["How do you index a slow query?", ""], "felt": 2, "outcome": "advanced"}}, format="json").json()
        self.assertTrue(log["logged"])
        self.assertEqual(log["questions"], ["How do you index a slow query?"])
        self.assertEqual(Drill.objects.get().source, "real")
        lst = self.c.get("/api/coach/interviews/").json()
        self.assertEqual(lst["upcoming"], [])
        self.assertEqual(len(lst["past"]), 1)

    # ---- inbox -------------------------------------------------------------------------------------------------------
    def test_pasted_email_suggests_a_status_for_a_tracked_job(self):
        body = "Hi, thanks for applying to Acme Insurance. We'd like to schedule an interview for the Python Developer role. Are you free Tuesday, 8 October?"
        r = self.c.post("/api/coach/inbox/parse/", {"subject": "Interview", "body": body, "sender": "hr@acmeinsurance.com"}, format="json").json()
        self.assertEqual(r["kind"], "invite")
        self.assertEqual(r["matches"], [])                  # c1 isn't tracked yet: nothing to match
        self.c.post("/api/jobs/bulk-status/", {"job_ids": ["c1"], "status": "Applied"}, format="json")
        r = self.c.post("/api/coach/inbox/parse/", {"subject": "Interview", "body": body, "sender": "hr@acmeinsurance.com"}, format="json").json()
        self.assertEqual(r["matches"][0]["job_id"], "c1")
        self.assertEqual(r["suggested_status"], "Interviewing")
        sug = self.c.get("/api/coach/inbox/").json()["suggestions"]
        self.assertEqual(len(sug), 1)
        self.assertEqual(self.c.post(f"/api/coach/inbox/{sug[0]['id']}/", {"action": "nope"}, format="json").status_code, 400)
        self.c.post(f"/api/coach/inbox/{sug[0]['id']}/", {"action": "dismissed"}, format="json")
        self.assertEqual(self.c.get("/api/coach/inbox/").json()["suggestions"], [])

    def test_check_inbox_requires_env_credentials(self):
        from django.core.management.base import CommandError
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(CommandError):
                call_command("check_inbox")

    def test_check_inbox_reads_readonly_and_suggests(self):
        self.c.post("/api/jobs/bulk-status/", {"job_ids": ["c1"], "status": "Applied"}, format="json")
        raw = (b"From: Jane <jane@acmeinsurance.com>\r\nSubject: Your application\r\nMessage-ID: <1@acme>\r\nDate: Mon, 7 Oct 2026 10:00:00 -0400\r\n"
               b"Content-Type: text/plain\r\n\r\nThank you for applying to Acme Insurance. Unfortunately we have decided to move forward with other candidates.\r\n")
        imap = mock.MagicMock()
        imap.search.return_value = ("OK", [b"1"])
        imap.fetch.return_value = ("OK", [(b"1 (BODY[] {100}", raw)])
        env = {"JOBHUNT_IMAP_HOST": "imap.example.com", "JOBHUNT_IMAP_USER": "me", "JOBHUNT_IMAP_PASSWORD": "app-pw"}
        with mock.patch.dict("os.environ", env), mock.patch("imaplib.IMAP4_SSL", return_value=imap):
            call_command("check_inbox", stdout=open("/dev/null", "w"))
            call_command("check_inbox", stdout=open("/dev/null", "w"))       # re-run: same Message-ID isn't duplicated
        imap.select.assert_called_with("INBOX", readonly=True)
        self.assertIn("BODY.PEEK[]", imap.fetch.call_args[0][1])
        s = InboxSuggestion.objects.get()
        self.assertEqual((s.kind, s.suggested_status, s.job_id), ("rejection", "Rejected", "c1"))

    # ---- weekly -----------------------------------------------------------------------------------------------------
    def test_weekly_report(self):
        self.c.post("/api/jobs/bulk-status/", {"job_ids": ["c1"], "status": "Applied"}, format="json")
        self.c.post("/api/jobs/bulk-status/", {"job_ids": ["c2"], "status": "Applied"}, format="json")
        self.c.post("/api/jobs/bulk-status/", {"job_ids": ["c2"], "status": "Interviewing"}, format="json")
        Story.objects.create(title="t", text=STORY)
        RealInterview.objects.create(job_id="c1", scheduled_on=timezone.localdate() + timedelta(days=2))
        w = self.c.get("/api/coach/weekly/").json()
        self.assertEqual(w["this"]["applied"], 2)
        self.assertEqual(w["this"]["responses"], 1)
        self.assertEqual(w["response_rate"], 50)
        self.assertEqual(w["this"]["stories"], 1)
        self.assertEqual(w["next_interview"]["job_id"], "c1")
        self.assertTrue(w["reads"])


class ContactsOffersTests(ScannerDBTestCase):
    def setUp(self):
        self.c = APIClient()
        from src import profile_store
        profile_store.import_resume(RESUME.encode(), "jane.md", embed=False)
        self.make_job("n1", title="Python Developer", company="Acme Insurance", description=DESC, region="North", location="Port of Spain, Trinidad")

    def test_contacts_crud_due_and_private(self):
        self.assertEqual(self.c.post("/api/coach/contacts/", {"company": "Acme"}, format="json").status_code, 400)
        today = timezone.localdate()
        a = self.c.post("/api/coach/contacts/", {"name": "Jane Recruiter", "company": "Acme Insurance", "kind": "recruiter",
                                                 "next_step": "Ask about the timeline", "next_date": today.isoformat()}, format="json").json()
        self.c.post("/api/coach/contacts/", {"name": "Later Person", "next_date": (today + timedelta(days=5)).isoformat()}, format="json")
        d = self.c.get("/api/coach/contacts/").json()
        self.assertEqual([x["name"] for x in d["due"]], ["Jane Recruiter"])
        u = self.c.put(f"/api/coach/contacts/{a['id']}/", {"last_contacted": today.isoformat(), "next_date": (today + timedelta(days=7)).isoformat()}, format="json").json()
        self.assertFalse(u["due"])
        other = APIClient()
        other.force_authenticate(User.objects.create_user(username="z@example.com", password="correct-horse-battery-9"))
        self.assertEqual(other.get("/api/coach/contacts/").json()["contacts"], [])
        self.assertEqual(other.delete(f"/api/coach/contacts/{a['id']}/").status_code, 404)

    def test_offers_compare_in_ttd_with_floor(self):
        self.c.post("/api/coach/offers/", {"company": "A", "base_monthly": 3000, "currency": "US$", "bonus_pct": 10, "commute_minutes": 45}, format="json")
        self.c.post("/api/coach/offers/", {"company": "B", "base_monthly": 18000, "currency": "TT$", "signing": 12000, "remote_days": 5, "leave_days": 25}, format="json")
        self.assertEqual(self.c.post("/api/coach/offers/", {"base_monthly": 1}, format="json").status_code, 400)
        d = self.c.get("/api/coach/offers/").json()
        self.assertEqual([o["company"] for o in d["offers"]], ["A", "B"])      # A is worth more in year one
        self.assertEqual(d["offers"][1]["value"]["total_ttd"], 19000)          # 18,000 + 12,000 signing / 12
        self.assertTrue(any("more days of leave" in n for n in d["notes"]))

    def test_negotiation_practice_uses_the_real_offer(self):
        r = self.c.post("/api/jobs/n1/interview/questions/", {"kind": "negotiation", "offer_amount": 21500, "offer_currency": "TT$"}, format="json").json()
        self.assertEqual(r["offer"]["amount"], 21500)
        self.assertIn("21,500 TT dollars a month", r["questions"][0]["q"])

    def test_due_contacts_are_in_the_alert(self):
        from unittest import mock
        from core import alerts_service
        self.c.post("/api/coach/contacts/", {"name": "Jane Recruiter", "company": "Acme", "next_step": "Send portfolio",
                                             "next_date": timezone.localdate().isoformat()}, format="json")
        out = alerts_service.run(None, dry_run=True)
        self.assertIn("REACH OUT", out["message"]["text"])
        self.assertIn("Jane Recruiter at Acme: Send portfolio", out["message"]["text"])
