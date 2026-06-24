"""Plant Assistant — stateless chat over a live snapshot of the whole plant.

Sync PyMongo variant (matches the rest of the data layer). This is the domain
logic behind `POST /chat` (api/chat.py): it reads everything an operator might
ask about — machines + latest readings, alarm thresholds, active/recent
anomalies, the on-call workforce, the knowledge base, and field-resolution
feedback — folds it into one context block, and asks DeepSeek (OpenAI-compatible)
to answer using only that snapshot.

No state is kept between calls; the frontend replays the last few turns as
`history`. With no LLM key configured the assistant degrades to a clear
"not configured" reply rather than erroring (mirrors the agent worker's fallback).

Embeddings/vectors are irrelevant here — this is a plain chat-completions call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..core import config
from ..core.db import col

log = logging.getLogger(__name__)

# App-wide display timezone (Spain/Madrid). Storage stays UTC; we localize only
# what the assistant shows the operator. DST-aware via the IANA database (needs
# the `tzdata` package on Windows); falls back to UTC if it's unavailable.
try:
    from zoneinfo import ZoneInfo

    _DISPLAY_TZ: Any = ZoneInfo("Europe/Madrid")
except Exception:  # pragma: no cover - tz database missing (pip install tzdata)
    _DISPLAY_TZ = None

# Keep the prompt bounded — the fleet is small, but an unattended run can
# accumulate many anomalies/feedback entries, so cap the noisier collections.
MAX_HISTORY = 10
MAX_ANOMALIES = 40
MAX_KNOWLEDGE = 40
MAX_FEEDBACK = 20
_TEXT_CLIP = 400

SYSTEM_PROMPT = (
    "You are the Plant Assistant for an industrial anomaly-detection platform "
    "that monitors a ball mill (MILL-01) and its sensors. Below is a live "
    "snapshot of the plant: machines and their latest readings, alarm "
    "thresholds, active and recent anomalies, the on-call workforce, the "
    "knowledge base, and field-resolution feedback.\n\n"
    "Answer the operator's question using ONLY the data in the snapshot. Be "
    "concise and factual. If the snapshot does not contain the answer, say so "
    "plainly — never invent sensor values, people, thresholds, or procedures. "
    "Format with short Markdown: **bold** for key values, bullet lists for "
    "multiple items. When you cite a reading, include its units and, if known, "
    "how it compares to the threshold. All timestamps in the snapshot are already "
    "in Europe/Madrid local time — present times to the operator in that zone."
)

_NO_KEY_REPLY = (
    "The Plant Assistant is not configured — no LLM API key is set. Add "
    "`LLM_API_KEY` (DeepSeek, or any OpenAI-compatible provider) to the data "
    "layer's environment and restart it to enable chat."
)

_ERROR_REPLY = "Sorry, I couldn't reach the assistant service right now. Please try again."


def _clip(text: Any, limit: int = _TEXT_CLIP) -> str:
    s = "" if text is None else str(text)
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _fmt_ts(value: Any) -> str:
    """Render a timestamp in Europe/Madrid local time (the app-wide display zone).
    Stored values are UTC; a naive datetime is assumed UTC. Falls back to the raw
    UTC value if the tz database isn't available."""
    if isinstance(value, datetime):
        dt = value
        if _DISPLAY_TZ is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(_DISPLAY_TZ)
        return dt.isoformat(timespec="seconds")
    return str(value) if value else "n/a"


def _latest_reading(sensor_id: str) -> dict[str, Any] | None:
    cursor = (
        col("telemetry_history")
        .find({"sensor_id": sensor_id}, {"_id": 0})
        .sort("timestamp_utc", -1)
        .limit(1)
    )
    rows = list(cursor)
    return rows[0] if rows else None


def _reading_values(reading: dict[str, Any]) -> str:
    """Render a flattened `reading` doc as `k=v` pairs (skip envelope fields)."""
    skip = {"metric_type", "unit_system"}
    parts = [
        f"{k}={v}"
        for k, v in reading.items()
        if k not in skip and isinstance(v, (int, float, str))
    ]
    return ", ".join(parts) if parts else "no values"


def gather_factory_context() -> dict[str, Any]:
    """Pull a snapshot of every collection the operator might ask about.

    Returns a plain dict so it's easy to unit-test the gather step in isolation
    from the LLM call.
    """
    sensors = list(col("sensors").find({}, {"_id": 0}).sort("sensor_id", 1))
    for s in sensors:
        latest = _latest_reading(s.get("sensor_id", ""))
        s["_latest_reading"] = latest

    thresholds = list(
        col("system_metadata").find({"config_type": "anomaly_thresholds"}, {"_id": 0})
    )

    anomalies = list(
        col("anomalies").find({}, {"_id": 0}).sort("timestamp_utc", -1).limit(MAX_ANOMALIES)
    )

    staff = list(
        col("staff_on_call").find({"is_active": True}, {"_id": 0}).sort("escalation_rank", 1)
    )

    # Knowledge an operator can be told about = active, non-feedback corpus
    # (seed + manual) plus approved feedback. Pending feedback is surfaced
    # separately below so the assistant can flag what's awaiting curation.
    knowledge = list(
        col("knowledge_base")
        .find({"is_active": True}, {"_id": 0})
        .sort("ingested_at_utc", -1)
        .limit(MAX_KNOWLEDGE)
    )

    # Field-resolution feedback (fb-* docs), including pending entries that have
    # not yet been curated into retrieval — the assistant should still know they
    # exist when asked "what feedback has come in?".
    feedback = list(
        col("knowledge_base")
        .find({"document_id": {"$regex": "^fb-"}}, {"_id": 0})
        .sort("ingested_at_utc", -1)
        .limit(MAX_FEEDBACK)
    )

    return {
        "sensors": sensors,
        "thresholds": thresholds,
        "anomalies": anomalies,
        "staff": staff,
        "knowledge": knowledge,
        "feedback": feedback,
    }


def render_context(ctx: dict[str, Any]) -> str:
    """Render the gathered snapshot into a compact, readable text block."""
    lines: list[str] = ["PLANT SNAPSHOT"]

    # --- Machines + latest readings ---
    lines.append("\n## Machines (sensors)")
    sensors = ctx.get("sensors") or []
    if not sensors:
        lines.append("- (none — database not seeded)")
    for s in sensors:
        latest = s.get("_latest_reading")
        if latest and isinstance(latest.get("reading"), dict):
            reading = f"latest {_reading_values(latest['reading'])} @ {_fmt_ts(latest.get('timestamp_utc'))}"
        else:
            reading = "no recent readings"
        flags = "active" if s.get("is_active", True) else "inactive"
        stress = s.get("sim_stress")
        if stress is not None:
            flags += f", degradation={stress}"
        lines.append(
            f"- **{s.get('sensor_id', '?')}** "
            f"({s.get('equipment_id') or '?'} / {s.get('equipment_type') or '?'}, "
            f"{s.get('metric_type') or '?'}) — {reading} [{flags}]"
        )

    # --- Thresholds ---
    lines.append("\n## Alarm thresholds")
    thresholds = ctx.get("thresholds") or []
    if not thresholds:
        lines.append("- (none configured)")
    for t in thresholds:
        lines.append(f"- {t.get('target_metric', '?')}: {t.get('rules', {})}")

    # --- Anomalies ---
    lines.append("\n## Anomalies (most recent first)")
    anomalies = ctx.get("anomalies") or []
    if not anomalies:
        lines.append("- (none)")
    for a in anomalies:
        tv = a.get("trigger_value") or {}
        assignee = a.get("assigned_to_employee_id") or a.get("recommended_employee_id") or "—"
        lines.append(
            f"- **{a.get('anomaly_id', '?')}** [{a.get('status', '?')}, "
            f"{a.get('severity_type', '?')}] {a.get('error_code', 'ANOMALY')} on "
            f"{a.get('equipment_id') or a.get('sensor_id') or '?'} — "
            f"{tv.get('metric', '?')} observed {tv.get('observed', '?')} "
            f"(limit {tv.get('limit', 'n/a')}), assignee {assignee}, "
            f"@ {_fmt_ts(a.get('timestamp_utc'))}"
        )
        if a.get("recommended_solution"):
            lines.append(f"    · recommended: {_clip(a['recommended_solution'])}")

    # --- Staff ---
    lines.append("\n## On-call workforce")
    staff = ctx.get("staff") or []
    if not staff:
        lines.append("- (none)")
    for p in staff:
        spec = ", ".join(p.get("specialization") or []) or "general"
        contact = p.get("email") or p.get("phone_number") or p.get("contact_method") or "—"
        lines.append(
            f"- **{p.get('name', '?')}** ({p.get('employee_id', '?')}, "
            f"{p.get('role', 'staff')}) — handles {p.get('handled_severity_type', '?')} "
            f"severity, specialties: {spec}, "
            f"{'ON CALL' if p.get('is_on_call') else 'off call'}, contact: {contact}"
        )

    # --- Knowledge base ---
    lines.append("\n## Knowledge base (active)")
    knowledge = ctx.get("knowledge") or []
    if not knowledge:
        lines.append("- (none)")
    for d in knowledge:
        eq = d.get("equipment_type") or "general"
        lines.append(
            f"- **{_clip(d.get('section_title'), 80)}** ({eq}): "
            f"{_clip(d.get('text_content'))}"
        )

    # --- Feedback ---
    lines.append("\n## Field-resolution feedback")
    feedback = ctx.get("feedback") or []
    if not feedback:
        lines.append("- (none)")
    for d in feedback:
        status = d.get("curation_status") or ("active" if d.get("is_active") else "pending")
        lines.append(f"- [{status}] {_clip(d.get('text_content'))}")

    return "\n".join(lines)


def _call_llm(messages: list[dict[str, str]]) -> str:
    """Single DeepSeek (OpenAI-compatible) chat-completions call. Isolated so
    tests can monkeypatch it without a network/key."""
    from openai import OpenAI  # lazy: keeps import cost off the gather path

    client = OpenAI(api_key=config.llm_api_key(), base_url=config.llm_base_url())
    resp = client.chat.completions.create(
        model=config.chat_model(),
        messages=messages,
        temperature=0.3,
        max_tokens=700,
    )
    return (resp.choices[0].message.content or "").strip()


def answer(message: str, history: list[dict[str, Any]] | None = None) -> str:
    """Answer one operator turn against a fresh plant snapshot.

    `history` is the prior conversation (most recent last); only well-formed
    user/assistant turns are forwarded, capped at MAX_HISTORY.
    """
    if not config.llm_api_key():
        return _NO_KEY_REPLY

    context = render_context(gather_factory_context())
    messages: list[dict[str, str]] = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{context}"}
    ]
    for turn in (history or [])[-MAX_HISTORY:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    try:
        reply = _call_llm(messages)
    except Exception as exc:  # noqa: BLE001 — LLM/network errors must not 500 the API
        log.warning("chat assistant LLM call failed: %s", exc)
        return _ERROR_REPLY
    return reply or _ERROR_REPLY
