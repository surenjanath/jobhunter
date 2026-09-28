"""
test_pipeline.py — offline test suite.

Intercepts requests.get and serves fixture payloads shaped like each board's
real API response, then runs the actual production parsers against them.

    python tests/test_pipeline.py

No network, no credentials, no Google account needed.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import src  # noqa: E402,F401  (first-run: creates config/*.yaml from the *.example templates)

# Use a temp DB for tests so live data is not polluted
import os
os.environ["JOBHUNT_DB"] = str(ROOT / "output" / ".test.db")
# Clean any stale test DB
try:
    (ROOT / "output" / ".test.db").unlink()
    (ROOT / "output" / ".test.db-shm").unlink(missing_ok=True)
    (ROOT / "output" / ".test.db-wal").unlink(missing_ok=True)
except Exception:
    pass

import yaml  # noqa: E402

from tests import fixtures  # noqa: E402

PASS, FAIL = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(name)
    mark = "PASS" if condition else "FAIL"
    line = f"  [{mark}] {name}"
    if detail and not condition:
        line += f"\n         -> {detail}"
    elif detail:
        line += f"  ({detail})"
    print(line)


# ---------------------------------------------------------------------------
# fake network
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.content = json.dumps(payload).encode()

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


CALLS: list[str] = []


def fake_get(url, params=None, headers=None, timeout=None):
    CALLS.append(url)
    # Longest fragment first so /jobs/<id> beats /jobs.
    for fragment, payload in sorted(
        fixtures.ROUTES.items(), key=lambda kv: -len(kv[0])
    ):
        if fragment in url:
            # Greenhouse/Lever/Ashby: only the first configured token resolves,
            # the rest 404 — mirrors reality, where some tokens are stale.
            if any(k in url for k in ("greenhouse", "lever", "ashby")):
                token_ok = any(
                    t in url for t in ("anthropic", "palantir", "baseten")
                )
                if not token_ok:
                    return FakeResponse({}, status=404)
            return FakeResponse(payload)
    return FakeResponse({}, status=404)


# ---------------------------------------------------------------------------

def load_cfg() -> dict:
    """The real profile, but with every fixture-backed board on and live Trinidad boards off.

    The user's profile.yaml toggles sources from the UI, so tests must not depend on it.
    """
    with open(ROOT / "config" / "profile.yaml", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg["sources"] = {k: True for k in ("remotive", "remoteok", "arbeitnow", "himalayas", "hn_whoishiring",
                                        "greenhouse", "lever", "ashby")}
    cfg["sources"]["trinidad"] = False
    return cfg


def test_parsers(cfg: dict) -> list[dict]:
    print("\n1. SOURCE PARSERS (real parser code, fixture payloads)")
    from src import sources

    with mock.patch.object(sources.requests, "get", side_effect=fake_get), \
         mock.patch.object(sources.time, "sleep"):
        rows = sorted(sources.fetch_all(cfg), key=lambda r: r["job_id"])  # parallel fetch order is not deterministic

    by_source = {}
    for r in rows:
        by_source.setdefault(r["source"].split(":")[0], []).append(r)

    for expected in (
        "remotive", "remoteok", "arbeitnow", "himalayas",
        "hn_whoishiring", "greenhouse", "lever", "ashby",
    ):
        got = by_source.get(expected, [])
        check(f"{expected} parsed", len(got) > 0, f"{len(got)} rows")

    # RemoteOK's first element is a legal notice with no "position" key.
    ok_rows = by_source.get("remoteok", [])
    check(
        "remoteok skips legal-notice row",
        all(r["title"] for r in ok_rows) and len(ok_rows) == 1,
        f"{len(ok_rows)} row(s), titles={[r['title'] for r in ok_rows]}",
    )

    check("every row has a URL", all(r.get("url") for r in rows))
    check("every row has a job_id", all(r.get("job_id") for r in rows))
    check("every row has a title", all(r.get("title") for r in rows))
    check(
        "descriptions are HTML-stripped",
        not any("<p>" in (r.get("description") or "") for r in rows),
    )
    check(
        "HTML entities decoded (greenhouse double-encodes)",
        not any("&lt;" in (r.get("description") or "") for r in rows),
    )

    # Date normalisation is the classic silent failure.
    bad_dates = [
        (r["source"], r["posted_at"])
        for r in rows
        if r["posted_at"] and not r["posted_at"].startswith("202")
    ]
    check("all posted_at dates normalise to ISO", not bad_dates, str(bad_dates))

    missing_dates = [r["source"] for r in rows if not r["posted_at"]]
    check(
        "no source silently loses its date",
        not missing_dates,
        f"sources with empty posted_at: {missing_dates}",
    )

    check("404 boards degrade quietly", len(rows) > 0, f"{len(CALLS)} HTTP calls made")

    # --- regressions locked down by live API behaviour (verified 2026-08-10) ---
    gh = [r for r in rows if r["source"].startswith("greenhouse")]
    check(
        "greenhouse fetches per-job content (list endpoint has none)",
        gh and len(gh[0]["description"]) > 200,
        f"desc={len(gh[0]['description']) if gh else 0} chars",
    )
    check(
        "greenhouse triple-encoded HTML fully decoded",
        gh and "&lt;" not in gh[0]["description"] and "<" not in gh[0]["description"],
        (gh[0]["description"][:70] if gh else ""),
    )
    check(
        "greenhouse uses company_name, not the board token",
        gh and gh[0]["company"] == "Anthropic",
        (gh[0]["company"] if gh else ""),
    )
    check(
        "greenhouse title pre-filter skips irrelevant roles",
        all("Office Manager" != r["title"] for r in gh),
        str([r["title"] for r in gh]),
    )
    check(
        "greenhouse picks up Remote from metadata",
        gh and gh[0]["remote"] is True,
    )

    check(
        "HN uses search_by_date (relevance search returns a 2020 thread)",
        any("search_by_date" in c for c in CALLS),
    )
    check(
        "HN resolved the CURRENT thread, not a stale one",
        any("49156683" in c for c in CALLS),
        str([c for c in CALLS if "items" in c]),
    )
    return rows


def test_resilience(cfg: dict) -> None:
    print("\n2. RESILIENCE")
    from src import sources

    def exploding_get(*a, **k):
        raise ConnectionError("simulated total network failure")

    with mock.patch.object(sources.requests, "get", side_effect=exploding_get), \
         mock.patch.object(sources.time, "sleep"):
        rows = sources.fetch_all(cfg)
    check("total network failure returns [] not a crash", rows == [])

    def half_broken(url, **k):
        if "remoteok" in url or "lever" in url:
            raise ConnectionError("simulated board outage")
        return fake_get(url, **k)

    with mock.patch.object(sources.requests, "get", side_effect=half_broken), \
         mock.patch.object(sources.time, "sleep"):
        rows = sources.fetch_all(cfg)
    srcs = {r["source"].split(":")[0] for r in rows}
    check(
        "one dead board does not kill the run",
        len(rows) > 0 and "remoteok" not in srcs,
        f"surviving sources: {sorted(srcs)}",
    )

    with mock.patch.object(sources.requests, "get", return_value=FakeResponse({"jobs": None})), \
         mock.patch.object(sources.time, "sleep"):
        rows = sources.fetch_all(cfg)
    check("malformed payload (null jobs) handled", isinstance(rows, list))


def test_scoring(rows: list[dict], cfg: dict) -> list[dict]:
    print("\n3. SCORING & RANKING")
    from src import score

    ranked = score.rank(rows, cfg)
    check("ranking produced results", len(ranked) > 0, f"{len(ranked)} of {len(rows)} kept")
    check(
        "sorted by fit descending",
        all(ranked[i]["fit_score"] >= ranked[i + 1]["fit_score"] for i in range(len(ranked) - 1)),
    )

    # Two boards carry an FDE role, so key on the best-scoring one per title.
    titles: dict[str, dict] = {}
    for r in ranked:
        if r["title"] not in titles or r["fit_score"] > titles[r["title"]]["fit_score"]:
            titles[r["title"]] = r
    dropped = {r["title"] for r in rows} - set(titles)

    check(
        "US-citizens-only + 10yrs + k8s role rejected",
        "Site Reliability Engineer" not in titles,
        f"dropped: {sorted(dropped)}",
    )

    fde = titles.get("Forward Deployed Engineer")
    check("FDE role kept", fde is not None)
    if fde:
        check("best FDE scores Tier 1", fde["fit_score"] >= 65, f"score={fde['fit_score']}")

    ins = titles.get("Senior Python Engineer")
    if ins:
        check(
            "insurance domain bonus applied",
            "insurance" in ins["why"],
            ins["why"][:80],
        )

    applied_ai = titles.get("Applied AI Engineer")
    if applied_ai:
        check(
            "evals gap flagged on AI role",
            "eval" in applied_ai["flags"].lower(),
            applied_ai["flags"][:90],
        )

    # Dedupe: same company+title from two boards should collapse to one.
    dupes = rows + [dict(rows[0], source="other", job_id="dup:1", description="short")]
    deduped = score.dedupe(dupes)
    check(
        "dedupe collapses cross-board duplicates",
        len(deduped) == len(score.dedupe(rows)),
        f"{len(dupes)} -> {len(deduped)}",
    )
    ats = dict(rows[0], source="ashby:acme", job_id="ats:1",
               url="https://jobs.ashbyhq.com/acme/xyz", description="short but official")
    picked = score.dedupe([rows[0], ats])
    same = [j for j in picked if j["title"] == rows[0]["title"]][0]
    check(
        "dedupe prefers the company ATS link over the aggregator",
        "ashbyhq.com" in same["url"],
        same["url"][:60],
    )
    check(
        "losing listing is preserved in alt_urls",
        rows[0]["url"] in (same.get("alt_urls") or ""),
    )
    check(
        "dedupe keeps the richer description",
        max(len(j["description"]) for j in deduped if j["title"] == rows[0]["title"])
        == len(rows[0]["description"]),
    )

    # A year-old posting that scores well on keywords must still be dropped.
    stale = [r for r in rows if r["title"] == "Solutions Engineer, Legacy"]
    check("stale fixture present in raw fetch", len(stale) == 1)
    if stale:
        s = score.score_job(dict(stale[0]), cfg)
        check(
            "stale posting would score above threshold",
            s["fit_score"] >= cfg["min_score_to_include"],
            f"score={s['fit_score']}",
        )
        check(
            "but age filter drops it",
            "Solutions Engineer, Legacy" not in {r["title"] for r in ranked},
        )

    check(
        "lever epoch-in-milliseconds parsed to the right year",
        any(r["posted_at"].startswith("2026") for r in rows if r["source"].startswith("lever")),
        str([r["posted_at"] for r in rows if r["source"].startswith("lever")]),
    )

    scores = [r["fit_score"] for r in ranked]
    check(
        "score distribution is not saturated",
        len(set(scores)) > 1 and max(scores) <= 100,
        f"range {min(scores)}-{max(scores)}",
    )
    return ranked


def test_sheets_upsert(ranked: list[dict]) -> None:
    """
    The single most important guarantee: a refresh must never clobber the
    Status / Applied Date / Notes columns you filled in by hand.
    """
    print("\n4. GOOGLE SHEETS UPSERT (fake gspread client)")
    from src import sheets

    job = ranked[0]
    user_data = ["Applied", "2026-08-01", "cover_x.md", "2026-08-15", "Spoke to Dana"]
    header_row = list(sheets.HEADERS)
    existing_row = [
        job["job_id"], "2026-07-20", 10, "stale tier", "stale title",
        "stale co", "", "", "", "", "", "", "", "",
    ] + user_data

    class FakeWorksheet:
        id = 1
        def __init__(self):
            self.rows = [header_row, existing_row]
            self.batch_updates = []
            self.appended = []
            self.spreadsheet = mock.MagicMock()
        def row_values(self, n): return self.rows[n - 1]
        def get_all_values(self): return self.rows
        def update(self, **kw): pass
        def format(self, *a, **k): pass
        def freeze(self, **k): pass
        def batch_update(self, data, **k): self.batch_updates.extend(data)
        def append_rows(self, rows, **k): self.appended.extend(rows)

    ws = FakeWorksheet()
    with mock.patch.object(sheets, "_client", return_value=mock.MagicMock()), \
         mock.patch.object(sheets, "_open_sheet", return_value=ws), \
         mock.patch.object(sheets, "_apply_formatting"):
        result = sheets.sync(ranked, "fake-sheet-id")

    check("existing job updated, not duplicated", result["updated"] == 1, str(result))
    check("new jobs appended", result["new"] == len(ranked) - 1, str(result))

    ranges = [u["range"] for u in ws.batch_updates]
    check(
        "bot writes only columns A:M",
        all(r.split(":")[1].rstrip("0123456789") == "N" for r in ranges),
        str(ranges),
    )
    check(
        "user columns O:S never in a write range",
        not any(c in "".join(ranges) for c in "OPQRS"),
        str(ranges),
    )

    updated_vals = ws.batch_updates[0]["values"][0]
    check("stale bot data refreshed", updated_vals[4] != "stale title", updated_vals[4][:40])
    check(
        "First Seen preserved from original row",
        updated_vals[1] == "2026-07-20",
        f"got {updated_vals[1]}",
    )
    check("update row length is exactly 14 (A:N)", len(updated_vals) == 14, str(len(updated_vals)))

    if ws.appended:
        check("new rows default to Status=New", ws.appended[0][14] == "New")
        check("new rows are full width (19 cols)", len(ws.appended[0]) == 19, str(len(ws.appended[0])))
        check(
            "new rows appended highest-fit first",
            ws.appended[0][2] >= ws.appended[-1][2],
        )
    check(
        "link cell is a clickable HYPERLINK formula",
        updated_vals[10].startswith('=HYPERLINK("http'),
        updated_vals[10][:50],
    )


def test_cover_letters(ranked: list[dict]) -> None:
    print("\n5. COVER LETTERS (template path, no API key)")
    from src import cover_letter

    profile = cover_letter.load_profile()
    fact_bank = cover_letter.load_fact_bank()
    check("fact bank loads", len(fact_bank) > 2000, f"{len(fact_bank)} chars")

    banned = [
        "passionate", "thrilled", "rockstar", "10x", "world-class",
        "obsessed", "cutting-edge", "perfect fit", "elite",
    ]

    tested = 0
    for job in ranked[:5]:
        text = cover_letter.generate_with_template(job, profile)
        tested += 1
        low = text.lower()
        hits = [w for w in banned if w in low]
        check(f"no hype words: {job['title'][:34]}", not hits, str(hits))
        body = text.split("---")[0]
        check(f"under 300 words: {job['title'][:34]}", len(body.split()) < 300, f"{len(body.split())} words")
        check(f"no em dash: {job['title'][:34]}", "—" not in body)

    ai_job = next((j for j in ranked if "AI" in j["title"] or "Forward" in j["title"]), ranked[0])
    text = cover_letter.generate_with_template(ai_job, profile)
    # Status wording in the candidate's own material ("in testing", "in pilot") is kept verbatim, so what must never
    # appear is a bare claim that something IS in production when the source said it is not yet.
    import re as _re
    overclaim = _re.search(r"(?<!not yet )(?<!not )in production", text) if _re.search(r"in testing|in pilot", text) else None
    check("letter never turns 'in testing / pilot' into 'in production'", overclaim is None, f"overclaim: {overclaim.group(0) if overclaim else None}")
    cand = profile["candidate"]
    check("location / timezone / work-authorisation text from the profile is included",
          cand["timezone"] in text and ("employer of record" in text.lower()) == ("employer of record" in (cand.get("work_authorization") or "").lower()))
    check("letter is signed with the profile's name", cand["name"] in text)
    check("template draft is clearly labelled", "TEMPLATE DRAFT" in text)
    gap_job = dict(ai_job, description="Requirements\n- 5 years of Rust and Haskell in production\n- Strong Python")
    t = cover_letter.generate_with_template(gap_job, profile)
    check("a required skill the candidate lacks is acknowledged honestly, not claimed",
          "I haven't used" in t and "Rust" in t, t[-420:-200].strip()[:90])
    check("evidence comes from the candidate's own material", len(cover_letter.candidate_material()[0]) >= 2)

    from src import llm
    avail = llm.describe()
    print(f"         backends: " + ", ".join(
        f"{k}={'yes' if v['available'] else 'no'}" for k, v in avail.items()))
    check("template is always available as a floor", avail["template"]["available"])
    check(
        "no backend reachable here, so template path is used",
        cover_letter.generate_with_llm(ranked[0], fact_bank, {})[0] is None
        or any(v["available"] for k, v in avail.items() if k != "template"),
    )
    check("pinning provider=template short-circuits the LLMs",
          cover_letter.generate_with_llm(ranked[0], fact_bank, {"provider": "template"})[0] is None)
    check("fence stripping cleans local-model output",
          llm._strip_fences("```\nHello,\n\nBody text here.\n```") == "Hello,\n\nBody text here.")
    check("preamble stripping cleans local-model output",
          llm._strip_fences("Here is the cover letter:\n\nHello,").startswith("Hello,"))
    print(f"         ({tested} letters generated)")


def test_end_to_end(cfg: dict) -> None:
    print("\n6. END-TO-END (src.run --dry-run)")
    from src import run as runner, sources

    argv = sys.argv
    sys.argv = ["run", "--dry-run", "--limit", "10"]
    try:
        with mock.patch.object(sources.requests, "get", side_effect=fake_get), \
             mock.patch.object(sources.time, "sleep"), \
             mock.patch.object(runner, "load_config", return_value=cfg):
            code = runner.main()
    finally:
        sys.argv = argv

    check("run.main() exits 0", code == 0, f"exit={code}")

    out = ROOT / "output"
    js, csv_ = out / "jobs_latest.json", out / "jobs_latest.csv"
    check("jobs_latest.json written", js.exists())
    check("jobs_latest.csv written", csv_.exists())

    if js.exists():
        data = json.loads(js.read_text())
        check("JSON cache is a non-empty list", isinstance(data, list) and data, f"{len(data)} jobs")
        needed = {"job_id", "title", "company", "url", "fit_score", "tier", "why", "flags"}
        check("every cached job has the full schema", all(needed <= set(j) for j in data))

        from src import cover_letter
        found = cover_letter.find_job(data[0]["job_id"])
        check("cover_letter can look up a cached job by id", found is not None)
        if found:
            _text, path, _backend = cover_letter.generate(found)
            check("letter written to disk", path.exists(), path.name)
            head = path.read_text()[:400]
            check("letter file has posting link + fit header", "Posting:" in head and "Fit score:" in head)


LD_PAGE = """<html><head><script type="application/ld+json">{
 "@context":"https://schema.org","@type":"JobPosting","title":"Python Developer",
 "datePosted":"%(posted)s","validThrough":"%(valid)s",
 "hiringOrganization":{"@type":"Organization","name":"Acme Ltd"},
 "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Port-of-Spain","addressRegion":"Port of Spain"}},
 "baseSalary":{"@type":"MonetaryAmount","currency":"TTD","value":{"@type":"QuantitativeValue","minValue":12000,"maxValue":15000,"unitText":"MONTH"}},
 "description":"&lt;p&gt;Build Django &amp;amp; REST APIs.&lt;/p&gt;"}</script></head></html>"""


def test_trinidad(cfg: dict) -> None:
    print("\n7. TRINIDAD & TOBAGO SOURCES (shared JSON-LD parser, ids, expiry, health, geo)")
    from src import trinidad as tt, tt_geo, score, db

    today = date.today()
    fresh = LD_PAGE % {"posted": today.isoformat(), "valid": (today.replace(year=today.year + 1)).isoformat()}
    stale = LD_PAGE % {"posted": "2020-01-01", "valid": "2020-02-01"}

    ld = tt.jobposting_ld(fresh)
    check("JSON-LD JobPosting is found in a page", bool(ld) and ld["title"] == "Python Developer")
    graph = '<script type="application/ld+json">{"@graph":[{"@type":"WebPage"},{"@type":"JobPosting","title":"X"}]}</script>'
    check("JobPosting inside @graph is found", (tt.jobposting_ld(graph) or {}).get("title") == "X")
    job = tt.job_from_ld(ld, source="jobstt", key="python-developer", url="https://jobstt.com/job/python-developer")
    check("job dict has stable id, company, region, salary",
          job and job["job_id"] == "jobstt:python-developer" and job["company"] == "Acme Ltd"
          and job["region"] == "Port of Spain" and "TT$12,000" in job["salary"], str(job and job["salary"]))
    check("double-escaped description is cleaned", job and "Django & REST" in job["description"] and "<" not in job["description"])
    check("expired posting is dropped",
          tt.job_from_ld(tt.jobposting_ld(stale), source="jobstt", key="old", url="u") is None)
    check("location always names Trinidad & Tobago", job and "Trinidad & Tobago" in job["location"])

    # deterministic ids: same input across processes must give the same id
    a = tt.build_job(source="x", key=tt.slug_from_url("https://x.tt/job/Some-Role/"), title="Some Role", company="C", url="u")
    check("slug ids are deterministic", a["job_id"] == "x:some-role")

    # sitemap ordering (newest first) and filtering
    sm = ("<urlset><url><loc>https://jobstt.com/job/old</loc><lastmod>2026-01-01</lastmod></url>"
          "<url><loc>https://jobstt.com/</loc></url>"
          "<url><loc>https://jobstt.com/job/new</loc><lastmod>2026-09-01</lastmod></url></urlset>")
    with mock.patch.object(tt, "fetch", return_value=sm):
        ents = tt.sitemap_entries("s", r"/job/[^/]+$")
    check("sitemap entries: filtered + newest first", [e[0].rsplit("/", 1)[1] for e in ents] == ["new", "old"], str(ents))

    # a whole board through the shared pipeline
    sm2 = f"<urlset><url><loc>https://jobstt.com/job/python-developer</loc><lastmod>{today.isoformat()}</lastmod></url></urlset>"

    def fake_fetch(url, params=None, **kw):
        return sm2 if url.endswith(".xml") else fresh

    with mock.patch.object(tt, "fetch", side_effect=fake_fetch):
        rows = tt.fetch_jobstt(10)
        check("fetch_jobstt end-to-end", len(rows) == 1 and rows[0]["source"] == "jobstt")

        # health tracking
        got = tt.run_source("jobstt", lambda: tt.fetch_jobstt(10), "JobsTT")
        h = tt.HEALTH["jobstt"]
        check("run_source records ok health", h["ok"] and h["count"] == 1 and len(got) == 1)

    with mock.patch.object(tt, "fetch", return_value=None):
        tt.run_source("jobstt", lambda: tt.fetch_jobstt(10), "JobsTT")
        check("unreachable board is reported, not raised", not tt.HEALTH["jobstt"]["ok"] and tt.HEALTH["jobstt"]["error"])

    # layout drift: many links, nothing parses
    many = "<urlset>" + "".join(f"<url><loc>https://jobstt.com/job/j{i}</loc></url>" for i in range(8)) + "</urlset>"
    with mock.patch.object(tt, "fetch", side_effect=lambda u, p=None, **k: many if u.endswith(".xml") else "<html/>"):
        tt.run_source("jobstt", lambda: tt.fetch_jobstt(10), "JobsTT")
        check("layout drift is flagged", not tt.HEALTH["jobstt"]["ok"] and "parsed 0" in tt.HEALTH["jobstt"]["error"])

    # custom site by sitemap
    with mock.patch.object(tt, "fetch", side_effect=lambda u, p=None, **k: sm2.replace("jobstt.com", "acme.tt") if u.endswith(".xml") else fresh):
        rows = tt.fetch_custom_site({"name": "Acme TT", "sitemap": "https://acme.tt/sitemap.xml", "url_pattern": "/job/"}, 5)
        check("custom sitemap site works", len(rows) == 1 and rows[0]["source"] == "acmett")

    # findworktt demo filtering
    demo = json.dumps({"jobs": [{"id": "1", "title": "[DEMO] role", "description": "DEMO DATA ONLY", "location": "San Juan"}]})
    with mock.patch.object(tt, "fetch", return_value=demo):
        check("findworktt skips [DEMO] rows", tt.fetch_findworktt(10) == [])

    # geography + categories
    check("region: hyphenated / multi-place strings", tt_geo.normalize_region("Chaguanas,Port-of-Spain,San Fernando") == "Chaguanas / Caroni")
    check("region: St Augustine belongs to Tunapuna/Piarco", tt_geo.normalize_region("St. Augustine/ Tunapuna") == "Tunapuna / Piarco")
    check("region: unknown -> nationwide", tt_geo.normalize_region("Nationwide") == "Trinidad & Tobago")
    check("category: legal beats engineering on 'civil litigation'", tt_geo.classify_category("Attorney-at-Law – Civil Litigation") == "Legal & Compliance")
    check("category: tech", tt_geo.classify_category("Senior Python Developer") == "Technology")

    # scoring: a local, non-tech role is kept but must not score high on geography alone
    barista = dict(job, title="Barista", description="Serve coffee in Port of Spain, Trinidad and Tobago. Entry level.", salary="")
    ranked = score.rank([barista], dict(cfg, keep_all_trinidad=True))
    check("local job is kept (keep_all_trinidad)", len(ranked) == 1)
    check("geography alone does not inflate fit", ranked and ranked[0]["fit_score"] < 35, str(ranked and ranked[0]["fit_score"]))
    check("keep_all_trinidad=false filters it out", score.rank([dict(barista)], dict(cfg, keep_all_trinidad=False)) == [])
    dev = dict(job, title="Django Developer", description="Python Django REST API developer in Port of Spain, Trinidad and Tobago")
    r = score.rank([dev], cfg)
    check("relevant local job still scores high", r and r[0]["fit_score"] >= 50, str(r and r[0]["fit_score"]))
    ag = dict(job, title="Direct Sales Agent", description="Sales agent for retail store. Port of Spain, Trinidad")
    check("'sales agent' is not an AI-agent signal", "agent" not in (score.score_job(dict(ag), cfg)["why"]))

    # db: migration, persistence of local fields, health, purge
    db.upsert_jobs([dict(job, fit_score=50, tier="t", why="", flags="", expires_at="2020-01-01")])
    row = db.get_job(job["job_id"])
    check("db stores region/category/expires_at", row and row["region"] == "Port of Spain" and row["expires_at"] == "2020-01-01")
    db.record_source_runs([{"name": "jobstt", "label": "JobsTT", "ok": False, "count": 0, "ms": 5, "error": "boom"}])
    check("db source health round-trips", db.source_health()["jobstt"]["error"] == "boom")
    check("purge_expired removes closed untracked postings", db.purge_expired() >= 1 and db.get_job(job["job_id"]) is None)


def main() -> int:
    print("=" * 74)
    print("  jobhunt — offline test suite")
    print("  (job board endpoints are unreachable from this sandbox;")
    print("   parsers run against fixtures matching each board's real shape)")
    print("=" * 74)

    # Backup live output so tests don't clobber it
    out = ROOT / "output"
    backup_json = out / "jobs_latest.json.bak"
    backup_csv = out / "jobs_latest.csv.bak"
    backup_db = Path(os.environ.get("JOBHUNT_DB", str(out / ".test.db")))
    # backup real json if exists
    has_backup = False
    try:
        if (out / "jobs_latest.json").exists():
            (out / "jobs_latest.json").rename(backup_json)
            if (out / "jobs_latest.csv").exists():
                (out / "jobs_latest.csv").rename(backup_csv)
            has_backup = True
    except Exception:
        pass

    # Cover letters written by the e2e test must not clobber or add to the user's real letters.
    letters_before = {p: p.read_bytes() for p in out.glob("cover_*.md")}

    try:
        cfg = load_cfg()
        rows = test_parsers(cfg)
        test_resilience(cfg)
        ranked = test_scoring(rows, cfg)
        test_sheets_upsert(ranked)
        test_cover_letters(ranked)
        test_end_to_end(cfg)
        test_trinidad(cfg)
        from tests import test_profile
        test_profile.run(check, cfg)
        from tests import test_sources
        test_sources.run(check, cfg)
        from tests import test_ai
        test_ai.run(check, cfg)
    finally:
        for p in out.glob("cover_*.md"):
            if p not in letters_before:
                p.unlink(missing_ok=True)
        for p, data in letters_before.items():
            if not p.exists() or p.read_bytes() != data:
                p.write_bytes(data)
        # Restore live output
        try:
            if has_backup and backup_json.exists():
                backup_json.rename(out / "jobs_latest.json")
                if backup_csv.exists():
                    backup_csv.rename(out / "jobs_latest.csv")
            # Clean test DB
            for p in [backup_db, Path(str(backup_db)+"-shm"), Path(str(backup_db)+"-wal"), Path(str(backup_db)+"-journal")]:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
            # Also clean any cover letters created during test (they have today's date and test job_ids)
            for p in (out).glob("cover_*.md"):
                # Keep the two original covers from Aug 10, remove test-generated ones that contain fixture job_ids
                if "sierra-forward-deployed" in p.name and p.stat().st_mtime > backup_json.stat().st_mtime if backup_json.exists() else False:
                    pass # keep live ones
        except Exception:
            pass

    print("\n" + "=" * 74)
    print(f"  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("\n  Failures:")
        for f in FAIL:
            print(f"    - {f}")
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
