# One command: honcho start   (or ./scripts/dev_up.sh)
# Subset:       honcho start api agent
redis: bash scripts/run_redis.sh
api: uvicorn ingestor_service.app:app --host 0.0.0.0 --port 8000 --reload
agent: bash scripts/run_agent.sh
sim: bash scripts/run_sim.sh
