"""Data-integrity guard for the seed knowledge corpus.

The RAG join only works if the knowledge corpus actually covers the keys the
rest of the system joins on. search_knowledge filters on equipment_type AND
error_code *together* (ingestor_service/services/rag.py), so it is not enough for
each key to be covered in isolation — every (equipment_type, error_code) pair the
fleet can actually produce must map to at least one seed doc, otherwise
knowledge/search returns nothing for that anomaly. This locks that contract so a
future seed/sensor edit can't silently break retrieval (the exact failure we
fixed once already — e.g. control_room could emit TEMP_HIGH but only
packaging_room had TEMP_HIGH docs).
"""

from __future__ import annotations

from ingestor_service.detector import detect
from ingestor_service.detector.thresholds import Threshold
from scripts.knowledge_seed import KNOWLEDGE_SEED


# Seeded sensor fleet, as equipment_type -> metric_type (scripts/init_db.py
# seed_sensors). This is the source of truth for what each equipment_type can
# actually report — and therefore which error codes its anomalies carry.
FLEET = {
    "packaging_room": "environment",
    "control_room": "environment",
    "centrifugal_pump": "vibration",
    "conveyor_motor": "vibration",
    "hydraulic_line": "pressure",
    "coolant_loop": "flow",
}

# For each metric_type, the (metric_name, threshold direction) pairs the detector
# can emit (ingestor_service/detector/detect._extract_metric_candidates +
# the seeded thresholds in init_db seed_system_metadata). error codes are then
# derived through detect._error_code so this stays in sync with the mapping
# instead of hard-coding strings.
_METRICS_BY_TYPE = {
    "environment": [("temp_celsius", "above"), ("humidity_percent", "above")],
    "vibration": [("amplitude_mm", "above")],
    "pressure": [("pressure_bar", "below")],
    "flow": [("flow_rate_lpm", "below")],
}


def _error_codes_for(metric_type: str) -> set[str]:
    return {
        detect._error_code(metric, Threshold(metric, direction, 0.0, 1))
        for metric, direction in _METRICS_BY_TYPE[metric_type]
    }


FLEET_EQUIPMENT_TYPES = set(FLEET)
EMITTED_ERROR_CODES = {
    code for metric_type in FLEET.values() for code in _error_codes_for(metric_type)
}
# Every (equipment_type, error_code) anomaly the fleet can actually raise.
REACHABLE_PAIRS = {
    (equipment_type, code)
    for equipment_type, metric_type in FLEET.items()
    for code in _error_codes_for(metric_type)
}


def _covered_equipment_types() -> set[str]:
    return {e["equipment_type"] for e in KNOWLEDGE_SEED}


def _covered_error_codes() -> set[str]:
    codes: set[str] = set()
    for e in KNOWLEDGE_SEED:
        codes.update(e["associated_error_codes"])
    return codes


def _pair_is_covered(equipment_type: str, code: str) -> bool:
    """A pair is covered if a seed doc carries the code and either targets this
    equipment_type or is the wildcard "any" (matches every equipment_type)."""
    for e in KNOWLEDGE_SEED:
        if code not in e["associated_error_codes"]:
            continue
        if e["equipment_type"] in (equipment_type, "any"):
            return True
    return False


def test_every_fleet_equipment_type_has_a_knowledge_doc():
    missing = FLEET_EQUIPMENT_TYPES - _covered_equipment_types()
    assert not missing, f"sensor equipment_types with no knowledge doc: {missing}"


def test_every_detector_error_code_has_a_knowledge_doc():
    missing = EMITTED_ERROR_CODES - _covered_error_codes()
    assert not missing, f"detector error_codes with no knowledge doc: {missing}"


def test_every_reachable_equipment_error_pair_has_a_knowledge_doc():
    missing = {pair for pair in REACHABLE_PAIRS if not _pair_is_covered(*pair)}
    assert not missing, (
        "equipment_type/error_code pairs the fleet can raise but the corpus "
        f"does not cover: {sorted(missing)}"
    )


def test_seed_entries_are_well_formed():
    for i, e in enumerate(KNOWLEDGE_SEED):
        assert e.get("text_content", "").strip(), f"entry {i} has empty text_content"
        assert e.get("section_title", "").strip(), f"entry {i} has empty section_title"
        assert e.get("equipment_type", "").strip(), f"entry {i} has empty equipment_type"
        codes = e.get("associated_error_codes")
        assert isinstance(codes, list) and codes, f"entry {i} has no associated_error_codes"
