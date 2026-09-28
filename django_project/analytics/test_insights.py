import json
from datetime import date, timedelta

from django.test import SimpleTestCase

from analytics import insights as ins

TODAY = date(2026, 9, 27)
iso = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731


def skill(name, status, kind="required", cat="Web & Backend", w=1.0, years=0, via=""):
    return {"name": name, "status": status, "kind": kind, "category": cat, "weight": w, "years": years, "via": via}


def row(job_id, fit=60, odds=45, region="", mode="remote", status="New", skills=(), blockers=(), first_seen=None, expires="", scope="worldwide", pay=None, **kw):
    m = {"skills": {"items": list(skills), "missing_required": [s["name"] for s in skills if s["status"] == "missing" and s["kind"] == "required"]},
         "blockers": list(blockers), "breakdown": {}, "job": {"pay": pay}, "confidence": "high", "advice": "Apply"}
    base = {"job_id": job_id, "title": f"Role {job_id}", "company": "Acme", "source": "ashby", "region": region, "category": "Technology",
            "location": "x", "remote": mode == "remote", "fit": fit, "likelihood": odds, "chance": round(odds / 5, 1), "work_mode": mode,
            "remote_scope": scope if mode == "remote" else "", "posted_at": iso(-1), "first_seen": first_seen or iso(-1), "expires_at": expires,
            "url": "u", "match": m, "status": status, "starred": False, "applied_date": "", "followup_date": "", "status_updated": "",
            "dismiss_reason": ""}
    base.update(kw)
    return base


class InsightsTests(SimpleTestCase):
    def rows(self):
        return [
            row("a", 80, 60, skills=[skill("Python", "have", years=4), skill("Kubernetes", "missing")], expires=iso(3)),
            row("b", 70, 50, skills=[skill("Python", "have", years=4), skill("Kubernetes", "missing"), skill("Communication", "soft")]),
            row("c", 60, 40, skills=[skill("Kubernetes", "missing"), skill("Terraform", "missing")]),
            row("d", 55, 0, mode="onsite", skills=[skill("Python", "have")], blockers=["On-site abroad"]),
            row("e", 45, 30, region="Port of Spain", mode="onsite", skills=[skill("SQL", "related", via="PostgreSQL")]),
            row("f", 30, 5, mode="remote", scope="us_only", skills=[], blockers=["US only"]),
        ]

    def test_market_skills_and_soft_skills_excluded(self):
        ms = {s["skill"]: s for s in ins.market_skills(self.rows())}
        self.assertEqual(ms["Python"]["jobs"], 3)
        self.assertEqual(ms["Python"]["status"], "have")
        self.assertEqual(ms["Kubernetes"]["status"], "missing")
        self.assertNotIn("Communication", ms)
        self.assertEqual(ms["SQL"]["status"], "related")

    def test_strengths_ranked_by_demand(self):
        st = ins.strengths(self.rows())
        self.assertEqual(st[0], {"skill": "Python", "jobs": 3, "years": 4})

    def test_gap_roi_counts_sole_gaps_and_respects_focus(self):
        roi = ins.gap_roi(self.rows())
        k = next(g for g in roi if g["skill"] == "Kubernetes")
        self.assertEqual((k["jobs"], k["sole_gap"]), (3, 2))     # job c also misses Terraform
        self.assertEqual(roi[0]["skill"], "Kubernetes")
        self.assertEqual(ins.gap_roi(self.rows(), focus={"Cloud & DevOps"}), [])   # categories the user doesn't work in
        prof = {"skills": {"Python": {"category": "Web & Backend"}, "Django": {"category": "Web & Backend"}, "R": {"category": "Languages"}}}
        self.assertEqual(ins.focus_categories(prof), {"Web & Backend"})

    def test_mode_split_and_histogram(self):
        mc = {m["mode"]: m for m in ins.mode_compare(self.rows())}
        self.assertEqual(mc["local"]["count"], 1)
        self.assertEqual(mc["remote"]["count"], 4)
        self.assertEqual(mc["abroad"]["count"], 1)
        self.assertEqual(mc["abroad"]["blocked"], 1)
        h = ins.fit_histogram(self.rows())
        self.assertEqual(sum(b["local"] + b["remote"] + b["abroad"] for b in h), 6)
        self.assertEqual(h[8]["remote"], 1)   # fit 80

    def test_timeline_and_closing(self):
        rows = self.rows()
        tl = ins.timeline(rows, TODAY, days=5)
        self.assertEqual(len(tl), 5)
        self.assertEqual(sum(t["local"] + t["remote"] for t in tl), 6)
        cl = ins.closing(rows, TODAY, days=7)
        self.assertEqual(cl[3]["count"], 1)
        self.assertEqual(cl[3]["good"], 1)

    def test_funnel_conversion_and_hint(self):
        rows = [row(f"x{i}", status=s, applied_date=iso(-40)) for i, s in enumerate(
            ["Applied"] * 6 + ["Interviewing", "Interviewing", "Rejected", "Rejected", "Rejected", "Offer"])]
        f = ins.funnel(rows, TODAY)
        self.assertEqual((f["applied"], f["interviews"], f["offers"], f["rejected"]), (12, 3, 1, 3))
        self.assertEqual(f["conversion"]["applied_to_interview"], 25)
        self.assertEqual(f["conversion"]["applied_to_response"], 50)
        self.assertEqual(f["stale_applied"], 6)
        self.assertNotIn("Only", f["hint"])
        f0 = ins.funnel([row("n")], TODAY)
        self.assertIn("No applications recorded", f0["hint"])

    def test_salary_bins_and_floor(self):
        pay = {"currency": "USD", "monthly_ttd_max": 40000, "monthly_usd_max": 6000, "monthly_ttd_min": 30000, "monthly_usd_min": 5000}
        s = ins.salary([row("p", pay=pay), row("q")], {"min_salary_monthly_ttd": 12000})
        self.assertEqual(s["remote"]["n"], 1)
        self.assertEqual(s["remote"]["median"], 6000)
        self.assertEqual(s["floor_ttd"], 12000)
        self.assertEqual(s["disclosed_share"], 50)

    def test_top_opportunities_excludes_blocked_and_applied(self):
        rows = self.rows() + [row("z", 99, 99, status="Applied")]
        ids = [t["job_id"] for t in ins.top_opportunities(rows)]
        self.assertNotIn("z", ids)
        self.assertNotIn("d", ids)
        self.assertNotIn("f", ids)
        self.assertEqual(ids[0], "a")

    def test_build_end_to_end_and_insight_text(self):
        d = ins.build(self.rows(), {"min_salary_monthly_ttd": 0}, today=TODAY, profile={"skills": {}})
        self.assertEqual(d["overview"]["total"], 6)
        self.assertEqual(d["overview"]["local"], 1)
        self.assertEqual(d["overview"]["blocked"], 2)
        texts = " ".join(i["text"] for i in d["insights"])
        self.assertIn("Kubernetes", texts)
        self.assertIn("restricted", texts)            # us_only remote role
        self.assertIn("relocation", texts)            # good fit but on-site abroad
        json.dumps(d)                                 # payload must be serialisable
        self.assertEqual(ins.build([], {}, today=TODAY)["insights"][0]["kind"], "info")


class InsightsV2Tests(SimpleTestCase):
    def rows(self):
        pay = {"currency": "TTD", "monthly_ttd_max": 9000, "monthly_usd_max": 1300}
        return [
            row("a", 80, 60, skills=[skill("Python", "have"), skill("Kubernetes", "missing")], company="Acme"),
            row("b", 70, 50, skills=[skill("Python", "have"), skill("Kubernetes", "missing")], company="Acme"),
            row("c", 60, 40, region="Port of Spain", mode="onsite", skills=[skill("SQL", "related")], company="Corp", pay=pay,
                posted_at=iso(-10), expires_at=iso(4)),
            row("d", 20, 5, skills=[], company="Low"),
            row("e", 65, 30, skills=[skill("Python", "have")], company="Blocked Co", blockers=["US only"]),
        ]

    def test_opportunity_map_only_open_fitting_roles(self):
        pts = ins.opportunity_map(self.rows() + [row("z", 90, 90, status="Applied")])
        ids = [p["job_id"] for p in pts]
        self.assertNotIn("z", ids)
        self.assertNotIn("d", ids)             # fit < 30
        self.assertTrue(next(p for p in pts if p["job_id"] == "e")["blocked"])
        self.assertEqual(ids[0], "a")

    def test_skill_bundles_pair_requirements(self):
        b = ins.skill_bundles(self.rows())
        top = b[0]
        self.assertEqual((top["a"], top["b"], top["jobs"]), ("Kubernetes", "Python", 2))
        self.assertEqual(top["missing"], ["Kubernetes"])
        self.assertFalse(top["have_both"])

    def test_employers_group_good_unblocked_roles(self):
        e = {x["company"]: x for x in ins.employers(self.rows(), TODAY)}
        self.assertEqual(e["Acme"]["good"], 2)
        self.assertNotIn("Blocked Co", e)       # its only good-fit role is blocked
        self.assertNotIn("Low", e)

    def test_pay_by_category_needs_enough_data(self):
        self.assertEqual(ins.salary_by_category(self.rows(), min_n=3), {"local": [], "remote": []})
        out = ins.salary_by_category(self.rows(), min_n=1)
        self.assertEqual(out["local"][0]["median"], 9000)

    def test_experience_asked_and_time_open(self):
        rows = self.rows()
        rows[0]["match"]["job"].update(min_years=4, level=2.0)
        rows[1]["match"]["job"].update(min_years=1, level=1.0)
        e = ins.experience_asked(rows, 6.0)
        self.assertEqual(e["your_years"], 6.0)
        self.assertEqual(next(b["count"] for b in e["bins"] if b["label"] == "4-5"), 1)
        self.assertEqual(next(l["count"] for l in e["levels"] if l["level"] == "senior"), 1)
        t = ins.time_open(rows)
        self.assertEqual(t["n"], 1)
        self.assertEqual(t["median"], 14)        # posted 10 days ago, closes in 4

    def test_market_score_and_what_would_raise_it(self):
        m = ins.market_score(self.rows(), {"skills": {"Python": {"category": "Web & Backend"}, "Django": {"category": "Web & Backend"}}})
        self.assertGreater(m["score"], 0)
        self.assertEqual(m["raise"][0]["skill"], "Kubernetes")
        self.assertGreater(m["raise"][0]["gain"], 0)

    def test_build_includes_v2_sections_and_is_json_safe(self):
        d = ins.build(self.rows(), {}, today=TODAY, profile={"skills": {}, "years_experience": 5})
        for k in ("map", "bundles", "employers", "pay_by_category", "experience", "time_open", "market", "passed_reasons"):
            self.assertIn(k, d)
        json.dumps(d)

    def test_passed_reasons_counts_and_ignores_no_reason(self):
        rows = [
            row("p1", status="Passed on it", dismiss_reason="Pay too low"),
            row("p2", status="Passed on it", dismiss_reason="Pay too low"),
            row("p3", status="Passed on it", dismiss_reason="Wrong seniority"),
            row("p4", status="Passed on it", dismiss_reason=""),   # dismissed before this feature existed — no reason on file
            row("p5", status="Rejected", dismiss_reason=""),        # not a dismissal
        ]
        pr = ins.passed_reasons(rows)
        self.assertEqual(pr["total"], 4)
        self.assertEqual(pr["with_reason"], 3)
        self.assertEqual(pr["reasons"][0], {"reason": "Pay too low", "count": 2})

    def test_text_insights_flags_a_dominant_dismissal_reason(self):
        rows = self.rows() + [row(f"p{i}", status="Passed on it", dismiss_reason="Pay too low") for i in range(3)]
        d = ins.build(rows, {}, today=TODAY, profile={})
        self.assertTrue(any("Pay too low" in x["text"] for x in d["insights"]))
