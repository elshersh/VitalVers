"""
tools/build_hf_space.py - build the Hugging Face Space folder from the clean GitHub export.

    python tools/build_hf_space.py "D:/VitalVers" "D:/VitalVers-space"

Copies only what the web app needs at runtime, adds the Space README (YAML header that tells Hugging Face
to build the Dockerfile) and a .gitattributes that stores binary files with Git LFS, as Hugging Face requires.
Keeps the target's .git folder so it can be pushed again after changes.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

RUNTIME = [
    "app.py", "ai_health_model.py", "health_engine.py", "offline_ai_chatbot.py", "resource_facts.py", "generate_data.py",
    "requirements.txt", "Dockerfile", ".dockerignore", ".env.example",
    "backend", "static", "config", "models", "scripts", "references", "uploads_private",
    "data/astronaut_health_app.db", "data_raw/team_supplied/07_health_indicators_schema.json",
]
LFS_PATTERNS = ["*.db", "*.joblib", "*.png", "*.jpg", "*.jpeg", "*.ico", "*.wav", "*.woff2", "*.pdf"]

README = """---
title: Vitalverse
emoji: 🚀
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: AI health monitoring for astronauts (NASA Space Apps 2026)
---

# Vitalverse: AI health monitoring for astronauts

Prototype for the NASA Space Apps Challenge 2026. Built with fictional, simulated data;
not a certified medical device.

Source code and full documentation: https://github.com/elshersh/VitalVers

Demo logins: astronaut `VTA-DEMO01` / `DemoAstro#2026`, flight surgeon `VTD-DEMO01` / `DemoDoctor#2026`.
"""


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    dst.mkdir(parents=True, exist_ok=True)
    for item in dst.iterdir():
        if item.name == ".git":
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    for rel in RUNTIME:
        s, d = src / rel, dst / rel
        if s.is_dir():
            shutil.copytree(s, d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif s.is_file():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
        else:
            print("missing:", rel)
    (dst / "README.md").write_text(README, encoding="utf-8")
    (dst / ".gitattributes").write_text("".join(f"{p} filter=lfs diff=lfs merge=lfs -text\n" for p in LFS_PATTERNS),
                                        encoding="utf-8")
    (dst / ".gitignore").write_text(".env\n__pycache__/\n*.pyc\n", encoding="utf-8")
    total = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file() and ".git" not in f.parts)
    print(f"space folder ready: {dst} ({total / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
