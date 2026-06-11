# Agent Team Integration Guide

How the backend works **now**, where your agent plugs in, and the things that
will bite you if you don't know them up front.

> TL;DR: The detector creates an anomaly and pushes a job to a Redis stream. A
> separate `agent_worker` process consumes it. **Your LangGraph graph goes inside
> `agent_worker/consumer.py::process_anomaly_job()`.** It should talk to the data
> layer over the **HTTP API**, not by querying Mongo directly.

---

## 1. The flow, end to end

```
simulator ──HTTP──▶ ingestor (FastAPI) ──▶ stores telemetry ──▶ detector checks thresholds
                                                                      │
                                          (2 consecutive breaches) ───┘
                                                                      ▼
                                        anomaly written to Mongo (status="unresolved")
                                                                      ▼
                                        queue.dispatch_anomaly()  ──XADD──▶ Redis stream "anomaly:jobs"
                                                                      ▼
                          agent_worker  ──XREADGROUP──▶ gets {anomaly_id, sensor_id, error_code, severity...}
                                                                      ▼
                          process_anomaly_job()  ──HTTP GET /anomalies/{id}──▶ full context
                                                                      ▼
                          ★ YOUR LANGGRAPH GRAPH RUNS HERE ★
                                                                      ▼
                          ──HTTP PATCH /anomalies/{id}──▶ writes analysis (status="analyzed")
```

The ingestor **never blocks** on your agent — it only does a fast `XADD`. Your
worker runs independently and can be restarted/redeployed without touching the
data layer.

---

## 2. Where you plug in

**File: `agent_worker/consumer.py`, function `process_anomaly_job(fields)`.**

Today it's a placeholder that fetches the anomaly and logs it. Replace the body
with your graph. The `fields` dict you receive from the stream contains:

```python
{
  "anomaly_id": "ANOM-...",
  "sensor_id": "SENS-VIB-001",
  "error_code": "VIBRATION_HIGH",
  "severity_type": "high",
  "severity_level": "9",
  "timestamp_utc": "2026-06-08T12:00:00Z",
  "event_type": "anomaly_detected",
}
```

Use `anomaly_id` to fetch full context from the API, run your graph, then PATCH
the result back. **Do not import the ingestor's internals or query Mongo
directly** — go through the HTTP API so you stay decoupled (the worker is even a
separate config/process for this reason).

---

## 3. The API you build against

Base URL = `DATA_LAYER_BASE_URL` (default `http://localhost:8000`). All responses
are JSON with Mongo `_id` removed.

### Reads (gather context)
| Method | Path | Use |
|--------|------|-----|
| `GET` | `/anomalies/{id}` | full anomaly document |
| `GET` | `/anomalies?status=unresolved&limit=N` | poll/list anomalies |
| `GET` | `/sensors/{sensor_id}` | sensor metadata — **gives you `equipment_type`** for the knowledge filter |
| `GET` | `/sensors/{sensor_id}/readings?minutes=60&limit=200` | recent telemetry for trend analysis |
| `GET` | `/knowledge/search?q=...&equipment_type=...&error_codes=CSV&k=5` | RAG retrieval |
| `GET` | `/knowledge?is_active=false&source=feedback` | knowledge list / **curation review queue** (also `source=seed/manual`, `equipment_type`, `limit`, `skip`) |
| `GET` | `/knowledge/{document_id}` | one knowledge entry |
| `GET` | `/staff_on_call?is_on_call=true&specialization=vibration&handled_severity_type=high` | candidate workers |

### Writes (commit results)
| Method | Path | Use |
|--------|------|-----|
| `PATCH` | `/anomalies/{id}` | commit analysis: `{description, recommended_solution, similar_cases, recommended_employee_id, agent_run_id, status:"analyzed"}` |
| `POST` | `/anomalies/{id}/assign` | `{employee_id}` — manager action (sets `assigned`, marks staff busy) |
| `POST` | `/anomalies/{id}/resolve` | `{outcome, resolution_notes, resolved_by?}` — staff action; `outcome="fixed"` triggers the closed RAG loop |
| `POST` | `/agent_logs` | write a run trace to `agent_execution_logs` — **upsert keyed by `run_id`** (write `status:"running"` at the start, overwrite with `"completed"`/`"failed"` at the end) |
| `GET` | `/agent_logs?anomaly_id=...&run_id=...&status=...` | read run traces (for the observability dashboard) |
| `POST` | `/knowledge` | create a knowledge entry (text only — Atlas autoEmbed handles the vector) |
| `PATCH` | `/knowledge/{document_id}` | update an entry; curator **approves** feedback with `{"is_active": true}` |
| `DELETE` | `/knowledge/{document_id}` | hard delete; curator **rejects** a feedback entry |
| `POST` | `/simulation/reset` | demo reset: purges anomalies/telemetry/agent logs/session events, restores staff to on-call, trims the Redis job stream. Body `{"purge_feedback_knowledge": true}` also drops uncurated `fb-*` docs. Seed data untouched. |

### The anomaly document you get back
```json
{
  "anomaly_id": "ANOM-...", "timestamp_utc": "...",
  "sensor_id": "SENS-VIB-001", "facility_id": "FAC-01", "equipment_id": "PUMP-A12",
  "metric_type": "vibration", "error_code": "VIBRATION_HIGH",
  "severity_level": 9, "severity_type": "high", "breach_ratio": 0.4,
  "trigger_value": {"metric":"amplitude_mm","observed":0.7,"limit":0.5,"unit":"si","consecutive_count":2},
  "status": "unresolved", "created_at_utc": "...", "updated_at_utc": "..."
}
```

### Recommended agent flow
1. `GET /anomalies/{id}` → read `error_code`, `metric_type`, `equipment_id`, `trigger_value`.
2. `GET /sensors/{sensor_id}` → get `equipment_type`.
3. `GET /sensors/{sensor_id}/readings` → recent trend.
4. `GET /knowledge/search?q=<describe the fault>&equipment_type=<...>&error_codes=<error_code>&k=5` → grounding docs.
5. Run your LLM reasoning (Groq).
6. `PATCH /anomalies/{id}` with `description`, `recommended_solution`, `similar_cases`, `recommended_employee_id`, `agent_run_id`, `status:"analyzed"`.
7. (Optional) `GET /staff_on_call?...` to pick the worker you recommend.

---

## 4. The anomaly status lifecycle (the API enforces it)

```
unresolved ──PATCH──▶ analyzed ──assign──▶ assigned ──resolve──▶ resolved
```

Rules — violating these returns **HTTP 409**:
- `PATCH` may only move status to `unresolved`/`analyzed`. It **cannot** set
  `assigned` or `resolved` (those have side effects — use the dedicated endpoints).
- You **cannot move status backward** (e.g. `analyzed` → `unresolved`).
- `resolved` is terminal.

So your agent's only status write is `status:"analyzed"`. Assign/resolve are
human actions (manager/staff), not the agent's.

---

## 5. RAG / knowledge search

- Query with `q` (natural-language fault description) plus optional filters
  `equipment_type` and `error_codes` (comma-separated). The error codes are the
  **join key** — pass the anomaly's `error_code` to get knowledge tagged for that
  exact fault.
- Returns top-k docs with `text_content`, `section_title`, `equipment_type`,
  `associated_error_codes` (no raw embedding).
- Only `is_active=true` docs are returned (feedback awaiting curation is hidden).

---

## 6. Important considerations before you write code

### 6.1 ⚠️ Your current `main.py` targets the OLD schema — retarget it
The reviewed agent script reads `machines`, `raw_readings`, `reports` and
metrics `temperature/vibration/spindle_load`. **None of those exist here.** Map:

| Old (your script) | This backend |
|---|---|
| `db["machines"]`, keyed by `_id` | `sensors`, keyed by `sensor_id` (or `GET /sensors/{id}`) |
| `db["raw_readings"]` | `telemetry_history` (or `GET /sensors/{id}/readings`) |
| `db["reports"]` | `anomalies` (or `GET /anomalies/{id}`) |
| `machine_id` | `sensor_id` |
| `temperature / vibration / spindle_load` | polymorphic: `temp_celsius`, `humidity_percent`, `amplitude_mm`, `pressure_bar`, `flow_rate_lpm` |
| alert `{value, threshold}` | `trigger_value.{observed, limit}` |

**Metrics are polymorphic** — one metric type per sensor. An environment sensor
has temp/humidity; a vibration sensor has amplitude. Do **not** assume every
reading has the same three metrics, or you'll `KeyError`.

### 6.2 Use the API, not direct Mongo
It decouples you from our schema and gives you the documented, validated contract.
Direct DB access also means you'd need our `MONGO_URI`/`DB_NAME` and have to track
schema changes yourself.

### 6.3 Make `process_anomaly_job` idempotent
Redis Streams is **at-least-once** — the same job can be delivered more than once
(e.g. if a worker dies before `XACK`). Before analyzing, check the anomaly's
`status`; if it's already `analyzed`/`assigned`/`resolved`, skip or no-op. Don't
assume "I see this job ⇒ it's brand new."

### 6.4 Don't crash the worker
If your graph throws, let it propagate as an exception — the consumer logs it and
leaves the job **pending** for retry (it won't `XACK`). But avoid infinite
poison-message loops: consider catching, writing an error note via `PATCH`, and
acking after N attempts.

### 6.5 Chat model = Groq, OpenAI-compatible
Use `config.groq_api_key()` + `config.groq_base_url()` with the OpenAI SDK, or the
`groq` SDK directly. Model: `llama-3.3-70b-versatile`. Add `groq` (or `openai`) to
your deps. Watch the JSON-parsing typo from the reviewed script:
`recommended_solution` (two m's) must match what you actually parse.

### 6.6 RAG is semantic (the vector index is live)
The `knowledge_vector` autoEmbed index is created and Active — `/knowledge/search`
returns vector-ranked results. If the index ever goes missing/rebuilding, the
endpoint degrades gracefully to **recency-ranked** results (filtered by
equipment/error code) with a warning log. Plan prompts so they're robust to either.

### 6.7 Embeddings are managed by Atlas — you don't embed anything
Embedding is handled inside the data layer by Atlas Vector Search Automated
Embedding (Voyage AI): Atlas embeds `text_content` at index time and your query
text at query time. There's no embeddings API key and no separate rate limit to
worry about — you just call `/knowledge/search` with text.

### 6.8 Write your run traces to `agent_execution_logs`
There's a collection (and `agent_run_id` field on anomalies) for tracing agent
runs — tool calls, latency, tokens, final action. **Write to it via
`POST /agent_logs`** (don't touch Mongo directly — see §6.2). It's an upsert keyed
by `run_id`, so the pattern is: write a `status:"running"` record when the graph
starts, then overwrite it with the `"completed"`/`"failed"` record (execution
steps, tokens, final action) when it finishes. The document shape is the
`agent_execution_logs` contract in `scripts/init_db.py`.

**Correlation:** use the *same* id for the trace's `run_id` and the anomaly's
`agent_run_id` (the value you send in the `PATCH /anomalies/{id}` body). That lets
the dashboard join an anomaly to the agent run that analyzed it.

The reference graph in `agent_worker/anomaly_graph.py` already does all of this:
its `start` node writes the `running` record and its `finalize` node writes the
`completed` record, both best-effort (a tracing failure never breaks a run).

### 6.9 Database name — settled: `anomaly_db`
The DB name is **`anomaly_db`** (the stray `anomaly_detection` DB was dropped;
`.env.example` and README now say `anomaly_db`). Make sure your worker's
`DATA_LAYER_BASE_URL` points at an ingestor whose `.env` has `DB_NAME="anomaly_db"`
— otherwise you'll read an empty/old dataset.

### 6.10 No auth yet
The API is currently open (dev). Don't hardcode assumptions that it will stay that
way — a token/Bearer header is likely to be added.

---

## 7. Run it locally

```bash
# .env: set AGENT_DISPATCH=redis
redis-server                                            # terminal 1
uvicorn ingestor_service.app:app --reload --port 8000   # terminal 2
python -m agent_worker.main                             # terminal 3  (your worker)
python -m simulator_service.main --base-url http://localhost:8000 --deterministic-demo  # terminal 4
```

The simulator's `--deterministic-demo` forces a guaranteed anomaly every 10 ticks,
so you'll see a job hit your worker quickly. Swagger UI: `http://localhost:8000/docs`.

---

## 8. Open questions to settle with the data team

1. ~~**DB name**~~ — **settled**: `anomaly_db` (stray `anomaly_detection` dropped; see §6.9).
2. ~~**Vector index**~~ — **settled**: `knowledge_vector` autoEmbed index is live; RAG is semantic.
3. ~~**`agent_execution_logs` schema**~~ — **settled**: write via `POST /agent_logs`
   (see §6.8); shape is the contract in `scripts/init_db.py`.
4. **Retry/poison policy** — how many attempts before a job is parked/errored.
