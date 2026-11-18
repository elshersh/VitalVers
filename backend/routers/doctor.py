"""Doctor profile management & astronaut access approval/decline/revoke lifecycle routes."""
from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.database import get_db
from backend.security import require_csrf, require_user
from backend.services.alert_service import create_alert

router = APIRouter(tags=["doctor-access"])


class DoctorProfileUpdate(BaseModel):
    full_name: str
    staff_id: str = ""
    specialization: str = ""
    organization: str = ""
    contact: str = ""
    credential: str = ""


class DoctorAccessRequestCreate(BaseModel):
    target_id: str
    mission_crew_note: str = ""
    consent: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@router.get("/api/doctor/profile")
def get_doctor_profile(
    user: dict[str, Any] = Depends(require_user),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Return the authenticated doctor's own profile."""
    if user["role"] != "doctor":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor role required.")
    row = con.execute("SELECT * FROM doctor_profiles WHERE user_id = ?", (int(user["user_id"]),)).fetchone()
    return {
        "vitalverse_id": user["vitalverse_id"],
        "full_name": row["full_name"] if row else user["display_name"],
        "staff_id": row["staff_id"] if row else (user.get("legacy_user_id") or ""),
        "specialization": row["specialization"] if row else "",
        "organization": row["organization"] if row else "",
        "contact": row["contact"] if row else "",
        "credential": row["credential"] if row else "",
    }


@router.put("/api/doctor/profile")
def update_doctor_profile(
    payload: DoctorProfileUpdate,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Update the authenticated doctor's profile."""
    if user["role"] != "doctor":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor role required.")
    name = payload.full_name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Full name is required.")
    now = _utc_now()
    con.execute(
        """
        INSERT INTO doctor_profiles (user_id, staff_id, full_name, specialization, organization, contact, credential, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            staff_id = excluded.staff_id,
            full_name = excluded.full_name,
            specialization = excluded.specialization,
            organization = excluded.organization,
            contact = excluded.contact,
            credential = excluded.credential
        """,
        (
            int(user["user_id"]),
            payload.staff_id.strip(),
            name,
            payload.specialization.strip(),
            payload.organization.strip(),
            payload.contact.strip(),
            payload.credential.strip(),
            now,
        ),
    )
    con.execute("UPDATE users SET display_name = ? WHERE id = ?", (name, int(user["user_id"])))
    con.commit()
    return {"ok": True}


@router.post("/api/doctor/requests", status_code=status.HTTP_201_CREATED)
def create_access_request(
    payload: DoctorAccessRequestCreate,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Allow an authenticated doctor to request access to another astronaut by Vitalverse ID or Astronaut ID."""
    if user["role"] != "doctor":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor role required.")
    if not payload.consent:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authorization consent confirmation is required.")

    raw = payload.target_id.strip().upper()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter an Astronaut ID or Vitalverse ID.")

    u_row = con.execute(
        "SELECT astronaut_id FROM users WHERE role = 'astronaut' AND (UPPER(vitalverse_id) = ? OR UPPER(COALESCE(astronaut_id, '')) = ?)",
        (raw, raw),
    ).fetchone()
    if u_row and u_row["astronaut_id"]:
        target_aid = str(u_row["astronaut_id"])
    else:
        p_row = con.execute("SELECT astronaut_id FROM astronaut_profile WHERE UPPER(astronaut_id) = ?", (raw,)).fetchone()
        if p_row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Astronaut '{raw}' not found.")
        target_aid = str(p_row["astronaut_id"])

    uid = int(user["user_id"])
    existing = con.execute(
        "SELECT id, status FROM doctor_astronaut_links WHERE doctor_user_id = ? AND astronaut_id = ?",
        (uid, target_aid),
    ).fetchone()
    now = _utc_now()
    if existing is not None:
        if existing["status"] == "approved":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"You already have approved access to {target_aid}.")
        if existing["status"] == "pending":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"An access request for {target_aid} is already pending.")
        con.execute(
            """
            UPDATE doctor_astronaut_links
            SET status = 'pending', mission_crew_note = ?, consent_confirmed = 1, created_at = ?, decided_at = NULL
            WHERE id = ?
            """,
            (payload.mission_crew_note.strip(), now, int(existing["id"])),
        )
        link_id = int(existing["id"])
    else:
        cur = con.execute(
            """
            INSERT INTO doctor_astronaut_links (
                doctor_user_id, astronaut_id, status, mission_crew_note, consent_confirmed, created_at, decided_at
            ) VALUES (?, ?, 'pending', ?, 1, ?, NULL)
            """,
            (uid, target_aid, payload.mission_crew_note.strip(), now),
        )
        link_id = int(cur.lastrowid)
    con.commit()

    create_alert(
        con,
        astronaut_id=target_aid,
        mission_day=None,
        severity="info",
        source="access",
        short_message=f"Doctor access request from {user['display_name']} ({user['vitalverse_id']}) awaiting your approval.",
        detailed_explanation={
            "doctor_vitalverse_id": user["vitalverse_id"],
            "doctor_name": user["display_name"],
            "link_id": link_id,
            "recommended_action": "Open Profile -> Access tab to Approve or Decline.",
        },
        notify_doctors=False,
    )
    return {"ok": True, "id": link_id, "astronaut_id": target_aid, "status": "pending"}


@router.get("/api/access/requests")
def list_astronaut_access_requests(
    user: dict[str, Any] = Depends(require_user),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """List incoming doctor access requests for the logged-in astronaut."""
    if user["role"] != "astronaut" or not user.get("astronaut_id"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only astronauts manage access requests.")

    rows = con.execute(
        """
        SELECT l.id, l.doctor_user_id, l.astronaut_id, l.status, l.mission_crew_note, l.created_at, l.decided_at,
               u.vitalverse_id, u.display_name,
               d.staff_id, d.specialization, d.organization, d.contact
        FROM doctor_astronaut_links l
        JOIN users u ON u.id = l.doctor_user_id
        LEFT JOIN doctor_profiles d ON d.user_id = l.doctor_user_id
        WHERE l.astronaut_id = ?
        ORDER BY CASE l.status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, l.id DESC
        """,
        (user["astronaut_id"],),
    ).fetchall()
    return {
        "astronaut_id": user["astronaut_id"],
        "requests": [
            {
                "id": int(r["id"]),
                "doctor_vitalverse_id": r["vitalverse_id"],
                "doctor_name": r["display_name"],
                "staff_id": r["staff_id"] or "",
                "specialization": r["specialization"] or "",
                "organization": r["organization"] or "",
                "contact": r["contact"] or "",
                "status": r["status"],
                "mission_crew_note": r["mission_crew_note"] or "",
                "created_at": r["created_at"],
                "decided_at": r["decided_at"],
            }
            for r in rows
        ],
    }


def _transition_link_status(con: sqlite3.Connection, user: dict[str, Any], link_id: int, new_status: str) -> dict[str, Any]:
    if user["role"] != "astronaut" or not user.get("astronaut_id"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the astronaut can decide access requests.")

    row = con.execute("SELECT * FROM doctor_astronaut_links WHERE id = ?", (link_id,)).fetchone()
    if row is None or row["astronaut_id"] != user["astronaut_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Access request not found.")

    now = _utc_now()
    con.execute(
        "UPDATE doctor_astronaut_links SET status = ?, decided_at = ? WHERE id = ?",
        (new_status, now, link_id),
    )
    con.commit()
    return {"ok": True, "id": link_id, "status": new_status, "decided_at": now}


@router.post("/api/access/requests/{link_id}/approve")
def approve_access_request(
    link_id: int,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return _transition_link_status(con, user, link_id, "approved")


@router.post("/api/access/requests/{link_id}/decline")
def decline_access_request(
    link_id: int,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return _transition_link_status(con, user, link_id, "declined")


@router.post("/api/access/requests/{link_id}/revoke")
def revoke_access_request(
    link_id: int,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return _transition_link_status(con, user, link_id, "revoked")
