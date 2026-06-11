#!/usr/bin/env bash
# Wait for Redis, then start the agent worker.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
[[ -f .env ]] && set -a && source .env && set +a

REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
PORT="${REDIS_PORT:-6379}"
if [[ "$REDIS_URL" =~ :([0-9]+) ]]; then
  PORT="${BASH_REMATCH[1]}"
fi

echo "agent: waiting for Redis on :$PORT..."
for _ in $(seq 1 90); do
  if command -v redis-cli >/dev/null 2>&1 && redis-cli -p "$PORT" ping >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! redis-cli -p "$PORT" ping >/dev/null 2>&1; then
  echo "error: Redis not reachable on :$PORT" >&2
  exit 1
fi

echo "agent: Redis ready — starting worker"
exec python -m agent_worker.main
