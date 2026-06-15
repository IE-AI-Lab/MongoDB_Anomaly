#!/usr/bin/env bash
# Start Redis for local dev, or supervise an already-running instance (honcho
# keeps this process alive). Portable: no redis-cli dependency, so it works in
# Git Bash on Windows where only a Docker/native Redis may be listening.

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

# Already listening? Supervise without starting a second instance. Uses bash's
# /dev/tcp (available in Git Bash) instead of redis-cli.
if (echo > "/dev/tcp/127.0.0.1/$PORT") >/dev/null 2>&1; then
  echo "redis: already listening on :$PORT — supervising (no second instance)"
  exec sleep infinity
fi

if command -v redis-server >/dev/null 2>&1; then
  echo "redis: starting redis-server on :$PORT"
  exec redis-server --port "$PORT"
fi

if command -v docker >/dev/null 2>&1; then
  echo "redis: starting Redis via Docker on :$PORT"
  exec docker run --rm --name cnc-redis -p "$PORT:6379" redis
fi

echo "error: Redis not reachable on :$PORT and no redis-server/docker found." >&2
echo "       Start Redis first, e.g.: docker run -d -p 6379:6379 redis" >&2
exit 1
