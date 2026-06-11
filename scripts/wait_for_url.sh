#!/usr/bin/env bash
# Poll an HTTP URL until it returns 2xx or timeout.
# Usage: ./scripts/wait_for_url.sh http://localhost:8000/health [timeout_seconds]

set -euo pipefail

URL="${1:?usage: wait_for_url.sh <url> [timeout_seconds]}"
TIMEOUT="${2:-90}"
DEADLINE=$((SECONDS + TIMEOUT))

echo "waiting for $URL (timeout ${TIMEOUT}s)..."
while (( SECONDS < DEADLINE )); do
  if curl -sf "$URL" >/dev/null 2>&1; then
    echo "ready: $URL"
    exit 0
  fi
  sleep 1
done

echo "error: timed out waiting for $URL" >&2
exit 1
