from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RagEvalCase:
    name: str
    query: str
    equipment_type: str
    error_codes: tuple[str, ...]


RAG_EVAL_CASES: list[RagEvalCase] = [
    RagEvalCase(
        name="pump-vibration-bearing-wear",
        query="centrifugal pump vibration above threshold bearing wear",
        equipment_type="centrifugal_pump",
        error_codes=("VIBRATION_HIGH",),
    ),
    RagEvalCase(
        name="conveyor-misalignment-startup",
        query="conveyor motor startup vibration misalignment check",
        equipment_type="conveyor_motor",
        error_codes=("VIBRATION_HIGH",),
    ),
    RagEvalCase(
        name="packaging-room-temp",
        query="packaging room high temperature cooling fault steps",
        equipment_type="packaging_room",
        error_codes=("TEMP_HIGH",),
    ),
    RagEvalCase(
        name="control-room-humidity",
        query="control room humidity above 60 troubleshooting",
        equipment_type="control_room",
        error_codes=("HUMIDITY_HIGH",),
    ),
    RagEvalCase(
        name="hydraulic-pressure-drop",
        query="hydraulic pressure low leak suspected diagnostics",
        equipment_type="hydraulic_line",
        error_codes=("PRESSURE_LOW",),
    ),
    RagEvalCase(
        name="coolant-flow-low",
        query="coolant flow dropping below minimum clogged filter",
        equipment_type="coolant_loop",
        error_codes=("FLOW_LOW",),
    ),
]
