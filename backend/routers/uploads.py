"""Authenticated file uploads (images re-encoded with Pillow <=5MB, audio <=15MB) stored privately outside static/."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.config import UPLOADS_DIR
from backend.database import get_db
from backend.security import require_csrf, require_user, resolve_authorized_astronaut_id

router = APIRouter(tags=["uploads"])

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_AUDIO_BYTES = 15 * 1024 * 1024
ALLOWED_AUDIO_EXTS = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}
ALLOWED_TAGS = {"comfort", "happy", "energy"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@router.post("/api/uploads/{astronaut_id}")
async def upload_astronaut_media(
    astronaut_id: str,
    purpose: str = Form(default="photo"),
    tag: str = Form(default="comfort"),
    title: str = Form(default=""),
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Validate and save uploaded image/audio into uploads_private/{astronaut_id}/ for authorized users."""
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    if purpose not in {"profile_photo", "photo", "song_audio"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported upload purpose.")
    clean_tag = tag.strip().lower()
    if clean_tag not in ALLOWED_TAGS:
        clean_tag = "comfort"

    raw = await file.read()
    orig_name = Path(file.filename or "upload").name
    dest_dir = UPLOADS_DIR / aid
    dest_dir.mkdir(parents=True, exist_ok=True)
    now = _utc_now()

    if purpose in {"profile_photo", "photo"}:
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image exceeds 5 MB limit.")
        try:
            with Image.open(io.BytesIO(raw)) as img:
                img = ImageOps.exif_transpose(img)
                has_alpha = "A" in img.getbands()
                img_conv = img.convert("RGBA" if has_alpha else "RGB")
                out_buf = io.BytesIO()
                img_conv.save(out_buf, format="PNG")
                clean_bytes = out_buf.getvalue()

                w, h = img_conv.size
                side = min(w, h)
                left = (w - side) // 2
                top = (h - side) // 2
                square = img_conv.crop((left, top, left + side, top + side))
                avatar_img = square.resize((256, 256), Image.Resampling.LANCZOS)
                av_buf = io.BytesIO()
                avatar_img.save(av_buf, format="WEBP", quality=90)
                avatar_bytes = av_buf.getvalue()
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or corrupt image file.") from exc

        fname = f"{uuid.uuid4().hex}.png"
        rel = f"{aid}/{fname}"
        (dest_dir / fname).write_bytes(clean_bytes)
        digest = hashlib.sha256(clean_bytes).hexdigest()

        cur = con.execute(
            """
            INSERT INTO uploaded_files (
                owner_astronaut_id, uploaded_by_user_id, kind, mime_type,
                original_filename, storage_relpath, byte_size, sha256, created_at
            ) VALUES (?, ?, 'image', 'image/png', ?, ?, ?, ?, ?)
            """,
            (aid, int(user["user_id"]), orig_name, rel, len(clean_bytes), digest, now),
        )
        upload_id = int(cur.lastrowid)
        if purpose == "profile_photo":
            av_fname = f"{uuid.uuid4().hex}_avatar_256.webp"
            av_rel = f"{aid}/{av_fname}"
            (dest_dir / av_fname).write_bytes(avatar_bytes)
            av_digest = hashlib.sha256(avatar_bytes).hexdigest()
            av_cur = con.execute(
                """
                INSERT INTO uploaded_files (
                    owner_astronaut_id, uploaded_by_user_id, kind, mime_type,
                    original_filename, storage_relpath, byte_size, sha256, created_at
                ) VALUES (?, ?, 'image', 'image/webp', ?, ?, ?, ?, ?)
                """,
                (aid, int(user["user_id"]), f"{Path(orig_name).stem}_avatar_256.webp", av_rel, len(avatar_bytes), av_digest, now),
            )
            avatar_upload_id = int(av_cur.lastrowid)
            con.execute(
                "UPDATE astronaut_profile SET profile_photo = ?, profile_avatar = ? WHERE astronaut_id = ?",
                (f"/api/media/{upload_id}", f"/api/media/{avatar_upload_id}", aid),
            )
            con.commit()
            return {
                "ok": True,
                "upload_id": upload_id,
                "url": f"/api/media/{upload_id}",
                "avatar_upload_id": avatar_upload_id,
                "avatar_url": f"/api/media/{avatar_upload_id}",
            }

        con.execute(
            """
            INSERT INTO astronaut_photo_items (astronaut_id, tag, upload_id, url, caption, created_at)
            VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (aid, clean_tag, upload_id, Path(orig_name).stem, now),
        )
        con.commit()
        return {"ok": True, "upload_id": upload_id, "url": f"/api/media/{upload_id}"}

    ext = Path(orig_name).suffix.lower()
    mime = ALLOWED_AUDIO_EXTS.get(ext)
    if not mime:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .mp3, .m4a, and .wav audio files are allowed.")
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Audio file exceeds 15 MB limit.")

    fname = f"{uuid.uuid4().hex}{ext}"
    rel = f"{aid}/{fname}"
    (dest_dir / fname).write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()

    cur = con.execute(
        """
        INSERT INTO uploaded_files (
            owner_astronaut_id, uploaded_by_user_id, kind, mime_type,
            original_filename, storage_relpath, byte_size, sha256, created_at
        ) VALUES (?, ?, 'audio', ?, ?, ?, ?, ?, ?)
        """,
        (aid, int(user["user_id"]), mime, orig_name, rel, len(raw), digest, now),
    )
    upload_id = int(cur.lastrowid)
    con.execute(
        """
        INSERT INTO astronaut_playlist_items (astronaut_id, title, tag, kind, url, upload_id, created_at)
        VALUES (?, ?, ?, 'audio', NULL, ?, ?)
        """,
        (aid, title.strip() or Path(orig_name).stem, clean_tag, upload_id, now),
    )
    con.commit()
    return {"ok": True, "upload_id": upload_id, "url": f"/api/media/{upload_id}"}


@router.get("/api/media/{upload_id}")
def serve_private_media(
    upload_id: int,
    user: dict[str, Any] = Depends(require_user),
    con: sqlite3.Connection = Depends(get_db),
):
    """Stream private uploaded media strictly to the owning astronaut or approved doctor."""
    row = con.execute("SELECT * FROM uploaded_files WHERE id = ?", (upload_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media item not found.")
    resolve_authorized_astronaut_id(con, user, str(row["owner_astronaut_id"]))
    file_path = (UPLOADS_DIR / row["storage_relpath"]).resolve()
    if not str(file_path).startswith(str(UPLOADS_DIR.resolve())) or not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file missing on disk.")
    return FileResponse(
        file_path,
        media_type=row["mime_type"],
        headers={"Cache-Control": "private, no-store"},
    )
