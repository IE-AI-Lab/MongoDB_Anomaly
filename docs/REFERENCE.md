# Reference

Detailed reference for integrators. For the project overview, setup, and
architecture, see the root [README](../README.md). Live, interactive API docs are
always at `http://localhost:8000/docs`.

- [Anomaly detection](#anomaly-detection)
- [Agent worker (LangGraph)](#agent-worker-langgraph-investigation)
- [Anomaly lifecycle](#anomaly-lifecycle)
- [HTTP API](#http-api)
- [Telemetry ingestion contract](#telemetry-ingestion-contract)
- [Collections](#collections)
- [RAG retrieval](#rag-retrieval)
- [LLM provider](#llm-provider-chat--agent-reasoning)
- [Evaluation](#evaluation)
- [LangSmith tracing](#agent-debugging-with-langsmith)
- [Module map](#module-map)
- [Conventions & gotchas](#conventions--gotchas)

---

## Anomaly detection

The detector runs three detectors per metric, in priority order — the first to
fire wins (one anomaly per telemetry document):

1. **Threshold** *(always on)* — value crosses a static limit
   (`system_metadata.anomaly_thresholds`) for N consecutive readings. Severity
   comes from how far past the limit the value is.
2. **Rate-of-change** *(env-gated: `ANOMALY_ROC_ENABLED`)* — value jumps more
   than `ANOMALY_ROC_PCT` (e.g. 30%) versus the previous reading. Catches fast
   excursions that are still within static limits. Emits
   `{METRIC}_RAPID_RISE` / `{METRIC}_RAPID_DROP`.
3. **Statistical** *(env-gated: `ANOMALY_STAT_ENABLED`)* — value is a z-score
   outlier (`|z| > ANOMALY_STAT_ZSCORE`) versus a rolling baseline of the last
   `ANOMALY_STAT_MIN_READINGS`+ values. Emits `{METRIC}_OUTLIER`.

Windows are **count-based** (last `ANOMALY_WINDOW_SIZE` readings) rather than
time-based, because the simulator/pipeline runs intermittently — "last N
readings" is more reliable than "last N minutes". Each anomaly records a
`detection_method` field (`threshold` | `rate_of_change` | `statistical`) and
detector-specific stats under `trigger_value` (e.g. `pct_change`, `z_score`).

> The new rate-of-change/statistical error codes don't have seeded knowledge
> docs yet, so RAG retrieval for them falls back gracefully. Seed
> `{METRIC}_RAPID_RISE` etc. into `knowledge_base` if you want tailored guidance.

---

## Agent worker (LangGraph investigation)

`agent_worker/` is the reasoning agent — a separate process that consumes anomaly
jobs from Redis and writes its analysis back over the HTTP API (it imports
nothing from `ingestor_service`). Per anomaly:

1. **Consume** — `consumer.py` drains the per-severity streams in priority order
   (high → medium → low), at-least-once (XACK on success). A failed job is
   requeued with an incremented `attempts`; after `ANOMALY_MAX_RETRIES` (default
   3) it is dead-lettered to `anomaly:dlq`. A reset that wipes the streams is
   survived (the consumer group is recreated, not crashed).
2. **Investigate** — `anomaly_graph.py` (LangGraph) gathers context, then a ReAct
   agent (`investigation_agent.py`) calls tools (`agent_tools.py`) over the API:
   `query_rag_knowledge_base`, `get_staff_contact`, `get_sensor_readings`,
   `retrieve_recent_alerts`, `retrieve_machine_memory`. A retrieved escalation
   rule ("if temp is high, contact X") takes precedence over generic advice.
3. **Parse** — `decision_parser.py` recovers the decision JSON from the LLM's
   (often prose-wrapped) final message; `similar_cases` always come from the real
   RAG tool output, never the model's invention. No key / repeated LLM error → a
   deterministic fallback decision, so the worker always produces a result.
4. **Write back** — PATCHes the anomaly to `analyzed` (description, recommended
   solution, recommended employee, similar cases) and best-effort writes a trace
   to `agent_execution_logs`.

Each anomaly takes ~25–35s (several sequential LLM tool-calls), processed one at
a time. Tune via env: `CHAT_MODEL`, `ANOMALY_MAX_RETRIES`,
`AGENT_CONSUMER_BLOCK_MS`, `ANOMALY_STREAM_PREFIX`.

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
| `GET` | `/sensors` | `is_active` (default true), `metric_type` | list of machines/sensors |
| `GET` | `/sensors/{sensor_id}` | — | one sensor |
| `GET` | `/sensors/{sensor_id}/readings` | `minutes` (1–1440), `limit` (1–2000) | recent telemetry |
| `GET` | `/system_metadata` | `config_type`, `target_metric` | threshold + severity-band config (chart limit lines) |
| `GET` | `/knowledge/search` | `q` (required), `equipment_type`, `error_codes` (CSV), `k` (1–20) | ranked knowledge docs |
| `GET` | `/staff_on_call` | `is_on_call`, `specialization`, `handled_severity_type`, `facility_id` | staff, by escalation rank |

### Write (agent / manager / staff act)

| Method | Path | Body | Effect |
|--------|------|------|--------|
| `PATCH` | `/anomalies/{anomaly_id}` | `{description?, recommended_solution?, similar_cases?, recommended_employee_id?, agent_run_id?, status?}` | agent commits analysis (typically `status:"analyzed"`) |
| `POST` | `/anomalies/{anomaly_id}/assign` | `{employee_id}` | assigns staff, sets `assigned`, flips staff `is_on_call→false` |
| `POST` | `/anomalies/{anomaly_id}/resolve` | `{outcome, resolution_notes, resolved_by?}` | sets `resolved`, frees staff; if `outcome=="fixed"`, embeds notes into `knowledge_base` and returns `knowledge_document_id` |

### Knowledge curation (CRUD over `knowledge_base`)

Resolution feedback enters `knowledge_base` as `is_active=false`,
`curation_status="pending"` and is invisible to retrieval until a curator
approves it — a guardrail against poisoning RAG with bad field notes.

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
| `GET`  | `/queues/status` | — | per-severity Redis stream depths + DLQ count (`{available, streams:{high,medium,low}, dlq}`); fail-open to `available:false` when dispatch isn't redis. Backs the dashboard's Agent Queue panel. |
| `POST` | `/queues/reset` | — | wipes Redis anomaly streams only (`anomaly:high|medium|low`, `anomaly:dlq`); Mongo untouched. Use before a monitoring run for fresh Grafana `len`/`pending` counters. |
| `POST` | `/simulation/reset` | `{purge_feedback_knowledge?: false}` | full demo reset: purges anomalies, telemetry, agent logs, session events; restores all staff to on-call; clears in-memory detector debounce state; wipes the per-severity Redis streams + DLQ; seed data untouched. Restart the simulator to reset its sequence counters. |
| `GET`  | `/simulation/status` | — | `{running}` — simulator polls this each tick (fail-open to running) |
| `POST` | `/simulation/start` | — | resume telemetry emission (`{running:true}`) |
| `POST` | `/simulation/stop` | — | pause telemetry emission (`{running:false}`); the simulator process stays alive |

### Example agent flow

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

`metric_type` ∈ `environment | vibration | pressure | flow`; metric values go
under `reading.data` (e.g. `{"amplitude_mm": 0.7}`). Threshold error codes:
`TEMP_HIGH`, `TEMP_LOW`, `HUMIDITY_HIGH`, `VIBRATION_HIGH`, `PRESSURE_LOW`,
`FLOW_LOW`; the rate-of-change / statistical detectors add `{METRIC}_RAPID_RISE`,
`{METRIC}_RAPID_DROP`, `{METRIC}_OUTLIER` (see [Anomaly detection](#anomaly-detection)).
These error codes are the join keys into `knowledge_base.associated_error_codes`.

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
| `agent_execution_logs` | Agent run traces (written by `agent_worker`, upsert by `run_id`) |
| `session_events` | High-signal event stream |

Full field contracts are documented inline in [scripts/init_db.py](../scripts/init_db.py).

---

## RAG retrieval

`ingestor_service/services/rag.py` —
`search_knowledge(query, *, equipment_type=None, error_codes=None, k=5)` is
**hybrid**: it merges two passes and de-dupes by `document_id`:

- **Vector** — Atlas `$vectorSearch` with **automated query embedding** (passes
  the raw query text + model; Atlas embeds it), pre-filtered to `is_active=True`
  (+ optional `equipment_type` / `error_codes`).
- **Keyword** — a lexical regex pass over `text_content` / `section_title`,
  filtered only by `is_active`, so manually added rules (which often lack
  `equipment_type`/`error_codes`) and not-yet-indexed docs are still found.

If both come back empty it **falls back to a filtered recency sort** (e.g. the
`knowledge_vector` index isn't Active yet). The service never computes or stores
a vector — Atlas owns the embeddings (it materializes them into an internal
`_mdb_internal_search` collection; `knowledge_base` stays text-only).

**Closed loop:** resolving an anomaly with `outcome="fixed"` writes the
resolution notes back into `knowledge_base` as `is_active=false`,
`curation_status="pending"`. A human curator approves it via
`PATCH /knowledge/{document_id}` with `{"is_active": true}` before it influences
retrieval — a guardrail against poisoning RAG with bad notes.

**Migrations:** `python -m scripts.migrate_drop_embedding_fields` — one-off
cleanup that `$unset`s the pre-autoEmbed `text_embedding` / `embedding_model` /
`embedding_dimensions` fields from `knowledge_base`. Idempotent.

---

## LLM provider (chat / agent reasoning)

The agent reasons with **DeepSeek**. It calls it through
`langchain_openai.ChatOpenAI` (built with `max_retries=5`) — note that
**"OpenAI" here is the *wire format*, not the vendor**: the OpenAI
chat-completions API is a de-facto standard that DeepSeek implements, so the same
client library talks to DeepSeek when pointed at `LLM_BASE_URL`. No request goes
to OpenAI, and no OpenAI key is used. Configured by the env triple in
`agent_worker/config.py`:

| Env | `agent_worker.config` getter | Default |
|-----|------------------------------|---------|
| `LLM_BASE_URL` | `llm_base_url()` | `https://api.deepseek.com` |
| `LLM_API_KEY`  | `llm_api_key()` (falls back to `DEEPSEEK_API_KEY`) | — |
| `CHAT_MODEL`   | `chat_model()` | `deepseek-v4-flash` |

Because the endpoint is OpenAI-compatible, you *can* point it at another
compatible provider by changing `LLM_BASE_URL` + `LLM_API_KEY` + `CHAT_MODEL`.
With **no key**, the investigation node skips the LLM and returns a deterministic
fallback decision so the worker still runs.

---

## Evaluation

A compact, CI-safe eval suite lives under `tests/evals/` (`pytest tests/evals/`):

- **RAG retrieval evals** validate that representative anomaly queries
  (temperature, vibration, pressure, flow, humidity) retrieve at least one
  matching knowledge document.
- **Agent output evals** run `run_investigation_agent()` with a mocked ReAct app
  (no live API calls) and assert JSON schema quality: non-empty
  `description`/`recommended_solution` and traceable `rag_query_used`.
- **DeepEval judge metric (optional live mode)** runs only when
  `DEEPEVAL_LIVE=1` and `OPENAI_API_KEY` are set.

| Metric | Default in CI | Live mode |
|--------|----------------|-----------|
| Answer Relevancy | skipped | `DEEPEVAL_LIVE=1 OPENAI_API_KEY=...` |
| Faithfulness | documented target | can be added with same live toggle |
| Contextual Recall | documented target | can be added with same live toggle |

---

## Agent debugging with LangSmith

Enable LangSmith tracing for the `agent_worker` process to inspect full ReAct
execution (tool calls, tool payloads, and final JSON decision):

```bash
# in .env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=...
LANGCHAIN_PROJECT=mongodb-anomaly-agent
```

Then run the stack and trigger an anomaly. In LangSmith, open the
`mongodb-anomaly-agent` project, filter runs by `anomaly_id`, and inspect the
trace to see ReAct tool spans (`query_rag_knowledge_base`, `get_staff_contact`,
`get_sensor_readings`, etc.).

---

## Module map

```
scripts/
  init_db.py                Idempotent DB setup + seed (run once)
  knowledge_seed.py         Seed knowledge corpus
  dev_up.sh / dev_up.ps1    One-command whole-stack launchers (Unix / Windows)
ingestor_service/           Data layer (run: uvicorn ingestor_service.app:app)
  app.py                    FastAPI app; mounts api/all_routers + startup hooks
  models.py                 Telemetry ingestion Pydantic contract
  observability.py          Env-gated OTEL setup for the API
  core/
    config.py               Env accessors (Mongo, Voyage model, Redis, OTEL, dispatch, queue routing)
    db.py                   Sync PyMongo client + col() helper + indexes
  api/                      Thin HTTP routers
    telemetry.py            POST /ingest/telemetry, GET /health
    read.py                 GET endpoints (anomalies, sensors, system_metadata, staff, knowledge/search)
    write.py                PATCH/POST anomaly endpoints (analyze/assign/resolve)
    knowledge.py            knowledge_base CRUD + curation review queue
    agent_logs.py           POST/GET /agent_logs (agent run traces)
    admin.py                simulation start/stop/status/reset + queues status/reset
  services/                 Domain logic (no HTTP)
    ingest.py               Persist telemetry
    rag.py                  search_knowledge() — hybrid vector + keyword (Atlas autoEmbed)
    feedback_to_knowledge.py  Closed RAG loop
    severity_engine.py      breach_ratio → severity_level / severity_type
    simulation_control.py   Run/pause flag (system_metadata) read/write + canonical shape
  messaging/
    queue.py                Severity-routed Redis streams (XADD/reset/status) + DLQ
    agent_stub.py           stdout stub when AGENT_DISPATCH=stub
  detector/                 thresholds, state (rolling windows), detect (3 detectors)
agent_worker/               LangGraph reasoning agent (python -m agent_worker.main)
  main.py                   Entrypoint: load env → langsmith → otel → run_consumer
  consumer.py               Priority drain + retry/DLQ; recreates group on reset
  anomaly_graph.py          LangGraph: gather context → investigate → PATCH back
  investigation_agent.py    ReAct agent + deterministic fallback decision
  decision_parser.py        Recover decision JSON from messy LLM output
  agent_tools.py            Tool fns the agent calls over the HTTP API
  config.py / observability.py  LLM/Redis/OTEL env getters; LangSmith + OTEL
simulator_service/          Telemetry + fault generator (polls /simulation/status)
frontend/                   Next.js operator dashboard (see frontend/README.md)
monitoring/                 OTEL Collector → Prometheus → Grafana (optional)
```

---

## Conventions & gotchas

- **Synchronous PyMongo.** `db.py` is sync; FastAPI handlers are plain `def`
  (FastAPI runs them in a threadpool). Do **not** add `async`/`await` to DB calls.
- **Everything integrates over HTTP.** No service imports another's internals or
  touches its database directly.
- **Embeddings are managed by Atlas.** We store only `text_content`; the
  `knowledge_vector` autoEmbed index generates and syncs the vector. No
  dimensions to match. Change `VOYAGE_EMBED_MODEL`? Update the index's `model`
  to match (Atlas re-embeds), then re-seed if needed.
- **Status vocabulary:** `unresolved → analyzed → assigned → resolved`.
- **Knowledge search before the index exists** returns recency-sorted results
  (with a warning log), not vector-ranked. Create the `knowledge_vector` index
  for real similarity.
- **Windows:** use `127.0.0.1`, not `localhost`, for `DATA_LAYER_BASE_URL` — IPv6
  `::1` resolves first and adds ~2s per HTTP call.
