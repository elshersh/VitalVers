"""Database connection helpers and idempotent web schema setup."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event

from backend.config import DB_PATH

_ENGINE = None


def get_engine(db_path: Path | None = None):
    """Return a cached SQLAlchemy engine configured for SQLite foreign keys."""
    global _ENGINE
    target = Path(db_path or DB_PATH)
    if _ENGINE is None or db_path is not None:
        eng = create_engine(
            f"sqlite+pysqlite:///{target.as_posix()}",
            connect_args={"check_same_thread": False},
            future=True,
        )

        @event.listens_for(eng, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.close()

        if db_path is None:
            _ENGINE = eng
        return eng
    return _ENGINE


def open_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with Row access and foreign keys enabled."""
    con = sqlite3.connect(str(db_path or DB_PATH), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency yielding a managed SQLite connection."""
    con = open_connection()
    try:
        yield con
    finally:
        con.close()


WEB_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vitalverse_id TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('astronaut', 'doctor')),
    astronaut_id TEXT UNIQUE REFERENCES astronaut_profile(astronaut_id),
    legacy_user_id TEXT UNIQUE,
    display_name TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS web_sessions (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS uploaded_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_astronaut_id TEXT NOT NULL REFERENCES astronaut_profile(astronaut_id),
    uploaded_by_user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('image', 'audio')),
    mime_type TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    storage_relpath TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS astronaut_playlist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    astronaut_id TEXT NOT NULL REFERENCES astronaut_profile(astronaut_id),
    title TEXT NOT NULL,
    tag TEXT NOT NULL CHECK (tag IN ('comfort', 'happy', 'energy')),
    kind TEXT NOT NULL CHECK (kind IN ('audio', 'link')),
    url TEXT,
    upload_id INTEGER REFERENCES uploaded_files(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS astronaut_photo_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    astronaut_id TEXT NOT NULL REFERENCES astronaut_profile(astronaut_id),
    tag TEXT NOT NULL CHECK (tag IN ('comfort', 'happy', 'energy')),
    upload_id INTEGER REFERENCES uploaded_files(id),
    url TEXT,
    caption TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doctor_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    staff_id TEXT NOT NULL,
    full_name TEXT NOT NULL,
    specialization TEXT NOT NULL,
    organization TEXT NOT NULL,
    contact TEXT DEFAULT '',
    credential TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doctor_astronaut_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    astronaut_id TEXT NOT NULL REFERENCES astronaut_profile(astronaut_id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'declined', 'revoked')),
    mission_crew_note TEXT DEFAULT '',
    consent_confirmed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE(doctor_user_id, astronaut_id)
);

CREATE TABLE IF NOT EXISTS daily_todo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    astronaut_id TEXT NOT NULL REFERENCES astronaut_profile(astronaut_id),
    todo_date TEXT NOT NULL,
    item_key TEXT NOT NULL,
    label TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(astronaut_id, todo_date, item_key)
);

CREATE TABLE IF NOT EXISTS mood_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    astronaut_id TEXT NOT NULL REFERENCES astronaut_profile(astronaut_id),
    checkin_date TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    score REAL NOT NULL,
    recommended_tag TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(astronaut_id, checkin_date)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    astronaut_id TEXT NOT NULL REFERENCES astronaut_profile(astronaut_id),
    mission_day INTEGER,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'danger-confirm', 'danger')),
    source TEXT NOT NULL CHECK (source IN ('model', 'mood', 'access')),
    short_message TEXT NOT NULL,
    detailed_explanation_json TEXT NOT NULL,
    read_at TEXT,
    acknowledged_at TEXT,
    acknowledged_by_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint TEXT UNIQUE NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_rate_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_email TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS online_chat_rate_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rate_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_online_chat_rate_key_time
    ON online_chat_rate_limits(rate_key, created_at);
"""


def init_web_tables(con: sqlite3.Connection | None = None) -> None:
    """Create additive web tables in the working app DB without modifying existing ML tables."""
    own_con = con is None
    if con is None:
        con = open_connection()
    try:
        con.executescript(WEB_SCHEMA_SQL)
        cols = {str(r["name"]) for r in con.execute("PRAGMA table_info(astronaut_profile)").fetchall()}
        if "profile_avatar" not in cols:
            con.execute("ALTER TABLE astronaut_profile ADD COLUMN profile_avatar TEXT")
        con.commit()
    finally:
        if own_con:
            con.close()
