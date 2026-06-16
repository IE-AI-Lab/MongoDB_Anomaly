"""Decision parsing — recover the normalized decision dict from a messy agent run.

The investigation agent's hardest, most defect-prone job is turning the LLM's
final message plus the tool-call transcript into the decision object the rest of
the pipeline expects. Models wrap JSON in a prose preamble or a ```json fence,
invent empty placeholder `similar_cases`, and sometimes return analysis prose
instead of JSON at all. Every recovery rule lives here behind one interface,
`parse_decision`, so the rules sit in one place and are unit-testable without
running an LLM.

Precedence rule that is easy to get wrong, so it lives here: `similar_cases`
ALWAYS come from the real RAG tool output, never from the LLM (which fills the
field with empty placeholders). The LLM's list is only cleaned-and-kept when no
RAG tool actually ran.
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import config


def extract_json(text: Any) -> dict[str, Any] | None:
    """Pull the decision JSON object out of the agent's final message.

    Models (DeepSeek included) wrap the JSON in a prose preamble and/or a
    ```json fenced block instead of returning a bare object, so a strict
    json.loads on the whole message fails. Try, in order: the raw text, a fenced
    code block, then the first balanced { ... } span.
    """
    if not isinstance(text, str):
        return None

    candidates: list[str] = [text.strip()]

    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        candidates.append(fence.group(1))

    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


_COERCE_KEYS = (
    "decision, severity, confidence, rag_query_used, staff_lookup_used, "
    "description, recommended_solution, recommended_employee_id, similar_cases, reasoning"
)


def coerce_final_json(text: Any) -> dict[str, Any] | None:
    """Last-resort: ask the LLM (in forced json_object mode) to turn a prose final
    answer into the required object. Models sometimes return analysis prose after a
    long tool loop instead of JSON; this small no-tools call reliably recovers it."""
    if not config.llm_api_key() or not isinstance(text, str) or not text.strip():
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None
    try:
        llm = ChatOpenAI(
            model=config.chat_model(),
            temperature=0,
            api_key=config.llm_api_key(),
            base_url=config.llm_base_url(),
            max_retries=3,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        prompt = (
            "Convert the analysis below into a single JSON object with exactly these "
            f"keys: {_COERCE_KEYS}. Output ONLY the JSON object.\n\nAnalysis:\n{text}"
        )
        resp = llm.invoke(prompt)
        return extract_json(resp.content)
    except Exception:  # noqa: BLE001 — coercion is best-effort
        return None


def _load_tool_payload(message: Any) -> dict[str, Any] | None:
    content = getattr(message, "content", None)
    if not isinstance(content, str):
        return None

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _tool_name(message: Any) -> str:
    return getattr(message, "name", "") or getattr(message, "tool", "")


def _clean_cases(cases: Any) -> list[Any]:
    """Drop empty placeholder cases the LLM tends to invent (objects with no
    text/title/id, or blank strings)."""
    if not isinstance(cases, list):
        return []
    out: list[Any] = []
    for c in cases:
        if isinstance(c, str):
            if c.strip():
                out.append(c)
        elif isinstance(c, dict):
            if c.get("text_content") or c.get("section_title") or c.get("document_id"):
                out.append(c)
    return out


def enrich_from_tool_messages(decision: dict[str, Any], messages: list[Any]) -> dict[str, Any]:
    """Overlay facts from the tool transcript onto the LLM's decision: the real
    RAG query/results and the looked-up staff contact. See the module docstring
    for the `similar_cases` precedence rule."""
    enriched = dict(decision)
    rag_results: list[Any] | None = None
    rag_query: str | None = None

    for message in messages:
        payload = _load_tool_payload(message)
        if not payload:
            continue

        name = _tool_name(message)
        if name == "query_rag_knowledge_base":
            rag_query = rag_query or payload.get("query_used")
            results = payload.get("results")
            if results:
                rag_results = results

        if name == "get_staff_contact":
            enriched["staff_lookup_used"] = True
            candidates = payload.get("staff_candidates") or []
            if candidates and not enriched.get("recommended_employee_id"):
                enriched["recommended_employee_id"] = candidates[0].get("employee_id")

    if rag_query and not enriched.get("rag_query_used"):
        enriched["rag_query_used"] = rag_query

    # similar_cases ALWAYS come from the actual RAG tool output — the LLM fills the
    # field with empty placeholders, so never trust its version. Fall back to
    # cleaning the LLM's list (removing empties) only when no RAG tool ran.
    if rag_results is not None:
        enriched["similar_cases"] = rag_results
    else:
        enriched["similar_cases"] = _clean_cases(enriched.get("similar_cases"))

    return enriched


def parse_decision(final_message: Any, messages: list[Any]) -> dict[str, Any] | None:
    """Recover the normalized decision from the agent's final message and tool
    transcript, or return None if the message cannot be parsed/coerced into JSON.

    The caller owns the no-JSON fallback policy; this returns None so that policy
    stays in one place (the agent runner) rather than leaking in here.
    """
    decision = extract_json(final_message) or coerce_final_json(final_message)
    if decision is None:
        return None
    return enrich_from_tool_messages(decision, messages)
