"""Short fingerprints of what a signed-in account can see, so open pages know when to refresh.

Pages ask GET /api/live every few seconds (static/js/shell.js). When a fingerprint changes, for example after
an astronaut approves a flight surgeon's access request, every open page of the affected accounts reloads
just that part of its data. The fingerprints are one-way hashes and reveal nothing about the data itself.
Prototype for research/education only - not for clinical diagnosis.
"""
from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

LIVE_PARTS = ("access", "alerts", "health", "todo", "mood", "profile")


def _fingerprint(*values: Any) -> str:
    return hashlib.sha256(repr(values).encode("utf-8")).hexdigest()[:16]


def watched_astronauts(con: sqlite3.Connection, user: dict[str, Any]) -> list[str]:
    """Astronaut records this account may see: its own, or (flight surgeon) the approved ones."""
    if user["role"] == "astronaut":
        return [str(user["astronaut_id"])] if user.get("astronaut_id") else []
    rows = con.execute(
        "SELECT astronaut_id FROM doctor_astronaut_links WHERE doctor_user_id = ? AND status = 'approved' ORDER BY astronaut_id",
        (int(user["user_id"]),),
    ).fetchall()
    return [str(r["astronaut_id"]) for r in rows]


def _rows(con: sqlite3.Connection, sql: str, args: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in con.execute(sql, args).fetchall()]


def live_parts(con: sqlite3.Connection, user: dict[str, Any]) -> dict[str, str]:
    """One fingerprint per part of the data this account can see."""
    uid = int(user["user_id"])
    aids = watched_astronauts(con, user)
    if user["role"] == "astronaut":
        access = _rows(
            con,
            "SELECT id, doctor_user_id, status, created_at, decided_at FROM doctor_astronaut_links WHERE astronaut_id = ? ORDER BY id",
            (user.get("astronaut_id") or "",),
        )
    else:
        access = _rows(
            con,
            "SELECT id, astronaut_id, status, created_at, decided_at FROM doctor_astronaut_links WHERE doctor_user_id = ? ORDER BY id",
            (uid,),
        )
    me = _rows(con, "SELECT display_name FROM users WHERE id = ?", (uid,))
    doctor = _rows(con, "SELECT * FROM doctor_profiles WHERE user_id = ?", (uid,))

    if not aids:
        empty = _fingerprint(None)
        parts = {name: empty for name in LIVE_PARTS}
        parts["access"] = _fingerprint(access)
        parts["profile"] = _fingerprint(me, doctor)
        return parts

    ph = ",".join("?" * len(aids))
    args = tuple(aids)
    alerts = _rows(
        con,
        f"""SELECT COUNT(*), MAX(id), SUM(read_at IS NULL), SUM(acknowledged_at IS NULL), MAX(acknowledged_at)
            FROM alerts WHERE astronaut_id IN ({ph})""",
        args,
    )
    telemetry = _rows(
        con, f"SELECT COUNT(*), MAX(mission_day), MAX(timestamp) FROM mission_telemetry WHERE astronaut_id IN ({ph})", args
    )
    predictions = _rows(
        con,
        f"""SELECT COUNT(*), MAX(p.created_at) FROM model_predictions p
            JOIN mission_telemetry t ON t.record_id = p.record_id WHERE t.astronaut_id IN ({ph})""",
        args,
    )
    todo = _rows(
        con, f"SELECT COUNT(*), SUM(done), MAX(updated_at) FROM daily_todo WHERE astronaut_id IN ({ph})", args
    )
    mood = _rows(con, f"SELECT COUNT(*), MAX(updated_at) FROM mood_checkins WHERE astronaut_id IN ({ph})", args)
    profile = _rows(con, f"SELECT * FROM astronaut_profile WHERE astronaut_id IN ({ph}) ORDER BY astronaut_id", args)
    songs = _rows(con, f"SELECT COUNT(*), MAX(id) FROM astronaut_playlist_items WHERE astronaut_id IN ({ph})", args)
    photos = _rows(con, f"SELECT COUNT(*), MAX(id) FROM astronaut_photo_items WHERE astronaut_id IN ({ph})", args)
    return {
        "access": _fingerprint(access, aids),
        "alerts": _fingerprint(alerts),
        "health": _fingerprint(telemetry, predictions),
        "todo": _fingerprint(todo),
        "mood": _fingerprint(mood),
        "profile": _fingerprint(profile, songs, photos, me, doctor),
    }
