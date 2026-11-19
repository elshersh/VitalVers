"""GET /api/live: tells open pages when data they show has changed (see backend/services/live_service.py)."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from backend.database import get_db
from backend.security import get_session_user
from backend.services.live_service import live_parts

router = APIRouter(tags=["live"])


@router.get("/api/live")
def live_state(
    user: dict[str, Any] | None = Depends(get_session_user),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Fingerprints of what this tab's account can see; signed-out tabs get authenticated=false."""
    if user is None:
        return {"authenticated": False, "parts": {}}
    return {"authenticated": True, "role": user["role"], "parts": live_parts(con, user)}
