"""Alerts center, read/acknowledge actions, and Web Push subscription routes (live updates: /api/live)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.database import get_db
from backend.security import require_csrf, require_user, resolve_authorized_astronaut_id
from backend.services.alert_service import get_vapid_keys

router = APIRouter(tags=["alerts"])


class PushSubscriptionRequest(BaseModel):
    endpoint: str
    keys: dict[str, str]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _authorized_astronaut_filter(con: sqlite3.Connection, user: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    if user["role"] == "astronaut":
        return "a.astronaut_id = ?", (user["astronaut_id"],)
    if user["role"] == "doctor":
        return (
            "a.astronaut_id IN (SELECT astronaut_id FROM doctor_astronaut_links WHERE doctor_user_id = ? AND status = 'approved')",
            (int(user["user_id"]),),
        )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unsupported role.")


@router.get("/api/alerts")
def list_alerts(
    severity: str = Query(default="all"),
    unread: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict[str, Any] = Depends(require_user),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Return role-filtered alerts (with full doctor analytics or concise astronaut notices)."""
    where_auth, auth_params = _authorized_astronaut_filter(con, user)
    clauses = [where_auth]
    params: list[Any] = list(auth_params)

    sev = severity.strip().lower()
    if sev in {"danger", "danger-confirm", "warning", "info"}:
        if sev == "danger":
            clauses.append("a.severity IN ('danger', 'danger-confirm')")
        else:
            clauses.append("a.severity = ?")
            params.append(sev)
    if unread:
        clauses.append("a.read_at IS NULL")

    where_sql = " AND ".join(clauses)
    rows = con.execute(
        f"""
        SELECT a.*, p.name AS astronaut_name, p.contact_flight_surgeon
        FROM alerts a
        LEFT JOIN astronaut_profile p ON p.astronaut_id = a.astronaut_id
        WHERE {where_sql}
        ORDER BY a.id DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()

    counts = con.execute(
        f"""
        SELECT
          SUM(CASE WHEN a.read_at IS NULL THEN 1 ELSE 0 END) AS unread_count,
          SUM(CASE WHEN a.acknowledged_at IS NULL AND a.severity IN ('danger', 'danger-confirm') THEN 1 ELSE 0 END) AS unack_danger_count
        FROM alerts a
        WHERE {where_auth}
        """,
        auth_params,
    ).fetchone()

    items: list[dict[str, Any]] = []
    for r in rows:
        try:
            details = json.loads(r["detailed_explanation_json"] or "{}")
        except Exception:
            details = {}
        item: dict[str, Any] = {
            "id": r["id"],
            "astronaut_id": r["astronaut_id"],
            "astronaut_name": r["astronaut_name"] or r["astronaut_id"],
            "flight_surgeon": r["contact_flight_surgeon"] or "Flight Surgeon Desk (Ground Control)",
            "mission_day": r["mission_day"],
            "severity": r["severity"],
            "source": r["source"],
            "short_message": r["short_message"],
            "read_at": r["read_at"],
            "acknowledged_at": r["acknowledged_at"],
            "created_at": r["created_at"],
        }
        if user["role"] == "doctor":
            item["detailed_explanation"] = details
        else:
            item["detailed_explanation"] = {
                "summary": details.get("summary") or r["short_message"],
                "recommended_action": details.get("recommended_action"),
                "contact": r["contact_flight_surgeon"] or "Flight Surgeon Desk (Ground Control)",
            }
        items.append(item)

    return {
        "role": user["role"],
        "unread_count": int((counts["unread_count"] if counts else 0) or 0),
        "unack_danger_count": int((counts["unack_danger_count"] if counts else 0) or 0),
        "items": items,
    }


@router.post("/api/alerts/read-all")
def mark_all_alerts_read(
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Mark every currently visible alert as read for the authenticated user."""
    now = _utc_now()
    if user["role"] == "astronaut":
        cur = con.execute(
            "UPDATE alerts SET read_at = ? WHERE astronaut_id = ? AND read_at IS NULL",
            (now, user["astronaut_id"]),
        )
    elif user["role"] == "doctor":
        cur = con.execute(
            """
            UPDATE alerts
            SET read_at = ?
            WHERE read_at IS NULL
              AND astronaut_id IN (
                  SELECT astronaut_id FROM doctor_astronaut_links WHERE doctor_user_id = ? AND status = 'approved'
              )
            """,
            (now, int(user["user_id"])),
        )
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unsupported role.")
    con.commit()
    return {"ok": True, "marked": cur.rowcount}


@router.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: int,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Acknowledge a specific alert (marks both read_at and acknowledged_at)."""
    row = con.execute("SELECT id, astronaut_id FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found.")
    resolve_authorized_astronaut_id(con, user, str(row["astronaut_id"]))

    now = _utc_now()
    con.execute(
        """
        UPDATE alerts
        SET read_at = COALESCE(read_at, ?),
            acknowledged_at = COALESCE(acknowledged_at, ?),
            acknowledged_by_user_id = COALESCE(acknowledged_by_user_id, ?)
        WHERE id = ?
        """,
        (now, now, int(user["user_id"]), alert_id),
    )
    con.commit()
    return {"ok": True, "id": alert_id, "acknowledged_at": now}


@router.get("/api/alerts/stream")
def stream_alerts_retired() -> JSONResponse:
    """Retired. Pages now learn about new alerts from GET /api/live (static/js/shell.js), whose answers the
    browser checks like every other API answer. A long-lived stream could not be checked and kept a relay
    connection busy. 410 tells EventSource in pages still running older code to stop reconnecting."""
    return JSONResponse({"detail": "Live alerts now come through /api/live."}, status_code=status.HTTP_410_GONE)


@router.get("/api/push/vapid-public-key")
def push_vapid_public_key() -> dict[str, str]:
    """Return the VAPID public key for browser Web Push registration."""
    return {"public_key": get_vapid_keys()["public_key"]}


@router.post("/api/push/subscribe")
def subscribe_push(
    payload: PushSubscriptionRequest,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Store a browser Web Push subscription tied to the authenticated user."""
    p256dh = str(payload.keys.get("p256dh") or "").strip()
    auth = str(payload.keys.get("auth") or "").strip()
    endpoint = str(payload.endpoint or "").strip()
    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incomplete Web Push subscription payload.")

    now = _utc_now()
    con.execute(
        """
        INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(endpoint) DO UPDATE SET
            user_id = excluded.user_id,
            p256dh = excluded.p256dh,
            auth = excluded.auth,
            created_at = excluded.created_at
        """,
        (int(user["user_id"]), endpoint, p256dh, auth, now),
    )
    con.commit()
    return {"ok": True}
