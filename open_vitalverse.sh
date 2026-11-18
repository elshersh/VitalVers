#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
URL="http://127.0.0.1:8000/"

open_browser() {
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then
    open "$URL" >/dev/null 2>&1 &
  else
    echo "Open $URL in your browser."
  fi
}

if command -v curl >/dev/null 2>&1 && curl -fsS "$URL" >/dev/null 2>&1; then
  open_browser
  exit 0
fi

PY_BIN=""
if [ -x ".venv/bin/python" ]; then
  PY_BIN=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PY_BIN="python"
else
  echo "Python 3 not found. Install dependencies: pip install -r requirements.txt"
  exit 1
fi

"$PY_BIN" -m uvicorn app:app --host 127.0.0.1 --port 8000 &
SERVER_PID=$!

for _ in $(seq 1 50); do
  if command -v curl >/dev/null 2>&1 && curl -fsS "$URL" >/dev/null 2>&1; then
    break
  fi
  sleep 0.4
done

open_browser
wait "$SERVER_PID"
