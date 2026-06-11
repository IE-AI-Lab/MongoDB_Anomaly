#!/usr/bin/env bash
# Wait for ingestor /health, then start the simulator.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE_URL="${DATA_LAYER_BASE_URL:-http://localhost:8000}"
"$ROOT/scripts/wait_for_url.sh" "${BASE_URL%/}/health" 90

echo "sim: API ready — starting simulator"
exec python -m simulator_service.main \
  --base-url "$BASE_URL" \
  --deterministic-demo \
  --tick-seconds "${SIM_TICK_SECONDS:-5}"
