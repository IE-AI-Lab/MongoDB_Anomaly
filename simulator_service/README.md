# Simulator Service

This service simulates multiple sensors and posts telemetry events to the ingestor service.

## Run

```bash
pip install -r ../requirements.txt
python3 -m simulator_service.main --base-url http://localhost:8000 --tick-seconds 5
```

## What it sends

It posts one event per sensor per tick to:

- `POST {base_url}/ingest/telemetry`

The payload shape matches `ingestor_service.models.TelemetryIngestEvent`.

