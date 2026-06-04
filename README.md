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
                                   │                          ├ anomalies
                                   ├ detector/ (thresholds,   ├ sensors
                                   │   severity, debounce)    ├ staff_on_call
                                   ├ rag.py ──embed──▶ Gemini  ├ knowledge_base  (+ vector index)
                                   └ routes_read / routes_write├ system_metadata
                                                               ├ agent_execution_logs
        agent (external) ──HTTP──▶ read/write API ────────────┘ session_events
                          └─chat──▶ Groq
```

Two LLM providers (both free-tier):

| Use | Provider | Model | Notes |
|-----|----------|-------|-------|
| **Embeddings** | Google Gemini | `gemini-embedding-001` | 768 dims (Matryoshka-truncated, L2-normalized) |
| **Chat / reasoning** | Groq | `llama-3.3-70b-versatile` | OpenAI-compatible endpoint |

> Groq has **no embeddings endpoint** — that's why embeddings come from Gemini.
> The two are configured independently (see `.env.example`).

---

## Setup

### 1. Environment

Copy `.env.example` → `.env` and fill in:

```bash
MONGO_URI="mongodb+srv://<user>:<password>@<cluster>.mongodb.net/"
DB_NAME="anomaly_detection"

# Embeddings (https://aistudio.google.com/apikey)
GOOGLE_API_KEY=...
EMBED_MODEL=gemini-embedding-001
EMBED_DIMENSIONS=768

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

Creates collections + indexes, seeds thresholds/staff/sensors, and embeds the
14-entry knowledge corpus (`knowledge_seed.py`) into `knowledge_base`:

```bash
python init_db.py
```

### 4. Create the Atlas Vector Search index (one-time, manual)

The knowledge search falls back to a recency sort until this exists. In the
Atlas UI: **Atlas Search → Create Search Index → Vector Search → JSON editor**,
on the `knowledge_base` collection, named `knowledge_vector`:

```json
{
  "name": "knowledge_vector",
  "type": "vectorSearch",
  "fields": [
    { "type": "vector", "path": "text_embedding", "numDimensions": 768, "similarity": "cosine" },
    { "type": "filter", "path": "equipment_type" },
    { "type": "filter", "path": "associated_error_codes" },
    { "type": "filter", "path": "is_active" }
  ]
}
```

Wait ~1 min for status `READY`. **`numDimensions` must equal `EMBED_DIMENSIONS`.**

### 5. Run

```bash
# API
uvicorn ingestor_service.api:app --reload --host 0.0.0.0 --port 8000

# Simulator (separate terminal) — generates telemetry that triggers anomalies
python -m simulator_service.main --base-url http://localhost:8000 --tick-seconds 5

# ...or force a guaranteed anomaly every 10 ticks for demos:
python -m simulator_service.main --base-url http://localhost:8000 --deterministic-demo
```

Interactive API docs at `http://localhost:8000/docs`.

### 6. Tests

Pure-logic unit tests (severity, thresholds, detector) — no DB or API keys
needed:

```bash
pip install -r requirements-dev.txt
pytest
```

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
| `knowledge_base` | RAG corpus with `text_embedding` (768d). `is_active=false` = awaiting curation |
| `system_metadata` | Config-as-data: thresholds + severity bands |
| `agent_execution_logs` | Agent run traces (the agent team populates these) |
| `session_events` | High-signal event stream |

Full field contracts are documented inline in [init_db.py](init_db.py).

---

## RAG retrieval

`ingestor_service/rag.py`:

- `embed(text) -> list[float]` — 768-dim Gemini vector (L2-normalized).
- `search_knowledge(query, *, equipment_type=None, error_codes=None, k=5)` —
  Atlas `$vectorSearch` over `text_embedding`, pre-filtered to `is_active=True`
  (+ optional `equipment_type` / `error_codes`). **Falls back to a filtered
  recency sort** when the `knowledge_vector` index is missing or returns empty.

**Closed loop:** resolving an anomaly with `outcome="fixed"` embeds the
resolution notes back into `knowledge_base` as `is_active=false`. A human curator
must flip `is_active=true` before it influences retrieval — a guardrail against
poisoning RAG with bad notes.

---

## Using Groq chat from the agent

The chat model is OpenAI-compatible, so point the OpenAI SDK at Groq:

```python
from openai import OpenAI
from ingestor_service import config

client = OpenAI(api_key=config.groq_api_key(), base_url=config.groq_base_url())
resp = client.chat.completions.create(
    model=config.chat_model(),
    messages=[{"role": "user", "content": "..."}],
)
```

---

## Module map

```
init_db.py                  Idempotent DB setup + seed (run once)
knowledge_seed.py           14-entry knowledge corpus
ingestor_service/
  api.py                    FastAPI app; registers read+write routers
  config.py                 Env accessors (Mongo, Gemini, Groq)
  db.py                     Sync PyMongo client + col() helper + indexes
  models.py                 Telemetry ingestion Pydantic contract
  ingest.py                 Persist telemetry
  rag.py                    embed() + search_knowledge()
  routes_read.py            GET endpoints (agent reads)
  routes_write.py           PATCH/POST endpoints (agent/manager/staff writes)
  feedback_to_knowledge.py  Closed RAG loop
  detector/                 Thresholds, severity, state, detection
simulator_service/          Telemetry generator
severity_engine.py          breach_ratio → severity_level / severity_type
```

---

## Conventions & gotchas

- **Synchronous PyMongo.** `db.py` is sync; FastAPI handlers are plain `def`
  (FastAPI runs them in a threadpool). Do **not** add `async`/`await` to DB calls.
- **Embedding dims are load-bearing.** `EMBED_DIMENSIONS`, the stored
  `text_embedding`, and the Atlas index `numDimensions` must all match (768).
  Change the model? Re-embed everything and recreate the index.
- **Status vocabulary:** `unresolved → analyzed → assigned → resolved`.
- **Knowledge search before the index exists** returns recency-sorted results
  (with a warning log), not vector-ranked. Create the `knowledge_vector` index
  for real similarity.

## Status

Implemented & live-tested: DB setup, telemetry ingest, detection, severity,
RAG (embed + search + closed loop), full read/write API.

Roadmap (quality, non-blocking): richer simulator curves (noise/drift/excursion)
and detector debounce to suppress duplicate anomalies within a window.
