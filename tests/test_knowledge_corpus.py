"""Data-integrity guard for the seed knowledge corpus.

The RAG join only works if the knowledge corpus actually covers the keys the
rest of the system joins on:
- every error_code the detector emits, and
- every equipment_type in the seeded sensor fleet,

must map to at least one seed knowledge doc — otherwise knowledge/search returns
nothing for that anomaly. This locks that contract so a future seed/sensor edit
can't silently break retrieval (the exact failure we fixed once already).
"""

from __future__ import annotations

from ingestor_service.detector import detect
from ingestor_service.detector.thresholds import Threshold
from scripts.knowledge_seed import KNOWLEDGE_SEED


# Equipment types of the seeded sensor fleet (scripts/init_db.py seed_sensors).
FLEET_EQUIPMENT_TYPES = {
    "packaging_room",
    "control_room",
    "centrifugal_pump",
    "conveyor_motor",
    "hydraulic_line",
    "coolant_loop",
}

# Error codes the detector actually emits, derived from detect._error_code with
# the metric/direction pairs the seeded thresholds produce (init_db
# seed_system_metadata + thresholds.get_threshold). Deriving keeps this in sync
# with the mapping instead of hard-coding strings.
_METRIC_DIRECTIONS = [
    ("temp_celsius", "above"),
    ("humidity_percent", "above"),
    ("amplitude_mm", "above"),
    ("pressure_bar", "below"),
    ("flow_rate_lpm", "below"),
]
EMITTED_ERROR_CODES = {
    detect._error_code(metric, Threshold(metric, direction, 0.0, 1))
    for metric, direction in _METRIC_DIRECTIONS
}


def _covered_equipment_types() -> set[str]:
    return {e["equipment_type"] for e in KNOWLEDGE_SEED}


def _covered_error_codes() -> set[str]:
    codes: set[str] = set()
    for e in KNOWLEDGE_SEED:
        codes.update(e["associated_error_codes"])
    return codes


def test_every_fleet_equipment_type_has_a_knowledge_doc():
    missing = FLEET_EQUIPMENT_TYPES - _covered_equipment_types()
    assert not missing, f"sensor equipment_types with no knowledge doc: {missing}"


def test_every_detector_error_code_has_a_knowledge_doc():
    missing = EMITTED_ERROR_CODES - _covered_error_codes()
    assert not missing, f"detector error_codes with no knowledge doc: {missing}"


def test_seed_entries_are_well_formed():
    for i, e in enumerate(KNOWLEDGE_SEED):
        assert e.get("text_content", "").strip(), f"entry {i} has empty text_content"
        assert e.get("section_title", "").strip(), f"entry {i} has empty section_title"
        assert e.get("equipment_type", "").strip(), f"entry {i} has empty equipment_type"
        codes = e.get("associated_error_codes")
        assert isinstance(codes, list) and codes, f"entry {i} has no associated_error_codes"
