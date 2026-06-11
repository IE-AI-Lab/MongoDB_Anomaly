#!/usr/bin/env bash
# Start ingestor + agent worker + simulator in one terminal (via Honcho).
#
# Usage:
#   ./scripts/dev_up.sh          # all processes in Procfile
#   ./scripts/dev_up.sh api agent   # subset
#
# Prerequisites:
#   pip install -r requirements.txt -r requirements-dev.txt
#   .env configured (copy from .env.example)
#   redis-server installed (started by Procfile if not already running)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "error: .env not found — copy .env.example to .env and fill in values" >&2
  exit 1
fi

if ! command -v honcho >/dev/null 2>&1; then
  echo "error: honcho not installed — run: pip install -r requirements-dev.txt" >&2
  exit 1
fi

echo "starting stack from $ROOT (redis + api + agent + sim — Ctrl+C stops all)"
exec honcho start "$@"
