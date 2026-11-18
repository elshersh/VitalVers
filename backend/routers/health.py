"""Health telemetry, replay, doctor crew, and AI model prediction endpoints."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from backend.database import get_db
from backend.security import require_user, resolve_authorized_astronaut_id
from backend.services.health_service import build_dashboard_payload, list_doctor_astronauts

router = APIRouter(tags=["health"])


@router.get("/api/astronauts/{astronaut_id}/predictions")
def get_astronaut_predictions(
    astronaut_id: str,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Return startup-loaded health_model.joblib predictions across all 180 real mission days."""
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    model_service = request.app.state.model_service
    return model_service.predict_astronaut_timeline(con, aid)


@router.get("/api/health/{astronaut_id}/dashboard")
def get_health_dashboard(
    astronaut_id: str,
    request: Request,
    day: int | None = Query(default=None, ge=1),
    user: dict[str, Any] = Depends(require_user),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Return real 180-day telemetry, baselines, check-in mood tags, and AI predictions."""
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    model_service = request.app.state.model_service
    return build_dashboard_payload(con, model_service, aid, replay_day=day)


@router.get("/api/health/{astronaut_id}/replay")
def get_health_replay(
    astronaut_id: str,
    request: Request,
    day: int = Query(..., ge=1),
    user: dict[str, Any] = Depends(require_user),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Return mission timeline replay data truncated cleanly through mission day X (1..180)."""
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    model_service = request.app.state.model_service
    return build_dashboard_payload(con, model_service, aid, replay_day=day)


@router.get("/api/doctor/astronauts")
def get_doctor_astronauts(
    request: Request,
    user: dict[str, Any] = Depends(require_user),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """List approved and pending astronauts strictly for authenticated doctors."""
    if user["role"] != "doctor":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor role required.")
    model_service = request.app.state.model_service
    return list_doctor_astronauts(con, user, model_service)
