#!/usr/bin/env bash
# Start the Next.js operator frontend (installs deps on first run).
# honcho keeps this process alive as the `web` proc.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/frontend"

if [[ ! -d node_modules ]]; then
  echo "web: installing frontend dependencies (first run, this can take a minute)…"
  npm install
fi

echo "web: starting Next.js dev server on :3000"
exec npm run dev
