#!/usr/bin/env bash
# One command to get running: creates a virtualenv, installs dependencies, migrates, starts the app.
#   ./scripts/start.sh            -> http://127.0.0.1:8000
#   PORT=9000 ./scripts/start.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  echo "Creating virtualenv (.venv)…"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if [ -f .env ]; then set -a; source .env; set +a; fi

cd django_project
python manage.py migrate --noinput >/dev/null
echo "JobHunter running at http://127.0.0.1:${PORT:-8000}  (Ctrl-C to stop)"
exec python manage.py runserver "127.0.0.1:${PORT:-8000}"
