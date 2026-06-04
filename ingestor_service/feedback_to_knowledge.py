"""Closed RAG loop — embed field-resolution feedback back into knowledge_base.

Sync PyMongo variant. Imported by routes_write.py (step 06). New entries are
inserted with is_active=False so a human curator reviews them before they
influence retrieval — a deliberate guardrail, since bad resolution notes would
otherwise poison RAG forever. The data team owns the curation queue.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from . import config
from .db import col
from .rag import embed


def embed_resolution_into_knowledge(
    *,
    anomaly_id: str,
    anomaly: dict,
    resolution_notes: str,
    resolved_by: Optional[str],
) -> str:
    """Embed a resolution into knowledge_base. Returns the new document_id."""
    now = datetime.now(timezone.utc)

    text = (
        f"Incident on {anomaly.get('equipment_id') or 'unknown equipment'} "
        f"({anomaly.get('metric_type')}). "
        f"Trigger: {anomaly.get('trigger_value')}. "
        f"Original description: {anomaly.get('description') or 'n/a'}. "
        f"Field resolution: {resolution_notes}"
    )

    vec = embed(text)
    doc_id = f"fb-{uuid.uuid4()}"

    # equipment_type lookup — fall back to the sensors collection if the
    # anomaly doc doesn't carry the joined value.
    equipment_type = anomaly.get("equipment_type")
    if not equipment_type and anomaly.get("sensor_id"):
        sensor = col("sensors").find_one({"sensor_id": anomaly["sensor_id"]})
        equipment_type = (sensor or {}).get("equipment_type")

    col("knowledge_base").insert_one({
        "document_id": doc_id,
        "source_file": f"anomaly:{anomaly_id}",
        "page_number": None,
        "section_title": (
            f"Field resolution: "
            f"{anomaly.get('error_code') or anomaly.get('metric_type') or 'incident'}"
        ),
        "equipment_type": equipment_type,
        "associated_error_codes": (
            [anomaly["error_code"]] if anomaly.get("error_code") else []
        ),
        "text_content": text,
        "text_embedding": vec,
        "embedding_model": config.embed_model(),
        "embedding_dimensions": config.embed_dimensions(),
        "chunk_index": 0,
        "is_active": False,            # awaits curator review
        "ingested_at_utc": now,
        "schema_version": 1,
        "source_metadata": {
            "type": "field_feedback",
            "anomaly_id": anomaly_id,
            "resolved_by": resolved_by,
        },
    })
    return doc_id
