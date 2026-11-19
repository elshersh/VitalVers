"""Application configuration and filesystem paths for Vitalverse."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
STATIC_DIR = PROJECT_ROOT / "static"
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"
CONFIG_DIR = PROJECT_ROOT / "config"
UPLOADS_DIR = PROJECT_ROOT / "uploads_private"
ONLINE_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "online_system.txt"

DB_PATH = Path(os.environ.get("ASTRO_HEALTH_DB") or (DATA_DIR / "astronaut_health_app.db"))
MODEL_PATH = MODELS_DIR / "health_model.joblib"
SCHEMA_PATH = PROJECT_ROOT / "data_raw" / "team_supplied" / "07_health_indicators_schema.json"
DEMO_CREDS_PATH = CONFIG_DIR / "demo_credentials.json"

# One browser can be signed in to several accounts at once, one per tab (for example an astronaut in one tab
# and a flight surgeon in another). SESSION_COOKIE (HttpOnly) lists this browser's session ids, newest last.
SESSION_COOKIE = "vv_sessions"
# Readable companion: one-way tags of those sessions, same order. Every API answer carries the tag of the
# session it was made for (TAG_HEADER) so the browser can reject answers meant for someone else.
TAG_COOKIE = "vv_tags"
TAG_HEADER = "X-VV-Tag"
ANON_TAG = "anon"
# Each tab says which of this browser's sessions it uses (static/js/fetch-guard.js). Page loads that cannot
# send a header use the ?account= query parameter; without either, the newest session is used.
ACCOUNT_HEADER = "X-VV-Account"
ACCOUNT_PARAM = "account"
# Sign-in and sign-out answers tell the tab which account it uses from now on (a tag, or ANON_TAG).
ACCOUNT_SET_HEADER = "X-VV-Account-Set"
MAX_BROWSER_SESSIONS = 6
LEGACY_COOKIES = ("vv_session", "vv_tag")
CSRF_HEADER = "X-CSRF-Token"
COOKIE_SECURE = os.environ.get("VITALVERSE_COOKIE_SECURE", "0") == "1"

DEFAULT_ONLINE_PROVIDER = "gemini"
# Fast model first (about 1 s); the larger model is tried only if it fails. Measured 2026-11-18:
# gemini-3.5-flash-lite ~1 s, gemini-3.6-flash ~36 s (past ONLINE_TIMEOUT_SECONDS).
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_BACKUP_MODEL = "gemini-3.6-flash"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5-5"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
ONLINE_TIMEOUT_SECONDS = 20
ONLINE_MAX_OUTPUT_TOKENS = 600
ONLINE_RATE_LIMIT_MAX_MESSAGES = 20
ONLINE_RATE_LIMIT_WINDOW_SECONDS = 600


def read_env_var(name: str, default: str = "", *, env_path: Path | None = None, env_only: bool = False) -> str:
    """Read config from .env first; when env_only=True (API keys), read strictly from .env only."""
    path = env_path or ENV_PATH
    if path.is_file():
        values = dotenv_values(path)
        raw = values.get(name)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    if env_only:
        return default
    env_val = os.environ.get(name)
    if env_val is not None and str(env_val).strip():
        return str(env_val).strip()
    return default


def load_demo_credentials() -> dict[str, Any]:
    """Load demo auth configuration and Argon2id parameters."""
    if not DEMO_CREDS_PATH.is_file():
        return {}
    return json.loads(DEMO_CREDS_PATH.read_text(encoding="utf-8"))
