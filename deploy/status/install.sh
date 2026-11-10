#!/usr/bin/env bash
# Deploy the status monitor to vps8. Run from your machine: deploy/status/install.sh
# Touches only /root/daybook_status and the "daybook-status" compose project on the server.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
KEY="${KEY:-$HOME/Projects/.keys/contabo_vps8}"
HOST="${HOST:-root@169.58.114.63}"
DEST="${DEST:-/root/daybook_status}"
SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes)

"${SSH[@]}" "$HOST" "mkdir -p '$DEST'"
rsync -az --delete -e "ssh -i $KEY -o IdentitiesOnly=yes" \
  --exclude .env --exclude tests/ --exclude __pycache__/ --exclude '*.sqlite3*' --exclude .pytest_cache/ \
  "$HERE/" "$HOST:$DEST/"
# An existing .env on the server is kept (rsync excludes it, and it is only created when missing).
"${SSH[@]}" "$HOST" "cd '$DEST' && { [ -f .env ] || cp .env.example .env; } && chmod 600 .env \
  && docker compose up -d --build && docker compose ps \
  && sleep 3 && curl -fsS -o /dev/null -w 'status page: HTTP %{http_code}\n' http://127.0.0.1:18095/"
