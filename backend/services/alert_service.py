"""Alert creation, deduplication, live SSE fan-out, and optional VAPID Web Push delivery."""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import json
import os
import sqlite3
import threading
from typing import Any

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01
from pywebpush import WebPushException, webpush

from backend.config import UPLOADS_DIR

_SUB_LOCK = threading.Lock()
_SSE_SUBSCRIBERS: list[dict[str, Any]] = []
_VAPID_CACHE: dict[str, str] | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_vapid_keys() -> dict[str, str]:
    """Load VAPID keys from environment or a private gitignored local dev key file."""
    global _VAPID_CACHE
    if _VAPID_CACHE is not None:
        return _VAPID_CACHE

    pub = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    priv = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    subj = os.environ.get("VAPID_SUBJECT", "mailto:flight-surgeon@vitalverse.local").strip()
    if pub and priv:
        _VAPID_CACHE = {"public_key": pub, "private_key": priv, "subject": subj}
        return _VAPID_CACHE

    dev_file = UPLOADS_DIR / ".vapid_dev.json"
    if dev_file.is_file():
        try:
            loaded = json.loads(dev_file.read_text(encoding="utf-8"))
            if loaded.get("public_key") and loaded.get("private_key"):
                _VAPID_CACHE = {
                    "public_key": str(loaded["public_key"]),
                    "private_key": str(loaded["private_key"]),
                    "subject": subj,
                }
                return _VAPID_CACHE
        except Exception:
            pass

    v = Vapid01()
    v.generate_keys()
    priv_pem = v.private_pem().decode("utf-8")
    pub_raw = v.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    pub_b64 = base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode("ascii")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dev_file.write_text(
        json.dumps({"public_key": pub_b64, "private_key": priv_pem}, indent=2),
        encoding="utf-8",
    )
    _VAPID_CACHE = {"public_key": pub_b64, "private_key": priv_pem, "subject": subj}
    return _VAPID_CACHE


def register_sse_subscriber(
    loop: asyncio.AbstractEventLoop,
    user_id: int,
    role: str,
    astronaut_id: str | None,
) -> dict[str, Any]:
    """Register an active client SSE listener."""
    sub = {
        "loop": loop,
        "queue": asyncio.Queue(maxsize=32),
        "user_id": int(user_id),
        "role": role,
        "astronaut_id": astronaut_id,
    }
    with _SUB_LOCK:
        _SSE_SUBSCRIBERS.append(sub)
    return sub


def unregister_sse_subscriber(sub: dict[str, Any]) -> None:
    """Remove an SSE listener cleanly when client disconnects."""
    with _SUB_LOCK:
        if sub in _SSE_SUBSCRIBERS:
            _SSE_SUBSCRIBERS.remove(sub)


def _recipient_user_ids(con: sqlite3.Connection, astronaut_id: str, include_doctors: bool = True) -> list[int]:
    ids: list[int] = []
    arow = con.execute(
        "SELECT id FROM users WHERE role = 'astronaut' AND astronaut_id = ?",
        (astronaut_id,),
    ).fetchone()
    if arow:
        ids.append(int(arow["id"]))
    if include_doctors:
        drows = con.execute(
            "SELECT doctor_user_id FROM doctor_astronaut_links WHERE astronaut_id = ? AND status = 'approved'",
            (astronaut_id,),
        ).fetchall()
        ids.extend(int(r["doctor_user_id"]) for r in drows)
    return list(dict.fromkeys(ids))


def _broadcast_sse(con: sqlite3.Connection, alert_payload: dict[str, Any], recipient_ids: list[int]) -> None:
    target_set = set(recipient_ids)
    with _SUB_LOCK:
        subs = list(_SSE_SUBSCRIBERS)
    for sub in subs:
        if sub["user_id"] in target_set:
            loop: asyncio.AbstractEventLoop = sub["loop"]
            q: asyncio.Queue = sub["queue"]

            def _push(queue: asyncio.Queue = q, item: dict[str, Any] = alert_payload) -> None:
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait(item)

            try:
                loop.call_soon_threadsafe(_push)
            except RuntimeError:
                pass


def _deliver_web_push(con: sqlite3.Connection, alert_payload: dict[str, Any], recipient_ids: list[int]) -> None:
    if not recipient_ids:
        return
    ph = ",".join("?" for _ in recipient_ids)
    subs = con.execute(
        f"SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id IN ({ph})",
        recipient_ids,
    ).fetchall()
    if not subs:
        return

    keys = get_vapid_keys()
    body = json.dumps(
        {
            "title": f"Vitalverse {alert_payload['severity'].upper()}",
            "body": alert_payload["short_message"],
            "url": "/alerts.html",
            "severity": alert_payload["severity"],
        }
    )
    stale_ids: list[int] = []
    for row in subs:
        sub_info = {
            "endpoint": row["endpoint"],
            "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
        }
        try:
            webpush(
                subscription_info=sub_info,
                data=body,
                vapid_private_key=keys["private_key"],
                vapid_claims={"sub": keys["subject"]},
                timeout=3,
            )
        except WebPushException as exc:
            resp = getattr(exc, "response", None)
            if resp is not None and getattr(resp, "status_code", None) in (404, 410):
                stale_ids.append(int(row["id"]))
        except Exception:
            pass

    if stale_ids:
        sph = ",".join("?" for _ in stale_ids)
        con.execute(f"DELETE FROM push_subscriptions WHERE id IN ({sph})", stale_ids)
        con.commit()


def create_alert(
    con: sqlite3.Connection,
    *,
    astronaut_id: str,
    mission_day: int | None,
    severity: str,
    source: str,
    short_message: str,
    detailed_explanation: dict[str, Any],
    notify_doctors: bool = True,
) -> dict[str, Any]:
    """Insert an alert record, broadcast SSE events, and trigger optional Web Push delivery."""
    now = _utc_now()
    aid = str(astronaut_id).strip().upper()
    cur = con.execute(
        """
        INSERT INTO alerts (
            astronaut_id, mission_day, severity, source, short_message,
            detailed_explanation_json, read_at, acknowledged_at, acknowledged_by_user_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
        """,
        (aid, mission_day, severity, source, short_message, json.dumps(detailed_explanation), now),
    )
    con.commit()
    alert_id = int(cur.lastrowid)

    payload = {
        "id": alert_id,
        "astronaut_id": aid,
        "mission_day": mission_day,
        "severity": severity,
        "source": source,
        "short_message": short_message,
        "detailed_explanation": detailed_explanation,
        "read_at": None,
        "acknowledged_at": None,
        "created_at": now,
    }
    recipients = _recipient_user_ids(con, aid, include_doctors=notify_doctors)
    _broadcast_sse(con, payload, recipients)
    _deliver_web_push(con, payload, recipients)
    return payload
