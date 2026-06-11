#!/usr/bin/env bash
# Start Redis for local dev, or no-op if already listening (honcho keeps this process alive).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
[[ -f .env ]] && set -a && source .env && set +a

REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
PORT="${REDIS_PORT:-6379}"

# Parse port from REDIS_URL if present (redis://host:6379/0)
if [[ "$REDIS_URL" =~ :([0-9]+) ]]; then
  PORT="${BASH_REMATCH[1]}"
fi

if command -v redis-cli >/dev/null 2>&1 && redis-cli -p "$PORT" ping >/dev/null 2>&1; then
  echo "redis: already listening on :$PORT — supervising (no second instance)"
  exec sleep infinity
fi

if ! command -v redis-server >/dev/null 2>&1; then
  echo "error: redis-server not found — install Redis or start it manually" >&2
  exit 1
fi

echo "redis: starting redis-server on :$PORT"
exec redis-server --port "$PORT"
