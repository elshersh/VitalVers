"""Authentication, Argon2id password hashing (via argon2-cffi), sessions, CSRF, and RBAC."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
import sqlite3
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status

from backend.config import (
    ACCOUNT_HEADER,
    ACCOUNT_PARAM,
    ACCOUNT_SET_HEADER,
    ANON_TAG,
    COOKIE_SECURE,
    CSRF_HEADER,
    LEGACY_COOKIES,
    MAX_BROWSER_SESSIONS,
    SESSION_COOKIE_PREFIX,
    TAG_COOKIE,
    load_demo_credentials,
)
from backend.database import get_db


_SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{20,128}")


def session_tag(session_id: str) -> str:
    """One-way, non-secret tag of a session id; safe to expose to page scripts."""
    return hashlib.sha256(f"vitalverse-session-tag:{session_id}".encode("utf-8")).hexdigest()[:20]


_TAG_RE = re.compile(r"[0-9a-f]{20}")


def _session_cookie_name(tag: str) -> str:
    return f"{SESSION_COOKIE_PREFIX}{tag}"


def browser_sessions(request: Request) -> list[str]:
    """Session ids this browser holds, oldest first.

    Each session has its own HttpOnly cookie named after its tag, so a sign-in or sign-out answer only ever
    carries the one session it creates, never the other sessions of the browser. The readable vv_tags cookie
    keeps their order (newest last).
    """
    held: dict[str, str] = {}
    for name, value in request.cookies.items():
        if not name.startswith(SESSION_COOKIE_PREFIX) or not _SESSION_ID_RE.fullmatch(value or ""):
            continue
        tag = name[len(SESSION_COOKIE_PREFIX):]
        if secrets.compare_digest(session_tag(value), tag):
            held[tag] = value
    listed = [t for t in request.cookies.get(TAG_COOKIE, "").split(".") if t in held]
    order = [t for t in held if t not in listed] + list(dict.fromkeys(listed))
    return [held[t] for t in order][-MAX_BROWSER_SESSIONS:]


def selected_session(request: Request) -> tuple[str | None, str]:
    """Which of this browser's sessions the request uses: (session id or None, tag the answer is made for).

    A tab names its account with the X-VV-Account header (or ?account= on page loads). Only sessions this
    browser really holds can be named, so the choice cannot reach anyone else's account. A tab that names an
    account this browser no longer holds is signed out; its answer still carries the tag it named, so that tab
    can tell it was signed out. Without a choice, the newest session is used.
    """
    sids = browser_sessions(request)
    wanted = (request.headers.get(ACCOUNT_HEADER) or request.query_params.get(ACCOUNT_PARAM) or "").strip()
    if wanted:
        if not _TAG_RE.fullmatch(wanted):
            return None, ANON_TAG
        for sid in sids:
            if secrets.compare_digest(session_tag(sid), wanted):
                return sid, wanted
        return None, wanted
    if sids:
        return sids[-1], session_tag(sids[-1])
    return None, ANON_TAG


def request_tag(request: Request) -> str:
    """Tag of the account this request's answer is made for (ANON_TAG when it names none)."""
    return selected_session(request)[1]


def _live_sessions(con: sqlite3.Connection, sids: list[str]) -> list[str]:
    """Keep only sessions that are still signed in, in the same order."""
    if not sids:
        return []
    ph = ",".join("?" * len(sids))
    rows = con.execute(
        f"SELECT session_id, expires_at FROM web_sessions WHERE revoked = 0 AND session_id IN ({ph})", sids
    ).fetchall()
    now = _now_utc()
    alive = {r["session_id"] for r in rows if _parse_iso(r["expires_at"]) > now}
    return [s for s in sids if s in alive]


def _cookie_options() -> dict[str, Any]:
    ttl = int(load_demo_credentials().get("session_ttl_seconds", 3600))
    return {"samesite": "lax", "secure": COOKIE_SECURE, "max_age": ttl, "path": "/"}


def _write_tags(response: Response, held: list[str], ended: list[str]) -> None:
    """Forget ended sessions and rewrite the readable tag list. Never writes a session id."""
    for legacy in LEGACY_COOKIES:
        response.delete_cookie(legacy, path="/")
    for sid in ended:
        response.delete_cookie(_session_cookie_name(session_tag(sid)), path="/")
    if held:
        response.set_cookie(key=TAG_COOKIE, value=".".join(session_tag(s) for s in held), httponly=False, **_cookie_options())
    else:
        response.delete_cookie(TAG_COOKIE, path="/")


def add_browser_session(request: Request, response: Response, con: sqlite3.Connection, session_id: str) -> str:
    """Add a new sign-in to this browser's sessions (other tabs keep theirs) and tell the tab to use it."""
    before = browser_sessions(request)
    live = [s for s in _live_sessions(con, before) if s != session_id] + [session_id]
    held = live[-MAX_BROWSER_SESSIONS:]
    ended = [s for s in before if s not in held]
    tag = session_tag(session_id)
    response.set_cookie(key=_session_cookie_name(tag), value=session_id, httponly=True, **_cookie_options())
    _write_tags(response, held, ended)
    response.headers[ACCOUNT_SET_HEADER] = tag
    return tag


def drop_ended_browser_sessions(request: Request, response: Response, con: sqlite3.Connection) -> None:
    """After a sign-out, forget sessions that ended and tell the tab it is signed out."""
    before = browser_sessions(request)
    held = _live_sessions(con, before)
    _write_tags(response, held, [s for s in before if s not in held])
    response.headers[ACCOUNT_SET_HEADER] = ANON_TAG


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def build_password_hasher() -> PasswordHasher:
    """Create the official argon2-cffi PasswordHasher using configured cost parameters."""
    cfg = load_demo_credentials()
    ap = cfg.get("argon2_params", {})
    return PasswordHasher(
        time_cost=int(ap.get("time_cost", 2)),
        memory_cost=int(ap.get("memory_cost", 4096)),
        parallelism=int(ap.get("parallelism", 2)),
        hash_len=int(ap.get("hash_len", 32)),
        salt_len=int(ap.get("salt_len", 16)),
    )


_PH = build_password_hasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password using official argon2-cffi."""
    return _PH.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against an argon2id hash via argon2-cffi."""
    if not isinstance(password, str) or not password or not stored_hash:
        return False
    try:
        return bool(_PH.verify(stored_hash, password))
    except (VerifyMismatchError, InvalidHashError):
        return False


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def authenticate_web_user(
    con: sqlite3.Connection,
    identifier: str,
    password: str,
    requested_role: str | None = None,
) -> dict[str, Any]:
    """Verify credentials with 5-attempt lockout and enforce requested role match."""
    raw = str(identifier or "").strip()
    if not raw or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vitalverse ID and password are required.")

    upper = raw.upper()
    row = con.execute(
        "SELECT * FROM users WHERE UPPER(vitalverse_id) = ? OR UPPER(COALESCE(legacy_user_id, '')) = ? OR LOWER(COALESCE(email, '')) = ?",
        (upper, upper, raw.lower()),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Vitalverse ID or password.")

    cfg = load_demo_credentials()
    max_attempts = int(cfg.get("max_failed_attempts", 5))
    lockout_sec = int(cfg.get("lockout_duration_seconds", 900))
    now = _now_utc()

    failed = int(row["failed_attempts"] or 0)
    locked_until = row["locked_until"]
    if locked_until:
        lock_dt = _parse_iso(locked_until)
        if now < lock_dt:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Account temporarily locked after repeated failures. Try again after {locked_until}.",
            )
        failed = 0
        locked_until = None

    if not verify_password(password, row["password_hash"]):
        failed += 1
        new_locked = None
        if failed >= max_attempts:
            new_locked = (now + timedelta(seconds=lockout_sec)).isoformat(timespec="seconds")
        con.execute("UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?", (failed, new_locked, row["id"]))
        con.commit()
        if new_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Invalid credentials ({failed}/{max_attempts}). Account locked for 15 minutes.",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Vitalverse ID or password ({failed}/{max_attempts} attempts).",
        )

    if requested_role and row["role"] != requested_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role mismatch: account {row['vitalverse_id']} is registered as {row['role']}.",
        )

    con.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (row["id"],))
    con.commit()
    return dict(row)


def create_web_session(con: sqlite3.Connection, user_id: int) -> dict[str, str]:
    """Create a stateful server session and CSRF token for Cookie auth."""
    cfg = load_demo_credentials()
    ttl_sec = int(cfg.get("session_ttl_seconds", 3600))
    now = _now_utc()
    session_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    created_at = now.isoformat(timespec="seconds")
    expires_at = (now + timedelta(seconds=ttl_sec)).isoformat(timespec="seconds")
    con.execute(
        "INSERT INTO web_sessions (session_id, user_id, csrf_token, created_at, expires_at, revoked) VALUES (?,?,?,?,?,0)",
        (session_id, int(user_id), csrf_token, created_at, expires_at),
    )
    con.commit()
    return {"session_id": session_id, "csrf_token": csrf_token, "expires_at": expires_at, "ttl_seconds": str(ttl_sec)}


def get_session_user(request: Request, con: sqlite3.Connection = Depends(get_db)) -> dict[str, Any] | None:
    """Resolve the signed-in user of the session this request (this tab) uses, or None."""
    sid, _tag = selected_session(request)
    if not sid:
        return None
    row = con.execute(
        """
        SELECT s.session_id, s.csrf_token, s.expires_at, s.revoked,
               u.id AS user_id, u.vitalverse_id, u.email, u.role, u.astronaut_id,
               u.legacy_user_id, u.display_name
        FROM web_sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.session_id = ?
        """,
        (sid,),
    ).fetchone()
    if row is None or int(row["revoked"]) != 0:
        return None
    if _now_utc() >= _parse_iso(row["expires_at"]):
        return None
    return dict(row)


def require_user(user: dict[str, Any] | None = Depends(get_session_user)) -> dict[str, Any]:
    """Require an active authenticated web session."""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return user


def require_csrf(request: Request, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """Validate X-CSRF-Token header against the active server session."""
    supplied = request.headers.get(CSRF_HEADER, "")
    if not supplied or not secrets.compare_digest(supplied, str(user["csrf_token"])):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or missing CSRF token.")
    return user


def resolve_authorized_astronaut_id(con: sqlite3.Connection, user: dict[str, Any], astronaut_id: str) -> str:
    """Enforce RBAC: astronaut owns their own ID; doctor needs an approved link."""
    target_aid = str(astronaut_id or "").strip().upper()
    if not target_aid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid astronaut ID.")

    if user["role"] == "astronaut":
        if user.get("astronaut_id") != target_aid:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied for another astronaut's data.")
        return target_aid

    if user["role"] == "doctor":
        link = con.execute(
            "SELECT status FROM doctor_astronaut_links WHERE doctor_user_id = ? AND astronaut_id = ?",
            (int(user["user_id"]), target_aid),
        ).fetchone()
        if link is None or link["status"] != "approved":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: astronaut approval is required before viewing this record.",
            )
        return target_aid

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unsupported role.")
