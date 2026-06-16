#!/usr/bin/env bash
# Wipe anomaly Redis streams (high/medium/low + dlq) for a fresh Grafana run.
#
# Option A — via API (ingestor must be running):
#   ./scripts/reset_redis_queues.sh
#
# Option B — direct Redis (no API needed):
#   ./scripts/reset_redis_queues.sh --direct
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--direct" ]]; then
  python - <<'PY'
from dotenv import load_dotenv
load_dotenv()
from ingestor_service.messaging.queue import reset_anomaly_streams
import json
print(json.dumps(reset_anomaly_streams(), indent=2))
PY
  exit 0
fi

BASE_URL="${DATA_LAYER_BASE_URL:-http://localhost:8000}"
echo "reset: POST ${BASE_URL}/queues/reset"
curl -sf -X POST "${BASE_URL}/queues/reset" | python -m json.tool
