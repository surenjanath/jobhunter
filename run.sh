#!/usr/bin/env bash
# Run JobHunter locally with your normal python3 (where Django, Kokoro etc. are installed).
#
#   ./run.sh              -> http://127.0.0.1:8000, opens your browser
#   ./run.sh 9000         -> another port
#   NO_BROWSER=1 ./run.sh -> don't open the browser
#
# Stop it with Ctrl+C. (scripts/start.sh is the alternative that builds a separate .venv.)
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
PORT="${1:-${PORT:-8000}}"

# settings from .env, if you keep one (API keys, alert settings…)
if [ -f .env ]; then set -a; source .env; set +a; fi

# everything the app needs must import; otherwise say exactly what to install
if ! "$PY" -c "import django, rest_framework, whitenoise, yaml, requests" 2>/dev/null; then
  echo "Some packages are missing. Install them with:"
  echo "  $PY -m pip install -r requirements.txt"
  exit 1
fi

# port already taken (e.g. another copy running)?
if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use. Stop the other server, or run: ./run.sh $((PORT + 1))"
  exit 1
fi

cd django_project
"$PY" manage.py migrate --noinput >/dev/null

# what's available (informational only)
if "$PY" -c "import sys; sys.path.insert(0, '../jobhunt'); from src import voice; sys.exit(0 if voice.available() else 1)" 2>/dev/null; then
  echo "Voice: Kokoro (natural interviewer voice)"
else
  echo "Voice: browser voice (for Kokoro: $PY -m pip install kokoro-onnx soundfile && cd jobhunt && $PY -m src.voice --download)"
fi
if curl -s --max-time 1 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "AI: Ollama is running (local, nothing leaves your machine)"
else
  echo "AI: Ollama not running, built-in rules only (start the Ollama app to turn AI on)"
fi

URL="http://127.0.0.1:$PORT/"
echo "JobHunter: $URL   (Ctrl+C to stop)"
if [ -z "${NO_BROWSER:-}" ] && command -v open >/dev/null 2>&1; then
  (sleep 2 && open "$URL") &
fi
exec "$PY" manage.py runserver "127.0.0.1:$PORT"
