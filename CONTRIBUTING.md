# Contributing

Issues and pull requests are welcome, especially new Trinidad & Tobago or Caribbean job sources.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt ruff
make test          # scanner suite (offline) + Django suite
make lint
```

## Ground rules

- **Never commit personal data**: resumes, `profile.yaml`, `fact_bank.md`, job databases, `.env`. `.gitignore` covers them;
  keep example files generic.
- **Tests run offline.** New sources need fixture-based tests (see `jobhunt/tests/test_sources.py`); audit the real site
  separately with `python jobhunt/live_check.py --source <name>`.
- Tests must not write to a real database or config. The Django runner already uses a temporary database; the scanner
  tests set `JOBHUNT_DB` to a temp file.
- Fetchers must be polite: public feeds / sitemaps / APIs first, bounded concurrency, no login walls, no CAPTCHA
  circumvention. Do not add LinkedIn or Indeed scraping.
- Sources raise `SourceError` when a site is unreachable or its layout changed, so the board-health table can say so.

## Style

Plain Python and plain JavaScript (no build step). Keep pages independent: shared code goes in `core.js` / `ui.js`,
page code in the page's own script. Comments explain *why*.
