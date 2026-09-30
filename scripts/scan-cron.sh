#!/usr/bin/env bash
# scan-cron.sh — a scan you can schedule (cron, launchd, systemd timer) instead of running one from the UI.
#
# Why a script and not an in-process scheduler in Django: the web app can run under more than one worker
# (gunicorn, docker-compose), and a timer thread started inside each worker would fire once per worker —
# duplicate scans hammering the job boards. A scheduled OS-level job runs once, and the lock below makes sure
# a slow run is never started twice even if the schedule overlaps it (e.g. cron firing while the last run is
# still going after a slow network).
#
#   */30 * * * *  /path/to/JobHunter/scripts/scan-cron.sh   >> /path/to/JobHunter/jobhunt/output/scan-cron.log 2>&1
#
# See docs/SCHEDULING.md for the full cron line and a macOS launchd example.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LOCK="$ROOT/jobhunt/output/.scan.lock"
STALE_AFTER=7200   # seconds; a lock older than this is assumed to be from a crashed run, not a slow one

mkdir -p "$ROOT/jobhunt/output"

if [ -d "$LOCK" ]; then
  age=$(( $(date +%s) - $(stat -f%m "$LOCK" 2>/dev/null || stat -c%Y "$LOCK" 2>/dev/null || echo 0) ))
  if [ "$age" -lt "$STALE_AFTER" ]; then
    echo "$(date -Iseconds) skipped: a scan is already running (lock is ${age}s old)"
    exit 0
  fi
  echo "$(date -Iseconds) previous lock is ${age}s old (> ${STALE_AFTER}s) — assuming a crashed run and continuing"
  rmdir "$LOCK" 2>/dev/null || true
fi
mkdir "$LOCK"
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
if [ -f .env ]; then set -a; source .env; set +a; fi

echo "$(date -Iseconds) scan starting"
cd jobhunt
ARGS=()
[ -z "${SHEET_ID:-}" ] && ARGS+=("--dry-run")     # no SHEET_ID configured -> skip the Google Sheet write, same as `make scan`
[ "${SCAN_DIGEST:-}" = "1" ] && ARGS+=("--digest")
python -m src.run "${ARGS[@]}"
echo "$(date -Iseconds) scan finished"
# job alerts (email / Telegram): only does anything when a channel is configured — see docs/ALERTS.md
(cd ../django_project && python manage.py send_alerts) || echo "alerts: skipped (see docs/ALERTS.md)"
