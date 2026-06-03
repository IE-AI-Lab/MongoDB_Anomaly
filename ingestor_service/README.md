# Ingestor Service (FastAPI)

This service receives telemetry events, writes them into MongoDB Atlas, runs the anomaly detector,
and calls a local `agent_stub(anomaly_doc)` when an anomaly triggers.

## Run

```bash
pip install -r ../requirements.txt
uvicorn ingestor_service.api:app --reload --host 0.0.0.0 --port 8000
```

## Endpoint

- `POST /ingest/telemetry`: ingest one telemetry event

Response:

```json
{ "stored": true, "anomaly_created": false }
```

or

```json
{ "stored": true, "anomaly_created": true, "anomaly_id": "ANOM-..." }
```

