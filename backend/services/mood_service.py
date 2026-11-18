"""Canonical Mental Health mood score calculation, check-in persistence, and low-mood alert triggers."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any

from fastapi import HTTPException, status

from backend.services.alert_service import create_alert

LOW_MOOD_THRESHOLD = 2.5
LOW_MOOD_STREAK_DAYS = 3
ALLOWED_Q1_EMOTIONS = {"Calm", "Happy", "Tired", "Stressed", "Sad", "Excited"}
ALLOWED_Q3_SMILE = {"Yes", "No", "Something else"}
ALLOWED_Q5_OVERWHELMED = {"Never", "Sometimes", "Often"}


def compute_mood_score(answers: dict[str, Any]) -> tuple[float, str, dict[str, Any]]:
    """
    Compute the canonical 1.0-5.0 mood score and recommended media tag matching mental.html.

    Returns (score, recommended_tag, sanitized_answers).
    """
    clean: dict[str, Any] = {}
    for ci_idx, allowed, label in (
        ("1", ALLOWED_Q1_EMOTIONS, "question 2"),
        ("3", ALLOWED_Q3_SMILE, "question 4"),
        ("5", ALLOWED_Q5_OVERWHELMED, "question 6"),
    ):
        raw_choice = answers.get(ci_idx, answers.get(int(ci_idx) if ci_idx.isdigit() else ci_idx))
        val = str(raw_choice or "").strip()
        if val not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Please select a valid answer for {label}.",
            )
        clean[ci_idx] = val

    scale_scores: list[float] = []
    for si in ("0", "2", "4", "6", "8"):
        raw_num = answers.get(si, answers.get(int(si)))
        try:
            num = float(raw_num)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid rating scale value for question {int(si) + 1}.",
            ) from exc
        if num < 1.0 or num > 5.0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Rating for question {int(si) + 1} must be between 1 and 5.",
            )
        rounded = round(num)
        clean[si] = int(rounded)
        scale_scores.append(float(rounded))

    clean["3t"] = str(answers.get("3t") or "").strip()[:1000] if clean["3"] in {"Yes", "Something else"} else ""
    clean["7"] = str(answers.get("7", answers.get(7)) or "").strip()[:1000]
    clean["9"] = str(answers.get("9", answers.get(9)) or "").strip()[:1000]

    score = sum(scale_scores) / len(scale_scores)
    if clean["5"] == "Often":
        score -= 0.7
    elif clean["5"] == "Never":
        score += 0.2
    if clean["1"] in {"Sad", "Stressed"}:
        score -= 0.3

    score = round(max(1.0, min(5.0, score)), 1)

    if score < 2.7:
        tag = "comfort"
    elif score < 3.8:
        tag = "happy"
    else:
        tag = "energy"
    if clean["1"] in {"Sad", "Stressed", "Tired"} or clean["5"] == "Often":
        tag = "comfort"

    return score, tag, clean


def upsert_daily_checkin(
    con: sqlite3.Connection,
    astronaut_id: str,
    answers: dict[str, Any],
    checkin_date: str | None = None,
) -> dict[str, Any]:
    """Create or update today's editable mental health check-in and emit warning alert if warranted."""
    aid = str(astronaut_id).strip().upper()
    day_str = (checkin_date or datetime.now(timezone.utc).date().isoformat()).strip()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    score, tag, clean_answers = compute_mood_score(answers)

    existing = con.execute(
        "SELECT id, created_at FROM mood_checkins WHERE astronaut_id = ? AND checkin_date = ?",
        (aid, day_str),
    ).fetchone()

    answers_json = json.dumps(clean_answers)
    if existing is None:
        cur = con.execute(
            """
            INSERT INTO mood_checkins (astronaut_id, checkin_date, answers_json, score, recommended_tag, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (aid, day_str, answers_json, score, tag, now_iso, now_iso),
        )
        checkin_id = int(cur.lastrowid)
        created_at = now_iso
    else:
        checkin_id = int(existing["id"])
        created_at = str(existing["created_at"])
        con.execute(
            """
            UPDATE mood_checkins
            SET answers_json = ?, score = ?, recommended_tag = ?, updated_at = ?
            WHERE id = ?
            """,
            (answers_json, score, tag, now_iso, checkin_id),
        )
    con.commit()

    recent_rows = con.execute(
        "SELECT score, checkin_date FROM mood_checkins WHERE astronaut_id = ? ORDER BY checkin_date DESC LIMIT 3",
        (aid,),
    ).fetchall()
    low_streak = len(recent_rows) == LOW_MOOD_STREAK_DAYS and all(float(r["score"]) < LOW_MOOD_THRESHOLD for r in recent_rows)

    alert_emitted = False
    if score < LOW_MOOD_THRESHOLD or low_streak:
        existing_alert = con.execute(
            """
            SELECT id FROM alerts
            WHERE astronaut_id = ? AND source = 'mood' AND DATE(created_at) = ?
            """,
            (aid, day_str),
        ).fetchone()
        if existing_alert is None:
            msg = (
                f"Sustained low mood streak ({LOW_MOOD_STREAK_DAYS} days < {LOW_MOOD_THRESHOLD}/5) reported for {aid}."
                if low_streak
                else f"Low daily mental check-in score ({score:.1f}/5) reported for {aid} on {day_str}."
            )
            create_alert(
                con,
                astronaut_id=aid,
                mission_day=None,
                severity="warning",
                source="mood",
                short_message=msg,
                detailed_explanation={
                    "summary": msg,
                    "checkin_date": day_str,
                    "score": score,
                    "low_streak": low_streak,
                    "recommended_action": "Review daily check-in responses and reach out via flight surgeon support channels.",
                },
                notify_doctors=True,
            )
            alert_emitted = True

    return {
        "id": checkin_id,
        "astronaut_id": aid,
        "checkin_date": day_str,
        "time": day_str,
        "score": score,
        "recommended_tag": tag,
        "answers": clean_answers,
        "created_at": created_at,
        "updated_at": now_iso,
        "low_streak": low_streak,
        "alert_emitted": alert_emitted,
    }
