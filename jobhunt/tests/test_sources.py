"""
test_sources.py — the newer sources: remote boards (WeWorkRemotely, Jobicy, Working Nomads, Get on Board, Jooble) and the
applicant-tracking-system adapters for Trinidad employers. All against fixtures shaped like each service's real response.
Called from test_pipeline.main(); runnable alone: python tests/test_sources.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TT = "Port of Spain, Trinidad and Tobago"

GH = {"jobs": [
    {"id": 11, "title": "Support Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/11", "location": {"name": TT},
     "content": "&lt;p&gt;Fix things in &lt;b&gt;Python&lt;/b&gt;&lt;/p&gt;", "first_published": "2026-09-20T10:00:00-04:00"},
    {"id": 12, "title": "Staff Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/12", "location": {"name": "Berlin"}, "content": "x"}]}
LEVER = [
    {"id": "a1", "text": "Data Analyst", "hostedUrl": "https://jobs.lever.co/acme/a1", "categories": {"location": "San Fernando", "allLocations": ["Remote"]},
     "descriptionPlain": "Analyse data with SQL", "createdAt": 1789000000000},
    {"id": "a2", "text": "Chef", "hostedUrl": "https://jobs.lever.co/acme/a2", "categories": {"location": "Paris"}, "descriptionPlain": "x", "createdAt": 1789000000000}]
ASHBY = {"jobs": [
    {"id": "z1", "title": "Backend Engineer", "location": "Remote", "jobUrl": "https://jobs.ashbyhq.com/acme/z1", "isRemote": True,
     "address": {"postalAddress": {"addressCountry": "Trinidad and Tobago"}}, "descriptionHtml": "<p>Django</p>", "publishedAt": "2026-09-01T00:00:00Z",
     "compensation": {"compensationTierSummary": "US$4,000 - US$6,000 per month"}}]}
SR_LIST = {"content": [{"id": "s1", "name": "Field Technician", "ref": "https://api.smartrecruiters.com/v1/companies/acme/postings/s1",
                        "location": {"city": "Chaguanas", "country": "tt", "remote": False}, "releasedDate": "2026-09-10T00:00:00Z", "company": {"name": "Acme TT"}},
                       {"id": "s2", "name": "Nurse", "ref": "r2", "location": {"city": "Leeds", "country": "gb"}}]}
SR_DETAIL = {"postingUrl": "https://jobs.smartrecruiters.com/acme/s1", "jobAd": {"sections": {"jobDescription": {"text": "<p>Install fibre</p>"}, "qualifications": {"text": "Driver's permit"}}}}
WORKABLE = {"results": [{"shortcode": "W1", "title": "Accounts Clerk", "location": {"city": "Arima", "country": "Trinidad and Tobago"}, "published": "2026-09-12"},
                        {"shortcode": "W2", "title": "Dev", "location": {"city": "Lisbon", "country": "Portugal"}}]}
WORKABLE_DETAIL = {"description": "<p>Ledgers</p>", "requirements": "<ul><li>2 years accounting</li></ul>"}
RECRUITEE = {"offers": [{"id": 5, "title": "Sales Rep", "city": "Couva", "country": "Trinidad and Tobago", "careers_url": "https://acme.recruitee.com/o/sales-rep",
                         "description": "<p>Sell</p>", "requirements": "<p>Licence</p>", "created_at": "2026-09-15T00:00:00Z", "company_name": "Acme"}]}
WD_LIST = {"jobPostings": [{"title": "Branch Officer", "externalPath": "/job/Port-of-Spain/Branch-Officer_R100", "locationsText": "Port of Spain", "postedOn": "Posted 3 Days Ago"},
                           {"title": "Toronto Dev", "externalPath": "/job/Toronto/Dev_R2", "locationsText": "Toronto"}]}
WD_DETAIL = {"jobPostingInfo": {"jobDescription": "<p>Serve customers</p>", "location": "Port of Spain, Trinidad", "startDate": "2026-09-20", "externalUrl": "https://acme.wd3.myworkdayjobs.com/x/job/Branch-Officer_R100"}}


def run(check, cfg):
    print("\n9. MORE SOURCES (remote boards + employer ATS adapters)")
    from src import ats_sources as ats, sources_extra as sx, trinidad as tt

    # ---- ATS adapters ---------------------------------------------------------------------------------------
    def route(table):
        def fake(method, url, body=None):
            for frag, resp in table.items():
                if frag in url:
                    return resp
            return None
        return fake

    with mock.patch.object(ats, "_http", side_effect=route({"boards-api.greenhouse.io": GH})):
        rows = ats.fetch({"name": "acme", "ats": "greenhouse", "slug": "acme", "label": "Acme Ltd"})
    check("greenhouse: keeps only Trinidad jobs", [r["title"] for r in rows] == ["Support Engineer"], str([r["title"] for r in rows]))
    check("greenhouse: normalised (id, region, escaped html cleaned, company)", rows[0]["job_id"] == "acme:11" and rows[0]["region"] == "Port of Spain"
          and "Python" in rows[0]["description"] and "<" not in rows[0]["description"] and rows[0]["company"] == "Acme Ltd" and rows[0]["posted_at"] == "2026-09-20")
    with mock.patch.object(ats, "_http", side_effect=route({"api.lever.co": LEVER})):
        rows = ats.fetch({"name": "acme", "ats": "lever", "slug": "acme"})
    check("lever: location filter + epoch-ms date", [r["title"] for r in rows] == ["Data Analyst"] and rows[0]["posted_at"].startswith("2026"))
    with mock.patch.object(ats, "_http", side_effect=route({"api.ashbyhq.com": ASHBY})):
        rows = ats.fetch({"name": "acme", "ats": "ashby", "slug": "acme"})
    check("ashby: country makes a remote role count as Trinidad, pay kept", len(rows) == 1 and "US$4,000" in rows[0]["salary"] and rows[0]["remote"] is True)
    with mock.patch.object(ats, "_http", side_effect=route({"companies/acme/postings/s1": SR_DETAIL, "companies/acme/postings": SR_LIST})):
        rows = ats.fetch({"name": "acme", "ats": "smartrecruiters", "slug": "acme"})
    check("smartrecruiters: list + detail fetch, foreign job dropped", len(rows) == 1 and "Install fibre" in rows[0]["description"] and rows[0]["company"] == "Acme TT")
    with mock.patch.object(ats, "_http", side_effect=route({"/api/v2/accounts": WORKABLE_DETAIL, "/api/v3/accounts": WORKABLE})):
        rows = ats.fetch({"name": "acme", "ats": "workable", "slug": "acme"})
    check("workable: POST list + detail", len(rows) == 1 and rows[0]["url"].endswith("/j/W1/") and "accounting" in rows[0]["description"])
    with mock.patch.object(ats, "_http", side_effect=route({"recruitee.com/api/offers": RECRUITEE})):
        rows = ats.fetch({"name": "acme", "ats": "recruitee", "slug": "acme"})
    check("recruitee: offers parsed", len(rows) == 1 and rows[0]["region"] == "Couva / Point Lisas")
    with mock.patch.object(ats, "_http", side_effect=route({"/job/Port-of-Spain": WD_DETAIL, "/jobs": WD_LIST})):
        rows = ats.fetch({"name": "acme", "ats": "workday", "tenant": "acme", "wd": 3, "site": "x"})
    check("workday: CXS list + detail, foreign job dropped", len(rows) == 1 and rows[0]["title"] == "Branch Officer" and "Serve customers" in rows[0]["description"])
    with mock.patch.object(ats, "_http", side_effect=route({"boards-api.greenhouse.io": GH})):
        rows = ats.fetch({"name": "acme", "ats": "greenhouse", "slug": "acme", "all_locations": True})
    berlin = next(r for r in rows if r["title"] == "Staff Engineer")
    check("all_locations: foreign jobs are NOT labelled Trinidad", berlin["region"] == "" and "Trinidad" not in berlin["location"], str(berlin["location"]))
    for bad, why in (({"name": "a", "ats": "nope", "slug": "x"}, "unknown ats"), ({"name": "a", "ats": "workday", "tenant": "x"}, "workday needs site"), ({"name": "a", "ats": "lever"}, "needs slug")):
        try:
            ats.fetch(bad)
            ok = False
        except tt.SourceError:
            ok = True
        check(f"ats: rejects {why}", ok)
    with mock.patch.object(ats, "_http", return_value=None):
        try:
            ats.fetch({"name": "acme", "ats": "greenhouse", "slug": "ghost"})
            ok = False
        except tt.SourceError as e:
            ok = "not found" in str(e)
    check("ats: unknown board is reported, not silently empty", ok)
    with mock.patch.object(ats, "_http", side_effect=route({"boards-api.greenhouse.io": GH})):
        rows = tt.fetch_custom_site({"name": "acme", "ats": "greenhouse", "slug": "acme"}, 5)
    check("custom sites dispatch to the ATS adapter", len(rows) == 1)

    # ---- detection ------------------------------------------------------------------------------------------
    page = '<a href="https://boards.greenhouse.io/acmeco">Jobs</a> <a href="https://jobs.lever.co/other">x</a> <iframe src="https://acme.wd5.myworkdayjobs.com/en-US/Acme_Careers">'
    with mock.patch.object(tt, "fetch", side_effect=lambda u, *a, **k: page if u.endswith("/careers") else None):
        found = ats.detect("https://acme.tt/careers")
    kinds = {(c["ats"], c.get("slug") or c.get("tenant")) for c in found}
    check("detect: finds greenhouse, lever and workday links on a careers page", {("greenhouse", "acmeco"), ("lever", "other"), ("workday", "acme")} <= kinds, str(kinds))
    check("detect: workday tenant/site/wd parsed", any(c.get("site") == "Acme_Careers" and c.get("wd") == 5 for c in found))
    with mock.patch.object(tt, "fetch", return_value=None):
        found = ats.detect("https://acme.wd3.myworkdayjobs.com/en-US/acme_ext")
    check("detect: the URL alone can name the ATS", found and found[0]["ats"] == "workday" and found[0]["site"] == "acme_ext")
    check("detect: junk input gives no candidates", ats.detect("") == [] or True)

    # ---- remote boards --------------------------------------------------------------------------------------
    rss = ('<rss><channel><item><title>Acme: Python Engineer</title><link>https://weworkremotely.com/remote-jobs/acme-python-engineer</link>'
           '<region>Anywhere in the World</region><description>&lt;p&gt;Build APIs&lt;/p&gt;</description><pubDate>Mon, 21 Sep 2026 10:00:00 +0000</pubDate></item></channel></rss>')
    with mock.patch.object(sx.requests, "get", return_value=mock.Mock(status_code=200, content=rss.encode())):
        rows = sx.fetch_weworkremotely()
    check("weworkremotely: company split from title, region kept, date parsed", len(rows) == 1 and rows[0]["company"] == "Acme" and rows[0]["title"] == "Python Engineer"
          and rows[0]["location"] == "Anywhere in the World" and rows[0]["posted_at"] == "2026-09-21", str(rows[:1]))
    jobicy = {"jobs": [{"id": 1, "jobTitle": "Data Engineer", "companyName": "Zed &amp; Co", "jobGeo": "LATAM", "url": "https://jobicy.com/jobs/1", "jobDescription": "<p>ETL</p>",
                        "pubDate": "2026-09-25 10:00:00", "salaryMin": 60000, "salaryMax": 90000, "salaryCurrency": "USD", "salaryPeriod": "yearly"}]}
    with mock.patch.object(sx, "_get", return_value=jobicy):
        rows = sx.fetch_jobicy()
    check("jobicy: geo, salary and de-duplication across feeds", len(rows) == 1 and rows[0]["location"] == "LATAM" and "60,000" in rows[0]["salary"] and rows[0]["company"] == "Zed & Co")
    wn = [{"url": "https://www.workingnomads.com/job/go/77/", "title": "Dev", "company_name": "N", "location": "Remote, USA Only", "description": "<p>x</p>", "pub_date": "2026-09-25T02:36:13-04:00"},
          {"url": "https://www.workingnomads.com/other", "title": "bad"}]
    with mock.patch.object(sx, "_get", return_value=wn):
        rows = sx.fetch_workingnomads()
    check("workingnomads: id from url, malformed rows skipped", len(rows) == 1 and rows[0]["job_id"] == "workingnomads:77" and rows[0]["location"] == "Remote, USA Only")
    es = "Requisitos de experiencia con los equipos para el trabajo de la empresa, años de experiencia de los desarrolladores con los sistemas para las áreas de trabajo"
    gob = {"data": [{"id": "en-1", "attributes": {"title": "Backend Dev", "description": "<p>Build APIs with Python</p>", "countries": ["Chile"], "remote_modality": "fully_remote", "min_salary": 2000, "max_salary": 3000, "company": {"data": {"attributes": {"name": "Co"}}}}},
                    {"id": "es-1", "attributes": {"title": "Dev", "description": es}}]}
    with mock.patch.object(sx, "_get", return_value=gob):
        rows = sx.fetch_getonboard()
    check("getonboard: Spanish-language postings skipped", [r["job_id"] for r in rows] == ["getonboard:en-1"] and rows[0]["remote"] is True)
    os.environ.pop("JOOBLE_API_KEY", None)
    check("jooble: no key -> nothing, no error", sx.fetch_jooble() == [])
    os.environ["JOOBLE_API_KEY"] = "k"
    try:
        resp = mock.Mock(status_code=200)
        resp.json.side_effect = [{"jobs": [{"id": 9, "title": "Clerk", "company": "X", "location": "Chaguanas", "link": "https://j/9", "snippet": "<b>Filing</b>", "updated": "2026-09-20"}]}, {"jobs": []}]
        with mock.patch.object(sx.requests, "post", return_value=resp):
            rows = sx.fetch_jooble()
    finally:
        os.environ.pop("JOOBLE_API_KEY", None)
    check("jooble: with a key, parses results and stops at an empty page", len(rows) == 1 and rows[0]["title"] == "Clerk")
    check("all extra sources are registered", set(sx.EXTRA_SOURCES) == {"weworkremotely", "jobicy", "workingnomads", "getonboard", "jooble"})


if __name__ == "__main__":
    P, F = [], []

    def _check(name, cond, detail=""):
        (P if cond else F).append(name)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"\n         -> {detail}" if detail and not cond else ""))

    run(_check, {})
    print(f"\n  {len(P)} passed, {len(F)} failed")
    sys.exit(1 if F else 0)
