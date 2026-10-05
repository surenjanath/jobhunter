# Configuration

## Files (`jobhunt/config/`)

Created from the `*.example*` templates on first run. They are git-ignored, so your details stay local.

| File | Purpose |
|---|---|
| `profile.yaml` | Candidate details, target titles, keyword scoring weights, which sources are on, cover-letter provider, saved preferences, custom sites |
| `fact_bank.md` | The only facts the cover-letter generator may use (write it flat and honest) |
| `form_answers.md` | Copy-paste answers for application forms |
| `ui_settings.json` | Display preferences (remote / links / salary visibility) |
| `llm_keys.json` | API keys saved from Settings → AI providers (created when you save the first one) |

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
cover_letter: {provider: auto}   # auto | claude_code | ollama | anthropic | openai | gemini | groq | openrouter | mistral | deepseek | xai | together | cerebras | fireworks | custom | template
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
| `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `DEEPSEEK_API_KEY`, `XAI_API_KEY`, `TOGETHER_API_KEY`, `CEREBRAS_API_KEY`, `FIREWORKS_API_KEY` | Keys for the other API providers |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | The custom OpenAI-compatible endpoint (key optional) |
| `JOOBLE_API_KEY` | Enables the Jooble source |

## AI providers

Used for cover letters and the optional "AI read of your resume". Pin one in **Settings** or `cover_letter.provider`:

- `claude_code`: the Claude Code CLI on your PATH (no key)
- `ollama`: a local model (offline, nothing leaves your machine)
- `anthropic`: the API (`ANTHROPIC_API_KEY`)
- `openai`, `gemini`, `groq`, `openrouter`, `mistral`, `deepseek`, `xai`, `together`, `cerebras`, `fireworks`: hosted APIs,
  each with its own key
- `custom`: any OpenAI-compatible endpoint (LM Studio, vLLM, LiteLLM, a company gateway). Give its base URL, for
  example `http://localhost:1234/v1`, and a model id; the key is optional
- `template`: deterministic, built from your resume / fact bank, always available
- `auto`: tries them in that order (skipping APIs with no key), falling back to the template

**Settings → AI providers** is where you add a key, choose a model (**List models** asks the provider what it offers)
and check the connection (**Save and test**). Keys are never sent back to the browser.

Whose key is used:

- **Your account's own.** Signed in, the section edits your account: your keys, provider, models, custom endpoint and
  generation options. Only your requests use them and no other account (the admin included) can see them. They are
  stored with your account in Django's database, as plain text like the site keys, so protect the database file.
- **The site-wide ones**, wherever your account has set nothing, and always for guests. An admin sets these under
  **Everyone (site-wide)**; they are saved to `jobhunt/config/llm_keys.json` (git-ignored, readable only by your
  user) and `profile.yaml`, and win over the environment variables above. On a hosted copy whose disk resets on
  deploy, set the environment variables instead.
- With no accounts at all (a plain local install) there is only the site-wide set, and anyone using the copy can edit it.

An account that is not an admin cannot point the custom endpoint at a private or local address. Usage counts are
shown to admins only. The scheduled scanner and the command line always use the site-wide settings.

Also in that section (per account, or under `cover_letter` in `profile.yaml` for the site):

- **If that provider fails, try the other ready ones** (`fallback: true`): a pinned provider that errors (rate limit,
  outage) hands the request to the next ready provider instead of dropping to the template. Off by default, because
  your text can then reach any provider you have set up.
- **Generation options**: `temperature` (0 to 1.5, default 0.4), `max_tokens` (200 to 8000, default 1500) and
  `timeout` in seconds (10 to 600, default 120).
- **Usage**: each provider shows its requests, tokens, average time and last error. These are counts only, kept in
  `jobhunt/output/llm_usage.json`; no prompt or reply text is stored. **Reset usage counts** clears them.
- **Test every ready provider** sends one short prompt to each and reports which work and which is fastest.

For semantic resume matching install an embedding model (`ollama pull nomic-embed-text`) and press **Re-index** on the
Profile page. Without it retrieval is keyword-based (BM25), which works well but is less forgiving of different wording.

## Google Sheets sync (optional)

Create a Google Cloud service account, share a sheet with its email, set `SHEET_ID` and
`GOOGLE_APPLICATION_CREDENTIALS`, then run `python -m src.run` (without `--dry-run`) from `jobhunt/`. Columns A:M are
owned by the scanner; N:R (status, notes…) are yours and never overwritten.
