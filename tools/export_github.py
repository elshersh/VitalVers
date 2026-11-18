"""
tools/export_github.py - build a clean, publishable copy of the project for GitHub + Render.

    python tools/export_github.py "D:/VitalVers"

What it does
  * copies the project (code, website, model, data, tests, docs) into the target folder, keeping its .git
  * leaves out secrets (.env), the virtual environment, caches, screenshots, old frontend copies, code dumps
  * leaves out real users' uploads (only the seeded demo media in uploads_private/A001/demo_* is kept)
  * scrubs a copy of data/astronaut_health_app.db: only the fictional astronauts A001-A200 and the three demo
    web accounts remain; every login session and rate-limit row is removed
  * redacts a third-party public API key that appears in a saved copy of the challenge web page
  * writes the README: repository intro + the full project documentation
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent

EXCLUDE_DIRS = {".git", ".venv", ".pytest_cache", "__pycache__", "screenshots", "frontend_extra", "uploads_private", ".claude", "deploy"}
EXCLUDE_FILES = {
    ".env", "ALL_PROJECT_CODES.txt", "AI_CHATBOT_CODE.txt", "AI_MODEL_CODE.txt",
    "Astronaut_AI_Health_Monitoring_Guide.pdf", "README.md",
}
EXCLUDE_REL = {"data/astronaut_health.db"}            # empty placeholder
DOCS_FROM_ROOT: set = set()                            # reports stay at the root (tests check them there)
MAX_BYTES = 95 * 1024 * 1024                           # GitHub hard limit is 100 MB per file
DEMO_USER_IDS = (1, 2, 3)                              # VTA-DEMO01, VTD-DEMO01, VTD-DEMO02
KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{35}")


def clean_target(dst: Path) -> None:
    for item in dst.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def copy_tree(dst: Path) -> list[str]:
    skipped = []
    for path in SRC.rglob("*"):
        rel = path.relative_to(SRC)
        parts = rel.parts
        if any(p in EXCLUDE_DIRS for p in parts):
            continue
        if path.is_dir():
            continue
        rel_posix = rel.as_posix()
        if len(parts) == 1 and rel.name in EXCLUDE_FILES:
            continue
        if rel_posix in EXCLUDE_REL or path.suffix in (".pyc", ".pyo"):
            continue
        if path.stat().st_size > MAX_BYTES:
            skipped.append(f"{rel_posix} (too large)")
            continue
        target = dst / ("docs/" + rel.name if len(parts) == 1 and rel.name in DOCS_FROM_ROOT else rel_posix)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    # project README becomes docs/PROJECT_README.md
    # README = the repository intro (live link, quick start, deploy) + the full project documentation
    intro = (SRC / "deploy" / "README.md").read_text(encoding="utf-8") if (SRC / "deploy" / "README.md").is_file() else ""
    full = (SRC / "README.md").read_text(encoding="utf-8")
    (dst / "README.md").write_text(intro.rstrip() + "\n\n---\n\n# Full project documentation\n\n" + full, encoding="utf-8")
    gi = dst / ".gitignore"
    extra = "\n# local test output\nscreenshots/\ndeploy/\n"
    gi.write_text(gi.read_text(encoding="utf-8").rstrip() + "\n" + extra, encoding="utf-8")
    # seeded demo media only
    for media in sorted((SRC / "uploads_private" / "A001").glob("demo_*")):
        if media.suffix in (".png", ".wav"):
            t = dst / "uploads_private" / "A001" / media.name
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(media, t)
    return skipped


def scrub_db(db: Path) -> dict:
    con = sqlite3.connect(db)
    q = ",".join("?" * len(DEMO_USER_IDS))
    real = [r[0] for r in con.execute("SELECT astronaut_id FROM astronaut_profile WHERE astronaut_id NOT GLOB 'A[0-9][0-9][0-9]'")]
    aq = ",".join("?" * len(real)) or "''"
    cur = con.cursor()
    removed = {}

    def run(label, sql, params=()):
        cur.execute(sql, params)
        removed[label] = removed.get(label, 0) + cur.rowcount

    if real:
        run("model_predictions", f"DELETE FROM model_predictions WHERE record_id IN (SELECT record_id FROM mission_telemetry WHERE astronaut_id IN ({aq}))", real)
        run("telemetry_labels", f"DELETE FROM telemetry_labels WHERE record_id IN (SELECT record_id FROM mission_telemetry WHERE astronaut_id IN ({aq}))", real)
        for t in ("mission_telemetry", "preflight_baseline", "astronaut_profile", "daily_todo", "mood_checkins", "alerts",
                  "astronaut_playlist_items", "astronaut_photo_items", "doctor_astronaut_links"):
            run(t, f"DELETE FROM {t} WHERE astronaut_id IN ({aq})", real)
        run("uploaded_files", f"DELETE FROM uploaded_files WHERE owner_astronaut_id IN ({aq})", real)
    run("users", f"DELETE FROM users WHERE id NOT IN ({q})", DEMO_USER_IDS)
    run("doctor_profiles", f"DELETE FROM doctor_profiles WHERE user_id NOT IN ({q})", DEMO_USER_IDS)
    run("doctor_astronaut_links", f"DELETE FROM doctor_astronaut_links WHERE doctor_user_id NOT IN ({q})", DEMO_USER_IDS)
    run("uploaded_files", f"DELETE FROM uploaded_files WHERE uploaded_by_user_id IS NOT NULL AND uploaded_by_user_id NOT IN ({q})", DEMO_USER_IDS)
    run("mood_checkins", "DELETE FROM mood_checkins")                 # free-text answers typed while testing
    for t in ("web_sessions", "auth_sessions", "push_subscriptions", "email_rate_limits", "online_chat_rate_limits"):
        run(t, f"DELETE FROM {t}")
    run("alerts (read state reset)", "UPDATE alerts SET read_at = NULL, acknowledged_at = NULL, acknowledged_by_user_id = NULL")
    con.commit()
    con.execute("VACUUM")
    left = {
        "users": [r[0] for r in con.execute("SELECT vitalverse_id FROM users ORDER BY id")],
        "non_fictional_astronauts": con.execute("SELECT COUNT(*) FROM astronaut_profile WHERE astronaut_id NOT GLOB 'A[0-9][0-9][0-9]'").fetchone()[0],
        "uploads": [r[0] for r in con.execute("SELECT storage_relpath FROM uploaded_files")],
    }
    con.close()
    return {"removed_astronauts": real, "rows_removed": removed, "left": left}


def redact_keys(dst: Path) -> list[str]:
    hits = []
    for path in dst.rglob("*"):
        if ".git" in path.parts or not path.is_file() or path.suffix.lower() not in (".txt", ".json", ".md", ".html", ".csv", ".py", ".js"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if KEY_PATTERN.search(text):
            path.write_text(KEY_PATTERN.sub("REDACTED_PUBLIC_KEY", text), encoding="utf-8")
            hits.append(path.relative_to(dst).as_posix())
    return hits


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    dst = Path(sys.argv[1]).resolve()
    if not (dst / ".git").is_dir():
        print(f"{dst} is not a git clone")
        return 2
    clean_target(dst)
    skipped = copy_tree(dst)
    report = scrub_db(dst / "data" / "astronaut_health_app.db")
    redacted = redact_keys(dst)
    print("copied to", dst)
    print("skipped:", skipped or "none")
    print("db scrub:", report)
    print("redacted third-party keys in:", redacted or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
