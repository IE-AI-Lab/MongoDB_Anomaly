"""HTTP routers for the data layer.

`all_routers` is the single, ordered list `app.py` mounts. Order matters in one
place: `knowledge` MUST come after `read` — the literal `GET /knowledge/search`
lives in `read.py`, and FastAPI matches in registration order, so mounting
`knowledge` (with its `/knowledge/{document_id}` param route) first would shadow
it. Keep `read` before `knowledge`.
"""
from __future__ import annotations

from . import admin, agent_logs, knowledge, read, telemetry, write

all_routers = [
    telemetry.router,
    read.router,
    write.router,
    agent_logs.router,
    knowledge.router,  # after read: /knowledge/{id} must not shadow /knowledge/search
    admin.router,
]
