# Run the WHOLE stack with one command (Ctrl+C stops everything):
#   Windows:  powershell -ExecutionPolicy Bypass -File scripts\dev_up.ps1
#   Unix:     ./scripts/dev_up.sh
#   Direct:   honcho start            (needs venv active + honcho installed)
# Subset:     honcho start api agent
redis: bash scripts/run_redis.sh
api: uvicorn ingestor_service.app:app --host 0.0.0.0 --port 8000 --reload
agent: bash scripts/run_agent.sh
sim: bash scripts/run_sim.sh
web: bash scripts/run_web.sh
