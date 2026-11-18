"""Health dashboard data assembly backed by real telemetry, baselines, mood check-ins, and AI predictions."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import HTTPException, status

from backend.services.model_service import ModelService

# Maps dashboard.js metric IDs cleanly to mission_telemetry & preflight_baseline columns.
METRIC_SPECS: list[dict[str, Any]] = [
    {"id": "hr", "scale": 1.0, "channels": [("value", "heart_rate")]},
    {"id": "bp", "scale": 1.0, "channels": [("sys", "systolic_bp"), ("dia", "diastolic_bp")]},
    {"id": "spo2", "scale": 1.0, "channels": [("value", "oxygen_saturation")]},
    {"id": "temp", "scale": 1.0, "channels": [("value", "temperature")]},
    {"id": "glucose", "scale": 1.0, "channels": [("value", "blood_glucose_mg_dl")]},
    {"id": "sleep", "scale": 1.0, "channels": [("value", "sleep_hours")]},
    {"id": "activity", "scale": 1.0, "channels": [("value", "daily_physical_activity_min")]},
    {"id": "mood", "scale": 10.0, "channels": [("value", "mood")]},
    {"id": "immune", "scale": 1.0, "channels": [("value", "immunity_indicators")]},
    {"id": "bone", "scale": 1.0, "channels": [("value", "bone_health")]},
]


def _initials(name: str) -> str:
    parts = [p for p in str(name or "").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return str(name or "VV")[:2].upper()


def list_doctor_astronauts(con: sqlite3.Connection, doctor_user: dict[str, Any], model_service: ModelService) -> dict[str, Any]:
    """Return approved and pending astronauts linked to the authenticated doctor."""
    rows = con.execute(
        """
        SELECT l.astronaut_id, l.status, l.mission_crew_note, l.created_at, l.decided_at,
               p.name, p.mission_role, p.age, p.destination_for_flight
        FROM doctor_astronaut_links l
        JOIN astronaut_profile p ON p.astronaut_id = l.astronaut_id
        WHERE l.doctor_user_id = ?
        ORDER BY l.status ASC, l.astronaut_id ASC
        """,
        (int(doctor_user["user_id"]),),
    ).fetchall()

    approved: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for r in rows:
        item = {
            "id": r["astronaut_id"],
            "astronaut_id": r["astronaut_id"],
            "name": r["name"],
            "initials": _initials(r["name"]),
            "role": r["mission_role"],
            "age": r["age"],
            "destination": r["destination_for_flight"],
            "status": r["status"],
        }
        if r["status"] == "approved":
            pred_info = model_service.predict_astronaut_timeline(con, r["astronaut_id"])
            item["total_days"] = pred_info["total_days"]
            item["missionDay"] = pred_info["latest"]["mission_day"] if pred_info["latest"] else 0
            item["prediction"] = pred_info["latest"]
            approved.append(item)
        elif r["status"] == "pending":
            pending.append(item)

    return {"approved": approved, "pending": pending}


def build_dashboard_payload(
    con: sqlite3.Connection,
    model_service: ModelService,
    astronaut_id: str,
    replay_day: int | None = None,
) -> dict[str, Any]:
    """Assemble full 180-day telemetry, check-in mood source tags, schema badges, and AI predictions."""
    aid = str(astronaut_id).strip().upper()
    prof = con.execute("SELECT * FROM astronaut_profile WHERE astronaut_id = ?", (aid,)).fetchone()
    base = con.execute("SELECT * FROM preflight_baseline WHERE astronaut_id = ?", (aid,)).fetchone()
    if prof is None or base is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Astronaut record {aid} not found.")

    total_row = con.execute("SELECT COUNT(*) AS cnt, MAX(mission_day) AS mx FROM mission_telemetry WHERE astronaut_id = ?", (aid,)).fetchone()
    total_days = int(total_row["mx"] or 0)
    effective_day = total_days if replay_day is None else max(1, min(total_days, int(replay_day)))

    tel_rows = con.execute(
        "SELECT * FROM mission_telemetry WHERE astronaut_id = ? AND mission_day <= ? ORDER BY mission_day ASC",
        (aid, effective_day),
    ).fetchall()
    if not tel_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No telemetry rows found for {aid}.")

    # Optional mood check-ins mapped cleanly by calendar date (YYYY-MM-DD).
    checkin_rows = con.execute(
        "SELECT checkin_date, score FROM mood_checkins WHERE astronaut_id = ?",
        (aid,),
    ).fetchall()
    checkin_by_date = {str(r["checkin_date"]): float(r["score"]) for r in checkin_rows}

    times = [str(r["timestamp"]) for r in tel_rows]
    mission_days = [int(r["mission_day"]) for r in tel_rows]
    series: dict[str, Any] = {}

    for spec in METRIC_SPECS:
        mid = spec["id"]
        scale = float(spec["scale"])
        channels_out: list[dict[str, Any]] = []
        for ch_key, col_name in spec["channels"]:
            base_val = round(float(base[f"{col_name}_mean"]) * scale, 2)
            vals: list[float] = []
            sources: list[str] | None = [] if mid == "mood" else None
            for row in tel_rows:
                raw_v = row[col_name]
                if mid == "mood":
                    day_date = str(row["timestamp"])[:10]
                    if day_date in checkin_by_date:
                        val = round(max(0.0, min(100.0, checkin_by_date[day_date] * 20.0)), 1)
                        sources.append("check-in")
                    else:
                        fallback_mood = float(raw_v) * 10.0 if raw_v is not None else base_val
                        val = round(max(0.0, min(100.0, fallback_mood)), 1)
                        sources.append("simulated data")
                else:
                    val = round(float(raw_v) * scale, 2) if raw_v is not None else base_val
                vals.append(val)

            ch_payload: dict[str, Any] = {
                "key": ch_key,
                "baseline": base_val,
                "values": vals,
            }
            if sources is not None:
                ch_payload["sources"] = sources
            badge = model_service.schema_badges.get(col_name)
            if badge:
                ch_payload["schema_badge"] = badge.get("ui_badge", "Placeholder")
            channels_out.append(ch_payload)
        series[mid] = {"channels": channels_out}

    pred_result = model_service.predict_astronaut_timeline(con, aid, max_day=effective_day)

    return {
        "granularity": "daily",
        "astronaut": {
            "id": aid,
            "name": prof["name"],
            "initials": _initials(prof["name"]),
            "role": prof["mission_role"],
            "mission": prof["destination_for_flight"] or "Orbital Mission",
            "age": prof["age"],
            "missionDay": effective_day,
            "totalDays": total_days,
            "flightSurgeon": prof["contact_flight_surgeon"],
        },
        "times": times,
        "mission_days": mission_days,
        "series": series,
        "prediction": {
            "model_version": pred_result["model_version"],
            "selected_architecture": pred_result["selected_architecture"],
            "latest": pred_result["latest"],
            "history": pred_result["predictions"],
        },
        "schema_badges": model_service.schema_badges,
    }
