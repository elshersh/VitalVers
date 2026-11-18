"""Seed official argon2-cffi password hashes and web demo records into data/astronaut_health_app.db.

Never modifies data/astronaut_health_eval.db (the SHA-256-sealed evaluation database).
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import shutil
import sqlite3
import struct
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image, ImageDraw

from backend.config import DB_PATH, DEMO_CREDS_PATH, UPLOADS_DIR, load_demo_credentials
from backend.database import init_web_tables, open_connection
from backend.security import hash_password


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rehash_legacy_auth_users(con: sqlite3.Connection, cfg: dict) -> int:
    """Re-create password hashes in auth_users using official argon2-cffi."""
    rule = cfg.get("astronaut_credential_rule", {})
    fmt = rule.get("format", "PIN-{astronaut_id}")
    overrides = rule.get("overrides", {})

    updated = 0
    rows = con.execute("SELECT user_id, role FROM auth_users ORDER BY user_id ASC").fetchall()
    fs_map = {str(fs["user_id"]): str(fs["credential"]) for fs in cfg.get("flight_surgeons", [])}

    for r in rows:
        uid = str(r["user_id"])
        if uid in fs_map:
            cred = fs_map[uid]
        elif uid in overrides:
            cred = str(overrides[uid])
        else:
            cred = fmt.format(astronaut_id=uid)
        con.execute(
            "UPDATE auth_users SET password_hash = ?, failed_attempts = 0, locked_until = NULL WHERE user_id = ?",
            (hash_password(cred), uid),
        )
        updated += 1
    return updated


def _upsert_web_user(
    con: sqlite3.Connection,
    *,
    vitalverse_id: str,
    email: str,
    password: str,
    role: str,
    astronaut_id: str | None,
    legacy_user_id: str | None,
    display_name: str,
) -> int:
    now = _utc_now()
    pw_hash = hash_password(password)
    existing = con.execute("SELECT id FROM users WHERE vitalverse_id = ?", (vitalverse_id,)).fetchone()
    if existing:
        con.execute(
            """
            UPDATE users
            SET email = ?, password_hash = ?, role = ?, astronaut_id = ?, legacy_user_id = ?,
                display_name = ?, failed_attempts = 0, locked_until = NULL
            WHERE id = ?
            """,
            (email, pw_hash, role, astronaut_id, legacy_user_id, display_name, int(existing["id"])),
        )
        return int(existing["id"])

    cur = con.execute(
        """
        INSERT INTO users (
            vitalverse_id, email, password_hash, role, astronaut_id, legacy_user_id,
            display_name, failed_attempts, locked_until, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)
        """,
        (vitalverse_id, email, pw_hash, role, astronaut_id, legacy_user_id, display_name, now),
    )
    return int(cur.lastrowid)


def _write_demo_png(dest: Path, bg_rgb: tuple[int, int, int], accent_rgb: tuple[int, int, int], label: str) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (640, 420), bg_rgb)
    draw = ImageDraw.Draw(img)
    for y in range(0, 420, 28):
        draw.line([(0, y), (640, y)], fill=(min(255, bg_rgb[0] + 10), min(255, bg_rgb[1] + 14), min(255, bg_rgb[2] + 18)), width=1)
    draw.ellipse([180, 75, 460, 355], outline=accent_rgb, width=4)
    draw.ellipse([235, 130, 405, 300], fill=accent_rgb)
    draw.text((24, 24), f"Vitalverse Demo Media - {label}", fill=(240, 246, 252))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    dest.write_bytes(data)
    return len(data), hashlib.sha256(data).hexdigest()


def _write_demo_wav(dest: Path, freq_hz: float, duration_s: float = 1.5) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 16000
    n_samples = int(sample_rate * duration_s)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_samples):
            env = min(1.0, i / 1600.0) * min(1.0, (n_samples - i) / 1600.0)
            val = int(6000 * env * math.sin(2.0 * math.pi * freq_hz * (i / sample_rate)))
            frames += struct.pack("<h", val)
        wf.writeframes(bytes(frames))
    data = buf.getvalue()
    dest.write_bytes(data)
    return len(data), hashlib.sha256(data).hexdigest()


def _seed_demo_media_and_alerts(con: sqlite3.Connection, astro_user_id: int, astronaut_id: str) -> None:
    now = _utc_now()
    tag_specs = [
        ("comfort", "Orbital Horizon Dawn", "Earthlight Ambient", (14, 26, 40), (168, 224, 122), 261.63),
        ("happy", "Crew Reunion Portrait", "Zero-G Uplift", (22, 34, 48), (110, 200, 240), 329.63),
        ("energy", "EVA Thruster Warmup", "Solar Array Pulse", (30, 24, 38), (245, 196, 81), 392.00),
    ]

    for tag, caption, song_title, bg_rgb, acc_rgb, freq in tag_specs:
        has_song = con.execute(
            "SELECT id FROM astronaut_playlist_items WHERE astronaut_id = ? AND tag = ? AND title = ?",
            (astronaut_id, tag, song_title),
        ).fetchone()
        if not has_song:
            rel_audio = f"{astronaut_id}/demo_{tag}.wav"
            size_a, sha_a = _write_demo_wav(UPLOADS_DIR / rel_audio, freq)
            cur_u = con.execute(
                """
                INSERT INTO uploaded_files (
                    owner_astronaut_id, uploaded_by_user_id, kind, mime_type,
                    original_filename, storage_relpath, byte_size, sha256, created_at
                ) VALUES (?, ?, 'audio', 'audio/wav', ?, ?, ?, ?, ?)
                """,
                (astronaut_id, astro_user_id, f"demo_{tag}.wav", rel_audio, size_a, sha_a, now),
            )
            con.execute(
                """
                INSERT INTO astronaut_playlist_items (
                    astronaut_id, title, tag, kind, url, upload_id, created_at
                ) VALUES (?, ?, ?, 'audio', NULL, ?, ?)
                """,
                (astronaut_id, song_title, tag, int(cur_u.lastrowid), now),
            )

        has_photo = con.execute(
            "SELECT id FROM astronaut_photo_items WHERE astronaut_id = ? AND tag = ? AND caption = ?",
            (astronaut_id, tag, caption),
        ).fetchone()
        if not has_photo:
            rel_img = f"{astronaut_id}/demo_{tag}.png"
            size_i, sha_i = _write_demo_png(UPLOADS_DIR / rel_img, bg_rgb, acc_rgb, caption)
            cur_u = con.execute(
                """
                INSERT INTO uploaded_files (
                    owner_astronaut_id, uploaded_by_user_id, kind, mime_type,
                    original_filename, storage_relpath, byte_size, sha256, created_at
                ) VALUES (?, ?, 'image', 'image/png', ?, ?, ?, ?, ?)
                """,
                (astronaut_id, astro_user_id, f"demo_{tag}.png", rel_img, size_i, sha_i, now),
            )
            con.execute(
                """
                INSERT INTO astronaut_photo_items (
                    astronaut_id, tag, upload_id, url, caption, created_at
                ) VALUES (?, ?, ?, NULL, ?, ?)
                """,
                (astronaut_id, tag, int(cur_u.lastrowid), caption, now),
            )

    existing_alerts = con.execute("SELECT COUNT(*) FROM alerts WHERE astronaut_id = ?", (astronaut_id,)).fetchone()[0]
    if existing_alerts == 0:
        tel = con.execute(
            "SELECT mission_day, heart_rate, systolic_bp, diastolic_bp, temperature FROM mission_telemetry WHERE astronaut_id = ? ORDER BY mission_day DESC LIMIT 1",
            (astronaut_id,),
        ).fetchone()
        latest_day = int(tel["mission_day"]) if tel else 180
        details = json.dumps(
            {
                "astronaut_id": astronaut_id,
                "mission_day": latest_day,
                "summary": "Routine end-of-cycle health model verification on onboard telemetry.",
                "heart_rate": round(float(tel["heart_rate"]), 1) if tel else None,
                "systolic_bp": round(float(tel["systolic_bp"]), 1) if tel else None,
            }
        )
        con.execute(
            """
            INSERT INTO alerts (
                astronaut_id, mission_day, severity, source, short_message,
                detailed_explanation_json, read_at, acknowledged_at, acknowledged_by_user_id, created_at
            ) VALUES (?, ?, 'info', 'model', ?, ?, NULL, NULL, NULL, ?)
            """,
            (
                astronaut_id,
                latest_day,
                f"Mission day {latest_day} model sync complete — telemetry monitoring active.",
                details,
                now,
            ),
        )


def seed_all(db_path: Path | None = None) -> dict[str, int]:
    """Run full idempotent database seeding with official argon2-cffi hashes."""
    if not DEMO_CREDS_PATH.is_file():
        raise FileNotFoundError(f"Missing {DEMO_CREDS_PATH}")
    cfg = load_demo_credentials()
    web = cfg.get("web_demo_accounts", {})
    if not web:
        raise ValueError("demo_credentials.json missing 'web_demo_accounts'")

    con = open_connection(db_path or DB_PATH)
    try:
        init_web_tables(con)
        auth_count = _rehash_legacy_auth_users(con, cfg)

        astro = web["astronaut"]
        astro_uid = _upsert_web_user(
            con,
            vitalverse_id=astro["vitalverse_id"],
            email=astro["email"],
            password=astro["password"],
            role="astronaut",
            astronaut_id=astro["astronaut_id"],
            legacy_user_id=astro["astronaut_id"],
            display_name=astro["display_name"],
        )

        # Also reset any stale sessions so re-seeded credentials take effect cleanly.
        now = _utc_now()
        doc1 = web["approved_doctor"]
        doc1_uid = _upsert_web_user(
            con,
            vitalverse_id=doc1["vitalverse_id"],
            email=doc1["email"],
            password=doc1["password"],
            role="doctor",
            astronaut_id=None,
            legacy_user_id=doc1.get("legacy_user_id"),
            display_name=doc1["display_name"],
        )
        con.execute(
            """
            INSERT INTO doctor_profiles (user_id, staff_id, full_name, specialization, organization, contact, credential, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              staff_id = excluded.staff_id,
              full_name = excluded.full_name,
              specialization = excluded.specialization,
              organization = excluded.organization
            """,
            (doc1_uid, doc1["staff_id"], doc1["display_name"], doc1["specialization"], doc1["organization"], doc1["email"], "DEMO-APPROVED", now),
        )
        con.execute(
            """
            INSERT INTO doctor_astronaut_links (doctor_user_id, astronaut_id, status, mission_crew_note, consent_confirmed, created_at, decided_at)
            VALUES (?, ?, 'approved', 'Seeded approved flight surgeon link (demo)', 1, ?, ?)
            ON CONFLICT(doctor_user_id, astronaut_id) DO UPDATE SET
              status = 'approved',
              consent_confirmed = 1,
              decided_at = excluded.decided_at
            """,
            (doc1_uid, doc1["linked_astronaut_id"], now, now),
        )

        doc2 = web["pending_doctor"]
        doc2_uid = _upsert_web_user(
            con,
            vitalverse_id=doc2["vitalverse_id"],
            email=doc2["email"],
            password=doc2["password"],
            role="doctor",
            astronaut_id=None,
            legacy_user_id=doc2.get("legacy_user_id"),
            display_name=doc2["display_name"],
        )
        con.execute(
            """
            INSERT INTO doctor_profiles (user_id, staff_id, full_name, specialization, organization, contact, credential, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              staff_id = excluded.staff_id,
              full_name = excluded.full_name,
              specialization = excluded.specialization,
              organization = excluded.organization
            """,
            (doc2_uid, doc2["staff_id"], doc2["display_name"], doc2["specialization"], doc2["organization"], doc2["email"], "DEMO-PENDING", now),
        )
        con.execute(
            """
            INSERT INTO doctor_astronaut_links (doctor_user_id, astronaut_id, status, mission_crew_note, consent_confirmed, created_at, decided_at)
            VALUES (?, ?, 'pending', 'Seeded pending review request (demo)', 0, ?, NULL)
            ON CONFLICT(doctor_user_id, astronaut_id) DO UPDATE SET
              status = 'pending',
              consent_confirmed = 0,
              decided_at = NULL
            """,
            (doc2_uid, doc2["linked_astronaut_id"], now),
        )

        _seed_demo_media_and_alerts(con, astro_uid, astro["astronaut_id"])
        con.commit()
        return {"rehashed_auth_users": auth_count, "web_users": 3}
    finally:
        con.close()


if __name__ == "__main__":
    summary = seed_all()
    print(f"Seeded successfully with official argon2-cffi: {summary}")
