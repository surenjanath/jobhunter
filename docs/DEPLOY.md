# Deploying to Render

JobHunter is built to run on your own computer. You can also put a private copy on [Render](https://render.com) so you
can open it from your phone or any browser. `render.yaml` in the repository root sets everything up.

## What you get on the free plan

- A private site at `https://<name>.onrender.com`, behind your sign-in (nobody else can create an account).
- **No persistent disk.** Every restart starts from empty, and a free instance restarts whenever it wakes up after
  about 15 minutes idle, and on every deploy. On each start it rebuilds itself automatically:
  your account (from environment variables), your resume and `profile.yaml` (from Secret Files), and a fresh job scan
  in the background (the site is usable while it runs; jobs appear after a few minutes).
- **Lost on restart:** statuses, notes, stars, mock-interview history, stories and drills made on the hosted copy.
  Keep your real pipeline on your own computer, or move to a paid plan with a disk (below).
- **Voice:** the browser's built-in voice (Kokoro needs more memory than the free plan has).
- **AI features:** the built-in rules, or set `ANTHROPIC_API_KEY` to use Claude (billed to that key). There's no
  Ollama on Render.

## Steps

1. Push this repository to GitHub (your personal files, like `profile.yaml` and your resume, are gitignored and stay local).
2. In Render: **New → Blueprint**, pick the repository. Render reads `render.yaml` and creates the `jobhunter` web service.
3. When it asks for the unset environment variables:
   - `JOBHUNTER_OWNER_EMAIL`: the email you'll sign in with.
   - `JOBHUNTER_OWNER_PASSWORD`: at least 12 characters. This is your only way in.
   - `ANTHROPIC_API_KEY`: optional.
4. In the service's **Environment → Secret Files**, add:
   - `profile.yaml`: the contents of your `jobhunt/config/profile.yaml` (search terms, targets, preferences).
   - `resume.md` (or `resume.pdf` / `resume.docx`): your resume.
5. Deploy. Open the site, sign in, and give the first scan a few minutes.

## Keeping it awake

`.github/workflows/keep-alive.yml` pings the site every 14 minutes so the free instance never sleeps. That also means
far fewer restarts, so the hosted copy keeps its data until the next deploy or platform restart. Turn it on by adding a
repository variable `RENDER_URL` = `https://<your-service>.onrender.com` (Settings → Secrets and variables → Actions →
Variables). One always-on free service uses about 744 of Render's 750 free instance-hours a month.

## Settings you can change later

- **Settings page → Site access**: "Allow new accounts" and "Require sign-in". Only your account (the admin) can change
  them. On the free plan they go back to the `render.yaml` defaults after a restart.
- `JOBHUNTER_SCAN_EVERY_HOURS` (default 12): re-scan while the service is awake.
- `JOBHUNTER_PRIVATE` / `JOBHUNTER_ALLOW_SIGNUP`: the starting values of the two Site access switches.

## Keeping your data (paid plan)

Switch the service to a paid instance, add a **Disk** mounted at `/var/data`, and set:

```
JOBHUNT_DB=/var/data/jobhunt.db
JOBHUNTER_DJANGO_DB=/var/data/django.sqlite3
```

Everything then survives restarts and deploys. With 2 GB of memory you can also add the natural Kokoro voice:
add `pip install kokoro-onnx soundfile && cd jobhunt && python -m src.voice --download` to the build command.

## How it works

- `scripts/render-start.sh`: migrate → `manage.py boot_hosted` (owner account, Secret Files, first scan) → gunicorn,
  plus an optional re-scan loop.
- Production settings switch on when `DJANGO_DEBUG=0`: HTTPS redirect (except `/health/`), secure cookies, HSTS, and
  static files served by WhiteNoise. Sessions are signed with the `DJANGO_SECRET_KEY` Render generates.
