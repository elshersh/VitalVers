"""Account registration & automatic baseline/telemetry initialization for new Astronaut and Doctor accounts."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
import secrets
import sqlite3
from typing import Any

import numpy as np
from fastapi import HTTPException, status

import generate_data as gd
import resource_facts as rf
from backend.security import create_web_session, hash_password

_AID_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,31}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _generate_vitalverse_id(con: sqlite3.Connection, prefix: str) -> str:
    for _ in range(30):
        candidate = f"{prefix}-{secrets.randbelow(900000) + 100000}"
        row = con.execute("SELECT 1 FROM users WHERE vitalverse_id = ?", (candidate,)).fetchone()
        if row is None:
            return candidate
    raise HTTPException(status_code=500, detail="Unable to allocate a unique Vitalverse ID.")


def _parse_int(raw: Any, default: int | None = None) -> int | None:
    s = str(raw or "").strip()
    if not s:
        return default
    m = re.search(r"-?\d+", s)
    return int(m.group(0)) if m else default


def _parse_float(raw: Any, default: float | None = None) -> float | None:
    s = str(raw or "").strip()
    if not s:
        return default
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else default


def _seed_new_astronaut_telemetry(con: sqlite3.Connection, aid: str, fields: dict[str, Any]) -> None:
    """Create astronaut_profile + preflight_baseline + 180-day telemetry for a brand-new Astronaut ID."""
    seed_int = int.from_bytes(hashlib.sha256(aid.encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng(seed_int)
    base, mis = gd.simulate_astronaut(rng, aid)

    prev_flight = 1 if str(fields.get("previousFlight") or "").strip() else 0
    con.execute(
        """
        INSERT INTO astronaut_profile (
            astronaut_id, name, mission_role, nationality, profile_photo,
            contact_flight_surgeon, previous_flight, age, gender, weight_kg, height_cm,
            blood_type, allergies, previous_surgeries, previous_injuries,
            immunization_history, family_medical_history, family_photo, song,
            type_of_aircraft, estimated_time_for_flight_days, destination_for_flight
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            aid,
            str(fields["fullName"]).strip(),
            str(fields.get("missionRole") or "Crew Member").strip(),
            str(fields.get("nationality") or "Unspecified").strip(),
            "",
            str(fields.get("flightSurgeon") or "Flight Surgeon Desk (Ground Control)").strip(),
            prev_flight,
            _parse_int(fields.get("age"), 35),
            str(fields.get("gender") or "Unspecified").strip(),
            _parse_float(fields.get("weight"), 72.0),
            _parse_float(fields.get("height"), 175.0),
            str(fields.get("bloodType") or "Unknown").strip(),
            str(fields.get("allergies") or "").strip(),
            str(fields.get("surgeries") or "").strip(),
            str(fields.get("injuries") or "").strip(),
            str(fields.get("immunizations") or "").strip(),
            str(fields.get("familyHistory") or "").strip(),
            "",
            "",
            str(fields.get("aircraft") or "Orbital Spacecraft").strip(),
            _parse_int(fields.get("duration"), 180),
            str(fields.get("destination") or "Low Earth Orbit").strip(),
        ),
    )

    base_cols = list(base.keys())
    placeholders = ", ".join("?" for _ in base_cols)
    con.execute(
        f"INSERT INTO preflight_baseline ({', '.join(base_cols)}) VALUES ({placeholders})",
        tuple(base[c] for c in base_cols),
    )

    max_row = con.execute("SELECT COALESCE(MAX(record_id), 0) AS mx FROM mission_telemetry").fetchone()
    next_id = int(max_row["mx"]) + 1
    tel_df = mis.drop(columns=["true_class"]).copy()
    tel_df.insert(0, "record_id", np.arange(next_id, next_id + len(tel_df)))

    tel_cols = list(tel_df.columns)
    tel_ph = ", ".join("?" for _ in tel_cols)
    tel_records = [tuple(None if (isinstance(v, float) and np.isnan(v)) else v for v in row) for row in tel_df.itertuples(index=False, name=None)]
    con.executemany(
        f"INSERT INTO mission_telemetry ({', '.join(tel_cols)}) VALUES ({tel_ph})",
        tel_records,
    )

    label_records = [(int(tel_df.iloc[i]["record_id"]), str(mis.iloc[i]["true_class"])) for i in range(len(mis))]
    con.executemany(
        "INSERT INTO telemetry_labels (record_id, true_class) VALUES (?, ?)",
        label_records,
    )


def register_account(con: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    """Register an Astronaut or Doctor account with official argon2-cffi hashing and session cookie data."""
    role = str(payload.get("role") or "").strip().lower()
    if role not in {"astronaut", "doctor"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role must be 'astronaut' or 'doctor'.")

    full_name = str(payload.get("fullName") or "").strip()
    password = str(payload.get("password") or "")
    confirm_password = str(payload.get("confirmPassword") or "")
    if not full_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Full Name is required.")
    if len(password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters.")
    if password != confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match.")

    now = _utc_now()
    pw_hash = hash_password(password)

    if role == "astronaut":
        raw_aid = str(payload.get("astronautId") or "").strip().upper()
        if not _AID_RE.match(raw_aid):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Astronaut ID must be 2–32 letters, numbers, '-' or '_' (e.g. A002 or CREW-09).",
            )
        taken = con.execute(
            "SELECT vitalverse_id FROM users WHERE UPPER(COALESCE(astronaut_id, '')) = ?",
            (raw_aid,),
        ).fetchone()
        if taken is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Astronaut ID {raw_aid} already has an account ({taken['vitalverse_id']}). Please log in or choose another ID.",
            )

        prof_exists = con.execute("SELECT 1 FROM astronaut_profile WHERE astronaut_id = ?", (raw_aid,)).fetchone()
        if prof_exists is not None:
            con.execute(
                """
                UPDATE astronaut_profile
                SET name = ?, mission_role = ?, nationality = ?, contact_flight_surgeon = ?,
                    type_of_aircraft = ?, estimated_time_for_flight_days = ?, destination_for_flight = ?
                WHERE astronaut_id = ?
                """,
                (
                    full_name,
                    str(payload.get("missionRole") or "Crew Member").strip(),
                    str(payload.get("nationality") or "").strip(),
                    str(payload.get("flightSurgeon") or "Flight Surgeon Desk (Ground Control)").strip(),
                    str(payload.get("aircraft") or "").strip(),
                    _parse_int(payload.get("duration"), 180),
                    str(payload.get("destination") or "").strip(),
                    raw_aid,
                ),
            )
        else:
            _seed_new_astronaut_telemetry(con, raw_aid, payload)

        vid = _generate_vitalverse_id(con, "VTA")
        cur = con.execute(
            """
            INSERT INTO users (
                vitalverse_id, email, password_hash, role, astronaut_id, legacy_user_id,
                display_name, failed_attempts, locked_until, created_at
            ) VALUES (?, NULL, ?, 'astronaut', ?, NULL, ?, 0, NULL, ?)
            """,
            (vid, pw_hash, raw_aid, full_name, now),
        )
        user_id = int(cur.lastrowid)

        for song in payload.get("songs") or []:
            title = str(song.get("title") or "").strip()
            tag = str(song.get("tag") or "comfort").strip().lower()
            url = str(song.get("url") or "").strip()
            if title and url and tag in {"comfort", "happy", "energy"} and (url.startswith("http://") or url.startswith("https://")):
                con.execute(
                    """
                    INSERT INTO astronaut_playlist_items (astronaut_id, title, tag, kind, url, upload_id, created_at)
                    VALUES (?, ?, ?, 'link', ?, NULL, ?)
                    """,
                    (raw_aid, title, tag, url, now),
                )

        sess = create_web_session(con, user_id)
        con.commit()
        return {
            "ok": True,
            "role": "astronaut",
            "vitalverse_id": vid,
            "astronaut_id": raw_aid,
            "csrf_token": sess["csrf_token"],
            "session_id": sess["session_id"],
            "ttl_seconds": sess["ttl_seconds"],
            "profile": {
                "fullName": full_name,
                "astronautId": raw_aid,
                "missionRole": str(payload.get("missionRole") or "Crew Member").strip(),
                "destination": str(payload.get("destination") or "Orbital Mission").strip(),
            },
        }

    # Doctor registration
    if not payload.get("consent"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You must confirm the authorization checkbox.")

    staff_id = str(payload.get("staffId") or "").strip()
    specialization = str(payload.get("specialization") or "").strip()
    organization = str(payload.get("organization") or "").strip()
    contact = str(payload.get("contact") or "").strip()
    credential = str(payload.get("credential") or "").strip()
    target_input = str(payload.get("astId") or "").strip().upper()
    crew_note = str(payload.get("crew") or "").strip()
    if not staff_id or not specialization or not organization or not target_input:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please complete all required doctor and astronaut connection fields.")

    astro_row = con.execute(
        "SELECT astronaut_id, display_name FROM users WHERE role = 'astronaut' AND (UPPER(vitalverse_id) = ? OR UPPER(COALESCE(astronaut_id, '')) = ?)",
        (target_input, target_input),
    ).fetchone()
    if astro_row is not None:
        target_aid = str(astro_row["astronaut_id"])
    else:
        prof = con.execute(
            "SELECT astronaut_id, name FROM astronaut_profile WHERE UPPER(astronaut_id) = ?",
            (target_input,),
        ).fetchone()
        if prof is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Astronaut ID '{target_input}' was not found. Enter a valid Vitalverse ID (e.g. VTA-DEMO01) or mission Astronaut ID (e.g. A001).",
            )
        target_aid = str(prof["astronaut_id"])

    vid = _generate_vitalverse_id(con, "VTD")
    cur = con.execute(
        """
        INSERT INTO users (
            vitalverse_id, email, password_hash, role, astronaut_id, legacy_user_id,
            display_name, failed_attempts, locked_until, created_at
        ) VALUES (?, NULL, ?, 'doctor', NULL, NULL, ?, 0, NULL, ?)
        """,
        (vid, pw_hash, full_name, now),
    )
    user_id = int(cur.lastrowid)
    con.execute(
        """
        INSERT INTO doctor_profiles (user_id, staff_id, full_name, specialization, organization, contact, credential, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, staff_id, full_name, specialization, organization, contact, credential, now),
    )
    con.execute(
        """
        INSERT INTO doctor_astronaut_links (
            doctor_user_id, astronaut_id, status, mission_crew_note, consent_confirmed, created_at, decided_at
        ) VALUES (?, ?, 'pending', ?, 1, ?, NULL)
        """,
        (user_id, target_aid, crew_note, now),
    )
    con.execute(
        """
        INSERT INTO alerts (
            astronaut_id, mission_day, severity, source, short_message,
            detailed_explanation_json, read_at, acknowledged_at, acknowledged_by_user_id, created_at
        ) VALUES (?, NULL, 'info', 'access', ?, ?, NULL, NULL, NULL, ?)
        """,
        (
            target_aid,
            f"Doctor access request from {full_name} ({vid}) awaiting your approval.",
            '{"doctor_vitalverse_id": "' + vid + '", "staff_id": "' + staff_id.replace('"', "") + '"}',
            now,
        ),
    )

    sess = create_web_session(con, user_id)
    con.commit()
    return {
        "ok": True,
        "role": "doctor",
        "vitalverse_id": vid,
        "astronaut_id": None,
        "target_astronaut_id": target_aid,
        "link_status": "pending",
        "csrf_token": sess["csrf_token"],
        "session_id": sess["session_id"],
        "ttl_seconds": sess["ttl_seconds"],
        "profile": {
            "fullName": full_name,
            "staffId": staff_id,
            "specialization": specialization,
            "organization": organization,
        },
    }
