"""Mental health check-in routes, saved mood media recommendations, and rate-limited email support."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import json
import os
import re
import smtplib
import sqlite3
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from backend.database import get_db
from backend.security import require_csrf, require_user, resolve_authorized_astronaut_id
from backend.services.mood_service import LOW_MOOD_STREAK_DAYS, LOW_MOOD_THRESHOLD, upsert_daily_checkin

router = APIRouter(prefix="/api/mental", tags=["mental"])

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
MAX_EMAILS_PER_HOUR = 10


class CheckinSubmitRequest(BaseModel):
    answers: dict[str, Any]
    checkin_date: str | None = None


class MentalEmailRequest(BaseModel):
    to_email: str
    subject: str = ""
    body: str = ""


def _serialize_checkin(row: sqlite3.Row) -> dict[str, Any]:
    try:
        ans = json.loads(row["answers_json"] or "{}")
    except Exception:
        ans = {}
    return {
        "id": int(row["id"]),
        "astronaut_id": row["astronaut_id"],
        "checkin_date": row["checkin_date"],
        "time": row["checkin_date"],
        "score": float(row["score"]),
        "recommended_tag": row["recommended_tag"],
        "answers": ans,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _load_media(con: sqlite3.Connection, astronaut_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    srows = con.execute(
        "SELECT id, title, tag, kind, url, upload_id FROM astronaut_playlist_items WHERE astronaut_id = ? ORDER BY id ASC",
        (astronaut_id,),
    ).fetchall()
    songs: list[dict[str, Any]] = []
    for r in srows:
        media_url = f"/api/media/{r['upload_id']}" if r["upload_id"] else (r["url"] or "")
        if media_url:
            songs.append(
                {
                    "id": int(r["id"]),
                    "title": r["title"],
                    "tag": r["tag"],
                    "kind": r["kind"],
                    "url": media_url,
                }
            )

    prows = con.execute(
        "SELECT id, tag, url, upload_id, caption FROM astronaut_photo_items WHERE astronaut_id = ? ORDER BY id ASC",
        (astronaut_id,),
    ).fetchall()
    photos: list[dict[str, Any]] = []
    for r in prows:
        media_url = f"/api/media/{r['upload_id']}" if r["upload_id"] else (r["url"] or "")
        if media_url:
            photos.append(
                {
                    "id": int(r["id"]),
                    "tag": r["tag"],
                    "url": media_url,
                    "caption": r["caption"] or "",
                }
            )
    return songs, photos


@router.get("/{astronaut_id}/checkins")
def list_checkins(
    astronaut_id: str,
    limit: int = Query(default=60, ge=1, le=365),
    user: dict[str, Any] = Depends(require_user),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Return mood check-in history, today's editable check-in (if any), low-mood streak, and saved media."""
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    rows = con.execute(
        "SELECT * FROM mood_checkins WHERE astronaut_id = ? ORDER BY checkin_date DESC, id DESC LIMIT ?",
        (aid, limit),
    ).fetchall()
    entries = [_serialize_checkin(r) for r in rows]

    today_str = datetime.now(timezone.utc).date().isoformat()
    today_checkin = next((e for e in entries if e["checkin_date"] == today_str), None)
    low_streak = len(entries) >= LOW_MOOD_STREAK_DAYS and all(e["score"] < LOW_MOOD_THRESHOLD for e in entries[:LOW_MOOD_STREAK_DAYS])
    songs, photos = _load_media(con, aid)

    return {
        "astronaut_id": aid,
        "today_date": today_str,
        "today_checkin": today_checkin,
        "low_streak": low_streak,
        "entries": entries,
        "songs": songs,
        "photos": photos,
    }


@router.post("/{astronaut_id}/checkins", status_code=status.HTTP_201_CREATED)
def submit_checkin(
    astronaut_id: str,
    payload: CheckinSubmitRequest,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Save today's mental health check-in (astronaut owner only; editable on the same day)."""
    if user["role"] != "astronaut":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only astronauts can submit check-ins.")
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    saved = upsert_daily_checkin(con, aid, payload.answers, payload.checkin_date)
    songs, photos = _load_media(con, aid)
    return {"ok": True, "entry": saved, "songs": songs, "photos": photos}


@router.put("/{astronaut_id}/checkins/today")
def edit_today_checkin(
    astronaut_id: str,
    payload: CheckinSubmitRequest,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Edit today's already-submitted mental health check-in cleanly."""
    if user["role"] != "astronaut":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only astronauts can update today's check-in.")
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    today_str = datetime.now(timezone.utc).date().isoformat()
    saved = upsert_daily_checkin(con, aid, payload.answers, today_str)
    songs, photos = _load_media(con, aid)
    return {"ok": True, "entry": saved, "songs": songs, "photos": photos}


@router.post("/email")
def send_mental_email(
    payload: MentalEmailRequest,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Validate recipient, enforce per-user hourly rate limit, and send via SMTP or mailto fallback without logging bodies."""
    to_addr = str(payload.to_email or "").strip()
    if not _EMAIL_RE.match(to_addr):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please enter a valid recipient email address.")

    now_dt = datetime.now(timezone.utc)
    cutoff = (now_dt - timedelta(hours=1)).isoformat(timespec="seconds")
    cnt_row = con.execute(
        "SELECT COUNT(*) FROM email_rate_limits WHERE user_id = ? AND sent_at >= ?",
        (int(user["user_id"]), cutoff),
    ).fetchone()
    if int(cnt_row[0]) >= MAX_EMAILS_PER_HOUR:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Hourly email send limit reached. Please try again later.",
        )

    subject = str(payload.subject or "Note from Orbit").strip()[:160]
    body = str(payload.body or "").strip()[:5000]
    now_iso = now_dt.isoformat(timespec="seconds")

    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    if smtp_host:
        smtp_port = int(os.environ.get("SMTP_PORT", "587") or "587")
        smtp_user = os.environ.get("SMTP_USER", "").strip()
        smtp_pass = os.environ.get("SMTP_PASSWORD", "").strip()
        smtp_from = os.environ.get("SMTP_FROM", smtp_user or "no-reply@vitalverse.local").strip()

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = smtp_from
        msg["To"] = to_addr
        msg.set_content(body)
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as client:
                if smtp_port == 587:
                    client.starttls()
                if smtp_user and smtp_pass:
                    client.login(smtp_user, smtp_pass)
                client.send_message(msg)
            con.execute(
                "INSERT INTO email_rate_limits (user_id, recipient_email, sent_at, status) VALUES (?, ?, ?, 'sent_smtp')",
                (int(user["user_id"]), to_addr, now_iso),
            )
            con.commit()
            return {"ok": True, "mode": "smtp", "message": f"Email sent securely to {to_addr}."}
        except Exception as exc:
            con.execute(
                "INSERT INTO email_rate_limits (user_id, recipient_email, sent_at, status) VALUES (?, ?, ?, 'smtp_error')",
                (int(user["user_id"]), to_addr, now_iso),
            )
            con.commit()
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"SMTP delivery failed: {type(exc).__name__}") from exc

    con.execute(
        "INSERT INTO email_rate_limits (user_id, recipient_email, sent_at, status) VALUES (?, ?, ?, 'mailto_fallback')",
        (int(user["user_id"]), to_addr, now_iso),
    )
    con.commit()
    mailto_url = f"mailto:{quote(to_addr)}?subject={quote(subject)}&body={quote(body)}"
    return {"ok": True, "mode": "mailto", "mailto_url": mailto_url}
