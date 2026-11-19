"""One browser, several accounts: each tab keeps its own account, and open pages update live.

An astronaut can be signed in in one tab and a flight surgeon in another tab of the same browser. Refreshing a
tab keeps that tab's account. When one account changes something the other can see (for example approving a
flight surgeon's access request), the other account's open pages refresh by themselves.
"""
from __future__ import annotations

import json
import socket
import sqlite3
import threading
import time

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
import pytest
import uvicorn

from app import app
from backend.config import DB_PATH, DEMO_CREDS_PATH, MAX_BROWSER_SESSIONS
from backend.security import session_tag


def _creds() -> dict:
    return json.loads(DEMO_CREDS_PATH.read_text(encoding="utf-8"))["web_demo_accounts"]


def _login(client: TestClient, who: str, role: str) -> str:
    acct = _creds()[who]
    r = client.post("/api/auth/login", json={"vitalverse_id": acct["vitalverse_id"], "password": acct["password"], "role": role})
    assert r.status_code == 200, r.text
    return r.headers["x-vv-account-set"]


def _me(client: TestClient, tag: str | None = None) -> dict:
    headers = {"X-VV-Account": tag} if tag else {}
    return client.get("/api/auth/me", headers=headers).json()


def test_two_accounts_in_one_browser_each_tab_keeps_its_own():
    with TestClient(app) as browser:
        astro = _login(browser, "astronaut", "astronaut")
        doctor = _login(browser, "approved_doctor", "doctor")
        assert astro != doctor
        assert browser.cookies["vv_tags"] == f"{astro}.{doctor}"
        held = sorted(n[len("vv_s_"):] for n in browser.cookies.keys() if n.startswith("vv_s_"))
        assert held == sorted([astro, doctor])
        assert all(session_tag(browser.cookies[f"vv_s_{t}"]) == t for t in held)

        assert _me(browser, astro)["role"] == "astronaut"
        assert _me(browser, doctor)["role"] == "doctor"
        assert _me(browser)["role"] == "doctor", "without a choice the newest sign-in is used"

        # the dashboard page follows the account the tab names
        assert 'data-role="astronaut"' in browser.get(f"/health.html?account={astro}").text
        assert 'data-role="doctor"' in browser.get(f"/health.html?account={doctor}").text
        r = browser.get(f"/doctor-dashboard.html?account={astro}", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == f"/health.html?account={astro}"

        # a tab's CSRF token only works for that tab's account
        astro_csrf = _me(browser, astro)["csrf_token"]
        r = browser.post("/api/auth/logout", headers={"X-VV-Account": doctor, "X-CSRF-Token": astro_csrf})
        assert r.status_code == 403

        # signing out in the astronaut tab leaves the flight surgeon tab signed in
        r = browser.post("/api/auth/logout", headers={"X-VV-Account": astro, "X-CSRF-Token": astro_csrf})
        assert r.status_code == 200 and r.headers["x-vv-account-set"] == "anon"
        assert browser.cookies["vv_tags"] == doctor
        assert f"vv_s_{astro}" not in browser.cookies and f"vv_s_{doctor}" in browser.cookies
        assert _me(browser, astro)["authenticated"] is False
        assert _me(browser, doctor)["role"] == "doctor"


def test_browser_keeps_a_limited_number_of_sign_ins():
    with TestClient(app) as browser:
        tags = [_login(browser, "astronaut", "astronaut") for _ in range(MAX_BROWSER_SESSIONS + 1)]
        assert browser.cookies["vv_tags"].split(".") == tags[1:]
        assert sorted(n for n in browser.cookies.keys() if n.startswith("vv_s_")) == sorted(f"vv_s_{t}" for t in tags[1:])
        assert _me(browser, tags[0])["authenticated"] is False
        assert _me(browser, tags[-1])["authenticated"] is True


def _link_row(con: sqlite3.Connection, vid: str, aid: str) -> dict:
    return dict(
        con.execute(
            """SELECT l.* FROM doctor_astronaut_links l JOIN users u ON u.id = l.doctor_user_id
               WHERE u.vitalverse_id = ? AND l.astronaut_id = ?""",
            (vid, aid),
        ).fetchone()
    )


def _restore_link(row: dict) -> None:
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "UPDATE doctor_astronaut_links SET status = ?, decided_at = ?, created_at = ? WHERE id = ?",
        (row["status"], row["decided_at"], row["created_at"], row["id"]),
    )
    con.commit()
    con.close()


@pytest.fixture()
def pending_link():
    """The seeded pending flight surgeon request for A001, restored after the test."""
    creds = _creds()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    row = {**_link_row(con, creds["pending_doctor"]["vitalverse_id"], creds["astronaut"]["astronaut_id"]),
           "status": "pending", "decided_at": None}   # as seeded
    con.close()
    _restore_link(row)
    yield row
    _restore_link(row)


def test_live_fingerprints_follow_access_changes(pending_link):
    with TestClient(app) as astro_c, TestClient(app) as doc_c:
        _login(astro_c, "astronaut", "astronaut")
        _login(doc_c, "pending_doctor", "doctor")
        a_csrf = _me(astro_c)["csrf_token"]

        assert TestClient(app).get("/api/live").json() == {"authenticated": False, "parts": {}}
        a0 = astro_c.get("/api/live").json()["parts"]
        d0 = doc_c.get("/api/live").json()["parts"]
        assert a0 == astro_c.get("/api/live").json()["parts"], "nothing changed, nothing to refresh"

        r = astro_c.post(f"/api/access/requests/{pending_link['id']}/approve", headers={"X-CSRF-Token": a_csrf})
        assert r.status_code == 200
        a1 = astro_c.get("/api/live").json()["parts"]
        d1 = doc_c.get("/api/live").json()["parts"]
        assert a1["access"] != a0["access"]
        assert d1["access"] != d0["access"]
        assert d1["health"] != d0["health"], "the flight surgeon now sees the astronaut's health data"

        r = astro_c.post(f"/api/access/requests/{pending_link['id']}/revoke", headers={"X-CSRF-Token": a_csrf})
        assert r.status_code == 200
        d2 = doc_c.get("/api/live").json()["parts"]
        assert d2["access"] != d1["access"] and d2["health"] == d0["health"]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def live_server():
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 25.0
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("test server did not start")
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


_LOGIN_JS = """([v, pw, role]) => fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({vitalverse_id: v, password: pw, role: role})}).then(r => r.status)"""
_ROLE_JS = "fetch('/api/auth/me').then(r => r.json()).then(j => j.role)"


def test_two_tabs_two_accounts_and_live_access_updates(live_server, pending_link):
    creds = _creds()
    astro, doc = creds["astronaut"], creds["pending_doctor"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        tab1 = context.new_page()
        tab1.goto(live_server + "/about.html")
        assert tab1.evaluate(_LOGIN_JS, [astro["vitalverse_id"], astro["password"], "astronaut"]) == 200

        tab2 = context.new_page()
        tab2.goto(live_server + "/about.html")
        assert tab2.evaluate(_ROLE_JS) == "astronaut", "a new tab starts with the latest sign-in"
        assert tab2.evaluate(_LOGIN_JS, [doc["vitalverse_id"], doc["password"], "doctor"]) == 200

        # refreshing keeps each tab's own account
        tab1.reload()
        tab2.reload()
        assert tab1.evaluate(_ROLE_JS) == "astronaut"
        assert tab2.evaluate(_ROLE_JS) == "doctor"

        # the dashboard opens for each tab's account, even though the flight surgeon signed in last
        tab1.goto(live_server + "/health.html")
        tab1.wait_for_function("document.body.dataset.role === 'astronaut'", timeout=15000)
        assert "account=" in tab1.url
        tab2.goto(live_server + "/health.html")
        tab2.wait_for_function("document.body.dataset.role === 'doctor'", timeout=15000)
        tab2.wait_for_function("/No approved astronauts/.test(document.getElementById('loadError').textContent)", timeout=15000)
        tab2.wait_for_function("window.VV_SHELL.liveState().ready", timeout=15000)

        # record every notice tab 2 shows (each one fades out after a few seconds)
        tab2.evaluate("""() => { window.__notices = [];
          new MutationObserver(rs => rs.forEach(r => r.addedNodes.forEach(n => {
            if (n.classList && n.classList.contains('vv-toast')) window.__notices.push(n.textContent);
          }))).observe(document.body, {childList: true, subtree: true}); }""")

        # the astronaut approves in tab 1: the flight surgeon's dashboard in tab 2 fills in by itself
        csrf = tab1.evaluate("fetch('/api/auth/me').then(r => r.json()).then(j => j.csrf_token)")
        approve = f"fetch('/api/access/requests/{pending_link['id']}/approve', {{method: 'POST', headers: {{'X-CSRF-Token': '{csrf}'}}}}).then(r => r.status)"
        assert tab1.evaluate(approve) == 200
        tab2.wait_for_function("document.querySelector('#astronautList [data-id=\"A001\"]') !== null", timeout=15000)
        notices = " | ".join(tab2.evaluate("window.__notices"))
        assert "ACCESS UPDATED" in notices
        assert "ALERT" not in notices, "older alerts that just became visible are listed, not popped up as new"

        # revoking clears the record from tab 2 again
        revoke = approve.replace("/approve", "/revoke")
        assert tab1.evaluate(revoke) == 200
        tab2.wait_for_function(
            "document.querySelector('#astronautList [data-id=\"A001\"]') === null"
            " && /No approved astronauts/.test((document.getElementById('loadError') || {}).textContent || '')",
            timeout=20000,
        )
        assert tab2.evaluate(_ROLE_JS) == "doctor" and tab1.evaluate(_ROLE_JS) == "astronaut"
        browser.close()
