"""Hybrid AI Chatbot API routes (POST /api/chat and GET /api/chat/status)."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.database import get_db
from backend.security import get_session_user
from backend.services import online_llm

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    question: str
    astronaut_id: str | None = None
    engine: str = "offline"


@router.get("/chat/status")
def chat_status() -> dict[str, Any]:
    """Return safe public metadata on online AI engine availability (never exposes API keys)."""
    return online_llm.get_online_status()


@router.post("/chat")
def chat_query(
    payload: ChatRequest,
    request: Request,
    user: dict[str, Any] | None = Depends(get_session_user),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Route chat question to On-board or Online AI with local RBAC, scope gate, urgent escalation, and rate limit."""
    chat_service = request.app.state.chat_service
    client_host = request.client.host if request.client else "anonymous"
    return chat_service.ask(
        con,
        user,
        payload.question,
        requested_astronaut_id=payload.astronaut_id,
        engine=payload.engine,
        client_id=client_host,
    )
