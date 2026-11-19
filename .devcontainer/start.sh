#!/usr/bin/env bash
# Starts the Vitalverse website inside a GitHub Codespace and makes it reachable by anyone with the link.
cd "$(dirname "$0")/.." || exit 1

# (re)start the server in the background so it keeps running after this script ends
pkill -f "uvicorn app:app" 2>/dev/null
setsid nohup python scripts/render_start.py > /tmp/vitalverse.log 2>&1 < /dev/null &

for i in $(seq 1 60); do
  curl -s -o /dev/null http://127.0.0.1:8000/ && break
  sleep 2
done

if [ -n "$CODESPACE_NAME" ]; then
  LINK="https://${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  if gh codespace ports visibility 8000:public -c "$CODESPACE_NAME" >/dev/null 2>&1; then
    echo "Vitalverse is live: $LINK"
  else
    echo "Vitalverse is running. To share it, open the PORTS tab, right-click port 8000 > Port Visibility > Public."
    echo "Link: $LINK"
  fi
  echo "$LINK" > /tmp/vitalverse-link.txt
fi
