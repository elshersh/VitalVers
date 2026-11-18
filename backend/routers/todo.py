"""Daily routine To-Do checklist routes (/api/todo/*) with automatic per-day reset."""
from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.database import get_db
from backend.security import require_csrf, require_user, resolve_authorized_astronaut_id

router = APIRouter(prefix="/api/todo", tags=["todo"])

DEFAULT_TASKS: list[tuple[str, str]] = [
    ("todo-01", "Personal hygiene"),
    ("todo-02", "Measure vital signs"),
    ("todo-03", "Check overall health condition"),
    ("todo-04", "Eat breakfast"),
    ("todo-05", "Drink water periodically"),
    ("todo-06", "Perform cognitive exercises"),
    ("todo-07", "Eat lunch"),
    ("todo-08", "Track nutritional intake"),
    ("todo-09", "Perform cardio exercise"),
    ("todo-10", "Perform resistance training"),
    ("todo-11", "Perform mobility exercises"),
    ("todo-12", "Monitor physical performance"),
    ("todo-13", "Check hydration status"),
    ("todo-14", "Complete mental health check-in"),
    ("todo-15", "Practice relaxation"),
    ("todo-16", "Communicate with family"),
    ("todo-17", "Eat dinner"),
    ("todo-18", "Review daily health data"),
    ("todo-19", "Record health observations"),
    ("todo-20", "Sleep for 6-8 hours"),
]
TASK_LABELS = dict(DEFAULT_TASKS)


class TodoToggleRequest(BaseModel):
    done: bool


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _build_todo_state(con: sqlite3.Connection, astronaut_id: str, date_str: str) -> dict[str, Any]:
    rows = con.execute(
        "SELECT item_key, done, updated_at FROM daily_todo WHERE astronaut_id = ? AND todo_date = ?",
        (astronaut_id, date_str),
    ).fetchall()
    done_map = {str(r["item_key"]): bool(int(r["done"])) for r in rows}

    items: list[dict[str, Any]] = []
    completed = 0
    for key, label in DEFAULT_TASKS:
        is_done = done_map.get(key, False)
        if is_done:
            completed += 1
        items.append({"key": key, "label": label, "done": is_done})

    total = len(DEFAULT_TASKS)
    percent = round((completed / total) * 100) if total else 0
    return {
        "astronaut_id": astronaut_id,
        "date": date_str,
        "total": total,
        "completed": completed,
        "remaining": total - completed,
        "percent": percent,
        "items": items,
    }


@router.get("/{astronaut_id}")
def get_daily_todo(
    astronaut_id: str,
    user: dict[str, Any] = Depends(require_user),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Return today's routine tasks for an astronaut or an approved doctor (auto-clean per date)."""
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    state = _build_todo_state(con, aid, _today_str())
    state["readonly"] = user["role"] != "astronaut"
    return state


@router.patch("/{astronaut_id}/items/{item_key}")
def toggle_todo_item(
    astronaut_id: str,
    item_key: str,
    payload: TodoToggleRequest,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Toggle completion state for one daily task item (astronaut owner only)."""
    if user["role"] != "astronaut":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owning astronaut can update routine items.")
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    label = TASK_LABELS.get(item_key)
    if label is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown daily task key.")

    today = _today_str()
    now = _now_iso()
    con.execute(
        """
        INSERT INTO daily_todo (astronaut_id, todo_date, item_key, label, done, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(astronaut_id, todo_date, item_key) DO UPDATE SET
            done = excluded.done,
            updated_at = excluded.updated_at
        """,
        (aid, today, item_key, label, 1 if payload.done else 0, now),
    )
    con.commit()
    state = _build_todo_state(con, aid, today)
    state["readonly"] = False
    return state


@router.post("/{astronaut_id}/reset")
def reset_daily_todo(
    astronaut_id: str,
    user: dict[str, Any] = Depends(require_csrf),
    con: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Reset all of today's routine task checkboxes back to incomplete."""
    if user["role"] != "astronaut":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owning astronaut can reset today's checklist.")
    aid = resolve_authorized_astronaut_id(con, user, astronaut_id)
    today = _today_str()
    con.execute(
        "DELETE FROM daily_todo WHERE astronaut_id = ? AND todo_date = ?",
        (aid, today),
    )
    con.commit()
    state = _build_todo_state(con, aid, today)
    state["readonly"] = False
    return state
