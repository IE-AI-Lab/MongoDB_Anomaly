"""Initial knowledge corpus to seed `knowledge_base`.

Imported by scripts/init_db.py (see seed_knowledge_base there). Each entry uses the
field names knowledge_base expects, minus the fields init_db fills in at insert
time (document_id, ingested_at_utc, schema_version). Embeddings are not stored —
Atlas Automated Embedding generates them from text_content.

Metric types follow the existing enum: environment, vibration, pressure, flow.

NOTE: associated_error_codes here should intersect the codes the detector emits
(see ingestor_service/detector/detect.py _error_code) so search_knowledge's
error_code filter can join anomalies to docs.

NOTE: equipment_type values must match the seeded sensor fleet's equipment_type
(see scripts/init_db.py seed_sensors): packaging_room, control_room, centrifugal_pump,
conveyor_motor, hydraulic_line, coolant_loop. This is the join key for
search_knowledge's equipment_type filter — every sensor type below has at least
one matching active doc. error_code remains the primary join; equipment_type is
a scoping filter on top of it.
"""

KNOWLEDGE_SEED: list[dict] = [
    # --- environment (temperature / humidity) ---
    {
        "section_title": "High temperature on industrial chiller loop",
        "equipment_type": "packaging_room",
        "associated_error_codes": ["TEMP_HIGH", "COOLING_FAULT"],
        "text_content": (
            "When chiller outlet temperature exceeds the setpoint by more than 10%, "
            "first check for clogged filters or restricted coolant flow. If flow is "
            "normal, inspect the condenser fins for fouling. Persistent high "
            "temperatures with normal flow and a clean condenser usually indicate "
            "refrigerant undercharge — schedule a leak test."
        ),
    },
    {
        "section_title": "Server-room humidity rising above 60%",
        "equipment_type": "control_room",
        "associated_error_codes": ["HUMIDITY_HIGH"],
        "text_content": (
            "Humidity drift above 60% in conditioned space is most often a stuck "
            "dehumidifier solenoid or a failed condensate pump. Check the pump "
            "first — if water is backing up in the drain pan, replace the float "
            "switch before suspecting the dehumidifier."
        ),
    },
    {
        "section_title": "Simultaneous temperature rise across multiple sensors",
        "equipment_type": "packaging_room",
        "associated_error_codes": ["TEMP_HIGH"],
        "text_content": (
            "If several environment sensors trend up at the same time, suspect a "
            "shared chilled-water plant fault rather than individual equipment "
            "faults. Check the primary loop pump status before dispatching "
            "technicians to each location."
        ),
    },
    # --- vibration ---
    {
        "section_title": "Pump bearing vibration above 4.5 mm/s",
        "equipment_type": "centrifugal_pump",
        "associated_error_codes": ["VIBRATION_HIGH", "BEARING_WEAR"],
        "text_content": (
            "Sustained vibration above 4.5 mm/s RMS on a centrifugal pump is a "
            "leading indicator of bearing wear. Run a spectrum analysis — "
            "bearing-defect frequencies (BPFI/BPFO) confirm the diagnosis. "
            "Schedule replacement during the next planned outage rather than "
            "waiting for failure."
        ),
    },
    {
        "section_title": "Motor vibration spike during start-up",
        "equipment_type": "conveyor_motor",
        "associated_error_codes": ["VIBRATION_HIGH", "MISALIGNMENT"],
        "text_content": (
            "A vibration spike on motor start-up that settles within 30 seconds is "
            "usually misalignment between motor and load shaft. Verify with a "
            "laser alignment check at the next shutdown. Persistent vibration "
            "after start-up more likely indicates rotor imbalance."
        ),
    },
    {
        "section_title": "Fan vibration after blade cleaning or replacement",
        "equipment_type": "conveyor_motor",
        "associated_error_codes": ["VIBRATION_HIGH", "IMBALANCE"],
        "text_content": (
            "New vibration on a fan after cleaning or blade replacement is almost "
            "always imbalance from uneven debris removal or a missing/damaged "
            "blade weight. Re-balance in place using the trial-weight method "
            "before suspecting bearings."
        ),
    },
    # --- pressure ---
    {
        "section_title": "Hydraulic system pressure drop below threshold",
        "equipment_type": "hydraulic_line",
        "associated_error_codes": ["PRESSURE_LOW", "LEAK_SUSPECTED"],
        "text_content": (
            "Hydraulic pressure dropping below the configured minimum while load "
            "is steady almost always means an internal or external leak. Check "
            "return-line flow first — high return flow with low system pressure "
            "points at a worn relief valve or cylinder seal."
        ),
    },
    {
        "section_title": "Pneumatic main line pressure spikes",
        "equipment_type": "hydraulic_line",
        "associated_error_codes": ["PRESSURE_HIGH"],
        "text_content": (
            "Repeated pressure spikes above setpoint on a pneumatic main line "
            "usually indicate a stuck unloader valve on the compressor or a "
            "failing pressure regulator downstream. Inspect the unloader first — "
            "cheaper and more common than regulator failure."
        ),
    },
    {
        "section_title": "Slow pressure rise after compressor start",
        "equipment_type": "hydraulic_line",
        "associated_error_codes": ["PRESSURE_LOW", "LEAK_SUSPECTED"],
        "text_content": (
            "If a compressor takes much longer than baseline to build pressure, "
            "the most common cause is air leakage in the distribution loop, not "
            "compressor wear. Run an ultrasonic leak survey before scheduling "
            "compressor maintenance."
        ),
    },
    # --- flow ---
    {
        "section_title": "Coolant flow dropping below minimum",
        "equipment_type": "coolant_loop",
        "associated_error_codes": ["FLOW_LOW", "FILTER_CLOGGED"],
        "text_content": (
            "Falling coolant flow with stable pump speed almost always means a "
            "clogged filter or strainer. Inspect and replace the filter element "
            "first. If flow stays low with a clean filter, check the pump "
            "impeller for cavitation damage."
        ),
    },
    {
        "section_title": "Flow oscillation on supply line",
        "equipment_type": "coolant_loop",
        "associated_error_codes": ["FLOW_OSCILLATION"],
        "text_content": (
            "Oscillating flow readings (cycling above and below setpoint) "
            "typically indicate an undersized accumulator or a failing check "
            "valve allowing backflow. Check the check valve first — flow can "
            "reverse briefly per cycle."
        ),
    },
    {
        "section_title": "Flow drops while pressure stays normal",
        "equipment_type": "coolant_loop",
        "associated_error_codes": ["FLOW_LOW"],
        "text_content": (
            "Decreasing flow with steady pressure is a classic signature of "
            "downstream fouling or scaling. Schedule a CIP (clean-in-place) cycle "
            "before assuming instrument fault."
        ),
    },
    # --- cross-cutting ---
    {
        "section_title": "Combined vibration + temperature rise on motor",
        "equipment_type": "conveyor_motor",
        "associated_error_codes": ["VIBRATION_HIGH", "TEMP_HIGH", "BEARING_WEAR"],
        "text_content": (
            "When vibration and temperature both trend up on the same motor over "
            "several hours, the cause is almost always advanced bearing wear. "
            "Schedule replacement as priority — failure is hours-to-days away, "
            "not weeks."
        ),
    },
    {
        "section_title": "Sensor reporting flat or static values",
        "equipment_type": "any",
        "associated_error_codes": ["SENSOR_FAULT"],
        "text_content": (
            "A sensor reporting exactly the same value for many consecutive "
            "readings is almost always a sensor or wiring fault, not a real "
            "measurement. Mark reading quality as suspect and dispatch "
            "instrumentation rather than process engineering."
        ),
    },
]
