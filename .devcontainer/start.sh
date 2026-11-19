#!/usr/bin/env bash
# Starts the Vitalverse website inside a GitHub Codespace and makes it reachable by anyone with the link.
# Safe to run any number of times: it installs missing libraries, and does nothing if the site already runs.
cd "$(dirname "$0")/.." || exit 1
LOG=/tmp/vitalverse.log

if curl -s -o /dev/null --max-time 3 http://127.0.0.1:8000/; then
  echo "Vitalverse is already running."
else
  if ! python -c "import fastapi, sklearn, uvicorn" 2>/dev/null; then
    echo "Installing Vitalverse libraries (first start only, a few minutes)..."
    grep -v -E '^(pytest|playwright)==' requirements.txt > /tmp/req.txt
    pip install --user -q -r /tmp/req.txt || pip install -q -r /tmp/req.txt
  fi
  # start fully detached so the server keeps running after this script and the start-up steps end
  nohup setsid python scripts/render_start.py > "$LOG" 2>&1 < /dev/null &
  disown 2>/dev/null
  for i in $(seq 1 90); do
    curl -s -o /dev/null --max-time 3 http://127.0.0.1:8000/ && break
    sleep 2
  done
  if ! curl -s -o /dev/null --max-time 3 http://127.0.0.1:8000/; then
    echo "Vitalverse did not start. Last lines of $LOG:"
    tail -20 "$LOG"
    exit 1
  fi
fi

if [ -n "$CODESPACE_NAME" ]; then
  LINK="https://${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  if gh codespace ports visibility 8000:public -c "$CODESPACE_NAME" >/dev/null 2>&1; then
    echo "Vitalverse is live: $LINK"
  else
    echo "Vitalverse is running. To share it: PORTS tab > right-click port 8000 > Port Visibility > Public."
    echo "Link: $LINK"
  fi
  echo "$LINK" > /tmp/vitalverse-link.txt
fi
