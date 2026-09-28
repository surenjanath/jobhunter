# Job sources

## Trinidad & Tobago

| Source | How it is read |
|---|---|
| CaribbeanJobs | RSS across several keyword queries, then `JobPosting` JSON-LD on each page |
| JobsTT | sitemap (newest first) + JSON-LD |
| TrinidadJob | sitemap + JSON-LD |
| EmployTT (government) | listing page + detail pages |
| FindWorkTT | JSON API (placeholder `[DEMO]` rows are skipped) |
| IslandJobHunt | paginated T&T listing + JSON-LD |
| Caribbean Jobs Online | T&T listing + detail pages (slow server; partial results are normal) |
| Eve Anderson Recruitment | sitemap + detail pages (client is confidential) |
| Digicel careers | SuccessFactors sitemap, Trinidad postings only |

Every posting gets a stable id (from the site's own slug or id), a canonical **region** (`tt_geo.py`), a **category**, an
expiry date when the site gives one, and a description cleaned of HTML.

## Remote

Remotive, RemoteOK, Arbeitnow, Himalayas, Hacker News "Who is hiring", WeWorkRemotely (RSS), Jobicy, Working Nomads,
Get on Board (English postings only), and company boards on Greenhouse, Lever and Ashby (`company_boards` in
`profile.yaml`). Optional: Jooble (`JOOBLE_API_KEY`), which searches Trinidad & Tobago directly.

Remote postings state who they are open to; `matching.remote_scope` reads that (worldwide, Americas, US-only, …).

## Add an employer (the easy way)

**Trinidad page → Add an employer from its careers page.** Paste the careers URL. JobHunter looks for a Greenhouse,
Lever, Ashby, SmartRecruiters, Workable, Recruitee or Workday board and shows how many Trinidad & Tobago jobs it has right
now. Click **Add**. Only jobs located in Trinidad & Tobago are kept.

Or by hand in `profile.yaml`:

```yaml
trinidad_custom_sites:
  - {name: acme,  ats: greenhouse,     slug: acmeco,  label: Acme Ltd}
  - {name: bank,  ats: workday,        tenant: examplebank, wd: 3, site: external_careers}
  - {name: shop,  ats: smartrecruiters, slug: ExampleShop}
```

## Add a site that publishes JobPosting data

Most job boards publish [schema.org `JobPosting`](https://schema.org/JobPosting) JSON-LD on each posting. If a site has a
sitemap of its job pages:

```yaml
trinidad_custom_sites:
  - {name: example, sitemap: https://example.tt/job-sitemap.xml, url_pattern: "/jobs?/", company: Example Ltd}
  - {name: example2, list_url: https://example.tt/careers, url_pattern: "/careers/[a-z0-9-]+"}
```

Test it first with the form on the Trinidad page (it shows a sample without saving) or `POST /api/sources/custom/test/`.

## Write a new built-in source

1. Add `fetch_<name>(limit)` to `jobhunt/src/trinidad.py` (Trinidad) or `sources_extra.py` (remote). Return dicts through
   `trinidad.build_job(...)` so ids, regions, categories and expiry are consistent. Raise `SourceError` when the site is
   unreachable or its layout changed (that is what feeds the board-health table); return `[]` only when it genuinely has
   nothing.
2. Register it (`TT_SOURCES` or `EXTRA_SOURCES`), add a flag under `sources:` in `profile.example.yaml`, and a trust score
   in `score.SOURCE_TRUST`.
3. Add a fixture-based test in `jobhunt/tests/` and run `python jobhunt/live_check.py --source <name>` to audit the real site.

## What is deliberately not scraped

LinkedIn and Indeed. Their terms forbid automated access; use their email alerts. Please check a site's terms and
`robots.txt` before adding it.
