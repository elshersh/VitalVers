"""End-to-end API, RBAC, offline, and Playwright browser tests for Steps A-C."""
from __future__ import annotations

import json
from pathlib import Path
import socket
import sqlite3
import threading
import time
from urllib.parse import urlparse

import argon2
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
import pytest
import uvicorn

import health_engine as he
from app import app
from backend.config import DB_PATH, DEMO_CREDS_PATH, PROJECT_ROOT

SCREENSHOTS_DIR = PROJECT_ROOT / "screenshots" / "step_c"


def _demo_creds() -> dict:
    return json.loads(DEMO_CREDS_PATH.read_text(encoding="utf-8"))["web_demo_accounts"]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def live_server():
    """Run real FastAPI + uvicorn app on an ephemeral localhost port for Playwright tests."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 25.0
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("Uvicorn test server failed to start within 25s")
        time.sleep(0.1)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=10)


def test_step_a_official_argon2_only_no_legacy_fallback():
    pkg_path = Path(argon2.__file__).resolve()
    assert "site-packages" in str(pkg_path).lower(), f"Expected site-packages argon2-cffi, got {pkg_path}"
    assert hasattr(argon2, "PasswordHasher")
    assert not hasattr(he, "_verify_legacy_scrypt_argon2id"), "Legacy fallback hash function must be removed"
    src = (PROJECT_ROOT / "health_engine.py").read_text(encoding="utf-8")
    assert "import bcrypt" not in src
    assert "_verify_legacy_scrypt_argon2id" not in src


def test_rbac_view_param_ignored_and_pending_doctor_blocked():
    web = _demo_creds()
    astro = web["astronaut"]
    doc_pending = web["pending_doctor"]

    with TestClient(app) as client:
        # 1. Logged-out /health.html redirects cleanly to /login.html
        r_anon = client.get("/health.html?view=doctor", follow_redirects=False)
        assert r_anon.status_code == 302
        assert r_anon.headers["location"].endswith("/login.html")

        # 2. Astronaut login: ?view=doctor MUST NOT grant doctor view
        r_login = client.post(
            "/api/auth/login",
            json={"vitalverse_id": astro["vitalverse_id"], "password": astro["password"], "role": "astronaut"},
        )
        assert r_login.status_code == 200
        r_dash = client.get("/health.html?view=doctor&astronaut=A014")
        assert r_dash.status_code == 200
        assert 'data-role="astronaut"' in r_dash.text
        assert 'data-role="doctor"' not in r_dash.text

        # 3. Predictions API returns full 180 mission days for authorized A001, and 403 for A014
        r_pred = client.get(f"/api/astronauts/{astro['astronaut_id']}/predictions")
        assert r_pred.status_code == 200
        pred = r_pred.json()
        assert pred["total_days"] == 180
        assert len(pred["predictions"]) == 180
        assert pred["latest"]["mission_day"] == 180

        assert client.get("/api/astronauts/A014/predictions").status_code == 403

    with TestClient(app) as pending_client:
        r_doc2 = pending_client.post(
            "/api/auth/login",
            json={
                "vitalverse_id": doc_pending["vitalverse_id"],
                "password": doc_pending["password"],
                "role": "doctor",
            },
        )
        assert r_doc2.status_code == 200
        r_list = pending_client.get("/api/doctor/astronauts").json()
        assert r_list["approved"] == []
        assert any(a["id"] == "A001" for a in r_list["pending"])
        assert pending_client.get("/api/health/A001/dashboard").status_code == 403
        assert pending_client.get("/api/astronauts/A001/predictions").status_code == 403


def test_themed_404_page_on_missing_route():
    with TestClient(app) as client:
        res = client.get("/this-route-does-not-exist.html")
        assert res.status_code == 404
        assert "Lost in <span>space</span>" in res.text
        assert "SIGNAL LOST" in res.text


def test_playwright_end_to_end_flows_12a_to_12f(live_server: str):
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    web = _demo_creds()
    astro = web["astronaut"]
    doc1 = web["approved_doctor"]

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ---------- 12a + 12c + 12d + 12e + 12f (Astronaut flow) ----------
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        external_requests: list[str] = []
        page_errors: list[str] = []

        def _track_req(req):
            u = urlparse(req.url)
            if u.scheme not in ("data", "blob") and u.hostname not in ("127.0.0.1", "localhost", "::1"):
                external_requests.append(req.url)

        page.on("request", _track_req)
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        # Fetch latest expected prediction first via logged-in API inside browser
        page.goto(f"{live_server}/login.html", wait_until="load")
        page.fill("#vid", astro["vitalverse_id"])
        page.fill("#pwd", astro["password"])
        page.click("#go")
        page.wait_for_selector("a.go[href='health.html']", timeout=10000)

        expected_pred = page.evaluate(
            f"""async () => {{
                const r = await fetch('/api/astronauts/{astro["astronaut_id"]}/predictions', {{ credentials: 'same-origin' }});
                return await r.json();
            }}"""
        )
        assert expected_pred["total_days"] == 180
        expected_label = expected_pred["latest"]["status_label"]

        # 12a: Navigate to Health dashboard -> opens astronaut dashboard with 180-day charts & model status pill
        page.click("a.go[href='health.html']")
        page.wait_for_url("**/health.html", timeout=10000)
        page.wait_for_selector("#modelStatusPill", timeout=10000)

        subtitle = page.inner_text("#overviewSubtitle")
        assert "Mission Day 180 of 180" in subtitle
        pill_text = page.inner_text("#modelStatusPill").strip()
        assert pill_text == expected_label

        # Check Health Metrics tab Chart.js actually loaded 180 data points & capture chart view
        page.click("#sectionTabs a[data-section='metrics']")
        page.wait_for_timeout(400)
        chart_len = page.evaluate("() => { const c = Chart.getChart('metricChart'); return c ? c.data.labels.length : 0; }")
        assert chart_len == 180, f"Expected 180-day series in chart, got {chart_len}"
        page.screenshot(path=str(SCREENSHOTS_DIR / "12a_astronaut_metrics_chart.png"), full_page=True)

        # Return to overview & capture full dashboard view with model status pill
        page.click("#sectionTabs a[data-section='overview']")
        page.wait_for_timeout(300)
        page.screenshot(path=str(SCREENSHOTS_DIR / "12a_astronaut_dashboard.png"), full_page=True)

        # 12f: No 404 from any navbar menu link across pages
        menu_hrefs = page.eval_on_selector_all("#vvNavMenu a", "els => els.map(e => e.getAttribute('href'))")
        for href in menu_hrefs:
            resp = page.request.get(f"{live_server}/{href.lstrip('/')}")
            assert resp.status < 400, f"Menu link {href} returned {resp.status}"

        # 12c, 12d, 12e: Chatbot E2E
        page.goto(f"{live_server}/chatbot.html", wait_until="load")
        page.wait_for_selector(f"#chatRoleBadge:has-text('{astro['astronaut_id']}')", timeout=10000)

        # 12c: "How is my heart rate?" -> uses A001's real data
        page.fill("#chatInput", "How is my heart rate?")
        page.click("#chatSendBtn")
        page.wait_for_selector(".vv-bubble--bot >> text=/bpm/i", timeout=10000)
        log_text_c = page.inner_text("#chatLog")
        assert astro["astronaut_id"] in log_text_c
        assert "bpm" in log_text_c.lower()
        page.evaluate("""() => {
            const log = document.getElementById('chatLog');
            const u = document.querySelectorAll('.vv-chat-row--user');
            if (log && u.length) log.scrollTop = Math.max(0, u[u.length - 1].offsetTop - log.offsetTop - 12);
            window.scrollTo(0, 0);
        }""")
        page.wait_for_timeout(200)
        page.screenshot(path=str(SCREENSHOTS_DIR / "12c_chatbot_hr.png"), full_page=True)

        # 12d: "What's the temperature on Venus?" -> refused
        page.click("#newChatBtn")
        page.fill("#chatInput", "What's the temperature on Venus?")
        page.click("#chatSendBtn")
        page.wait_for_selector(".vv-chat-refusal", timeout=10000)
        refusal_text = page.inner_text(".vv-chat-refusal")
        assert "OUT OF SCOPE" in refusal_text.upper()
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(200)
        page.screenshot(path=str(SCREENSHOTS_DIR / "12d_chatbot_venus.png"), full_page=True)

        # 12e: "I have chest pain" -> red "Contact your flight surgeon now" card
        page.click("#newChatBtn")
        page.fill("#chatInput", "I have chest pain")
        page.click("#chatSendBtn")
        page.wait_for_selector(".vv-urgent-card", timeout=10000)
        urgent_text = page.inner_text(".vv-urgent-card")
        assert "Contact your flight surgeon now" in urgent_text
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(200)
        page.screenshot(path=str(SCREENSHOTS_DIR / "12e_chatbot_chest_pain.png"), full_page=True)

        assert not external_requests, f"External requests detected: {external_requests}"
        assert not page_errors, f"Frontend page errors: {page_errors}"
        ctx.close()

        # ---------- 12b (Doctor flow) ----------
        ctx_doc = browser.new_context(viewport={"width": 1440, "height": 900})
        page_doc = ctx_doc.new_page()
        page_doc.on("request", _track_req)
        page_doc.on("pageerror", lambda err: page_errors.append(str(err)))

        page_doc.goto(f"{live_server}/login.html", wait_until="load")
        page_doc.click(".role[data-r='doctor']")
        page_doc.fill("#vid", doc1["vitalverse_id"])
        page_doc.fill("#pwd", doc1["password"])
        page_doc.click("#go")
        page_doc.wait_for_selector("a.go[href='health.html']", timeout=10000)
        page_doc.click("a.go[href='health.html']")
        page_doc.wait_for_url("**/health.html", timeout=10000)
        page_doc.wait_for_selector("#astronautDetail .ast-head h2", timeout=10000)

        doc_heading = page_doc.inner_text("#astronautDetail .ast-head h2")
        assert doc1["linked_astronaut_id"] in doc_heading
        slider_max = page_doc.get_attribute("#missionDaySlider", "max")
        assert slider_max == "180"

        page_doc.wait_for_timeout(300)
        page_doc.screenshot(path=str(SCREENSHOTS_DIR / "12b_doctor_dashboard.png"), full_page=True)

        assert not external_requests, f"External requests in doctor session: {external_requests}"
        assert not page_errors, f"Frontend page errors in doctor session: {page_errors}"
        ctx_doc.close()
        browser.close()


def _cleanup_test_accounts(astronaut_ids: list[str], vitalverse_ids: list[str]) -> None:
    """Remove synthetic test signup records so the working DB stays clean."""
    con = sqlite3.connect(str(DB_PATH))
    try:
        for vid in vitalverse_ids:
            row = con.execute("SELECT id FROM users WHERE vitalverse_id = ?", (vid,)).fetchone()
            if row:
                uid = int(row[0])
                con.execute("DELETE FROM web_sessions WHERE user_id = ?", (uid,))
                con.execute("DELETE FROM doctor_astronaut_links WHERE doctor_user_id = ?", (uid,))
                con.execute("DELETE FROM doctor_profiles WHERE user_id = ?", (uid,))
                con.execute("DELETE FROM alerts WHERE detailed_explanation_json LIKE ?", (f"%{vid}%",))
                con.execute("DELETE FROM users WHERE id = ?", (uid,))
        for aid in astronaut_ids:
            con.execute("DELETE FROM web_sessions WHERE user_id IN (SELECT id FROM users WHERE astronaut_id = ?)", (aid,))
            con.execute("DELETE FROM users WHERE astronaut_id = ?", (aid,))
            rec_rows = con.execute("SELECT record_id FROM mission_telemetry WHERE astronaut_id = ?", (aid,)).fetchall()
            rec_ids = [int(r[0]) for r in rec_rows]
            if rec_ids:
                ph = ",".join("?" for _ in rec_ids)
                con.execute(f"DELETE FROM telemetry_labels WHERE record_id IN ({ph})", rec_ids)
            con.execute("DELETE FROM mission_telemetry WHERE astronaut_id = ?", (aid,))
            con.execute("DELETE FROM preflight_baseline WHERE astronaut_id = ?", (aid,))
            con.execute("DELETE FROM astronaut_playlist_items WHERE astronaut_id = ?", (aid,))
            con.execute("DELETE FROM astronaut_photo_items WHERE astronaut_id = ?", (aid,))
            con.execute("DELETE FROM alerts WHERE astronaut_id = ?", (aid,))
            con.execute("DELETE FROM astronaut_profile WHERE astronaut_id = ?", (aid,))
        con.commit()
    finally:
        con.close()


def test_signup_doctor_pending_and_validation_api():
    created_vids: list[str] = []
    try:
        with TestClient(app) as client:
            # Validation: mismatched password -> 400
            r_bad = client.post(
                "/api/auth/signup",
                json={
                    "role": "astronaut",
                    "fullName": "Bad Pass",
                    "password": "password123",
                    "confirmPassword": "different123",
                    "astronautId": "TESTBAD01",
                },
            )
            assert r_bad.status_code == 400

            # Duplicate existing A001 -> 409
            r_dup = client.post(
                "/api/auth/signup",
                json={
                    "role": "astronaut",
                    "fullName": "Duplicate",
                    "password": "password123",
                    "confirmPassword": "password123",
                    "astronautId": "A001",
                },
            )
            assert r_dup.status_code == 409

            # Doctor signup targeting A001 -> 201, pending status, still 403 on telemetry until approved
            r_doc = client.post(
                "/api/auth/signup",
                json={
                    "role": "doctor",
                    "fullName": "Dr. Signup Verify",
                    "password": "docsignup123",
                    "confirmPassword": "docsignup123",
                    "staffId": "DOC-VERIFY-9",
                    "specialization": "Aerospace Cardiology",
                    "organization": "Vitalverse Space Lab",
                    "contact": "doc9@vitalverse.example",
                    "credential": "LIC-9001",
                    "astId": "A001",
                    "astName": "Sara Ahmed",
                    "crew": "Crew 1",
                    "consent": True,
                },
            )
            assert r_doc.status_code == 201, r_doc.text
            body = r_doc.json()
            assert body["ok"] is True
            assert body["role"] == "doctor"
            assert body["vitalverse_id"].startswith("VTD-")
            assert body["link_status"] == "pending"
            assert body["target_astronaut_id"] == "A001"
            created_vids.append(body["vitalverse_id"])

            assert client.get("/api/astronauts/A001/predictions").status_code == 403
    finally:
        _cleanup_test_accounts([], created_vids)


def test_playwright_astronaut_signup_e2e(live_server: str):
    test_aid = "TESTASTRO99"
    created_vids: list[str] = []
    _cleanup_test_accounts([test_aid], [])

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()

            external_requests: list[str] = []
            page_errors: list[str] = []

            def _track_req(req):
                host = urlparse(req.url).hostname or ""
                if host not in {"127.0.0.1", "localhost", ""}:
                    external_requests.append(req.url)

            page.on("request", _track_req)
            page.on("pageerror", lambda err: page_errors.append(str(err)))

            page.goto(f"{live_server}/signup.html", wait_until="load")
            page.click(".pick[data-r='astronaut']")

            # Step 1
            page.fill("input[data-n='fullName']", "Test Commander")
            page.fill("input[data-n='password']", "testpass1234")
            page.fill("input[data-n='confirmPassword']", "testpass1234")
            page.fill("input[data-n='astronautId']", test_aid)
            page.fill("input[data-n='missionRole']", "Pilot")
            page.fill("input[data-n='nationality']", "Egyptian")
            page.fill("input[data-n='flightSurgeon']", "Dr. Orbit")
            page.fill("input[data-n='previousFlight']", "Demo 1")
            page.click("#next")

            # Step 2
            page.fill("input[data-n='age']", "34")
            page.select_option("select[data-n='gender']", "Female")
            page.fill("input[data-n='weight']", "68")
            page.fill("input[data-n='height']", "172")
            page.select_option("select[data-n='bloodType']", "O+")
            page.click("#next")

            # Step 3 (free-text duration matching user's reported screenshot)
            page.fill("input[data-n='aircraft']", "fgsdf")
            page.fill("input[data-n='duration']", "gsdfgsd")
            page.fill("input[data-n='destination']", "dsfgsd")
            page.click("#next")

            page.wait_for_selector("#createdVitalverseId", timeout=15000)
            vid = page.inner_text("#createdVitalverseId").strip()
            assert vid.startswith("VTA-")
            created_vids.append(vid)
            assert "Verified" in page.inner_text("#pTag")
            page.screenshot(path=str(SCREENSHOTS_DIR / "signup_verified.png"), full_page=True)

            # New astronaut opens live dashboard with generated 180-day telemetry + AI predictions
            page.click("a.btn[href='health.html']")
            page.wait_for_url("**/health.html", timeout=10000)
            page.wait_for_selector("#modelStatusPill", timeout=15000)
            assert "Mission Day 180 of 180" in page.inner_text("#overviewSubtitle")
            page.click("#sectionTabs a[data-section='metrics']")
            page.wait_for_timeout(350)
            assert page.evaluate("() => Chart.getChart('metricChart').data.labels.length") == 180

            # New astronaut uses chatbot with their own new data
            page.goto(f"{live_server}/chatbot.html", wait_until="load")
            page.wait_for_selector(f"#chatRoleBadge:has-text('{test_aid}')", timeout=10000)
            page.fill("#chatInput", "How is my heart rate?")
            page.click("#chatSendBtn")
            page.wait_for_selector(".vv-bubble--bot >> text=/bpm/i", timeout=10000)
            assert test_aid in page.inner_text("#chatLog")

            assert not external_requests, f"External requests detected: {external_requests}"
            assert not page_errors, f"Frontend page errors detected: {page_errors}"
            ctx.close()
            browser.close()
    finally:
        _cleanup_test_accounts([test_aid], created_vids)
