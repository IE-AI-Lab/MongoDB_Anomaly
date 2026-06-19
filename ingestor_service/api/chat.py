"""Chatbot endpoint for operator assistance.

This endpoint is intentionally narrow:
- retrieve a small set of knowledge snippets relevant to the user query
- ask the configured LLM to answer using only those snippets
- return the assistant text plus the chosen sources for transparency
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from openai import OpenAI

from ..core import config
from ..services.rag import search_knowledge

router = APIRouter(tags=["chat"])

SYSTEM_PROMPT = """
You are a MongoDB anomaly detection operator assistant.

You have access to backend tools that can inspect the current system state and answer operator questions using live metadata, sensor telemetry, recent alerts, staff on-call information, and knowledge-base content.

When you can, use the available tools instead of guessing. The tools are:
- query_rag_knowledge_base: search the knowledge corpus for relevant snippets.
- get_sensor_readings: fetch recent telemetry for a given sensor.
- retrieve_recent_alerts: inspect recent anomaly history for a sensor.
- retrieve_machine_memory: collect the sensor record, recent readings, and recent anomalies.
- get_staff_contact: lookup on-call staff by severity, specialization, and facility.

If the user asks for an answer based on the platform state, call the appropriate tool(s). If the query is purely informational about the knowledge base, query the knowledge tool. Be honest when you do not know the answer.

Answer clearly and concisely for an operator audience. Do not include analysis steps or markdown formatting in the final answer.
"""


def _build_agent_app():
    api_key = config.llm_api_key()
    if not api_key:
        return None

    try:
        from langchain_openai import ChatOpenAI
        from langgraph.prebuilt import create_react_agent
        import agent_worker.agent_tools as agent_tools
    except ImportError:
        return None

    llm = ChatOpenAI(
        model=config.chat_model(),
        temperature=0.2,
        api_key=api_key,
        base_url=config.llm_base_url(),
        max_retries=5,
    )

    return create_react_agent(
        model=llm,
        tools=[
            agent_tools.query_rag_knowledge_base,
            agent_tools.get_staff_contact,
            agent_tools.get_sensor_readings,
            agent_tools.retrieve_recent_alerts,
            agent_tools.retrieve_machine_memory,
        ],
        prompt=SYSTEM_PROMPT,
    )


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    equipment_type: Optional[str] = None
    error_codes: Optional[list[str]] = None
    k: int = Field(3, ge=1, le=5)


class ChatResponse(BaseModel):
    query: str
    answer: str
    model: str
    sources: list[dict[str, Any]]


def _build_prompt(query: str, docs: list[dict[str, Any]]) -> list[dict[str, str]]:
    if docs:
        source_lines = [
            f"[{idx+1}] {doc.get('section_title', 'Knowledge snippet')}: {doc.get('text_content', '')}"
            for idx, doc in enumerate(docs)
        ]
        knowledge_snippet = (
            "Relevant knowledge snippets:\n"
            + "\n\n".join(source_lines)
            + "\n\n"
        )
    else:
        knowledge_snippet = (
            "No relevant knowledge snippets were found for this query.\n"
            "Answer based on the system knowledge you have.\n\n"
        )

    return [
        {
            "role": "system",
            "content": (
                "You are a MongoDB anomaly detection operations assistant. "
                "Answer operator questions clearly and concisely, and cite the knowledge snippets "
                "when they help support your answer. If the user asks for something not covered by "
                "the snippets, be honest and provide the most useful guidance you can."
            ),
        },
        {
            "role": "system",
            "content": knowledge_snippet,
        },
        {
            "role": "system",
            "content": (
                "Use only the information in the knowledge snippets above. Do not hallucinate "
                "documentation or make up citations. Keep answers operator-friendly and focused "
                "on diagnosing, troubleshooting, or understanding the anomaly platform." 
            ),
        },
    ]


def _extract_response_text(response: Any) -> str:
    if response is None:
        return ""

    # LangGraph/react-agent returns a dict with a 'messages' key containing
    # the conversation; prefer the last assistant message when present.
    if isinstance(response, dict):
        msgs = response.get("messages")
        if isinstance(msgs, (list, tuple)) and msgs:
            last = msgs[-1]
            if isinstance(last, dict):
                # common shapes: {"role":"assistant","content":...}
                cont = last.get("content") or last.get("text") or last.get("response")
                if isinstance(cont, str):
                    return cont
            elif hasattr(last, "content"):
                return getattr(last, "content")

    if hasattr(response, "choices"):
        choice = response.choices[0]
        message = getattr(choice, "message", None) or getattr(choice, "response", None)
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
        if message and hasattr(message, "content"):
            return getattr(message, "content")

    if hasattr(response, "output_text") and isinstance(response.output_text, str):
        return response.output_text

    output = getattr(response, "output", None)
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    return text
            elif hasattr(item, "text"):
                return getattr(item, "text")

    return ""


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    api_key = config.llm_api_key()
    if not api_key:
        raise HTTPException(
            503,
            "Missing LLM API key. Set LLM_API_KEY or OPENAI_API_KEY in the environment.",
        )

    query = request.messages[-1].content if request.messages else ""
    docs = search_knowledge(
        query,
        equipment_type=request.equipment_type,
        error_codes=request.error_codes,
        k=request.k,
    )

    messages = _build_prompt(query, docs) + [m.model_dump() for m in request.messages]
    agent_app = _build_agent_app()

    if agent_app is not None:
        try:
            result = agent_app.invoke(
                {
                    "messages": messages,
                },
                config={
                    "recursion_limit": 20,
                    "run_name": "chat_assistant",
                },
            )
            answer = _extract_response_text(result)
        except Exception as exc:  # noqa: BLE001
            # Agent reasoning may fail due to missing dependencies or runtime issues.
            answer = None
            agent_error = str(exc)
        else:
            agent_error = None
    else:
        answer = None
        agent_error = "agent unavailable"

    if not answer:
        try:
            client = OpenAI(api_key=api_key, base_url=config.llm_base_url())
            response = client.chat.completions.create(
                model=config.chat_model(),
                messages=messages,
                temperature=0.2,
                max_tokens=768,
            )
        except AttributeError:
            try:
                response = client.responses.create(
                    model=config.chat_model(),
                    messages=messages,
                    temperature=0.2,
                    max_tokens=768,
                )
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(502, f"LLM request failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"LLM request failed: {exc}")

        answer = _extract_response_text(response)
        if not answer:
            raise HTTPException(502, "LLM responded with an empty answer.")

    if answer is None:
        raise HTTPException(502, f"Chat agent failed: {agent_error}")

    return ChatResponse(query=query, answer=answer.strip(), model=config.chat_model(), sources=docs)
