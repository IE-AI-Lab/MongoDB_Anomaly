# MongoDB Atlas Anomaly Agent (Simulator + Ingestor)

This repository contains:

- `init_db.py`: Initializes MongoDB collections, indexes, and seed configuration.
- `ingestor_service/`: FastAPI service that ingests telemetry and runs anomaly detection.
- `simulator_service/`: Telemetry simulator that posts events to the ingestor.

## Quick start

1. Create `.env` in the repo root:

```bash
MONGO_URI="mongodb+srv://..."
DB_NAME="your_db_name"
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Initialize the database:

```bash
python3 init_db.py
```

4. Start the ingestor API:

```bash
uvicorn ingestor_service.api:app --reload --host 0.0.0.0 --port 8000
```

5. Run the simulator in a separate terminal:

```bash
python3 -m simulator_service.main --base-url http://localhost:8000 --tick-seconds 5
```

