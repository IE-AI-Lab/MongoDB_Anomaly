# Simulator Service

Simulates the monitoring points of one **ball mill** (MILL-01) and posts
telemetry to the ingestor. The fleet: two trunnion bearings (temperature),
the girth-gear and pinion drivetrain (vibration, mm/s RMS), the lube-oil system
(pressure), and the bearing coolant loop (flow).

## Run

```bash
pip install -r ../requirements.txt
python3 -m simulator_service.main --base-url http://localhost:8000 --tick-seconds 5
# --deterministic-demo : raise every machine's degradation rate to a floor so a
#                        fresh demo trips anomalies promptly.
# --emit-probability   : chance a HEALTHY machine emits on a tick (faulted ones
#                        always emit). Default 0.7.
```

## Signal model (see `generators.py`)

Each machine carries a **continuous** signal, not independent random draws:

```
value = baseline + seasonal(sine) + ar1_noise + sign*(wear + sub_threshold_spike)
```

- **Degradation trend**: `wear` accumulates each tick at a rate set by the
  per-machine `sim_stress` slider (0 = healthy/flat, 1 = steep climb). Steeper =
  crosses the alarm sooner = more frequent anomalies.
- **Step-faults**: occasional sudden jumps clear over the limit.
- **Sub-threshold texture**: frequent small spikes kept under the limit (no false
  anomalies) for realism.

A breach is **held** (the value stays over the limit) until a worker **resolves**
the anomaly — the simulator polls `GET /anomalies` to detect this — then the
signal **decays** back to baseline. It only decreases after the worker says done.

`sim_stress` lives on each `sensors` doc; the dashboard slider sets it via
`POST /simulation/sensors/{id}/stress`, and the simulator reads it each cycle.

## What it sends

One event per emitting sensor per tick to `POST {base_url}/ingest/telemetry`.
The payload shape matches `ingestor_service.models.TelemetryIngestEvent`.

