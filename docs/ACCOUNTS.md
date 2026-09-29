# Accounts

JobHunter stays usable with no account at all — upload a resume, get scored, track a pipeline, exactly as
before. An account is purely additive: email + password (Django's own auth, hashed with PBKDF2, session
cookies), so a resume, its fit/odds scores and a pipeline can be saved under a login and picked up again later,
on any device, instead of living in the one shared instance-wide profile every install starts with.

## The model

- **Job listings stay shared.** Postings are the same for everyone; there's no reason to scan the internet once
  per account. The `jobs` table (in `jobhunt.db`, the scanner's own database) is untouched by any of this.
- **Your resume, preferences and pipeline are private per account**, in three new tables in Django's own
  database (`db.sqlite3`), never in `jobhunt.db`:
  - `UserProfile` — the parsed resume (what `matching.get_context()` needs) plus preferences (target titles,
    salary floor, work mode, regions). One per account; re-uploading replaces it.
  - `UserJobStatus` — status, star, notes, follow-up date, dismiss reason: the private analogue of the shared
    `app_status` table, one row per (account, job).
  - `UserJobMatch` — a cache of fit/odds against *this* account's resume, one row per (account, job). Refreshed
    by `accounts.context.rescore_user()` right after a resume or preferences change, and by opening a job's
    Match tab (which also updates that one job's cached row).
- **Guest mode is unaffected.** Everywhere these tables get consulted, an unauthenticated request falls back to
  exactly what ran before accounts existed — the shared `profile.yaml`/resume and the shared `app_status` table.
  `jobs.queries.serialize()`'s `UNSET` sentinel is what makes this safe: a guest passes nothing and gets the
  shared data; a signed-in request always passes its own row *or `None`* — `None` means "this account has
  nothing for this job" and renders as New/unstarred, and must never fall through to the shared table (an
  earlier bug did exactly that for a moment during development: a brand new account's `/api/state/` response
  showed the shared/anonymous pipeline's star and status until `jobs/views.py`'s `state()` view was given the
  same per-account overlay as everything else — see `accounts/tests.py`'s
  `test_state_endpoint_is_private_per_account` for the regression test).

## What's fully personalized

Resume upload, preferences, rescoring, the Ledger (`/api/jobs/`, and `/api/state/` — what the frontend's `JOBS`
array actually loads from), the Match tab, `followups`, `pipeline`, star/status/notes/dismiss-reason, and the
"Tech / Needs / ATS / Interview / Salary" tabs' headline fit score.

## Known gaps (documented, not silently skipped)

- **CSV export** (`/api/jobs/export/`) always uses the shared scan's data, for every account.
- **The deeper analysis** behind the Tech/Needs/ATS/Interview/Salary tabs (keyword matching, generated interview
  questions, salary comparison) and **cover letter drafting** still read the shared instance-wide resume, even
  for a signed-in account with its own resume — only the headline fit score on those tabs is personalized. The
  Match tab is the one place that's fully personalized end to end.
- **AI features** (`ai/views.py` — summary, rewrite, practice, outreach, recommendations, resume review, ask,
  roadmap) and **Analytics** are not account-aware; they operate on the shared instance-wide resume for every
  request, signed in or not.
- **Multi-version resume history**, **manual overrides** (correcting extracted skills), **re-indexing with an
  embedding model**, and **LLM resume enrichment** are features of the shared/anonymous profile only. An
  account's resume is a single version with keyword (BM25) retrieval; no embeddings, no override diffing.
- **Sorting and pagination** in the Ledger still order by the shared scan's fit score, even when signed in — a
  signed-in account's own fit/odds numbers shown per row are correct, but *which* jobs land on page 1 vs page 2
  follows the shared ranking. Fixing this properly needs a cross-database query (SQLite's `ATTACH DATABASE`,
  since `jobs` and `UserJobMatch` live in two separate files) and wasn't attempted here.
- **No email verification, no password-reset-by-email.** This project ships with no outbound mail configured —
  it's a local-first tool, not a hosted service. A forgotten password today means asking whoever runs the
  Django admin (`/admin/`) to reset it by hand.

## Extending an account-aware view

The pattern used throughout `jobs/views.py` and `candidate/views.py`:

```python
from accounts.context import overlay_for
status_map, match_map = overlay_for(request, [job_ids...])
queries.serialize(job, status_map.get(job.job_id), match_map.get(job.job_id))
```

`overlay_for` returns real lookup dicts for a signed-in request, or dicts that always report `UNSET` for a
guest — so the same call works unchanged either way. For scoring against an account's own resume directly (not
through `serialize()`), use `accounts.context.matching_context(request)` in place of `src.matching.current_context()`.
