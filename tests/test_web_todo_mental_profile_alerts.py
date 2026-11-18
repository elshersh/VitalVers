"""End-to-end API, RBAC, offline, CLI, and Playwright browser tests for Phase 3 & Phase 4 features (B2, B3, B4, B6, A5, Simulate)."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
import pytest
import uvicorn

from app import app
from backend.config import DB_PATH, DEMO_CREDS_PATH, PROJECT_ROOT
from backend.services.mood_service import compute_mood_score

SCREENSHOTS_DIR = PROJECT_ROOT / "screenshots" / "phase3_4"


def _demo_creds() -> dict:
    return json.loads(DEMO_CREDS_PATH.read_text(encoding="utf-8"))["web_demo_accounts"]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _api_login(client: TestClient, vid: str, password: str, role: str) -> str:
    res = client.post(
        "/api/auth/login",
        json={"vitalverse_id": vid, "password": password, "role": role},
    )
    assert res.status_code == 200, res.text
    csrf = client.cookies.get("vv_csrf") or res.json().get("csrf_token") or ""
    assert csrf
    return csrf


@pytest.fixture(scope="module")
def live_server():
    """Run FastAPI + uvicorn on an ephemeral localhost port for Phase 3/4 Playwright checks."""
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


def test_logged_out_page_gates_and_pwa_assets():
    with TestClient(app) as client:
        for page in ("/todo.html", "/mental.html", "/profile.html", "/alerts.html"):
            r = client.get(page, follow_redirects=False)
            assert r.status_code == 302, f"{page} returned {r.status_code}"
            assert "/login.html" in r.headers["location"]

        manifest = client.get("/manifest.json")
        assert manifest.status_code == 200
        assert manifest.json()["name"].startswith("Vitalverse")

        sw = client.get("/sw.js")
        assert sw.status_code == 200
        assert "addEventListener" in sw.text


def test_todo_api_persistence_reset_and_doctor_readonly():
    web = _demo_creds()
    astro = web["astronaut"]
    doc1 = web["approved_doctor"]
    aid = astro["astronaut_id"]
    today = datetime.now(timezone.utc).date().isoformat()

    try:
        with TestClient(app) as client:
            csrf = _api_login(client, astro["vitalverse_id"], astro["password"], "astronaut")
            r0 = client.get(f"/api/todo/{aid}")
            assert r0.status_code == 200
            d0 = r0.json()
            assert d0["total"] == 20
            assert d0["readonly"] is False

            # Toggle 4 items -> 20%
            for key in ("todo-01", "todo-02", "todo-03", "todo-04"):
                rp = client.patch(
                    f"/api/todo/{aid}/items/{key}",
                    json={"done": True},
                    headers={"X-CSRF-Token": csrf},
                )
                assert rp.status_code == 200, rp.text

            me = client.get("/api/auth/me").json()
            assert me["todo_percent"] >= 20

            # Cross-astronaut isolation
            assert client.get("/api/todo/A014").status_code == 403

            # Reset restores 0
            rr = client.post(f"/api/todo/{aid}/reset", headers={"X-CSRF-Token": csrf})
            assert rr.status_code == 200
            assert rr.json()["completed"] == 0

        with TestClient(app) as doc_client:
            d_csrf = _api_login(doc_client, doc1["vitalverse_id"], doc1["password"], "doctor")
            r_doc = doc_client.get(f"/api/todo/{aid}")
            assert r_doc.status_code == 200
            assert r_doc.json()["readonly"] is True
            r_patch = doc_client.patch(
                f"/api/todo/{aid}/items/todo-01",
                json={"done": True},
                headers={"X-CSRF-Token": d_csrf},
            )
            assert r_patch.status_code == 403
    finally:
        con = sqlite3.connect(DB_PATH)
        con.execute("DELETE FROM daily_todo WHERE astronaut_id = ? AND todo_date = ?", (aid, today))
        con.commit()
        con.close()


def test_mental_health_scoring_edit_low_mood_alert_and_email():
    web = _demo_creds()
    astro = web["astronaut"]
    doc1 = web["approved_doctor"]
    aid = astro["astronaut_id"]
    today = datetime.now(timezone.utc).date().isoformat()
    low_answers = {
        "0": 2,
        "1": "Stressed",
        "2": 2,
        "3": "No",
        "4": 2,
        "5": "Often",
        "6": 2,
        "7": "Rough sleep cycle",
        "8": 2,
        "9": "Keep lights dim",
    }
    high_answers = {
        "0": 5,
        "1": "Happy",
        "2": 5,
        "3": "Yes",
        "3t": "Video call with family",
        "4": 4,
        "5": "Never",
        "6": 5,
        "7": "",
        "8": 5,
        "9": "",
    }
    expected_low, expected_low_tag, _ = compute_mood_score(low_answers)
    assert expected_low < 2.5

    created_alert_ids: list[int] = []
    try:
        with TestClient(app) as client:
            csrf = _api_login(client, astro["vitalverse_id"], astro["password"], "astronaut")
            r_post = client.post(
                f"/api/mental/{aid}/checkins",
                json={"answers": low_answers},
                headers={"X-CSRF-Token": csrf},
            )
            assert r_post.status_code == 201, r_post.text
            body = r_post.json()
            assert body["entry"]["score"] == expected_low
            assert body["entry"]["recommended_tag"] == expected_low_tag

            # Low mood (<2.5) created a 'mood' warning alert
            al_res = client.get("/api/alerts?severity=warning&limit=20").json()
            mood_alerts = [a for a in al_res["items"] if a["source"] == "mood" and a["astronaut_id"] == aid]
            assert mood_alerts, "Expected automatic low-mood warning alert"
            created_alert_ids.extend(int(a["id"]) for a in mood_alerts)

            # Same-day PUT edits today's entry in place
            r_put = client.put(
                f"/api/mental/{aid}/checkins/today",
                json={"answers": high_answers},
                headers={"X-CSRF-Token": csrf},
            )
            assert r_put.status_code == 200, r_put.text
            assert r_put.json()["entry"]["score"] >= 4.0

            r_list = client.get(f"/api/mental/{aid}/checkins").json()
            today_rows = [row for row in r_list["entries"] if row["checkin_date"] == today]
            assert len(today_rows) == 1
            assert today_rows[0]["score"] == r_put.json()["entry"]["score"]

            # Email endpoint falls back cleanly to mailto when SMTP is unset, and validates address
            bad_mail = client.post(
                "/api/mental/email",
                json={"to_email": "not-an-email", "subject": "Hi", "body": "Test"},
                headers={"X-CSRF-Token": csrf},
            )
            assert bad_mail.status_code == 400
            ok_mail = client.post(
                "/api/mental/email",
                json={"to_email": "surgeon@nasa.example", "subject": "Support check-in", "body": "Doing better today"},
                headers={"X-CSRF-Token": csrf},
            )
            assert ok_mail.status_code == 200
            mail_body = ok_mail.json()
            assert mail_body.get("ok") is True
            assert mail_body.get("mode") in ("mailto", "smtp")

        with TestClient(app) as doc_client:
            d_csrf = _api_login(doc_client, doc1["vitalverse_id"], doc1["password"], "doctor")
            r_doc = doc_client.get(f"/api/mental/{aid}/checkins")
            assert r_doc.status_code == 200
            assert doc_client.post(
                f"/api/mental/{aid}/checkins",
                json={"answers": high_answers},
                headers={"X-CSRF-Token": d_csrf},
            ).status_code == 403
    finally:
        con = sqlite3.connect(DB_PATH)
        con.execute("DELETE FROM mood_checkins WHERE astronaut_id = ? AND checkin_date = ?", (aid, today))
        if created_alert_ids:
            ph = ",".join("?" for _ in created_alert_ids)
            con.execute(f"DELETE FROM alerts WHERE id IN ({ph})", created_alert_ids)
        con.execute(
            "DELETE FROM email_rate_limits WHERE user_id IN (SELECT id FROM users WHERE vitalverse_id = ?)",
            (astro["vitalverse_id"],),
        )
        con.commit()
        con.close()


def test_doctor_access_approve_edit_revoke_and_password_logout_all():
    web = _demo_creds()
    astro = web["astronaut"]
    doc2 = web["pending_doctor"]
    aid = astro["astronaut_id"]

    con0 = sqlite3.connect(DB_PATH)
    con0.row_factory = sqlite3.Row
    doc2_uid = con0.execute("SELECT id FROM users WHERE vitalverse_id = ?", (doc2["vitalverse_id"],)).fetchone()["id"]
    orig_link = dict(
        con0.execute(
            "SELECT * FROM doctor_astronaut_links WHERE doctor_user_id = ? AND astronaut_id = ?",
            (doc2_uid, aid),
        ).fetchone()
    )
    orig_allergies = con0.execute(
        "SELECT allergies FROM astronaut_profile WHERE astronaut_id = ?",
        (aid,),
    ).fetchone()["allergies"]
    con0.close()

    temp_vid = None
    temp_aid = None
    try:
        with TestClient(app) as astro_c, TestClient(app) as doc2_c:
            a_csrf = _api_login(astro_c, astro["vitalverse_id"], astro["password"], "astronaut")
            d2_csrf = _api_login(doc2_c, doc2["vitalverse_id"], doc2["password"], "doctor")

            # Pending doctor initially blocked 403
            assert doc2_c.get(f"/api/profile/{aid}").status_code == 403

            # Astronaut approves pending doctor link
            reqs = astro_c.get("/api/access/requests").json()["requests"]
            target = next(r for r in reqs if r["doctor_vitalverse_id"] == doc2["vitalverse_id"])
            assert astro_c.post(
                f"/api/access/requests/{target['id']}/approve",
                headers={"X-CSRF-Token": a_csrf},
            ).status_code == 200

            # Doctor can now view profile + update Health tab, but NOT Personal/Flight tabs
            assert doc2_c.get(f"/api/profile/{aid}").status_code == 200
            prof_doc = doc2_c.get(f"/api/profile/{aid}").json()["health"]
            r_health_upd = doc2_c.put(
                f"/api/profile/{aid}/health",
                json={
                    "age": prof_doc.get("age"),
                    "gender": prof_doc.get("gender") or "",
                    "weight_kg": prof_doc.get("weight_kg"),
                    "height_cm": prof_doc.get("height_cm"),
                    "blood_type": prof_doc.get("blood_type") or "",
                    "allergies": "No known allergies (verified)",
                    "previous_surgeries": prof_doc.get("previous_surgeries") or "",
                    "previous_injuries": prof_doc.get("previous_injuries") or "",
                    "immunization_history": prof_doc.get("immunization_history") or "",
                    "family_medical_history": prof_doc.get("family_medical_history") or "",
                },
                headers={"X-CSRF-Token": d2_csrf},
            )
            assert r_health_upd.status_code == 200
            assert doc2_c.put(
                f"/api/profile/{aid}/personal",
                json={"name": "Unauthorized Rename"},
                headers={"X-CSRF-Token": d2_csrf},
            ).status_code == 403

            # Revoke access -> immediate 403
            assert astro_c.post(
                f"/api/access/requests/{target['id']}/revoke",
                headers={"X-CSRF-Token": a_csrf},
            ).status_code == 200
            assert doc2_c.get(f"/api/profile/{aid}").status_code == 403

        # Test password change + logout-all on a clean ephemeral astronaut account
        with TestClient(app) as c1, TestClient(app) as c2:
            reg = c1.post(
                "/api/auth/signup",
                json={
                    "role": "astronaut",
                    "astronautId": "CREW-TMP01",
                    "fullName": "Temp Test Crew",
                    "missionRole": "Payload Specialist",
                    "nationality": "EG",
                    "flightSurgeon": "Dr. Test",
                    "previousFlight": "no",
                    "age": "32",
                    "gender": "Other",
                    "weight": "72",
                    "height": "176",
                    "bloodType": "O+",
                    "aircraft": "Dragon",
                    "duration": "14",
                    "destination": "ISS",
                    "password": "TempPass#2026!",
                    "confirmPassword": "TempPass#2026!",
                },
            )
            assert reg.status_code == 201, reg.text
            temp_vid = reg.json()["vitalverse_id"]
            temp_aid = reg.json()["astronaut_id"]
            csrf1 = reg.json().get("csrf_token") or c1.get("/api/auth/me").json()["csrf_token"]

            _api_login(c2, temp_vid, "TempPass#2026!", "astronaut")
            # Change password on c1 -> invalidates other sessions + works with new password
            r_pw = c1.put(
                "/api/auth/password",
                json={
                    "current_password": "TempPass#2026!",
                    "new_password": "NewTempPass#2026!",
                    "confirm_password": "NewTempPass#2026!",
                },
                headers={"X-CSRF-Token": csrf1},
            )
            assert r_pw.status_code == 200, r_pw.text
            assert c2.get("/api/auth/me").json()["authenticated"] is False

            # Log in twice with new password and verify logout-all invalidates both
            _api_login(c2, temp_vid, "NewTempPass#2026!", "astronaut")
            csrf1b = _api_login(c1, temp_vid, "NewTempPass#2026!", "astronaut")
            assert c1.post("/api/auth/logout-all", headers={"X-CSRF-Token": csrf1b}).status_code == 200
            assert c1.get("/api/auth/me").json()["authenticated"] is False
            assert c2.get("/api/auth/me").json()["authenticated"] is False
    finally:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            "UPDATE doctor_astronaut_links SET status = ?, decided_at = ? WHERE id = ?",
            (orig_link["status"], orig_link["decided_at"], orig_link["id"]),
        )
        con.execute("UPDATE astronaut_profile SET allergies = ? WHERE astronaut_id = ?", (orig_allergies, aid))
        con.execute(
            "DELETE FROM alerts WHERE astronaut_id = ? AND source = 'access'",
            (aid,),
        )
        if temp_vid and temp_aid:
            con.execute("DELETE FROM web_sessions WHERE user_id IN (SELECT id FROM users WHERE vitalverse_id = ?)", (temp_vid,))
            con.execute("DELETE FROM users WHERE vitalverse_id = ?", (temp_vid,))
            con.execute("DELETE FROM telemetry_labels WHERE record_id IN (SELECT record_id FROM mission_telemetry WHERE astronaut_id = ?)", (temp_aid,))
            con.execute("DELETE FROM model_predictions WHERE record_id IN (SELECT record_id FROM mission_telemetry WHERE astronaut_id = ?)", (temp_aid,))
            con.execute("DELETE FROM mission_telemetry WHERE astronaut_id = ?", (temp_aid,))
            con.execute("DELETE FROM preflight_baseline WHERE astronaut_id = ?", (temp_aid,))
            con.execute("DELETE FROM astronaut_profile WHERE astronaut_id = ?", (temp_aid,))
        con.commit()
        con.close()


def test_predict_demo_advance_alerts_and_simulate_feed_cli():
    web = _demo_creds()
    astro = web["astronaut"]
    doc1 = web["approved_doctor"]
    aid = astro["astronaut_id"]

    # 1. Test live /api/predict/{aid}, /api/demo/advance?scenario=danger, /api/alerts/*, /api/push/vapid-public-key
    try:
        with TestClient(app) as astro_c, TestClient(app) as doc_c:
            a_csrf = _api_login(astro_c, astro["vitalverse_id"], astro["password"], "astronaut")
            _api_login(doc_c, doc1["vitalverse_id"], doc1["password"], "doctor")

            r_vapid = astro_c.get("/api/push/vapid-public-key")
            assert r_vapid.status_code == 200
            assert len(r_vapid.json()["public_key"]) > 20

            r_pred = astro_c.post(f"/api/predict/{aid}", headers={"X-CSRF-Token": a_csrf})
            assert r_pred.status_code == 200
            assert r_pred.json()["mission_day"] == 180

            r_adv = astro_c.post(
                f"/api/demo/advance?astronaut_id={aid}&scenario=danger",
                headers={"X-CSRF-Token": a_csrf},
            )
            assert r_adv.status_code == 200, r_adv.text
            adv = r_adv.json()
            assert adv["demo"] is True
            assert adv["mission_day"] == 181
            assert adv["predicted_class"] == "Medical_Danger_Alert"
            assert adv["alert_created"] is not None
            alert_id = adv["alert_created"]["id"]

            doc_alerts = doc_c.get("/api/alerts?severity=danger").json()
            matched = next(x for x in doc_alerts["items"] if x["id"] == alert_id)
            det = matched["detailed_explanation"]
            assert "class_probabilities" in det
            assert "triggered_vitals" in det and len(det["triggered_vitals"]) >= 1
            assert "trend_7d" in det and len(det["trend_7d"]) >= 1
            assert "Contact flight surgeon immediately" in det["countermeasures"][0]["title"]

            r_ack = astro_c.post(f"/api/alerts/{alert_id}/acknowledge", headers={"X-CSRF-Token": a_csrf})
            assert r_ack.status_code == 200
            assert r_ack.json()["acknowledged_at"]
    finally:
        con = sqlite3.connect(DB_PATH)
        con.execute("DELETE FROM model_predictions WHERE record_id IN (SELECT record_id FROM mission_telemetry WHERE astronaut_id = ? AND mission_day > 180)", (aid,))
        con.execute("DELETE FROM telemetry_labels WHERE record_id IN (SELECT record_id FROM mission_telemetry WHERE astronaut_id = ? AND mission_day > 180)", (aid,))
        con.execute("DELETE FROM mission_telemetry WHERE astronaut_id = ? AND mission_day > 180", (aid,))
        con.execute("DELETE FROM alerts WHERE astronaut_id = ? AND mission_day > 180", (aid,))
        con.commit()
        con.close()

    # 2. Test CLI scripts/simulate_feed.py on an isolated temporary DB copy
    tmp_db = PROJECT_ROOT / "tests" / ".tmp_simulate_feed.db"
    shutil.copy2(DB_PATH, tmp_db)
    try:
        env = dict(os.environ)
        env["ASTRO_HEALTH_DB"] = str(tmp_db)
        proc = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "simulate_feed.py"), "--astronaut-id", aid, "--days", "1", "--scenario", "danger"],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "day=181" in proc.stdout
        assert "Medical_Danger_Alert" in proc.stdout
    finally:
        if tmp_db.exists():
            tmp_db.unlink()


def test_playwright_phase3_4_pages_screenshots_and_offline_network(live_server: str):
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    web = _demo_creds()
    astro = web["astronaut"]
    doc1 = web["approved_doctor"]
    aid = astro["astronaut_id"]
    today = datetime.now(timezone.utc).date().isoformat()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            external_requests: list[str] = []
            page_errors: list[str] = []
            failed_http: list[str] = []

            def _watch(page):
                page.on(
                    "request",
                    lambda req: external_requests.append(req.url)
                    if (urlparse(req.url).scheme not in ("data", "blob") and urlparse(req.url).hostname not in ("127.0.0.1", "localhost", "::1"))
                    else None,
                )
                page.on("pageerror", lambda err: page_errors.append(str(err)))
                page.on(
                    "response",
                    lambda resp: failed_http.append(f"{resp.status} {resp.url}")
                    if resp.status >= 400 and "/api/alerts/" not in resp.url
                    else None,
                )

            # ---- Desktop (1440px) Astronaut flow ----
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            _watch(page)

            page.goto(f"{live_server}/login.html", wait_until="load")
            page.fill("#vid", astro["vitalverse_id"])
            page.fill("#pwd", astro["password"])
            page.click("#go")
            page.wait_for_selector("a.go[href='health.html']", timeout=10000)

            # B6 To-Do page + ring
            page.goto(f"{live_server}/todo.html", wait_until="load")
            page.wait_for_selector("#taskGrid input[type='checkbox']", timeout=10000)
            checks = page.locator("#taskGrid input[type='checkbox']")
            for idx in range(4):
                checks.nth(idx).check()
            page.wait_for_function("() => document.getElementById('completedCount')?.textContent.trim() === '4'")
            page.screenshot(path=str(SCREENSHOTS_DIR / "todo_desktop.png"), full_page=True)
            page.click("#resetBtn")
            page.wait_for_function("() => document.getElementById('completedCount')?.textContent.trim() === '0'")

            # A5 Mental Health astronaut page
            page.goto(f"{live_server}/mental.html", wait_until="load")
            page.wait_for_selector("#mhSave", timeout=10000)
            page.locator("label:has(input[name='q1'][value='Happy'])").click()
            page.locator("label:has(input[name='q3'][value='Yes'])").click()
            page.locator("label:has(input[name='q5'][value='Never'])").click()
            page.click("#mhSave")
            page.wait_for_selector("#mhEditTodayBtn", timeout=10000)
            page.wait_for_timeout(300)
            page.screenshot(path=str(SCREENSHOTS_DIR / "mental_astro_desktop.png"), full_page=True)

            # B3 Profile + #access hash tab
            page.goto(f"{live_server}/profile.html#access", wait_until="load")
            page.wait_for_selector(".pf-pass", timeout=10000)
            page.wait_for_timeout(200)
            page.screenshot(path=str(SCREENSHOTS_DIR / "profile_desktop.png"), full_page=True)

            # Mobile (390px) Profile screenshot
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(200)
            page.screenshot(path=str(SCREENSHOTS_DIR / "profile_mobile_390.png"), full_page=True)
            ctx.close()

            # ---- Desktop (1440px) Doctor flow: Mental + Alerts Center (DEMO danger alert) ----
            dctx = browser.new_context(viewport={"width": 1440, "height": 900})
            dpage = dctx.new_page()
            _watch(dpage)

            dpage.goto(f"{live_server}/login.html", wait_until="load")
            dpage.click(".role[data-r='doctor']")
            dpage.fill("#vid", doc1["vitalverse_id"])
            dpage.fill("#pwd", doc1["password"])
            dpage.click("#go")
            dpage.wait_for_selector("a.go[href='health.html']", timeout=10000)

            dpage.goto(f"{live_server}/mental.html", wait_until="load")
            dpage.wait_for_selector("#mhAstSel", timeout=10000)
            dpage.wait_for_timeout(300)
            dpage.screenshot(path=str(SCREENSHOTS_DIR / "mental_doc_desktop.png"), full_page=True)

            dpage.goto(f"{live_server}/alerts.html", wait_until="load")
            dpage.wait_for_selector("#alAstroSelect option", state="attached", timeout=10000)
            # Click real Run AI Check button first to prove CSRF wiring, then trigger Day 181 danger alert
            dpage.click("#alPredictBtn")
            dpage.wait_for_selector("#alNotice:not([hidden])", timeout=10000)
            adv_ok = dpage.evaluate(
                f"""async () => {{
                    const sess = await window.VV_SHELL.getSession();
                    const r = await fetch('/api/demo/advance?astronaut_id={aid}&scenario=danger', {{
                        method: 'POST',
                        headers: {{ 'X-CSRF-Token': (sess && sess.csrf_token) || '' }},
                        credentials: 'same-origin'
                    }});
                    return r.ok;
                }}"""
            )
            assert adv_ok is True
            dpage.reload(wait_until="load")
            dpage.wait_for_selector("#vvDangerBanner", timeout=10000)
            dpage.wait_for_selector(".al-details canvas", timeout=10000)
            dpage.wait_for_timeout(300)
            dpage.screenshot(path=str(SCREENSHOTS_DIR / "alerts_doc_desktop.png"), full_page=True)

            dpage.set_viewport_size({"width": 390, "height": 844})
            dpage.wait_for_timeout(200)
            dpage.screenshot(path=str(SCREENSHOTS_DIR / "alerts_mobile_390.png"), full_page=True)
            dctx.close()
            browser.close()

            assert external_requests == [], f"Unexpected external requests: {external_requests}"
            assert page_errors == [], f"Uncaught page errors: {page_errors}"
            assert failed_http == [], f"Failed HTTP responses: {failed_http}"
    finally:
        con = sqlite3.connect(DB_PATH)
        con.execute("DELETE FROM daily_todo WHERE astronaut_id = ? AND todo_date = ?", (aid, today))
        con.execute("DELETE FROM mood_checkins WHERE astronaut_id = ? AND checkin_date = ?", (aid, today))
        con.execute("DELETE FROM model_predictions WHERE record_id IN (SELECT record_id FROM mission_telemetry WHERE astronaut_id = ? AND mission_day > 180)", (aid,))
        con.execute("DELETE FROM telemetry_labels WHERE record_id IN (SELECT record_id FROM mission_telemetry WHERE astronaut_id = ? AND mission_day > 180)", (aid,))
        con.execute("DELETE FROM mission_telemetry WHERE astronaut_id = ? AND mission_day > 180", (aid,))
        con.execute("DELETE FROM alerts WHERE astronaut_id = ? AND mission_day > 180", (aid,))
        con.commit()
        con.close()
