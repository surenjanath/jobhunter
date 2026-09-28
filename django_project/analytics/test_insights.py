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
            "url": "u", "match": m, "status": status, "starred": False, "applied_date": "", "followup_date": "", "status_updated": ""}
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
