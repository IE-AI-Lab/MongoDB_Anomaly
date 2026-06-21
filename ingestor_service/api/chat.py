"""Plant Assistant chat endpoint.

Thin HTTP layer over services/chat.py: validate the turn + short history, hand
off to the domain logic (which gathers a live plant snapshot and calls DeepSeek),
return the reply. Stateless — the client replays recent turns as `history`.

Mounted via api/__init__.py's `all_routers`.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..services import chat as chat_service

router = APIRouter(tags=["chat"])


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: list[ChatTurn] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """Answer one operator message against a fresh snapshot of the whole plant."""
    history = [turn.model_dump() for turn in req.history]
    reply = chat_service.answer(req.message, history)
    return ChatResponse(reply=reply)
