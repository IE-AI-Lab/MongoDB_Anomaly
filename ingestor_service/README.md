# Ingestor Service (FastAPI)

The data layer: receives telemetry, persists it to MongoDB Atlas, runs the
anomaly detector, dispatches a job (Redis stream or stdout stub) when an anomaly
triggers, and exposes the HTTP API the agent + frontend build against.

## Run

```bash
pip install -r ../requirements.txt
uvicorn ingestor_service.app:app --reload --host 0.0.0.0 --port 8000
```

Interactive API docs at `http://localhost:8000/docs`. Full endpoint reference and
setup live in the root [README](../README.md).

## Package layout

The package is organized by responsibility so the HTTP surface stays thin and the
domain logic is testable in isolation:

```
ingestor_service/
  app.py            FastAPI app — loads env, mounts api/all_routers, startup hooks
  models.py         Shared Pydantic schema (telemetry ingestion contract)
  core/             Infrastructure
    config.py         Env accessors (Mongo, Voyage model, Groq, Redis)
    db.py             Sync PyMongo client + col() helper + index setup
  api/              HTTP routers (thin — parse, validate, delegate)
    __init__.py       all_routers (ordered; see note below)
    telemetry.py      POST /ingest/telemetry, GET /health
    read.py           GET endpoints (agent reads)
    write.py          PATCH/POST anomaly lifecycle (analyze/assign/resolve)
    knowledge.py      knowledge_base CRUD + curation review queue
    agent_logs.py     POST/GET /agent_logs (agent run traces)
    admin.py          POST /simulation/reset (demo state purge)
  services/         Domain logic (no HTTP)
    ingest.py         Persist telemetry
    rag.py            search_knowledge() over Atlas Vector Search (autoEmbed)
    feedback_to_knowledge.py  Closed RAG loop (resolution notes → knowledge_base)
    severity_engine.py        breach_ratio → severity_level / severity_type
  messaging/        Redis + dispatch
    queue.py          XADD anomaly jobs to a Redis stream
    agent_stub.py     stdout stub when AGENT_DISPATCH=stub
  detector/         Threshold checks, debounce state, anomaly creation
```

**Router ordering:** `api/__init__.py` builds `all_routers` with `read` before
`knowledge` on purpose — the literal `GET /knowledge/search` lives in `read.py`,
and FastAPI matches in registration order, so mounting `knowledge`'s
`/knowledge/{document_id}` first would shadow it.

## Endpoint (entrypoint)

- `POST /ingest/telemetry` — ingest one telemetry event:

```json
{ "stored": true, "anomaly_created": true, "anomaly_id": "ANOM-..." }
```
