# API

JSON over HTTP, served by the Django app under `/api/`. No authentication (run it on localhost). Every endpoint
answers with JSON, including errors (`{"error": "..."}`), and works with or without a trailing slash.

## Jobs

| Method & path | What it does |
|---|---|
| `GET /api/jobs/` | Paginated jobs. Filters: `search`, `source`, `tier`, `min_score`, `mode=local\|remote\|abroad\|hybrid\|onsite`, `local=1`, `remote`, `region`, `category`, `company`, `remote_scope`, `min_likelihood`, `posted_within`, `closing_within`, `has_salary`, `status`, `starred`, `hide_blockers`. `sort=fit\|likelihood\|chance\|recent\|new\|closing\|company\|title`, `page_size` (max 200) |
| `GET /api/jobs/export/` | CSV of the filtered list |
| `GET /api/jobs/<id>/` | One job with likelihood and technology breakdown |
| `GET /api/jobs/<id>/match/` | Deep, explainable match: requirement evidence, skills, factors, tailoring, rank among your listings, posting highlights |
| `GET /api/jobs/<id>/ats/` `interview/` `salary/` `ai-match/` `tailor/` | The per-job analysis tabs, built from your resume and the posting |
| `PUT /api/jobs/<id>/status/` | `{status, notes, applied_date, followup_date}` |
| `POST /api/jobs/<id>/star/` | Toggle, or `{"starred": true}` |
| `POST /api/jobs/bulk-status/` | `{job_ids: [...], status}` |
| `GET /api/followups/` | Overdue / upcoming follow-ups and tracked jobs closing soon |
| `GET /api/pipeline/` | Funnel counts and interview rate |
| `GET /api/calendar.ics` | Follow-ups and closing dates as an iCalendar feed |
| `GET /api/digest/` | New roles worth your time (`days`, `min_fit`, `limit`, `fmt=md`) |

## Resume, preferences, scoring

| Method & path | What it does |
|---|---|
| `GET /api/profile/` | Effective profile, preferences, calibration, versions, embedding status |
| `POST /api/profile/resume/` | Multipart `file` (PDF/DOCX/MD/TXT) or JSON `{text, filename}` |
| `POST /api/profile/overrides/` | `{add_skills, remove_skills, restore_skills, skill_years, years_experience, target_titles}` |
| `GET/PUT /api/profile/prefs/` | Work mode, salary floors, regions, avoid list… |
| `POST /api/profile/reindex/` | Recompute embeddings (after installing an embedding model) |
| `POST /api/profile/enrich/` | Optional AI read of the resume (`{provider}`); the text goes to that provider |
| `POST /api/profile/versions/<id>/activate/`, `DELETE /api/profile/versions/<id>/` | Manage resume versions |
| `POST /api/rescore/` | Re-score every stored job (background; `{"wait": true}` to block). `GET` reports progress |

## Sources, market, analytics

| Method & path | What it does |
|---|---|
| `GET /api/sources/` | Every board: enabled, last scan result, job count |
| `POST /api/sources/<name>/test/` | Run one board live and return a sample (nothing saved) |
| `POST /api/sources/detect/` | `{url}`: find the ATS behind an employer's careers page |
| `GET/POST/DELETE /api/sources/custom/`, `POST .../custom/test/` | Manage custom sites |
| `GET /api/local/`, `/api/local/employers/` | Local market summary |
| `GET /api/insights/` | Everything the Analytics page draws |
| `GET /api/brief/`, `/api/coach/brief/` | Home-page brief and daily coach text |

## Running the scanner

| Method & path | What it does |
|---|---|
| `POST /api/scan/` | `{dry_run: true\|false}` start a scan in the background |
| `GET /api/logs/?since=N` | Stream the running task's output |
| `POST /api/live-check/`, `/api/tests/` | Audit real sources / run the test suite |
| `GET /api/state/`, `/api/stats/`, `/health/` | App state, counts, health |
| `GET/PUT /api/settings/`, `POST /api/provider/` | Settings and the cover-letter provider |
