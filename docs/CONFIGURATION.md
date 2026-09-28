# Configuration

## Files (`jobhunt/config/`)

Created from the `*.example*` templates on first run. They are git-ignored, so your details stay local.

| File | Purpose |
|---|---|
| `profile.yaml` | Candidate details, target titles, keyword scoring weights, which sources are on, cover-letter provider, saved preferences, custom sites |
| `fact_bank.md` | The only facts the cover-letter generator may use (write it flat and honest) |
| `form_answers.md` | Copy-paste answers for application forms |
| `ui_settings.json` | Display preferences (remote / links / salary visibility) |

Most of `profile.yaml` can be edited in the app: **Settings** (sources, thresholds, provider) and **Profile**
(preferences, target titles, skills).

### `profile.yaml` keys

```yaml
candidate:            # used in cover letters and the "location / work authorisation" paragraph
  name: ...
  location: Port of Spain, Trinidad & Tobago
  timezone: UTC-4
  work_authorization: ...
targets:              # title keywords that earn a title-match bonus in the keyword pass
  tier_1: [solutions engineer, ...]
  tier_2: [data engineer, ...]
scoring:              # keyword weights: strong_signals, context_signals, negative_signals, modifiers, score_divisor
sources:              # true/false per source, e.g. remotive, jobicy, trinidad_jobstt, trinidad_digicel …
min_score_to_include: 35
max_age_days: 30
keep_all_trinidad: true          # keep every local posting, whatever its fit, so the local market is browsable
trinidad_limit_per_source: 40    # newest N postings per Trinidad board
trinidad_custom_sites: []        # employers added from the Trinidad page
company_boards: {greenhouse: [...], lever: [...], ashby: [...]}   # remote companies to watch
cover_letter: {provider: auto}   # auto | claude_code | ollama | anthropic | template
preferences:          # saved from the Profile page
  work_mode: both     # both | local_first | remote_first | local_only | remote_only
  min_salary_monthly_ttd: 0
  min_salary_monthly_usd: 0
  target_titles: []
  avoid_keywords: []
  preferred_regions: []
  willing_to_relocate: false
  open_to_contract: true
```

After changing preferences or your resume press **Re-score all jobs** (Profile page) or run `make rescore`.

## Environment variables

See [`.env.example`](../.env.example). All optional.

| Variable | Effect |
|---|---|
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | Django settings (defaults suit localhost) |
| `JOBHUNT_DB` | Path of the scanner database (default `jobhunt/output/jobhunt.db`) |
| `JOBHUNTER_DJANGO_DB` | Path of Django's own database |
| `SHEET_ID`, `GOOGLE_APPLICATION_CREDENTIALS` | Google Sheets sync (`python -m src.run` without `--dry-run`) |
| `OLLAMA_HOST`, `OLLAMA_MODEL` | Local model endpoint / default model |
| `ANTHROPIC_API_KEY` | Anthropic API backend |
| `JOOBLE_API_KEY` | Enables the Jooble source |

## AI providers

Used for cover letters and the optional "AI read of your resume". Pin one in **Settings** or `cover_letter.provider`:

- `claude_code`: the Claude Code CLI on your PATH (no key)
- `ollama`: a local model (offline, nothing leaves your machine)
- `anthropic`: the API (`ANTHROPIC_API_KEY`)
- `template`: deterministic, built from your resume / fact bank, always available
- `auto`: tries them in that order, falling back to the template

For semantic resume matching install an embedding model (`ollama pull nomic-embed-text`) and press **Re-index** on the
Profile page. Without it retrieval is keyword-based (BM25), which works well but is less forgiving of different wording.

## Google Sheets sync (optional)

Create a Google Cloud service account, share a sheet with its email, set `SHEET_ID` and
`GOOGLE_APPLICATION_CREDENTIALS`, then run `python -m src.run` (without `--dry-run`) from `jobhunt/`. Columns A:M are
owned by the scanner; N:R (status, notes…) are yours and never overwritten.
