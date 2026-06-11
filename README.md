# MongoDB Atlas Anomaly Detection — Data Layer

Backend substrate for an event-driven anomaly-detection agent. Telemetry flows
in, anomalies are detected and persisted, and an **HTTP API** exposes everything
an agent (LangGraph or otherwise) needs to read context and write back its
analysis, assignment, and resolution — closing a RAG feedback loop.

This repo is the **data layer**. The reasoning agent is built *on top* of this
API by the agent team — it lives elsewhere and is not in this repo.

---

## Architecture

```
 simulator_service ──HTTP──▶ ingestor_service (FastAPI) ──▶ MongoDB Atlas
                                   │                          ├ telemetry_history (time-series)
                                   ├ api/ (HTTP routers)      ├ anomalies
                                   ├ detector/ (thresholds,   ├ sensors
                                   │   severity, debounce)    ├ staff_on_call
                                   ├ messaging/queue ─XADD─▶ Redis ├ knowledge_base (+ vector index)
                                   ├ services/rag ─$vectorSearch─▶ ├ system_metadata
                                   └ core/ (config, db)        ├ agent_execution_logs
                                                               └ session_events
        agent_worker ──XREADGROUP──▶ Redis (anomaly:jobs)
              │
              └──HTTP──▶ read/write API ──▶ MongoDB Atlas
              └──chat──▶ Groq (LangGraph — wire in agent_worker/consumer.py)
```

Providers:

| Use | Provider | Model | Notes |
|-----|----------|-------|-------|
| **Embeddings** | Atlas Vector Search (Voyage AI) | `voyage-4-lite` | Automated Embedding — Atlas embeds `text_content` at index + query time; no key, no vectors stored |
| **Chat / reasoning** | Groq | `llama-3.3-70b-versatile` | OpenAI-compatible endpoint |

> Embeddings are a database concern: we store only `text_content` and Atlas
> generates the vector via the `knowledge_vector` autoEmbed index. The chat
> provider (Groq) is configured independently (see `.env.example`).

---

## Setup

### 1. Environment

Copy `.env.example` → `.env` and fill in:

```bash
MONGO_URI="mongodb+srv://<user>:<password>@<cluster>.mongodb.net/"
DB_NAME="anomaly_db"

# Embeddings — managed by Atlas (Voyage AI); no key needed.
# Must match the model set in the knowledge_vector autoEmbed index.
VOYAGE_EMBED_MODEL=voyage-4-lite

# Chat (https://console.groq.com/keys)
GROQ_API_KEY=...
GROQ_BASE_URL=https://api.groq.com/openai/v1
CHAT_MODEL=llama-3.3-70b-versatile
```

`.env` is gitignored — never commit real keys.

### 2. Install

```bash
pip install -r requirements.txt
```

### 3. Initialize the database

Creates collections + indexes, seeds thresholds/staff/sensors, and loads the
14-entry knowledge corpus (`scripts/knowledge_seed.py`) into `knowledge_base`
(text only — Atlas generates the embeddings):

```bash
python -m scripts.init_db
```

### 4. Create the Atlas Vector Search index (one-time, manual)

The knowledge search falls back to a recency sort until this index is **Active**.
In the Atlas UI: **Atlas Search → Create Search Index → Vector Search → JSON
editor**, on the `knowledge_base` collection, named `knowledge_vector`. This uses
**Automated Embedding** (`autoEmbed`) — Atlas embeds `text_content` for you, so we
store no vectors:

```json
{
  "fields": [
    { "type": "autoEmbed", "modality": "text", "path": "text_content", "model": "voyage-4-lite" },
    { "type": "filter", "path": "equipment_type" },
    { "type": "filter", "path": "associated_error_codes" },
    { "type": "filter", "path": "is_active" }
  ]
}
```

Wait ~1 min for status `READY`/`Active`. The `model` here must equal
`VOYAGE_EMBED_MODEL`. Requires a cluster tier with Automated Embedding (Voyage AI)
enabled — supported on M0/Flex and dedicated tiers.

### 5. Run

Set `AGENT_DISPATCH=redis` in `.env` when using the queue (default is `stub`).

```bash
# Redis (separate terminal)
redis-server

# API
uvicorn ingestor_service.app:app --reload --host 0.0.0.0 --port 8000

# Agent worker (separate terminal) — blocks on Redis up to 20s per read
python -m agent_worker.main

# Simulator (separate terminal) — generates telemetry that triggers anomalies
python -m simulator_service.main --base-url http://localhost:8000 --tick-seconds 5

# ...or force a guaranteed anomaly every 10 ticks for demos:
python -m simulator_service.main --base-url http://localhost:8000 --deterministic-demo
```

When an anomaly is detected, the ingestor **XADD**s `{ anomaly_id, ... }` to the
Redis stream `anomaly:jobs`. The agent worker **XREADGROUP**s with a 20s block
(`AGENT_CONSUMER_BLOCK_MS`), fetches full context via the read API, and **XACK**s
when done. Replace `process_anomaly_job()` in `agent_worker/consumer.py` with
your LangGraph graph.

Interactive API docs at `http://localhost:8000/docs`.

### 6. Tests

Pure-logic unit tests (severity, thresholds, detector) — no DB or API keys
needed:

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

GitHub Actions runs this same test command on every push to `main` and every pull request.

---

## Anomaly lifecycle

An anomaly moves through these `status` values — the API enforces the transitions:

```
unresolved ──(agent PATCH)──▶ analyzed ──(manager assign)──▶ assigned ──(staff resolve)──▶ resolved
   ▲ detector creates it                                                                       │
                                                          outcome="fixed" ──▶ knowledge_base (is_active=false, awaits curation)
```

Enforced by the write API (invalid moves return `409`):
- `PATCH` may only set `status` to `unresolved`/`analyzed`; it **cannot** set
  `assigned` or `resolved` (those carry side effects — use the dedicated
  endpoints) and cannot move a status backward.
- `assign` rejects an already-`assigned` or `resolved` anomaly.
- `resolve` rejects an already-`resolved` anomaly. `resolved` is terminal.

---

## HTTP API

Base URL: `http://localhost:8000`. All responses are JSON with Mongo `_id` stripped.

### Telemetry (simulator → ingestor)

| Method | Path | Body | Returns |
|--------|------|------|---------|
| `POST` | `/ingest/telemetry` | `TelemetryIngestEvent` | `{stored, anomaly_created, anomaly_id?}` |
| `GET`  | `/health` | — | `{status:"ok"}` |

### Read (agent gathers context)

| Method | Path | Query params | Returns |
|--------|------|--------------|---------|
| `GET` | `/anomalies/{anomaly_id}` | — | one anomaly |
| `GET` | `/anomalies` | `status`, `sensor_id`, `limit` (1–500) | list, newest first |
| `GET` | `/sensors/{sensor_id}` | — | one sensor |
| `GET` | `/sensors/{sensor_id}/readings` | `minutes` (1–1440), `limit` (1–2000) | recent telemetry |
| `GET` | `/knowledge/search` | `q` (required), `equipment_type`, `error_codes` (CSV), `k` (1–20) | ranked knowledge docs |
| `GET` | `/staff_on_call` | `is_on_call`, `specialization`, `handled_severity_type`, `facility_id` | staff, by escalation rank |

### Write (agent / manager / staff act)

| Method | Path | Body | Effect |
|--------|------|------|--------|
| `PATCH` | `/anomalies/{anomaly_id}` | `{description?, recommended_solution?, similar_cases?, recommended_employee_id?, agent_run_id?, status?}` | agent commits analysis (typically `status:"analyzed"`) |
| `POST` | `/anomalies/{anomaly_id}/assign` | `{employee_id}` | assigns staff, sets `assigned`, flips staff `is_on_call→false` |
| `POST` | `/anomalies/{anomaly_id}/resolve` | `{outcome, resolution_notes, resolved_by?}` | sets `resolved`, frees staff; if `outcome=="fixed"`, embeds notes into `knowledge_base` and returns `knowledge_document_id` |

### Knowledge curation (CRUD over `knowledge_base`)

| Method | Path | Params / body | Use |
|--------|------|---------------|-----|
| `GET` | `/knowledge` | `is_active`, `equipment_type`, `source` (seed/feedback/manual), `limit`, `skip` | list entries; `?is_active=false&source=feedback` = **review queue** |
| `GET` | `/knowledge/{document_id}` | — | one entry |
| `POST` | `/knowledge` | `{section_title, text_content, equipment_type?, associated_error_codes?, is_active?}` | create manual entry (`kb-` id); Atlas autoEmbed indexes it |
| `PATCH` | `/knowledge/{document_id}` | any subset of the create fields | curator **approves** feedback with `{"is_active": true}` |
| `DELETE` | `/knowledge/{document_id}` | — | hard delete — curator **rejects** a feedback entry |

### Admin (dev/demo)

| Method | Path | Body | Effect |
|--------|------|------|--------|
| `POST` | `/simulation/reset` | `{purge_feedback_knowledge?: false}` | purges anomalies, telemetry, agent logs, session events; restores all staff to on-call; trims the Redis job stream; seed data untouched. Restart the simulator to reset its sequence counters. |

#### Example agent flow

```bash
# 1. agent picks up an unresolved anomaly
curl localhost:8000/anomalies?status=unresolved&limit=1

# 2. retrieve similar past cases
curl "localhost:8000/knowledge/search?q=pump+bearing+vibration&error_codes=VIBRATION_HIGH&k=3"

# 3. write analysis back
curl -X PATCH localhost:8000/anomalies/ANOM-xxxx \
  -H 'Content-Type: application/json' \
  -d '{"description":"Likely bearing wear","recommended_solution":"Schedule replacement","recommended_employee_id":"EMP-002","status":"analyzed"}'

# 4. find an on-call specialist
curl "localhost:8000/staff_on_call?is_on_call=true&specialization=vibration"
```

---

## Telemetry ingestion contract

`POST /ingest/telemetry` body (`TelemetryIngestEvent`):

```json
{
  "event_id": "evt-123",
  "timestamp_utc": "2026-06-04T12:00:00Z",
  "sensor_id": "SENS-VIB-001",
  "facility_id": "FAC-01",
  "equipment_id": "PUMP-A12",
  "source": "simulator",
  "quality": "good",
  "sequence_number": 1,
  "reading": { "metric_type": "vibration", "unit_system": "si", "data": { "amplitude_mm": 0.7 } }
}
```

`metric_type` ∈ `environment | vibration | pressure | flow`. Detector error
codes: `TEMP_HIGH`, `TEMP_LOW`, `HUMIDITY_HIGH`, `VIBRATION_HIGH`,
`PRESSURE_LOW`, `FLOW_LOW`. These are the join keys into
`knowledge_base.associated_error_codes`.

---

## Collections

| Collection | Purpose |
|------------|---------|
| `telemetry_history` | Time-series sensor readings (7-day TTL) |
| `anomalies` | Detected anomalies + agent analysis + resolution |
| `sensors` | Sensor registry (`equipment_type` joins to knowledge) |
| `staff_on_call` | On-call roster, by `specialization` / `handled_severity_type` / `escalation_rank` |
| `knowledge_base` | RAG corpus (`text_content`; Atlas autoEmbed generates the vector). `is_active=false` = awaiting curation |
| `system_metadata` | Config-as-data: thresholds + severity bands |
| `agent_execution_logs` | Agent run traces (the agent team populates these) |
| `session_events` | High-signal event stream |

Full field contracts are documented inline in [scripts/init_db.py](scripts/init_db.py).

---

## RAG retrieval

`ingestor_service/rag.py`:

- `search_knowledge(query, *, equipment_type=None, error_codes=None, k=5)` —
  Atlas `$vectorSearch` with **automated query embedding** (passes the raw query
  text + model; Atlas embeds it), pre-filtered to `is_active=True` (+ optional
  `equipment_type` / `error_codes`). **Falls back to a filtered recency sort**
  when the `knowledge_vector` index is not Active yet or returns empty.

No `embed()` helper — the service never computes a vector.

**Closed loop:** resolving an anomaly with `outcome="fixed"` writes the
resolution notes back into `knowledge_base` as `is_active=false`. A human curator
must flip `is_active=true` before it influences retrieval — a guardrail against
poisoning RAG with bad notes.

---

## Using Groq chat from the agent

The chat model is OpenAI-compatible, so point the OpenAI SDK at Groq:

```python
from openai import OpenAI
from ingestor_service.core import config

client = OpenAI(api_key=config.groq_api_key(), base_url=config.groq_base_url())
resp = client.chat.completions.create(
    model=config.chat_model(),
    messages=[{"role": "user", "content": "..."}],
)
```

---

## Module map

```
scripts/
  init_db.py                Idempotent DB setup + seed (run once)
  knowledge_seed.py         14-entry knowledge corpus
ingestor_service/           Data layer (run: uvicorn ingestor_service.app:app)
  app.py                    FastAPI app; mounts api/all_routers + startup hooks
  models.py                 Telemetry ingestion Pydantic contract
  core/
    config.py               Env accessors (Mongo, Voyage model, Groq, Redis)
    db.py                   Sync PyMongo client + col() helper + indexes
  api/                      Thin HTTP routers
    telemetry.py            POST /ingest/telemetry, GET /health
    read.py                 GET endpoints (agent reads)
    write.py                PATCH/POST endpoints (agent/manager/staff writes)
    knowledge.py            knowledge_base CRUD + curation review queue
    agent_logs.py           POST/GET /agent_logs (agent run traces)
    admin.py                POST /simulation/reset (demo state purge)
  services/                 Domain logic (no HTTP)
    ingest.py               Persist telemetry
    rag.py                  search_knowledge() (Atlas autoEmbed)
    feedback_to_knowledge.py  Closed RAG loop
    severity_engine.py      breach_ratio → severity_level / severity_type
  messaging/
    queue.py                XADD anomaly jobs to Redis Streams
    agent_stub.py           stdout stub when AGENT_DISPATCH=stub
  detector/                 Thresholds, severity, state, detection
agent_worker/               Redis consumer (python -m agent_worker.main)
  consumer.py               XREADGROUP loop + process_anomaly_job hook
simulator_service/          Telemetry generator
```

---

## Conventions & gotchas

- **Synchronous PyMongo.** `db.py` is sync; FastAPI handlers are plain `def`
  (FastAPI runs them in a threadpool). Do **not** add `async`/`await` to DB calls.
- **Embeddings are managed by Atlas.** We store only `text_content`; the
  `knowledge_vector` autoEmbed index generates and syncs the vector. No
  dimensions to match. Change `VOYAGE_EMBED_MODEL`? Update the index's `model`
  to match (Atlas re-embeds), then re-seed if needed.
- **Status vocabulary:** `unresolved → analyzed → assigned → resolved`.
- **Knowledge search before the index exists** returns recency-sorted results
  (with a warning log), not vector-ranked. Create the `knowledge_vector` index
  for real similarity.

## Status

Implemented & live-tested: DB setup, telemetry ingest, detection, severity,
RAG (embed + search + closed loop), full read/write API.

Roadmap (quality, non-blocking): richer simulator curves (noise/drift/excursion)
and detector debounce to suppress duplicate anomalies within a window.
