"""Comprehensive verification for Tasks 1-4: avatars, online/offline chatbot, privacy, fallback, and 20 gentle-tone tests."""
from __future__ import annotations

import io
import json
import os
import re
import sqlite3
from pathlib import Path
import time

from fastapi.testclient import TestClient
from PIL import Image
from playwright.sync_api import sync_playwright
import pytest

import health_engine as he
import resource_facts as rf
from app import app
from backend import config as cfg
from backend.database import init_web_tables
from backend.services import online_llm
from tests.test_web_and_e2e import _demo_creds, live_server

TASK1_SHOTS = cfg.PROJECT_ROOT / "screenshots" / "task1_avatars"
TASK4_SHOTS = cfg.PROJECT_ROOT / "screenshots" / "task4_chatbot"

_DIAGNOSIS_WORDS_RE = re.compile(
    r"\b(diagnose[sd]?|diagnosis|diagnostic|diabetes|diabetic|hypoglycemia|hyperglycemia|hypertension|infection|disorder)\b",
    re.IGNORECASE,
)


def _make_png_bytes(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (width, height), rgb)
    # Draw contrasting center square so cropping & center orientation are clearly visible in screenshots.
    cx, cy = width // 2, height // 2
    box = min(width, height) // 3
    for y in range(max(0, cy - box), min(height, cy + box)):
        for x in range(max(0, cx - box), min(width, cx + box)):
            img.putpixel((x, y), (168, 224, 122))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _pick_astronaut_by_class(*classes: str) -> str:
    con = sqlite3.connect(cfg.DB_PATH)
    rows = con.execute(
        "SELECT t.astronaut_id, p.predicted_class FROM mission_telemetry t "
        "JOIN model_predictions p ON p.record_id = t.record_id "
        "WHERE t.mission_day = (SELECT MAX(mission_day) FROM mission_telemetry) "
        "ORDER BY t.astronaut_id"
    ).fetchall()
    con.close()
    for aid, cls in rows:
        if cls in classes:
            return str(aid)
    return "A001"


def _strip_footer(answer: str) -> str:
    lines = [
        ln
        for ln in str(answer or "").splitlines()
        if rf.DISCLAIMER not in ln and not ln.strip().startswith("Sources:")
    ]
    return "\n".join(lines).strip()


def _count_numbered_steps(text: str) -> int:
    return len(re.findall(r"(?:^|\s)([1-9])\.[ \t]+\S", text))


def _snapshot_avatar_state(aid: str) -> tuple[str | None, str | None]:
    con = sqlite3.connect(cfg.DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT profile_photo, profile_avatar FROM astronaut_profile WHERE astronaut_id = ?",
        (aid,),
    ).fetchone()
    con.close()
    if not row:
        return None, None
    return row["profile_photo"], row["profile_avatar"]


def _restore_avatar_state(aid: str, orig_photo: str | None, orig_avatar: str | None, upload_ids: list[int]) -> None:
    con = sqlite3.connect(cfg.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(
        "UPDATE astronaut_profile SET profile_photo = ?, profile_avatar = ? WHERE astronaut_id = ?",
        (orig_photo, orig_avatar, aid),
    )
    for uid in upload_ids:
        row = con.execute("SELECT storage_relpath FROM uploaded_files WHERE id = ?", (uid,)).fetchone()
        if row:
            p = (cfg.UPLOADS_DIR / row["storage_relpath"]).resolve()
            if p.is_file():
                p.unlink(missing_ok=True)
        con.execute("DELETE FROM uploaded_files WHERE id = ?", (uid,))
    con.commit()
    con.close()


# ============================================================================== TASK 1
def test_task1_avatar_upload_crops_256_webp_and_keeps_original():
    web = _demo_creds()
    astro = web["astronaut"]
    aid = astro["astronaut_id"]
    orig_photo, orig_avatar = _snapshot_avatar_state(aid)
    created_ids: list[int] = []

    try:
        with TestClient(app) as client:
            r_login = client.post(
                "/api/auth/login",
                json={"vitalverse_id": astro["vitalverse_id"], "password": astro["password"], "role": "astronaut"},
            )
            assert r_login.status_code == 200
            csrf = r_login.json()["csrf_token"]

            for label, dims in (("portrait", (240, 600)), ("landscape", (600, 240))):
                png_bytes = _make_png_bytes(dims[0], dims[1], (38, 86, 132))
                r_up = client.post(
                    f"/api/uploads/{aid}",
                    data={"purpose": "profile_photo"},
                    files={"file": (f"{label}.png", png_bytes, "image/png")},
                    headers={"X-CSRF-Token": csrf},
                )
                assert r_up.status_code == 200, r_up.text
                up = r_up.json()
                created_ids.append(int(up["upload_id"]))
                if up.get("avatar_upload_id"):
                    created_ids.append(int(up["avatar_upload_id"]))

                assert up.get("avatar_upload_id"), "Expected square 256x256 avatar upload id"
                assert up["avatar_url"].endswith(str(up["avatar_upload_id"]))

                # Original keeps original orientation aspect
                r_orig = client.get(up["url"])
                assert r_orig.status_code == 200
                orig_img = Image.open(io.BytesIO(r_orig.content))
                assert orig_img.size == dims

                # Navbar avatar is center-cropped square 256x256 webp
                r_av = client.get(up["avatar_url"])
                assert r_av.status_code == 200
                assert "image/webp" in r_av.headers["content-type"]
                av_img = Image.open(io.BytesIO(r_av.content))
                assert av_img.format == "WEBP"
                assert av_img.size == (256, 256)

                # /api/auth/me uses square navbar avatar, /api/profile/{id} keeps full original + exposes navbar_avatar_url
                me = client.get("/api/auth/me").json()
                assert me["user"]["avatar_url"] == up["avatar_url"]
                prof = client.get(f"/api/profile/{aid}").json()
                assert prof["avatar_url"] == up["url"]
                assert prof["navbar_avatar_url"] == up["avatar_url"]
    finally:
        _restore_avatar_state(aid, orig_photo, orig_avatar, created_ids)


def test_task1_playwright_navbar_avatars_and_screenshots(live_server):
    TASK1_SHOTS.mkdir(parents=True, exist_ok=True)
    web = _demo_creds()
    astro = web["astronaut"]
    aid = astro["astronaut_id"]
    orig_photo, orig_avatar = _snapshot_avatar_state(aid)
    created_ids: list[int] = []
    viewports = [(1440, 900), (1024, 768), (768, 900), (390, 844)]

    try:
        with TestClient(app) as client:
            r_login = client.post(
                "/api/auth/login",
                json={"vitalverse_id": astro["vitalverse_id"], "password": astro["password"], "role": "astronaut"},
            )
            csrf = r_login.json()["csrf_token"]
            tall_up = client.post(
                f"/api/uploads/{aid}",
                data={"purpose": "profile_photo"},
                files={"file": ("tall.png", _make_png_bytes(220, 620, (44, 92, 130)), "image/png")},
                headers={"X-CSRF-Token": csrf},
            ).json()
            wide_up = client.post(
                f"/api/uploads/{aid}",
                data={"purpose": "profile_photo"},
                files={"file": ("wide.png", _make_png_bytes(620, 220, (124, 72, 48)), "image/png")},
                headers={"X-CSRF-Token": csrf},
            ).json()
            for d in (tall_up, wide_up):
                created_ids.append(int(d["upload_id"]))
                if d.get("avatar_upload_id"):
                    created_ids.append(int(d["avatar_upload_id"]))

        # Reset back to no-photo first
        con = sqlite3.connect(cfg.DB_PATH)
        con.execute("UPDATE astronaut_profile SET profile_photo = NULL, profile_avatar = NULL WHERE astronaut_id = ?", (aid,))
        con.commit()
        con.close()

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                ctx = browser.new_context(viewport={"width": 1440, "height": 900})
                page = ctx.new_page()

                # Login via real form
                page.goto(f"{live_server}/login.html", wait_until="networkidle")
                page.fill("#vid", astro["vitalverse_id"])
                page.fill("#pwd", astro["password"])
                page.click("#go")
                page.wait_for_selector("a.go[href='health.html']", timeout=15000)

                states = [
                    ("no_photo", None, None),
                    ("tall_photo", tall_up["url"], tall_up["avatar_url"]),
                    ("wide_photo", wide_up["url"], wide_up["avatar_url"]),
                ]

                for state_name, photo_url, av_url in states:
                    con = sqlite3.connect(cfg.DB_PATH)
                    con.execute(
                        "UPDATE astronaut_profile SET profile_photo = ?, profile_avatar = ? WHERE astronaut_id = ?",
                        (photo_url, av_url, aid),
                    )
                    con.commit()
                    con.close()

                    for page_slug in ("index.html", "about.html"):
                        for vw, vh in viewports:
                            page.set_viewport_size({"width": vw, "height": vh})
                            page.goto(f"{live_server}/{page_slug}", wait_until="networkidle")
                            page.wait_for_timeout(150)

                            metrics = page.evaluate(
                                """() => {
                                  const av = document.getElementById('vvAvatar');
                                  const prof = document.getElementById('profileBtn');
                                  const img = av ? av.querySelector('img') : null;
                                  const avRect = av ? av.getBoundingClientRect() : null;
                                  const imgRect = img ? img.getBoundingClientRect() : null;
                                  const avStyle = av ? getComputedStyle(av) : null;
                                  const imgStyle = img ? getComputedStyle(img) : null;
                                  return {
                                    hasImg: Boolean(img),
                                    imgComplete: img ? img.complete : false,
                                    naturalW: img ? img.naturalWidth : 0,
                                    naturalH: img ? img.naturalHeight : 0,
                                    avW: avRect ? avRect.width : 0,
                                    avH: avRect ? avRect.height : 0,
                                    imgW: imgRect ? imgRect.width : 0,
                                    imgH: imgRect ? imgRect.height : 0,
                                    avRadius: avStyle ? avStyle.borderRadius : '',
                                    avBg: avStyle ? avStyle.backgroundImage : '',
                                    objFit: imgStyle ? imgStyle.objectFit : '',
                                    objPos: imgStyle ? imgStyle.objectPosition : '',
                                    imgDisplay: imgStyle ? imgStyle.display : ''
                                  };
                                }"""
                            )

                            assert abs(metrics["avW"] - metrics["avH"]) <= 0.8, f"Not circular at {page_slug} {vw}px: {metrics}"
                            assert "radial-gradient" in metrics["avBg"]
                            if page_slug == "index.html":
                                expected = vw * 0.025
                                assert abs(metrics["avW"] - expected) <= 1.2, f"Home width mismatch at {vw}: {metrics['avW']} vs {expected}"
                            else:
                                expected = 32.0 if vw <= 700 else 29.0
                                assert abs(metrics["avW"] - expected) <= 0.8, f"Shared width mismatch at {vw}: {metrics['avW']} vs {expected}"

                            if state_name != "no_photo":
                                assert metrics["hasImg"] is True and metrics["naturalW"] == 256 and metrics["naturalH"] == 256
                                assert metrics["objFit"] == "cover"
                                assert metrics["imgDisplay"] == "block"
                                assert abs(metrics["imgW"] - metrics["imgH"]) <= 0.8
                            else:
                                assert metrics["hasImg"] is False

                            # Close-up crop around the profile pill / navbar right cluster (with padding)
                            clip_box = page.evaluate(
                                """() => {
                                  const hdr = document.querySelector('header.nav, header.vv-nav');
                                  const prof = document.getElementById('profileBtn');
                                  const r = (prof || hdr).getBoundingClientRect();
                                  const padX = Math.max(24, Math.round(r.width * 0.4));
                                  const padY = Math.max(14, Math.round(r.height * 0.45));
                                  const x = Math.max(0, Math.floor(r.left - padX));
                                  const y = Math.max(0, Math.floor(r.top - padY));
                                  const w = Math.min(window.innerWidth - x, Math.ceil(r.width + padX * 2));
                                  const h = Math.min(window.innerHeight - y, Math.ceil(r.height + padY * 2));
                                  return { x, y, width: w, height: h };
                                }"""
                            )
                            shot_name = f"{page_slug.replace('.html', '')}_{state_name}_{vw}px.png"
                            page.screenshot(path=str(TASK1_SHOTS / shot_name), clip=clip_box)

                # Broken image fallback keeps radial-gradient circle cleanly without broken icon
                page.set_viewport_size({"width": 1440, "height": 900})
                page.route("**/api/media/*", lambda route: route.abort())
                page.goto(f"{live_server}/about.html", wait_until="domcontentloaded")
                page.wait_for_timeout(400)
                broken_ok = page.evaluate(
                    """() => {
                      const av = document.getElementById('vvAvatar');
                      return av && !av.querySelector('img') && getComputedStyle(av).backgroundImage.includes('radial-gradient');
                    }"""
                )
                assert broken_ok is True
                ctx.close()
            finally:
                browser.close()
    finally:
        _restore_avatar_state(aid, orig_photo, orig_avatar, created_ids)


# ============================================================================== TASK 2
def test_task2_env_and_example_hygiene(tmp_path, monkeypatch):
    gitignore = (cfg.PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert any(line.strip() == ".env" for line in gitignore)

    # Every variable in .env.example must have an empty value
    env_ex = (cfg.PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    found_keys = set()
    for line in env_ex:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        assert "=" in s
        k, v = s.split("=", 1)
        found_keys.add(k)
        assert v == "", f".env.example variable {k} must have an empty value, got {v!r}"
    for req_key in (
        "ONLINE_PROVIDER",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "ANTHROPIC_API_KEY",
        "CLAUDE_MODEL",
        "GROQ_API_KEY",
        "GROQ_MODEL",
    ):
        assert req_key in found_keys

    # Requirements pins official SDKs
    reqs = (cfg.PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    for pkg in ("google-genai==", "anthropic==", "groq=="):
        assert pkg in reqs

    # Online system prompt file matches expected core text
    prompt_txt = cfg.ONLINE_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    assert "You are Vitalverse, a calm and caring health assistant for astronauts on a space mission." in prompt_txt
    assert "Never invent data; if a value is missing, say so." in prompt_txt

    # API keys must NEVER be read from os.environ (strictly .env only)
    empty_env = tmp_path / ".env"
    empty_env.write_text("ONLINE_PROVIDER=gemini\nGEMINI_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "ENV_PATH", empty_env)
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaShouldNotBeReadFromProcessEnv")
    assert cfg.read_env_var("GEMINI_API_KEY", "", env_only=True) == ""

    # Real sentinel in temp .env must NEVER appear in /api/chat/status response
    sentinel = "AIzaTEST_SECRET_KEY_NEVER_LEAK_424242"
    keyed_env = tmp_path / ".env"
    keyed_env.write_text(f"ONLINE_PROVIDER=gemini\nGEMINI_API_KEY={sentinel}\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "ENV_PATH", keyed_env)
    monkeypatch.setattr(online_llm, "check_internet_reachable", lambda **kwargs: True)
    with TestClient(app) as client:
        st = client.get("/api/chat/status")
        assert st.status_code == 200
        assert sentinel not in st.text
        body = st.json()
        assert body["available"] is True
        assert body["button_label"] == "Online"

    # Release whitelist includes runtime prompt + online_llm and excludes .env
    from tools.export_release import collect_whitelist

    items, _warnings = collect_whitelist(cfg.PROJECT_ROOT)
    rels = {rel for _src, rel, _size in items}
    assert "backend/prompts/online_system.txt" in rels
    assert "backend/services/online_llm.py" in rels
    assert ".env" not in rels


def test_task2_privacy_payload_contains_zero_pii():
    con = sqlite3.connect(cfg.DB_PATH)
    con.row_factory = sqlite3.Row
    named = con.execute(
        "SELECT astronaut_id, name, contact_flight_surgeon FROM astronaut_profile "
        "WHERE name NOT LIKE 'Astronaut %' LIMIT 1"
    ).fetchone()
    if named is None:
        named = con.execute(
            "SELECT astronaut_id, name, contact_flight_surgeon FROM astronaut_profile WHERE astronaut_id = 'A001'"
        ).fetchone()
    aid = str(named["astronaut_id"])
    prof_name = str(named["name"])
    expected_fn = prof_name.split()[0]
    summary, meta = online_llm.build_privacy_safe_summary(con, aid)
    con.close()

    assert "Resting heart rate:" in summary
    assert "pre-mission baseline" in summary
    assert meta["first_name"] == expected_fn
    for forbidden in (
        prof_name,
        aid,
        "@",
        str(named["contact_flight_surgeon"]),
        "astronaut_profile",
    ):
        assert forbidden.lower() not in summary.lower(), f"PII leaked into online summary: {forbidden}"
    if expected_fn.lower() != "astronaut":
        assert expected_fn.lower() not in summary.lower(), f"First name leaked into online summary: {expected_fn}"


def test_task2_provider_fallback_chain_and_offline_fallback(tmp_path, monkeypatch):
    temp_env = tmp_path / ".env"
    temp_env.write_text(
        "ONLINE_PROVIDER=gemini\n"
        "GEMINI_API_KEY=AIzaDummyGemini\n"
        "ANTHROPIC_API_KEY=sk-ant-dummy\n"
        "GROQ_API_KEY=gsk_dummy\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "ENV_PATH", temp_env)
    monkeypatch.setattr(online_llm, "check_internet_reachable", lambda **kwargs: True)

    web = _demo_creds()
    astro = web["astronaut"]

    # Case 1: Gemini raises 429, Anthropic succeeds cleanly
    def gemini_429(*args, **kwargs):
        raise RuntimeError("429 RESOURCE_EXHAUSTED quota AIzaDummyGemini")

    def anthropic_ok(*args, **kwargs):
        return (
            "Thanks for checking in. Your resting heart rate today is 94 bpm, about 2% below your pre-mission baseline of 96.1 bpm.\n"
            "Next steps:\n1. Drink a glass of water.\n2. Take 5 quiet breaths."
        )

    monkeypatch.setattr(online_llm, "_call_gemini", gemini_429)
    monkeypatch.setattr(online_llm, "_call_anthropic", anthropic_ok)

    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"vitalverse_id": astro["vitalverse_id"], "password": astro["password"], "role": "astronaut"},
        )
        r = client.post("/api/chat", json={"question": "How is my heart rate?", "engine": "online"})
        assert r.status_code == 200
        data = r.json()
        assert data["engine_used"] == "online"
        assert data["engine_provider"] == "anthropic"
        assert data["engine_label"] == "Claude"
        assert "AIzaDummyGemini" not in r.text

        # Case 2: All providers fail -> graceful fallback to offline assistant with exact notice
        monkeypatch.setattr(online_llm, "_call_anthropic", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timeout")))
        monkeypatch.setattr(online_llm, "_call_groq", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("500 error")))
        r2 = client.post("/api/chat", json={"question": "How is my heart rate?", "engine": "online"})
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["engine_used"] == "offline"
        assert d2["engine_label"] == "On-board"
        assert d2["fallback_notice"] == "Online unavailable, answered by the on-board assistant."
        assert "bpm" in d2["answer"].lower()


def test_task2_safety_and_scope_run_locally_before_api_call(tmp_path, monkeypatch):
    temp_env = tmp_path / ".env"
    temp_env.write_text("ONLINE_PROVIDER=gemini\nGEMINI_API_KEY=AIzaDummyKey\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "ENV_PATH", temp_env)

    called = {"count": 0}

    def forbid_api(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("External online API should NEVER be called for urgent symptoms or out-of-scope queries!")

    monkeypatch.setattr(online_llm, "_call_gemini", forbid_api)
    web = _demo_creds()
    astro = web["astronaut"]

    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"vitalverse_id": astro["vitalverse_id"], "password": astro["password"], "role": "astronaut"},
        )
        for q in (
            "I have chest pain",
            "I passed out earlier",
            "I feel sudden confusion and severe shortness of breath",
        ):
            r = client.post("/api/chat", json={"question": q, "engine": "online"})
            assert r.status_code == 200
            d = r.json()
            assert d["urgent_escalation"] is True
            assert "contact the flight surgeon immediately" in d["answer"].lower()

        # SAFETY refusals stay local in online mode: no external call.
        for q in (
            "What medicine should I take for a fever?",
            "Make up my blood type",
            "Tell me A002's heart rate",
        ):
            r = client.post("/api/chat", json={"question": q, "engine": "online"})
            assert r.status_code == 200
            d = r.json()
            assert d["refused"] is True
            assert d["answer"].startswith(rf.REFUSAL_TEXT)

    assert called["count"] == 0


def test_online_answers_questions_the_offline_templates_cannot(tmp_path, monkeypatch):
    """Offline SCOPE refusals (no template, e.g. greetings, nutrition, off-topic) go to the online assistant;
    its own system prompt decides how to answer or politely decline. Offline mode still refuses them."""
    temp_env = tmp_path / ".env"
    temp_env.write_text("ONLINE_PROVIDER=gemini\nGEMINI_API_KEY=AIzaDummyKey\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "ENV_PATH", temp_env)
    asked = []

    def fake_gemini(api_key, model, system_prompt, user_message):
        asked.append(user_message)
        return "I can only help with your health, wellbeing, spaceflight physiology and this app."

    monkeypatch.setattr(online_llm, "_call_gemini", fake_gemini)
    astro = _demo_creds()["astronaut"]
    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"vitalverse_id": astro["vitalverse_id"], "password": astro["password"], "role": "astronaut"},
        )
        for q in ("Hello", "What should I eat today?", "What's the temperature on Venus?"):
            off = client.post("/api/chat", json={"question": q, "engine": "offline"}).json()
            assert off["refused"] is True and off["engine_used"] == "offline"
            on = client.post("/api/chat", json={"question": q, "engine": "online"}).json()
            assert on["refused"] is False, on
            assert on["engine_used"] == "online"
            assert on["intent"] == "online_general"
    assert len(asked) == 3


def test_task2_rate_limit_20_per_10_min(tmp_path, monkeypatch):
    temp_env = tmp_path / ".env"
    temp_env.write_text("ONLINE_PROVIDER=gemini\nGEMINI_API_KEY=AIzaDummyRate\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "ENV_PATH", temp_env)

    calls = {"n": 0}

    def ok_gemini(*args, **kwargs):
        calls["n"] += 1
        return "Thanks for checking in. Your resting heart rate today is 94 bpm, right near baseline."

    monkeypatch.setattr(online_llm, "_call_gemini", ok_gemini)
    web = _demo_creds()
    astro = web["astronaut"]

    con = sqlite3.connect(cfg.DB_PATH)
    con.execute("DELETE FROM online_chat_rate_limits")
    con.commit()
    con.close()

    try:
        with TestClient(app) as client:
            client.post(
                "/api/auth/login",
                json={"vitalverse_id": astro["vitalverse_id"], "password": astro["password"], "role": "astronaut"},
            )
            for idx in range(20):
                r = client.post("/api/chat", json={"question": "How is my heart rate?", "engine": "online"})
                assert r.status_code == 200
                assert r.json()["engine_used"] == "online", f"Failed at idx {idx}"
                assert r.json()["rate_limited"] is False

            # 21st request triggers friendly local rate-limit fallback without calling Gemini
            r21 = client.post("/api/chat", json={"question": "How is my heart rate?", "engine": "online"})
            assert r21.status_code == 200
            d21 = r21.json()
            assert d21["rate_limited"] is True
            assert d21["engine_used"] == "offline"
            assert "20-message limit" in d21["fallback_notice"]
            assert calls["n"] == 20
    finally:
        con = sqlite3.connect(cfg.DB_PATH)
        con.execute("DELETE FROM online_chat_rate_limits")
        con.commit()
        con.close()


# ============================================================================== TASK 3 (20 TONE TESTS ON BOTH ENGINES)
_TONE_CASES = [
    ("How is my heart rate?", "normal", False),
    ("What is my blood pressure today?", "normal", False),
    ("How is my oxygen saturation?", "normal", False),
    ("How many hours did I sleep last night?", "normal", False),
    ("What is my body temperature now?", "normal", False),
    ("What is my blood glucose reading today?", "normal", False),
    ("How is my bone health holding up?", "normal", False),
    ("How is my muscle strength looking?", "normal", False),
    ("How is my immune system doing?", "normal", False),
    ("What is my cortisol hormone level today?", "normal", False),
    ("Do I have any active alerts today?", "alert", False),
    ("How am I doing overall today?", "alert", False),
    ("I feel stressed today", "mood", True),
    ("I feel lonely", "mood", True),
    ("My mood feels low, what can I do?", "mood", True),
    ("I feel tired and overwhelmed", "mood", True),
    ("Which exercises are left on my to-do list?", "normal", False),
    ("Play something calming to help me relax", "mood", True),
    ("What was my health like on day 50?", "normal", False),
    ("How is my heart rate and sleep, tell me more detail", "detail", False),
]


def _mock_gentle_online_responder(api_key: str, model: str, system_prompt: str, user_message: str) -> str:
    """Synthesizes realistic Gemini responses grounded in user_message (no internet/key required)."""
    q_match = re.search(r"Astronaut question:\n(.+?)\n\n", user_message, re.DOTALL)
    q = (q_match.group(1) if q_match else user_message).lower()
    # Pull an authentic metric line from the PII-free telemetry summary
    metric_lines = re.findall(r"^- (.+)$", user_message, flags=re.MULTILINE)
    chosen = metric_lines[0] if metric_lines else "Resting heart rate: 94 bpm (pre-mission baseline 96.1 bpm)"
    for ml in metric_lines:
        if any(k in q for k in ("sleep",)) and "Sleep duration" in ml:
            chosen = ml
            break
        if any(k in q for k in ("blood pressure", "bp")) and "Systolic blood pressure" in ml:
            chosen = ml
            break
        if "oxygen" in q and "Oxygen saturation" in ml:
            chosen = ml
            break
        if "temperature" in q and "Body temperature" in ml:
            chosen = ml
            break
        if "glucose" in q and "Blood glucose" in ml:
            chosen = ml
            break
        if "bone" in q and "Bone health" in ml:
            chosen = ml
            break
        if "muscle" in q and "Muscle health" in ml:
            chosen = ml
            break
        if "immune" in q and "Immune resilience" in ml:
            chosen = ml
            break
        if "cortisol" in q and "Cortisol" in ml:
            chosen = ml
            break
        if any(k in q for k in ("mood", "stressed", "lonely", "overwhelmed", "relax")) and "Mood score" in ml:
            chosen = ml
            break

    is_mood = any(k in q for k in ("stressed", "lonely", "mood", "overwhelmed", "relax"))
    if is_mood:
        return (
            f"That sounds heavy, and it is understandable to feel this way in orbit. {chosen}.\n"
            "1. Try two minutes of slow box breathing, listen to your calming music, or rest and reach out to crewmates or your flight surgeon — support is always here."
        )
    if "more detail" in q:
        extra = "; ".join(metric_lines[:4])
        return (
            f"Thanks for checking in. Here is your detailed check: {extra}.\n"
            "1. Keep hydration steady throughout your work block.\n"
            "2. Log your scheduled cardio and resistance session.\n"
            "3. Prioritise regular cabin light cues before sleep."
        )
    return (
        f"Thanks for checking in. {chosen}.\n"
        "1. Drink water and re-check after five minutes of quiet rest.\n"
        "2. Keep your regular exercise and sleep routine steady."
    )


@pytest.mark.parametrize("question,kind,is_mood", _TONE_CASES)
def test_task3_20_tone_cases_both_engines(question: str, kind: str, is_mood: bool, tmp_path, monkeypatch):
    temp_env = tmp_path / ".env"
    temp_env.write_text("ONLINE_PROVIDER=gemini\nGEMINI_API_KEY=AIzaDummyTone\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "ENV_PATH", temp_env)
    monkeypatch.setattr(online_llm, "_call_gemini", _mock_gentle_online_responder)

    alert_aid = _pick_astronaut_by_class("Health_Warning", "Medical_Danger_Alert", "Stress_BP_Spike_No_Medical_Danger")
    target_aid = alert_aid if kind == "alert" else "A001"
    doc_card = he.earth_doctor_card(target_aid, last_n_days=1)
    first_name = str(doc_card["profile"]["name"]).strip().split()[0]
    status_class = doc_card["predicted_class"]
    zones = {z: doc_card["diagnostic_breakdown"][z]["status"] for z in doc_card["diagnostic_breakdown"]}
    warn_or_danger = status_class in ("Health_Warning", "Medical_Danger_Alert") or any(
        v in ("yellow", "red") for v in zones.values()
    )

    con = sqlite3.connect(cfg.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("DELETE FROM online_chat_rate_limits")
    con.commit()
    user_stub = {"user_id": 999999, "role": "astronaut", "astronaut_id": target_aid}

    try:
        from backend.services.chat_service import ChatService

        svc = ChatService()
        for eng in ("offline", "online"):
            res = svc.ask(con, user_stub, question, engine=eng)
            assert res["ok"] is True
            assert res["refused"] is False, f"{eng} refused {question!r}: {res}"
            if eng == "online":
                assert res["engine_used"] == "online"

            ans = res["answer"]
            body = _strip_footer(ans)

            # 1. Uses astronaut's first name once (when available)
            fn_hits = re.findall(rf"\b{re.escape(first_name)}\b", body, flags=re.IGNORECASE)
            assert len(fn_hits) == 1, f"[{eng}] Expected first name {first_name!r} once in {body!r}"

            # 2. Specific real value from telemetry/day record (not hallucinated placeholder)
            assert re.search(r"\d+(?:\.\d+)?", body), f"[{eng}] Missing real metric value in {body!r}"

            # 3. At most 3 concrete station actions
            assert _count_numbered_steps(body) <= 3, f"[{eng}] Too many actions in {body!r}"

            # 4. Zero clinical diagnosis words in answer body
            assert not _DIAGNOSIS_WORDS_RE.search(body), f"[{eng}] Forbidden diagnosis word in {body!r}"

            # 5. Mandatory calm flight-surgeon guidance when status is warning or danger
            if warn_or_danger:
                assert "contact your flight surgeon" in ans.lower(), f"[{eng}] Missing flight-surgeon line in {ans!r}"

            # 6. Concise <= 120 words unless more detail requested
            if kind != "detail":
                word_count = len(ans.split())
                assert word_count <= 120, f"[{eng}] Exceeded 120 words ({word_count} words): {ans!r}"

            # 7. Mood/stress/loneliness validation + calming step + support note
            if is_mood:
                low = body.lower()
                assert any(w in low for w in ("heavy", "tiring", "understandable", "sense")), f"[{eng}] Missing feeling validation: {body!r}"
                assert "support" in low, f"[{eng}] Missing support reassurance: {body!r}"
    finally:
        con.execute("DELETE FROM online_chat_rate_limits")
        con.commit()
        con.close()


# ============================================================================== TASK 4
def test_task4_chatbot_ui_selector_and_screenshots(live_server, tmp_path, monkeypatch):
    TASK4_SHOTS.mkdir(parents=True, exist_ok=True)
    web = _demo_creds()
    astro = web["astronaut"]

    # State A: Online unavailable (no key configured) -> Online chip disabled & greyed out
    empty_env = tmp_path / ".env"
    empty_env.write_text("ONLINE_PROVIDER=gemini\nGEMINI_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "ENV_PATH", empty_env)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(viewport={"width": 1280, "height": 860})
            page = ctx.new_page()
            external_hosts = []
            page.on("request", lambda req: external_hosts.append(req.url) if not req.url.startswith(live_server) and not req.url.startswith("data:") else None)

            page.goto(f"{live_server}/login.html", wait_until="networkidle")
            page.fill("#vid", astro["vitalverse_id"])
            page.fill("#pwd", astro["password"])
            page.click("#go")
            page.wait_for_selector("a.go[href='health.html']", timeout=15000)

            page.goto(f"{live_server}/chatbot.html", wait_until="networkidle")
            page.wait_for_timeout(250)
            assert page.is_disabled("#engineOnlineBtn")
            assert page.is_visible("#engineHint")
            assert "Online assistant unavailable" in (page.text_content("#engineHint") or "")
            assert "active" in (page.get_attribute("#engineOfflineBtn", "class") or "")
            assert page.is_hidden("#onlinePrivacyNotice")
            page.screenshot(path=str(TASK4_SHOTS / "chatbot_online_unavailable.png"), full_page=True)

            # State B: Online enabled (mocked Gemini backend) -> selector toggles, notice appears, engine tag shown, sessionStorage persists
            keyed_env = tmp_path / ".env"
            keyed_env.write_text("ONLINE_PROVIDER=gemini\nGEMINI_API_KEY=AIzaDummyUI\n", encoding="utf-8")
            monkeypatch.setattr(cfg, "ENV_PATH", keyed_env)
            monkeypatch.setattr(online_llm, "check_internet_reachable", lambda **kwargs: True)
            monkeypatch.setattr(online_llm, "_call_gemini", _mock_gentle_online_responder)

            page.reload(wait_until="networkidle")
            page.wait_for_timeout(250)
            assert not page.is_disabled("#engineOnlineBtn")
            assert (page.text_content("#engineOnlineBtn") or "").strip() == "Online"

            page.click("#engineOnlineBtn")
            assert page.is_visible("#onlinePrivacyNotice")
            assert (
                "Online mode sends your question and a short summary of your health data to an external AI service (Google Gemini)."
                in (page.text_content("#onlinePrivacyNotice") or "")
            )

            # Ask telemetry question -> answered with Gemini tag
            page.fill("#chatInput", "How is my heart rate?")
            page.click("#chatSendBtn")
            page.wait_for_function("document.querySelectorAll('.vv-chat-row--bot').length >= 2")
            last_bot = page.locator(".vv-chat-row--bot").last
            assert "Gemini" in (last_bot.locator(".vv-engine-tag").text_content() or "")
            assert "bpm" in (last_bot.text_content() or "").lower()
            page.screenshot(path=str(TASK4_SHOTS / "chatbot_online_gemini_answer.png"), full_page=True)

            # Reload persists selection in sessionStorage
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(250)
            assert "active" in (page.get_attribute("#engineOnlineBtn", "class") or "")
            assert page.is_visible("#onlinePrivacyNotice")

            # Urgent escalation & safety refusal behave identically in online mode
            page.fill("#chatInput", "What medicine should I take?")
            page.click("#chatSendBtn")
            page.wait_for_function("document.querySelectorAll('.vv-chat-refusal').length >= 1")

            page.fill("#chatInput", "I have chest pain")
            page.click("#chatSendBtn")
            page.wait_for_function("document.querySelectorAll('.vv-urgent-card').length >= 1")
            assert "Contact your flight surgeon now" in (page.locator(".vv-urgent-card").last.text_content() or "")
            page.screenshot(path=str(TASK4_SHOTS / "chatbot_online_gemini_and_urgent.png"), full_page=True)

            assert external_hosts == [], f"Browser leaked external requests: {external_hosts}"
            ctx.close()
        finally:
            browser.close()
