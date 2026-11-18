"""Authentication & session state routes (/api/auth/*)."""
from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict

from backend.config import COOKIE_SECURE, SESSION_COOKIE
from backend.database import get_db
from backend.security import (
    authenticate_web_user,
    create_web_session,
    get_session_user,
    hash_password,
    require_csrf,
    verify_password,
)
from backend.services.signup_service import register_account

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    vitalverse_id: str
    password: str
    role: str | None = None


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    fullName: str
    password: str
    confirmPassword: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


def _profile_summary(con: sqlite3.Connection, user: dict[str, Any]) -> dict[str, Any]:
    if user["role"] == "astronaut" and user.get("astronaut_id"):
        row = con.execute(
            "SELECT astronaut_id, name, mission_role, destination_for_flight FROM astronaut_profile WHERE astronaut_id = ?",
            (user["astronaut_id"],),
        ).fetchone()
        if row:
            return {
                "fullName": row["name"],
                "astronautId": row["astronaut_id"],
                "missionRole": row["mission_role"],
                "destination": row["destination_for_flight"] or "LEO Station",
            }
    if user["role"] == "doctor":
        doc = con.execute(
            "SELECT staff_id, full_name, specialization, organization FROM doctor_profiles WHERE user_id = ?",
            (int(user["user_id"]),),
        ).fetchone()
        if doc:
            return {
                "fullName": doc["full_name"],
                "staffId": doc["staff_id"],
                "specialization": doc["specialization"],
                "organization": doc["organization"],
            }
    return {"fullName": user.get("display_name") or user["vitalverse_id"]}


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, response: Response, con: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Register a new Astronaut or Doctor account, create its session, and issue an HttpOnly cookie."""
    res = register_account(con, payload.model_dump())
    session_id = res.pop("session_id")
    ttl_seconds = int(res.pop("ttl_seconds"))
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=ttl_seconds,
        path="/",
    )
    return res


@router.post("/login")
def login(payload: LoginRequest, response: Response, con: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Authenticate an astronaut or doctor using argon2-cffi and set an HttpOnly session cookie."""
    req_role = payload.role.strip().lower() if payload.role else None
    if req_role and req_role not in {"astronaut", "doctor"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role must be 'astronaut' or 'doctor'.")

    user = authenticate_web_user(con, payload.vitalverse_id, payload.password, requested_role=req_role)
    sess = create_web_session(con, int(user["id"]))

    response.set_cookie(
        key=SESSION_COOKIE,
        value=sess["session_id"],
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=int(sess["ttl_seconds"]),
        path="/",
    )

    prof = _profile_summary(
        con,
        {
            "user_id": user["id"],
            "role": user["role"],
            "astronaut_id": user["astronaut_id"],
            "display_name": user["display_name"],
            "vitalverse_id": user["vitalverse_id"],
        },
    )
    return {
        "ok": True,
        "role": user["role"],
        "vitalverse_id": user["vitalverse_id"],
        "astronaut_id": user["astronaut_id"],
        "csrf_token": sess["csrf_token"],
        "profile": prof,
    }


@router.post("/logout")
def logout(
    response: Response,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Revoke the current web session and clear the session cookie."""
    con.execute("UPDATE web_sessions SET revoked = 1 WHERE session_id = ?", (user["session_id"],))
    con.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/logout-all")
def logout_all(
    response: Response,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Revoke every active web session for this user across all browsers/devices."""
    cur = con.execute("UPDATE web_sessions SET revoked = 1 WHERE user_id = ?", (int(user["user_id"]),))
    con.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True, "revoked_count": cur.rowcount}


@router.put("/password")
def change_password(
    payload: PasswordChangeRequest,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Verify current password via argon2-cffi, update password hash, and revoke other sessions."""
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 8 characters.")
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New passwords do not match.")

    row = con.execute("SELECT password_hash FROM users WHERE id = ?", (int(user["user_id"]),)).fetchone()
    if row is None or not verify_password(payload.current_password, str(row["password_hash"])):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect.")

    new_hash = hash_password(payload.new_password)
    con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, int(user["user_id"])))
    con.execute(
        "UPDATE web_sessions SET revoked = 1 WHERE user_id = ? AND session_id != ?",
        (int(user["user_id"]), user["session_id"]),
    )
    con.commit()
    return {"ok": True}


@router.get("/me")
def me(
    user: dict[str, Any] | None = Depends(get_session_user),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Return active session metadata and shell counters without leaking sensitive fields."""
    if user is None:
        return {
            "authenticated": False,
            "role": None,
            "user": None,
            "csrf_token": None,
            "unread_alert_count": 0,
            "unack_danger_count": 0,
            "pending_access_count": 0,
            "todo_percent": 0,
        }

    prof = _profile_summary(con, user)
    name = prof.get("fullName") or user["display_name"]
    parts = [p for p in str(name).split() if p]
    initials = (parts[0][0] + parts[-1][0]).upper() if len(parts) >= 2 else str(name)[:2].upper()

    pending_count = 0
    if user["role"] == "astronaut" and user.get("astronaut_id"):
        row = con.execute(
            "SELECT COUNT(*) FROM doctor_astronaut_links WHERE astronaut_id = ? AND status = 'pending'",
            (user["astronaut_id"],),
        ).fetchone()
        pending_count = int(row[0])

    unread_count = 0
    unack_danger = 0
    if user["role"] == "astronaut" and user.get("astronaut_id"):
        arow = con.execute(
            """
            SELECT
              SUM(CASE WHEN read_at IS NULL THEN 1 ELSE 0 END) AS unread,
              SUM(CASE WHEN acknowledged_at IS NULL AND severity IN ('danger', 'danger-confirm') THEN 1 ELSE 0 END) AS danger
            FROM alerts WHERE astronaut_id = ?
            """,
            (user["astronaut_id"],),
        ).fetchone()
        if arow:
            unread_count = int(arow["unread"] or 0)
            unack_danger = int(arow["danger"] or 0)
    elif user["role"] == "doctor":
        arow = con.execute(
            """
            SELECT
              SUM(CASE WHEN a.read_at IS NULL THEN 1 ELSE 0 END) AS unread,
              SUM(CASE WHEN a.acknowledged_at IS NULL AND a.severity IN ('danger', 'danger-confirm') THEN 1 ELSE 0 END) AS danger
            FROM alerts a
            JOIN doctor_astronaut_links l ON l.astronaut_id = a.astronaut_id
            WHERE l.doctor_user_id = ? AND l.status = 'approved'
            """,
            (int(user["user_id"]),),
        ).fetchone()
        if arow:
            unread_count = int(arow["unread"] or 0)
            unack_danger = int(arow["danger"] or 0)

    todo_percent = 0
    avatar_url = None
    if user["role"] == "astronaut" and user.get("astronaut_id"):
        today = datetime.now(timezone.utc).date().isoformat()
        trow = con.execute(
            "SELECT SUM(CASE WHEN done = 1 THEN 1 ELSE 0 END) AS done_cnt FROM daily_todo WHERE astronaut_id = ? AND todo_date = ?",
            (user["astronaut_id"], today),
        ).fetchone()
        done_cnt = int((trow["done_cnt"] if trow else 0) or 0)
        todo_percent = min(100, round((done_cnt / 20) * 100))
        prow = con.execute("SELECT profile_photo, profile_avatar FROM astronaut_profile WHERE astronaut_id = ?", (user["astronaut_id"],)).fetchone()
        if prow:
            nav_av = prow["profile_avatar"] or prow["profile_photo"]
            if nav_av and str(nav_av).startswith("/api/media/"):
                avatar_url = str(nav_av)

    return {
        "authenticated": True,
        "role": user["role"],
        "csrf_token": user["csrf_token"],
        "user": {
            "vitalverse_id": user["vitalverse_id"],
            "name": name,
            "initials": initials,
            "avatar_url": avatar_url,
            "role": user["role"],
            "astronaut_id": user["astronaut_id"],
            "profile": prof,
        },
        "unread_alert_count": unread_count,
        "unack_danger_count": unack_danger,
        "pending_access_count": pending_count,
        "todo_percent": todo_percent,
    }
