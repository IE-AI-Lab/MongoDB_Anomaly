"""
Initialize the MongoDB Atlas data layout for an event-driven AI anomaly
detection agent.

The script is intentionally idempotent:
- Existing collections are reused.
- The time-series collection creation is skipped if it already exists.
- Default system metadata is inserted only when missing.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import certifi
from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import CollectionInvalid, OperationFailure, PyMongoError

from ingestor_service.core import config as svc_config
from .knowledge_seed import KNOWLEDGE_SEED


STANDARD_COLLECTIONS = (
    "anomalies",
    "knowledge_base",
    "staff_on_call",
    "agent_execution_logs",
    "system_metadata",
    "sensors",
    "session_events",
)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def require_env(name: str) -> str:
    """Read a required environment variable or raise a clear error."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def collection_exists(db: Database[dict[str, Any]], collection_name: str) -> bool:
    return collection_name in db.list_collection_names()


def create_time_series_collection(db: Database[dict[str, Any]], ttl_seconds: int) -> None:
    # telemetry_history document contract:
    # {
    #     "_id": ObjectId,
    #     "timestamp_utc": datetime,  # REQUIRED. Time-series timeField.
    #     "sensor_id": str,           # REQUIRED. Time-series metaField.
    #     "ingested_at_utc": datetime,
    #     "source": str,              # e.g. "mqtt", "opcua", "batch_import".
    #     "sequence_number": int,
    #     "quality": str,             # e.g. "good", "suspect", "bad".
    #     "facility_id": str,
    #     "equipment_id": str,
    #     "reading": {
    #         "metric_type": str,      # REQUIRED. e.g. "environment", "vibration".
    #         "unit_system": str,      # e.g. "si".
    #
    #         # Polymorphic examples:
    #         # Environment reading:
    #         # "temp_celsius": float,
    #         # "humidity_percent": float,
    #         # "dew_point_celsius": float,
    #
    #         # Vibration reading:
    #         # "frequency_hz": float,
    #         # "amplitude_mm": float,
    #         # "rms_velocity_mm_s": float,
    #         # "peak_acceleration_g": float,
    #     },
    # }
    try:
        db.create_collection(
            "telemetry_history",
            timeseries={
                "timeField": "timestamp_utc",
                "metaField": "sensor_id",
                "granularity": "seconds",
            },
            # Time-series retention is set at the collection level. MongoDB
            # expires a bucket once all its documents are older than this.
            expireAfterSeconds=ttl_seconds,
        )
        print("Created time-series collection: telemetry_history")
    except CollectionInvalid:
        print("Collection already exists: telemetry_history")
    except OperationFailure as exc:
        # Atlas may report an OperationFailure if a namespace already exists.
        # Re-raise other failures so deployment issues are not hidden.
        if collection_exists(db, "telemetry_history"):
            print("Collection already exists: telemetry_history")
            return
        raise exc


def ensure_standard_collections(db: Database[dict[str, Any]]) -> None:
    # anomalies document contract:
    # {
    #     "_id": ObjectId,
    #     "anomaly_id": str,           # Stable external ID, unique.
    #     "timestamp_utc": datetime,
    #     "sensor_id": str,
    #     "facility_id": str,
    #     "equipment_id": str,
    #     "metric_type": str,
    #     "error_code": str,
    #     "severity_level": int,       # 1-10 numeric score.
    #     "severity_type": str,        # "low", "medium", or "high".
    #     "breach_ratio": float,       # How far past the limit (e.g. 0.25 = 25% over).
    #     "trigger_value": {
    #         "metric": str,
    #         "observed": float,
    #         "limit": float,
    #         "unit": str,
    #         "consecutive_count": int,
    #     },
    #     "status": str,               # "unresolved" or "resolved".
    #     "description": str,
    #     "assigned_to_employee_id": str,
    #     "resolved_at_utc": datetime,
    #     "resolved_by": str,
    #     "resolution_notes": str,
    #     "agent_run_id": str,
    #     "created_at_utc": datetime,
    #     "updated_at_utc": datetime,
    #     "schema_version": int,
    # }
    #
    # knowledge_base document contract:
    # {
    #     "_id": ObjectId,
    #     "document_id": str,          # Stable chunk/document ID, unique.
    #     "source_file": str,
    #     "page_number": int,
    #     "section_title": str,
    #     "equipment_type": str,
    #     "associated_error_codes": list[str],
    #     "text_content": str,         # Atlas autoEmbed generates the vector.
    #     "chunk_index": int,
    #     "is_active": bool,
    #     "ingested_at_utc": datetime,
    #     "schema_version": int,
    # }
    #
    # staff_on_call document contract:
    # {
    #     "_id": ObjectId,
    #     "employee_id": str,              # Unique.
    #     "name": str,
    #     "role": str,                     # "staff", "senior", or "manager".
    #     "escalation_rank": int,          # 1=staff, 2=senior, 3=manager.
    #     "specialization": list[str],     # Sensor/metric types handled.
    #     "handled_severity_type": str,     # "low", "medium", or "high".
    #     "is_on_call": bool,
    #     "contact_method": str,           # "SMS" or "Email".
    #     "phone_number": str,
    #     "email": str,
    #     "facility_ids": list[str],
    #     "is_active": bool,
    #     "updated_at_utc": datetime,
    # }
    #
    # agent_execution_logs document contract:
    # {
    #     "_id": ObjectId,
    #     "run_id": str,               # Unique execution ID.
    #     "anomaly_id": str,
    #     "started_at": datetime,
    #     "completed_at": datetime,
    #     "status": str,               # "running", "completed", "failed".
    #     "agent_name": str,
    #     "agent_version": str,
    #     "model_id": str,
    #     "execution_steps": [
    #         {
    #             "step_index": int,
    #             "tool_name": str,
    #             "started_at": datetime,
    #             "completed_at": datetime,
    #             "input_summary": dict,
    #             "output_summary": dict,
    #             "success": bool,
    #             "latency_ms": int,
    #         }
    #     ],
    #     "final_action_taken": str,
    #     "tokens_used": {
    #         "prompt": int,
    #         "completion": int,
    #         "total": int,
    #         "embedding": int,
    #     },
    #     "error": {"code": str, "message": str},
    #     "correlation_id": str,
    # }
    #
    # system_metadata document contract:
    # {
    #     "_id": ObjectId,
    #     "config_type": str,          # e.g. "anomaly_thresholds".
    #     "target_metric": str,        # e.g. "temp_celsius" or "*".
    #     "rules": {
    #         "max_allowed_temp_celsius": float,
    #         "min_allowed_temp_celsius": float,
    #         "consecutive_violating_pings_required": int,
    #     },
    #     "is_enabled": bool,
    #     "description": str,
    #     "last_updated_by": str,
    #     "last_updated_at_utc": datetime,
    #     "schema_version": int,
    # }
    for collection_name in STANDARD_COLLECTIONS:
        if collection_exists(db, collection_name):
            print(f"Collection already exists: {collection_name}")
            continue

        db.create_collection(collection_name)
        print(f"Created collection: {collection_name}")


def ensure_timeseries_ttl(db: Database[dict[str, Any]], ttl_seconds: int) -> None:
    """
    Retention policy for telemetry_history.

    Time-series collections expire data via the collection-level
    expireAfterSeconds option, set when the collection is created. This applies
    (or updates) it for an already-existing collection via collMod, so reruns
    and TTL changes take effect without recreating the collection.

    Note: MongoDB TTL is best-effort and typically runs roughly once per minute.
    """
    db.command("collMod", "telemetry_history", expireAfterSeconds=ttl_seconds)
    print(f"Ensured telemetry_history TTL (expireAfterSeconds={ttl_seconds})")


def create_indexes(db: Database[dict[str, Any]]) -> None:
    """Create a small set of practical indexes for common lookups."""
    anomalies: Collection[dict[str, Any]] = db["anomalies"]
    anomalies.create_index([("anomaly_id", ASCENDING)], unique=True)
    anomalies.create_index(
        [
            ("status", ASCENDING),
            ("severity_type", ASCENDING),
            ("severity_level", DESCENDING),
            ("timestamp_utc", DESCENDING),
        ]
    )
    anomalies.create_index([("sensor_id", ASCENDING), ("timestamp_utc", DESCENDING)])

    knowledge_base: Collection[dict[str, Any]] = db["knowledge_base"]
    knowledge_base.create_index([("document_id", ASCENDING)], unique=True)
    knowledge_base.create_index([("equipment_type", ASCENDING)])
    knowledge_base.create_index([("associated_error_codes", ASCENDING)])

    staff_on_call: Collection[dict[str, Any]] = db["staff_on_call"]
    # Earlier versions used handled_severity_types as an array. Normalize to a
    # scalar because each role owns exactly one escalation bucket.
    for severity_type in ("low", "medium", "high"):
        staff_on_call.update_many(
            {"handled_severity_types": severity_type},
            {
                "$set": {"handled_severity_type": severity_type},
                "$unset": {"handled_severity_types": ""},
            },
        )

    for old_index_name in (
        "is_on_call_1_handled_severity_types_1_specialization_1_escalation_rank_1",
        "is_on_call_1_handled_severity_types_1_escalation_rank_1",
    ):
        try:
            staff_on_call.drop_index(old_index_name)
        except OperationFailure:
            pass

    staff_on_call.create_index([("employee_id", ASCENDING)], unique=True)
    staff_on_call.create_index(
        [
            ("is_on_call", ASCENDING),
            ("handled_severity_type", ASCENDING),
            ("specialization", ASCENDING),
            ("escalation_rank", ASCENDING),
        ]
    )

    agent_execution_logs: Collection[dict[str, Any]] = db["agent_execution_logs"]
    agent_execution_logs.create_index([("run_id", ASCENDING)], unique=True)
    agent_execution_logs.create_index([("anomaly_id", ASCENDING), ("started_at", DESCENDING)])

    system_metadata: Collection[dict[str, Any]] = db["system_metadata"]
    system_metadata.create_index([("config_type", ASCENDING), ("target_metric", ASCENDING)])

    sensors: Collection[dict[str, Any]] = db["sensors"]
    sensors.create_index([("sensor_id", ASCENDING)], unique=True)
    sensors.create_index([("is_active", ASCENDING), ("metric_type", ASCENDING)])

    session_events: Collection[dict[str, Any]] = db["session_events"]
    session_events.create_index([("session_id", ASCENDING), ("ts", DESCENDING)])

    print("Ensured indexes")


def seed_document_if_missing(
    collection: Collection[dict[str, Any]],
    lookup: dict[str, Any],
    document: dict[str, Any],
    label: str,
) -> None:
    if collection.find_one(lookup):
        print(f"Seed already exists: {label}")
        return
    collection.insert_one(document)
    print(f"Seeded {label}")


def upsert_seed_document(
    collection: Collection[dict[str, Any]],
    lookup: dict[str, Any],
    document: dict[str, Any],
    label: str,
) -> None:
    """
    Upsert a seed document so configuration changes are applied on reruns.

    Use this for mutable configuration (e.g., thresholds), not static seed data
    where preserving manual edits is preferred.
    """
    result = collection.update_one(lookup, {"$set": document}, upsert=True)
    if result.upserted_id is not None:
        print(f"Seeded {label}")
    else:
        print(f"Updated {label}")


def seed_system_metadata(db: Database[dict[str, Any]]) -> None:
    collection: Collection[dict[str, Any]] = db["system_metadata"]
    now = utc_now()
    base = {
        "is_enabled": True,
        "last_updated_by": "scripts/init_db.py",
        "last_updated_at_utc": now,
        "schema_version": 1,
    }

    threshold_docs = [
        {
            "config_type": "anomaly_thresholds",
            "target_metric": "temp_celsius",
            "rules": {
                "max_allowed_temp_celsius": 80.0,
                "min_allowed_temp_celsius": 10.0,
                "consecutive_violating_pings_required": 2,
            },
            "description": "Temperature limits for environment sensors.",
        },
        {
            "config_type": "anomaly_thresholds",
            "target_metric": "humidity_percent",
            "rules": {
                "max_allowed_humidity_percent": 65.0,
                "min_allowed_humidity_percent": 25.0,
                "consecutive_violating_pings_required": 2,
            },
            "description": "Humidity limits for environment sensors.",
        },
        {
            "config_type": "anomaly_thresholds",
            "target_metric": "amplitude_mm",
            "rules": {
                "max_allowed_amplitude_mm": 0.5,
                "consecutive_violating_pings_required": 2,
            },
            "description": "Vibration amplitude limits.",
        },
        {
            "config_type": "anomaly_thresholds",
            "target_metric": "pressure_bar",
            "rules": {
                "max_allowed_pressure_bar": 8.0,
                "min_allowed_pressure_bar": 4.5,
                "consecutive_violating_pings_required": 2,
            },
            "description": "Hydraulic pressure operating band.",
        },
        {
            "config_type": "anomaly_thresholds",
            "target_metric": "flow_rate_lpm",
            "rules": {
                "min_allowed_flow_rate_lpm": 12.0,
                "consecutive_violating_pings_required": 2,
            },
            "description": "Coolant loop minimum flow.",
        },
    ]

    for doc in threshold_docs:
        upsert_seed_document(
            collection,
            {"config_type": doc["config_type"], "target_metric": doc["target_metric"]},
            {**doc, **base},
            f"system_metadata.{doc['target_metric']}",
        )

    seed_document_if_missing(
        collection,
        {"config_type": "severity_bands"},
        {
            **base,
            "config_type": "severity_bands",
            "target_metric": "*",
            "rules": {
                "low_max_ratio": 0.10,
                "medium_max_ratio": 0.25,
                "level_ranges": {
                    "low": {"min": 1, "max": 3},
                    "medium": {"min": 4, "max": 7},
                    "high": {"min": 8, "max": 10},
                },
            },
            "description": (
                "Breach ratio bands for severity_type/severity_level. "
                "Example: temp 100 vs max 80 -> ratio 0.25 -> high, level 10."
            ),
        },
        "system_metadata.severity_bands",
    )


def seed_staff_on_call(db: Database[dict[str, Any]]) -> None:
    collection: Collection[dict[str, Any]] = db["staff_on_call"]
    now = utc_now()

    staff_docs = [
        {
            "employee_id": "EMP-001",
            "name": "Alex Morgan",
            "role": "staff",
            "escalation_rank": 1,
            "specialization": ["environment"],
            "handled_severity_type": "low",
            "is_on_call": True,
            "contact_method": "SMS",
            "phone_number": "+15551234001",
            "email": "alex.morgan@example.com",
            "facility_ids": ["FAC-01"],
            "is_active": True,
            "updated_at_utc": now,
        },
        {
            "employee_id": "EMP-002",
            "name": "Blake Rivera",
            "role": "staff",
            "escalation_rank": 1,
            "specialization": ["vibration"],
            "handled_severity_type": "low",
            "is_on_call": True,
            "contact_method": "SMS",
            "phone_number": "+15551234002",
            "email": "blake.rivera@example.com",
            "facility_ids": ["FAC-01"],
            "is_active": True,
            "updated_at_utc": now,
        },
        {
            "employee_id": "EMP-003",
            "name": "Casey Nguyen",
            "role": "staff",
            "escalation_rank": 1,
            "specialization": ["pressure"],
            "handled_severity_type": "low",
            "is_on_call": True,
            "contact_method": "Email",
            "phone_number": "+15551234003",
            "email": "casey.nguyen@example.com",
            "facility_ids": ["FAC-01"],
            "is_active": True,
            "updated_at_utc": now,
        },
        {
            "employee_id": "EMP-004",
            "name": "Dana Brooks",
            "role": "senior",
            "escalation_rank": 2,
            "specialization": ["environment", "vibration"],
            "handled_severity_type": "medium",
            "is_on_call": True,
            "contact_method": "SMS",
            "phone_number": "+15551234004",
            "email": "dana.brooks@example.com",
            "facility_ids": ["FAC-01"],
            "is_active": True,
            "updated_at_utc": now,
        },
        {
            "employee_id": "EMP-005",
            "name": "Evan Shaw",
            "role": "senior",
            "escalation_rank": 2,
            "specialization": ["pressure", "flow"],
            "handled_severity_type": "medium",
            "is_on_call": True,
            "contact_method": "SMS",
            "phone_number": "+15551234005",
            "email": "evan.shaw@example.com",
            "facility_ids": ["FAC-01"],
            "is_active": True,
            "updated_at_utc": now,
        },
        {
            "employee_id": "EMP-006",
            "name": "Frank Ortiz",
            "role": "manager",
            "escalation_rank": 3,
            "specialization": ["environment", "vibration", "pressure", "flow"],
            "handled_severity_type": "high",
            "is_on_call": True,
            "contact_method": "Email",
            "phone_number": "+15551234006",
            "email": "frank.ortiz@example.com",
            "facility_ids": ["FAC-01"],
            "is_active": True,
            "updated_at_utc": now,
        },
    ]

    for doc in staff_docs:
        seed_document_if_missing(
            collection,
            {"employee_id": doc["employee_id"]},
            doc,
            f"staff_on_call.{doc['employee_id']}",
        )


def seed_sensors(db: Database[dict[str, Any]]) -> None:
    # sensors document contract:
    # {
    #     "_id": ObjectId,
    #     "sensor_id": str,                 # Unique. Matches telemetry sensor_id.
    #     "metric_type": str,               # "environment"/"vibration"/"pressure"/"flow".
    #     "facility_id": str,
    #     "equipment_id": str,
    #     "equipment_type": str,            # Used to filter knowledge_base.
    #     "metrics": list[str],             # Metric fields this sensor reports.
    #     "expected_interval_seconds": int,
    #     "is_active": bool,
    #     "created_at_utc": datetime,
    #     "updated_at_utc": datetime,
    # }
    collection: Collection[dict[str, Any]] = db["sensors"]
    now = utc_now()

    sensor_docs = [
        {
            "sensor_id": "SENS-ENV-001",
            "metric_type": "environment",
            "facility_id": "FAC-01",
            "equipment_id": "ROOM-PACK-01",
            "equipment_type": "packaging_room",
            "metrics": ["temp_celsius", "humidity_percent"],
            "expected_interval_seconds": 5,
            "is_active": True,
            "created_at_utc": now,
            "updated_at_utc": now,
        },
        {
            "sensor_id": "SENS-ENV-002",
            "metric_type": "environment",
            "facility_id": "FAC-01",
            "equipment_id": "ROOM-CTRL-01",
            "equipment_type": "control_room",
            "metrics": ["temp_celsius", "humidity_percent"],
            "expected_interval_seconds": 5,
            "is_active": True,
            "created_at_utc": now,
            "updated_at_utc": now,
        },
        {
            "sensor_id": "SENS-VIB-001",
            "metric_type": "vibration",
            "facility_id": "FAC-01",
            "equipment_id": "PUMP-A12",
            "equipment_type": "centrifugal_pump",
            "metrics": ["amplitude_mm", "frequency_hz"],
            "expected_interval_seconds": 5,
            "is_active": True,
            "created_at_utc": now,
            "updated_at_utc": now,
        },
        {
            "sensor_id": "SENS-VIB-002",
            "metric_type": "vibration",
            "facility_id": "FAC-01",
            "equipment_id": "MOTOR-B07",
            "equipment_type": "conveyor_motor",
            "metrics": ["amplitude_mm", "frequency_hz"],
            "expected_interval_seconds": 5,
            "is_active": True,
            "created_at_utc": now,
            "updated_at_utc": now,
        },
        {
            "sensor_id": "SENS-PRES-001",
            "metric_type": "pressure",
            "facility_id": "FAC-01",
            "equipment_id": "HYD-LINE-03",
            "equipment_type": "hydraulic_line",
            "metrics": ["pressure_bar"],
            "expected_interval_seconds": 5,
            "is_active": True,
            "created_at_utc": now,
            "updated_at_utc": now,
        },
        {
            "sensor_id": "SENS-FLOW-001",
            "metric_type": "flow",
            "facility_id": "FAC-01",
            "equipment_id": "COOL-LOOP-01",
            "equipment_type": "coolant_loop",
            "metrics": ["flow_rate_lpm"],
            "expected_interval_seconds": 5,
            "is_active": True,
            "created_at_utc": now,
            "updated_at_utc": now,
        },
    ]

    for doc in sensor_docs:
        seed_document_if_missing(
            collection,
            {"sensor_id": doc["sensor_id"]},
            doc,
            f"sensors.{doc['sensor_id']}",
        )


def seed_knowledge_base(db: Database[dict[str, Any]]) -> None:
    """
    Upsert seed knowledge entries. Idempotent.

    Embeddings are managed by Atlas Automated Embedding (Voyage AI): we only store
    `text_content`, and the `knowledge_vector` autoEmbed index generates the vector
    for us. No embeddings API key is required. Each entry is keyed by a stable
    document_id so reruns refresh content without creating duplicates.
    """
    collection: Collection[dict[str, Any]] = db["knowledge_base"]
    now = utc_now()

    for i, entry in enumerate(KNOWLEDGE_SEED):
        doc_id = f"seed-{i:03d}"
        text = entry["text_content"]
        collection.replace_one(
            {"document_id": doc_id},
            {
                "document_id": doc_id,
                "source_file": "scripts/knowledge_seed.py:KNOWLEDGE_SEED",
                "page_number": None,
                "section_title": entry["section_title"],
                "equipment_type": entry["equipment_type"],
                "associated_error_codes": entry["associated_error_codes"],
                "text_content": text,
                "chunk_index": 0,
                "is_active": True,
                "ingested_at_utc": now,
                "schema_version": 1,
            },
            upsert=True,
        )
        print(f"Seeded knowledge_base.{doc_id}")


def main() -> None:
    load_dotenv()

    mongo_uri = require_env("MONGO_URI")
    db_name = require_env("DB_NAME")

    client: MongoClient[dict[str, Any]] = MongoClient(
        mongo_uri,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=10_000,
    )

    try:
        client.admin.command("ping")
        db = client[db_name]

        ttl_seconds = 60 * 60 * 24 * svc_config.telemetry_ttl_days()
        create_time_series_collection(db, ttl_seconds)
        ensure_standard_collections(db)
        ensure_timeseries_ttl(db, ttl_seconds)
        create_indexes(db)
        seed_system_metadata(db)
        seed_staff_on_call(db)
        seed_sensors(db)
        seed_knowledge_base(db)

        print(f"MongoDB initialization complete for database: {db_name}")
    except PyMongoError as exc:
        raise RuntimeError(f"MongoDB initialization failed: {exc}") from exc
    finally:
        client.close()


if __name__ == "__main__":
    main()
