"""Live telemetry inference, diagnostic alert payload builder, and simulated DEMO day generator."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Any

from fastapi import HTTPException, status

from backend.services.alert_service import create_alert
from backend.services.model_service import ModelService

TRACKED_VITALS: tuple[tuple[str, str, str], ...] = (
    ("heart_rate", "Resting Heart Rate", "bpm"),
    ("systolic_bp", "Systolic Blood Pressure", "mmHg"),
    ("diastolic_bp", "Diastolic Blood Pressure", "mmHg"),
    ("oxygen_saturation", "Blood Oxygen (SpO2)", "%"),
    ("temperature", "Core Body Temperature", "C"),
    ("blood_glucose_mg_dl", "Blood Glucose", "mg/dL"),
    ("sleep_hours", "Sleep Duration", "hrs"),
    ("immunity_indicators", "Immunity Index", "idx"),
    ("hormones", "Stress / Endocrine Load", "idx"),
    ("mood", "Crew Mood Rating", "/10"),
)

CLASS_AREAS = {
    "Medical_Danger_Alert": ("Medical_Danger", "Medical_Danger_Alert", "Cardiovascular"),
    "Health_Warning": ("Health_Warning", "Bone_Muscle", "Immune", "Sleep_Brain"),
    "Stress_BP_Spike_No_Medical_Danger": ("Stress", "Sleep_Brain"),
    "Normal": (),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _extract_diagnostics(
    con: sqlite3.Connection,
    model_service: ModelService,
    astronaut_id: str,
    predicted_class: str,
    latest_pred: dict[str, Any],
) -> dict[str, Any]:
    """Assemble triggered vitals with Step 5 source badges, 7d trend, and prioritized countermeasures."""
    aid = str(astronaut_id).strip().upper()
    recent_rows = con.execute(
        """
        SELECT *
        FROM mission_telemetry
        WHERE astronaut_id = ? AND mission_day <= ?
        ORDER BY mission_day DESC
        LIMIT 7
        """,
        (aid, int(latest_pred["mission_day"])),
    ).fetchall()
    if not recent_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No telemetry rows found for astronaut.")

    latest_row = recent_rows[0]
    base_row = con.execute(
        "SELECT * FROM preflight_baseline WHERE astronaut_id = ?",
        (aid,),
    ).fetchone()

    triggered_vitals: list[dict[str, Any]] = []
    for col, fallback_label, fallback_unit in TRACKED_VITALS:
        val = latest_row[col]
        if val is None:
            continue
        val_f = float(val)
        meta = model_service.schema_badges.get(col, {})
        base_mean = float(base_row[f"{col}_mean"]) if (base_row and f"{col}_mean" in base_row.keys() and base_row[f"{col}_mean"] is not None) else None
        base_std = float(base_row[f"{col}_std"]) if (base_row and f"{col}_std" in base_row.keys() and base_row[f"{col}_std"] is not None) else None
        z_val = round((val_f - base_mean) / max(base_std or 1.0, 1e-3), 2) if base_mean is not None else 0.0
        triggered_vitals.append(
            {
                "column": col,
                "indicator": str(meta.get("display_name") or fallback_label),
                "value": round(val_f, 2),
                "baseline": round(base_mean, 2) if base_mean is not None else None,
                "unit": str(meta.get("unit") or fallback_unit),
                "z": z_val,
                "source_badge": str(meta.get("ui_badge") or "Reference value"),
            }
        )
    triggered_vitals.sort(key=lambda item: abs(float(item["z"])), reverse=True)
    top_vitals = triggered_vitals[:5]

    trend_7d: list[dict[str, Any]] = []
    for row in reversed(recent_rows):
        relax = row["relaxation"]
        stress_proxy = round(max(0.0, min(100.0, (10.0 - float(relax)) * 10.0)), 1) if relax is not None else None
        mood_val = row["mood"]
        trend_7d.append(
            {
                "day": int(row["mission_day"]),
                "heart_rate": round(float(row["heart_rate"]), 1) if row["heart_rate"] is not None else None,
                "blood_oxygen": round(float(row["oxygen_saturation"]), 1) if row["oxygen_saturation"] is not None else None,
                "stress_index": stress_proxy,
                "mood": round(float(mood_val) * 10.0, 1) if mood_val is not None else None,
            }
        )

    countermeasures: list[dict[str, Any]] = []
    if predicted_class == "Medical_Danger_Alert":
        countermeasures.append(
            {
                "title": "Contact flight surgeon immediately",
                "category": "emergency",
                "priority": 0,
            }
        )

    areas = CLASS_AREAS.get(predicted_class, ())
    if areas:
        ph = ",".join("?" for _ in areas)
        cm_rows = con.execute(
            f"SELECT problem_area, advice_text, ui_badge FROM countermeasures WHERE problem_area IN ({ph}) LIMIT 4",
            areas,
        ).fetchall()
        for idx, cm in enumerate(cm_rows, start=1):
            countermeasures.append(
                {
                    "title": str(cm["advice_text"]),
                    "category": str(cm["problem_area"]),
                    "source_badge": str(cm["ui_badge"] or "NASA standard"),
                    "priority": idx,
                }
            )

    severity = _severity_for_prediction(predicted_class, latest_pred)
    if predicted_class == "Medical_Danger_Alert":
        recommended = "Contact your flight surgeon immediately."
    elif predicted_class == "Stress_BP_Spike_No_Medical_Danger":
        recommended = "Pause high-workload tasks, hydrate, perform paced breathing, and re-check vitals in 15 minutes."
    elif predicted_class == "Health_Warning":
        recommended = "Complete daily countermeasures checklist, prioritize sleep window, and consult flight surgeon if warning persists."
    else:
        recommended = "Continue nominal daily countermeasures and routine telemetry checks."

    status_label = latest_pred["status_label"]
    conf_pct = round(float(latest_pred["confidence"]) * 100)
    summary = (
        f"AI model classified Mission Day {latest_pred['mission_day']} as {status_label} "
        f"({conf_pct}% confidence, {latest_pred['danger_tier']})."
    )

    return {
        "severity": severity,
        "detailed_explanation": {
            "summary": summary,
            "recommended_action": recommended,
            "predicted_class": predicted_class,
            "status_label": status_label,
            "danger_tier": latest_pred["danger_tier"],
            "confidence": latest_pred["confidence"],
            "class_probabilities": latest_pred["class_probabilities"],
            "triggered_vitals": top_vitals,
            "trend_7d": trend_7d,
            "countermeasures": countermeasures,
        },
    }


def _severity_for_prediction(predicted_class: str, latest_pred: dict[str, Any]) -> str | None:
    if predicted_class == "Medical_Danger_Alert":
        tier = str(latest_pred.get("danger_tier") or "")
        conf = float(latest_pred.get("confidence") or 0.0)
        if "Tier 2" in tier or conf >= 0.65:
            return "danger"
        return "danger-confirm"
    if predicted_class in {"Health_Warning", "Stress_BP_Spike_No_Medical_Danger"}:
        return "warning"
    return None


def run_prediction_for_astronaut(
    con: sqlite3.Connection,
    model_service: ModelService,
    astronaut_id: str,
    emit_alert: bool = True,
) -> dict[str, Any]:
    """Run health_model.joblib on all recorded telemetry days, persist latest prediction, and trigger alert if warranted."""
    aid = str(astronaut_id).strip().upper()
    try:
        timeline = model_service.predict_astronaut_timeline(con, aid)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    latest = timeline.get("latest")
    if latest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No telemetry recorded for {aid}.")

    now_iso = _utc_now()
    model_version = str(timeline.get("model_version") or "rf_v1")
    con.execute(
        """
        INSERT INTO model_predictions (record_id, predicted_class, class_probabilities, model_version, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(record_id, model_version) DO UPDATE SET
            predicted_class = excluded.predicted_class,
            class_probabilities = excluded.class_probabilities,
            created_at = excluded.created_at
        """,
        (
            int(latest["record_id"]),
            str(latest["predicted_class"]),
            json.dumps(latest["class_probabilities"]),
            model_version,
            now_iso,
        ),
    )
    con.commit()

    diag = _extract_diagnostics(con, model_service, aid, str(latest["predicted_class"]), latest)
    sev = diag["severity"]
    alert_created = None

    if emit_alert and sev is not None:
        short_msg = (
            f"Day {latest['mission_day']}: {latest['status_label']} "
            f"({round(float(latest['confidence']) * 100)}% confidence)"
        )
        existing = con.execute(
            """
            SELECT id FROM alerts
            WHERE astronaut_id = ? AND mission_day = ? AND source = 'model' AND severity = ? AND acknowledged_at IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (aid, int(latest["mission_day"]), sev),
        ).fetchone()
        if existing is None:
            alert_created = create_alert(
                con,
                astronaut_id=aid,
                mission_day=int(latest["mission_day"]),
                severity=sev,
                source="model",
                short_message=short_msg,
                detailed_explanation=diag["detailed_explanation"],
                notify_doctors=True,
            )

    return {
        "ok": True,
        "astronaut_id": aid,
        "mission_day": int(latest["mission_day"]),
        "record_id": int(latest["record_id"]),
        "model_version": model_version,
        "predicted_class": latest["predicted_class"],
        "status_label": latest["status_label"],
        "ui_status": latest["ui_status"],
        "danger_tier": latest["danger_tier"],
        "confidence": latest["confidence"],
        "class_probabilities": latest["class_probabilities"],
        "alert_created": alert_created,
        "diagnostics": diag["detailed_explanation"],
    }


def advance_demo_day(
    con: sqlite3.Connection,
    model_service: ModelService,
    astronaut_id: str,
    scenario: str = "auto",
) -> dict[str, Any]:
    """Append the next simulated mission day (clearly flagged DEMO), run AI prediction, and trigger alerts if needed."""
    aid = str(astronaut_id).strip().upper()
    prev = con.execute(
        "SELECT * FROM mission_telemetry WHERE astronaut_id = ? ORDER BY mission_day DESC LIMIT 1",
        (aid,),
    ).fetchone()
    base = con.execute("SELECT * FROM preflight_baseline WHERE astronaut_id = ?", (aid,)).fetchone()
    if prev is None or base is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Telemetry baseline missing for {aid}.")

    next_day = int(prev["mission_day"]) + 1
    try:
        prev_dt = datetime.fromisoformat(str(prev["timestamp"]))
    except ValueError:
        prev_dt = datetime.now(timezone.utc)
    next_ts = (prev_dt + timedelta(days=1)).isoformat(timespec="seconds")

    scen = (scenario or "auto").strip().lower()
    if scen == "auto":
        mod = next_day % 4
        scen = "danger" if mod == 0 else ("warning" if mod == 2 else "normal")

    def _base(col: str, fallback: float) -> float:
        key = f"{col}_mean"
        if key in base.keys() and base[key] is not None:
            return float(base[key])
        if col in prev.keys() and prev[col] is not None:
            return float(prev[col])
        return fallback

    hr = _base("heart_rate", 68.0)
    sbp = _base("systolic_bp", 118.0)
    dbp = _base("diastolic_bp", 76.0)
    spo2 = _base("oxygen_saturation", 98.2)
    temp = _base("temperature", 36.7)
    glucose = _base("blood_glucose_mg_dl", 92.0)
    bone = float(prev["bone_health"] if prev["bone_health"] is not None else _base("bone_health", 96.0))
    muscle = float(prev["muscle_health"] if prev["muscle_health"] is not None else _base("muscle_health", 96.0))
    immunity = _base("immunity_indicators", 78.0)
    hormones = _base("hormones", 46.0)
    sleep = _base("sleep_hours", 7.3)
    relax = _base("relaxation", 7.0)
    mood = _base("mood", 7.5)
    mh = _base("mental_health_assessment", 74.0)
    game = _base("game_test_score", 72.0)
    cardio_done = 1
    cardio_min = 60.0
    res_done = 1
    res_min = 60.0
    act_min = 120.0
    train_hrs = 2.0
    true_lbl = "Normal"

    if scen == "warning":
        hr += 14.0
        sbp += 16.0
        dbp += 9.0
        spo2 = max(92.5, spo2 - 2.4)
        sleep = max(4.6, sleep - 2.0)
        relax = max(3.0, relax - 2.5)
        mood = max(3.5, mood - 2.2)
        hormones = min(90.0, hormones + 16.0)
        immunity = max(42.0, immunity - 12.0)
        cardio_done = 0
        cardio_min = 18.0
        act_min = 38.0
        train_hrs = 0.7
        true_lbl = "Health_Warning"
    elif scen == "danger":
        hr = max(108.0, hr + 38.0)
        sbp = max(158.0, sbp + 36.0)
        dbp = max(98.0, dbp + 20.0)
        spo2 = 88.4
        temp = 38.5
        glucose = max(142.0, glucose + 44.0)
        sleep = 3.8
        relax = 2.2
        mood = 3.0
        mh = max(35.0, mh - 28.0)
        game = max(38.0, game - 24.0)
        immunity = max(25.0, immunity - 28.0)
        hormones = min(95.0, hormones + 28.0)
        cardio_done = 0
        cardio_min = 0.0
        res_done = 0
        res_min = 0.0
        act_min = 15.0
        train_hrs = 0.25
        true_lbl = "Medical_Danger_Alert"

    cur = con.execute(
        """
        INSERT INTO mission_telemetry (
            astronaut_id, timestamp, mission_day, systolic_bp, diastolic_bp, heart_rate,
            oxygen_saturation, temperature, blood_glucose_mg_dl, bone_health, muscle_health,
            cardio_session_done, cardio_session_min, resistance_training_done, resistance_training_min,
            daily_physical_activity_min, immunity_indicators, hormones, sleep_hours, relaxation,
            mood, mental_health_assessment, game_test_score, daily_training_hours
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            aid, next_ts, next_day,
            round(sbp, 1), round(dbp, 1), round(hr, 1),
            round(spo2, 1), round(temp, 2), round(glucose, 1),
            round(bone, 2), round(muscle, 2),
            cardio_done, cardio_min, res_done, res_min, act_min,
            round(immunity, 1), round(hormones, 1), round(sleep, 1),
            round(relax, 1), round(mood, 1), round(mh, 1), round(game, 1), train_hrs,
        ),
    )
    record_id = int(cur.lastrowid)
    con.execute(
        "INSERT OR REPLACE INTO telemetry_labels (record_id, true_class) VALUES (?, ?)",
        (record_id, true_lbl),
    )
    con.commit()

    result = run_prediction_for_astronaut(con, model_service, aid, emit_alert=True)
    result["demo"] = True
    result["demo_badge"] = "DEMO"
    result["scenario"] = scen
    result["timestamp"] = next_ts
    return result
