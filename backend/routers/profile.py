"""Astronaut profile (Personal/Health/Flight) and tagged Song/Photo library routes (/api/profile/*)."""
from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.database import get_db
from backend.security import require_csrf, require_user, resolve_authorized_astronaut_id

router = APIRouter(prefix="/api/profile", tags=["profile"])

ALLOWED_TAGS = {"comfort", "happy", "energy"}


class PersonalProfileUpdate(BaseModel):
    name: str
    mission_role: str = ""
    nationality: str = ""
    contact_flight_surgeon: str = ""
    previous_flight: bool | int | str = 0


class HealthProfileUpdate(BaseModel):
    age: int | None = None
    gender: str = ""
    weight_kg: float | None = None
    height_cm: float | None = None
    blood_type: str = ""
    allergies: str = ""
    previous_surgeries: str = ""
    previous_injuries: str = ""
    immunization_history: str = ""
    family_medical_history: str = ""


class FlightProfileUpdate(BaseModel):
    type_of_aircraft: str = ""
    estimated_time_for_flight_days: int | None = None
    destination_for_flight: str = ""


class PlaylistLinkCreate(BaseModel):
    title: str
    tag: str = "comfort"
    url: str


class PhotoLinkCreate(BaseModel):
    tag: str = "comfort"
    url: str
    caption: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _serialize_profile(con: sqlite3.Connection, astronaut_id: str) -> dict[str, Any]:
    prof = con.execute("SELECT * FROM astronaut_profile WHERE astronaut_id = ?", (astronaut_id,)).fetchone()
    if prof is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Astronaut profile {astronaut_id} not found.")

    user_row = con.execute(
        "SELECT vitalverse_id, display_name FROM users WHERE role = 'astronaut' AND astronaut_id = ?",
        (astronaut_id,),
    ).fetchone()

    srows = con.execute(
        "SELECT id, title, tag, kind, url, upload_id, created_at FROM astronaut_playlist_items WHERE astronaut_id = ? ORDER BY id ASC",
        (astronaut_id,),
    ).fetchall()
    playlist = [
        {
            "id": int(r["id"]),
            "title": r["title"],
            "tag": r["tag"],
            "kind": r["kind"],
            "url": f"/api/media/{r['upload_id']}" if r["upload_id"] else (r["url"] or ""),
            "created_at": r["created_at"],
        }
        for r in srows
    ]

    prows = con.execute(
        "SELECT id, tag, url, upload_id, caption, created_at FROM astronaut_photo_items WHERE astronaut_id = ? ORDER BY id ASC",
        (astronaut_id,),
    ).fetchall()
    photos = [
        {
            "id": int(r["id"]),
            "tag": r["tag"],
            "url": f"/api/media/{r['upload_id']}" if r["upload_id"] else (r["url"] or ""),
            "caption": r["caption"] or "",
            "created_at": r["created_at"],
        }
        for r in prows
    ]

    avatar = prof["profile_photo"] if prof["profile_photo"] and str(prof["profile_photo"]).startswith("/api/media/") else ""
    nav_av_raw = prof["profile_avatar"] if "profile_avatar" in prof.keys() else None
    navbar_avatar = nav_av_raw if nav_av_raw and str(nav_av_raw).startswith("/api/media/") else avatar

    return {
        "astronaut_id": prof["astronaut_id"],
        "vitalverse_id": user_row["vitalverse_id"] if user_row else None,
        "avatar_url": avatar,
        "navbar_avatar_url": navbar_avatar,
        "personal": {
            "name": prof["name"],
            "mission_role": prof["mission_role"] or "",
            "nationality": prof["nationality"] or "",
            "contact_flight_surgeon": prof["contact_flight_surgeon"] or "",
            "previous_flight": bool(prof["previous_flight"]),
        },
        "health": {
            "age": prof["age"],
            "gender": prof["gender"] or "",
            "weight_kg": prof["weight_kg"],
            "height_cm": prof["height_cm"],
            "blood_type": prof["blood_type"] or "",
            "allergies": prof["allergies"] or "",
            "previous_surgeries": prof["previous_surgeries"] or "",
            "previous_injuries": prof["previous_injuries"] or "",
            "immunization_history": prof["immunization_history"] or "",
            "family_medical_history": prof["family_medical_history"] or "",
        },
        "flight": {
            "type_of_aircraft": prof["type_of_aircraft"] or "",
            "estimated_time_for_flight_days": prof["estimated_time_for_flight_days"],
            "destination_for_flight": prof["destination_for_flight"] or "",
        },
        "playlist": playlist,
        "photos": photos,
    }


@router.get("/{astronaut_id}")
def get_profile(
    astronaut_id: str,
    user: dict[str, Any] = Depends(require_user),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Return an astronaut's full profile sections and tagged media library (RBAC checked)."""
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    data = _serialize_profile(con, aid)
    data["can_edit_personal_and_media"] = user["role"] == "astronaut"
    return data


@router.put("/{astronaut_id}/personal")
def update_personal_profile(
    astronaut_id: str,
    payload: PersonalProfileUpdate,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Update personal metadata (owning astronaut only)."""
    if user["role"] != "astronaut":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the astronaut can edit personal details.")
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required.")

    prev = 1 if str(payload.previous_flight).strip().lower() in {"1", "true", "yes", "on"} or (isinstance(payload.previous_flight, bool) and payload.previous_flight) else 0
    con.execute(
        """
        UPDATE astronaut_profile
        SET name = ?, mission_role = ?, nationality = ?, contact_flight_surgeon = ?, previous_flight = ?
        WHERE astronaut_id = ?
        """,
        (
            name,
            payload.mission_role.strip(),
            payload.nationality.strip(),
            payload.contact_flight_surgeon.strip(),
            prev,
            aid,
        ),
    )
    con.execute("UPDATE users SET display_name = ? WHERE id = ?", (name, int(user["user_id"])))
    con.commit()
    return {"ok": True, "profile": _serialize_profile(con, aid)}


@router.put("/{astronaut_id}/health")
def update_health_profile(
    astronaut_id: str,
    payload: HealthProfileUpdate,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Update health background fields (owning astronaut or approved doctor)."""
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    con.execute(
        """
        UPDATE astronaut_profile
        SET age = ?, gender = ?, weight_kg = ?, height_cm = ?, blood_type = ?,
            allergies = ?, previous_surgeries = ?, previous_injuries = ?,
            immunization_history = ?, family_medical_history = ?
        WHERE astronaut_id = ?
        """,
        (
            payload.age,
            payload.gender.strip(),
            payload.weight_kg,
            payload.height_cm,
            payload.blood_type.strip(),
            payload.allergies.strip(),
            payload.previous_surgeries.strip(),
            payload.previous_injuries.strip(),
            payload.immunization_history.strip(),
            payload.family_medical_history.strip(),
            aid,
        ),
    )
    con.commit()
    return {"ok": True, "profile": _serialize_profile(con, aid)}


@router.put("/{astronaut_id}/flight")
def update_flight_profile(
    astronaut_id: str,
    payload: FlightProfileUpdate,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Update flight/mission metadata (owning astronaut or approved doctor)."""
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    con.execute(
        """
        UPDATE astronaut_profile
        SET type_of_aircraft = ?, estimated_time_for_flight_days = ?, destination_for_flight = ?
        WHERE astronaut_id = ?
        """,
        (
            payload.type_of_aircraft.strip(),
            payload.estimated_time_for_flight_days,
            payload.destination_for_flight.strip(),
            aid,
        ),
    )
    con.commit()
    return {"ok": True, "profile": _serialize_profile(con, aid)}


@router.post("/{astronaut_id}/playlist", status_code=status.HTTP_201_CREATED)
def add_playlist_link(
    astronaut_id: str,
    payload: PlaylistLinkCreate,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Add an external HTTP/HTTPS song link tagged comfort/happy/energy (owning astronaut only)."""
    if user["role"] != "astronaut":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the astronaut can edit playlist items.")
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    title = payload.title.strip()
    url = payload.url.strip()
    tag = payload.tag.strip().lower()
    if not title or not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Song title and http(s) URL are required.")
    if tag not in ALLOWED_TAGS:
        tag = "comfort"
    con.execute(
        """
        INSERT INTO astronaut_playlist_items (astronaut_id, title, tag, kind, url, upload_id, created_at)
        VALUES (?, ?, ?, 'link', ?, NULL, ?)
        """,
        (aid, title, tag, url, _utc_now()),
    )
    con.commit()
    return {"ok": True, "profile": _serialize_profile(con, aid)}


@router.delete("/{astronaut_id}/playlist/{item_id}")
def delete_playlist_item(
    astronaut_id: str,
    item_id: int,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Delete a playlist song item belonging to the astronaut."""
    if user["role"] != "astronaut":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the astronaut can remove playlist items.")
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    cur = con.execute(
        "DELETE FROM astronaut_playlist_items WHERE id = ? AND astronaut_id = ?",
        (item_id, aid),
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist item not found.")
    con.commit()
    return {"ok": True, "profile": _serialize_profile(con, aid)}


@router.post("/{astronaut_id}/photos", status_code=status.HTTP_201_CREATED)
def add_photo_link(
    astronaut_id: str,
    payload: PhotoLinkCreate,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Add an external HTTP/HTTPS comfort photo URL (prefer multipart /api/uploads for local images)."""
    if user["role"] != "astronaut":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the astronaut can add comfort photos.")
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    url = payload.url.strip()
    tag = payload.tag.strip().lower()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Valid http(s) URL required.")
    if tag not in ALLOWED_TAGS:
        tag = "comfort"
    con.execute(
        """
        INSERT INTO astronaut_photo_items (astronaut_id, tag, upload_id, url, caption, created_at)
        VALUES (?, ?, NULL, ?, ?, ?)
        """,
        (aid, tag, url, payload.caption.strip(), _utc_now()),
    )
    con.commit()
    return {"ok": True, "profile": _serialize_profile(con, aid)}


@router.delete("/{astronaut_id}/photos/{item_id}")
def delete_photo_item(
    astronaut_id: str,
    item_id: int,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Delete a comfort photo item belonging to the astronaut."""
    if user["role"] != "astronaut":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the astronaut can remove comfort photos.")
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    cur = con.execute(
        "DELETE FROM astronaut_photo_items WHERE id = ? AND astronaut_id = ?",
        (item_id, aid),
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo item not found.")
    con.commit()
    return {"ok": True, "profile": _serialize_profile(con, aid)}
