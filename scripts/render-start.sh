#!/usr/bin/env bash
# Start command for a hosted copy (Render: see render.yaml). Rebuilds from a blank disk every time:
# migrate -> owner account + secret-file config/resume + first scan (manage.py boot_hosted) -> gunicorn.
# JOBHUNTER_SCAN_EVERY_HOURS=N re-scans every N hours while the service is awake (a free instance sleeps when idle).
set -euo pipefail
cd "$(dirname "$0")/../django_project"
PY="$(command -v python || command -v python3)"

"$PY" manage.py migrate --noinput
"$PY" manage.py boot_hosted

if [ -n "${JOBHUNTER_SCAN_EVERY_HOURS:-}" ]; then
  (
    while sleep "$(( JOBHUNTER_SCAN_EVERY_HOURS * 3600 ))"; do
      (cd ../jobhunt && "$PY" -m src.run --dry-run >> output/scheduled_scan.log 2>&1) || true
      "$PY" manage.py send_alerts >> ../jobhunt/output/alerts.log 2>&1 || true   # no-op unless a channel is set up
    done
  ) &
fi

# one worker: scans run as subprocesses and the app keeps some state in memory; threads cover concurrent requests
exec gunicorn config.wsgi --bind "0.0.0.0:${PORT:-8000}" --workers 1 --threads 4 --timeout 120 --access-logfile -
