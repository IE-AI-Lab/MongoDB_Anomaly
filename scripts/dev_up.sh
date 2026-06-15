#!/usr/bin/env bash
# Run the WHOLE stack in one terminal via Honcho: redis + api + agent + sim + web.
# Ctrl+C stops everything.
#
# Usage:
#   ./scripts/dev_up.sh             # everything in the Procfile
#   ./scripts/dev_up.sh api agent   # subset

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "error: .env not found — copy .env.example to .env and fill in values" >&2
  exit 1
fi

# Use the project venv if present so child procs resolve to it.
if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
elif [[ -f .venv/Scripts/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/Scripts/activate
fi

# Ensure honcho is available (dev dependency).
python -m pip show honcho >/dev/null 2>&1 || pip install honcho

echo "starting stack from $ROOT (redis + api + agent + sim + web — Ctrl+C stops all)"
exec honcho start "$@"
