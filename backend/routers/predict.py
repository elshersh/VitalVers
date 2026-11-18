"""AI prediction execution and simulated DEMO feed advancement routes."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from backend.database import get_db
from backend.security import require_csrf, resolve_authorized_astronaut_id
from backend.services.prediction_service import advance_demo_day, run_prediction_for_astronaut

router = APIRouter(tags=["predict"])


@router.post("/api/predict/{astronaut_id}")
def trigger_prediction(
    astronaut_id: str,
    request: Request,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Run startup-loaded AI model on the astronaut's mission telemetry and emit alerts if triggered."""
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    model_service = request.app.state.model_service
    return run_prediction_for_astronaut(con, model_service, aid, emit_alert=True)


@router.post("/api/demo/advance")
def advance_demo(
    request: Request,
    astronaut_id: str | None = Query(default=None),
    scenario: str = Query(default="auto"),
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Append the next simulated DEMO day for an authorized astronaut and evaluate alerts."""
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    model_service = request.app.state.model_service
    return advance_demo_day(con, model_service, aid, scenario=scenario)
