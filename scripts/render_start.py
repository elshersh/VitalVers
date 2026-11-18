"""Start Vitalverse on a hosting platform (Render, Docker, ...).

The app reads API keys only from a local .env file, never from the process environment (a deliberate rule
checked by the tests). On a host, the keys live in the platform's secret settings, so this script copies the
relevant ones into a private .env file at start-up, then starts the web server on the port the host gives us.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYS = (
    "ONLINE_PROVIDER", "GEMINI_API_KEY", "GEMINI_MODEL",
    "ANTHROPIC_API_KEY", "CLAUDE_MODEL", "GROQ_API_KEY", "GROQ_MODEL",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM",
    "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT",
)


def write_env() -> None:
    values = {k: os.environ[k].strip() for k in KEYS if os.environ.get(k, "").strip()}
    if not values:
        print("render_start: no API keys in the environment; the online assistant will stay off.", flush=True)
        return
    env_path = ROOT / ".env"
    lines = [f"{k}={v}" for k, v in values.items() if "\n" not in v]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass
    print("render_start: wrote .env with " + ", ".join(sorted(values)), flush=True)   # names only, never values


def main() -> None:
    os.chdir(ROOT)
    write_env()
    port = os.environ.get("PORT", "10000")
    os.environ.setdefault("FORWARDED_ALLOW_IPS", "*")    # trust the host's HTTPS proxy headers
    args = [sys.executable, "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", port, "--proxy-headers"]
    if os.name == "nt":                      # Windows: execv does not quote paths with spaces
        import subprocess
        sys.exit(subprocess.call(args))
    os.execv(sys.executable, args)


if __name__ == "__main__":
    main()
