"""Answers that depend on the signed-in user must never reach anyone else.

The public Codespaces link runs behind a relay that was seen handing one visitor's API answer to another.
The server keeps per-user answers out of shared caches and stamps each API answer with the tag of the session
it was made for; static/js/fetch-guard.js throws away answers whose tag is not the browser's own.
"""
from __future__ import annotations

import json
import re
import socket
import threading
import time

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
import pytest
import uvicorn

from app import app
from backend.config import DEMO_CREDS_PATH, STATIC_DIR
from backend.security import session_tag


def _astronaut() -> dict:
    return json.loads(DEMO_CREDS_PATH.read_text(encoding="utf-8"))["web_demo_accounts"]["astronaut"]


def _private(resp) -> bool:
    cc = resp.headers.get("cache-control", "").lower()
    return "private" in cc or "no-store" in cc


def test_api_answers_are_never_stored():
    with TestClient(app) as client:
        for url in ("/api/auth/me", "/api/chat/status"):
            r = client.get(url)
            assert "no-store" in r.headers.get("cache-control", ""), url
            assert "cookie" in r.headers.get("vary", "").lower(), url

        astro = _astronaut()
        r = client.post(
            "/api/auth/login",
            json={"vitalverse_id": astro["vitalverse_id"], "password": astro["password"], "role": "astronaut"},
        )
        assert r.status_code == 200
        for url in ("/api/auth/me", f"/api/health/{astro['astronaut_id']}/dashboard"):
            r = client.get(url)
            assert r.status_code == 200, url
            assert "no-store" in r.headers.get("cache-control", ""), url


def test_pages_and_redirects_stay_out_of_shared_caches():
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200 and _private(home)
        gated = client.get("/health.html", follow_redirects=False)
        assert gated.status_code == 302 and _private(gated)


def test_static_assets_stay_cacheable():
    with TestClient(app) as client:
        r = client.get("/js/motion.js")
        assert r.status_code == 200
        assert not _private(r)


def _login(client: TestClient):
    astro = _astronaut()
    return client.post(
        "/api/auth/login",
        json={"vitalverse_id": astro["vitalverse_id"], "password": astro["password"], "role": "astronaut"},
    )


def test_sign_in_sets_readable_tag_of_the_hidden_session():
    with TestClient(app) as client:
        r = _login(client)
        assert r.status_code == 200
        raw = {c.split("=", 1)[0]: c for c in r.headers.get_list("set-cookie")}
        assert "httponly" in raw["vv_sessions"].lower()
        assert "httponly" not in raw["vv_tags"].lower(), "page scripts must be able to read the tag"
        assert client.cookies["vv_tags"] == session_tag(client.cookies["vv_sessions"])
        assert client.cookies["vv_tags"] != client.cookies["vv_sessions"]
        assert r.headers["x-vv-account-set"] == client.cookies["vv_tags"], "the tab is told which account it uses"


def test_every_api_answer_names_the_session_it_was_made_for():
    with TestClient(app) as client:
        assert client.get("/api/auth/me").headers["x-vv-tag"] == "anon"
        assert client.get("/api/chat/status").headers["x-vv-tag"] == "anon"
        _login(client)
        mine = client.cookies["vv_tags"]
        for url in ("/api/auth/me", "/api/chat/status", "/api/doctor/astronauts", "/api/health/A001/dashboard"):
            assert client.get(url).headers["x-vv-tag"] == mine, url   # also on errors (403 for the doctor list)


def test_tab_naming_an_account_this_browser_does_not_hold_is_signed_out():
    with TestClient(app) as client:
        _login(client)
        assert client.get("/api/auth/me").json()["authenticated"] is True
        for wanted in ("0123456789abcdef0123", "anon"):
            r = client.get("/api/auth/me", headers={"X-VV-Account": wanted})
            assert r.json()["authenticated"] is False, wanted
            assert r.headers["x-vv-tag"] == "anon"


def test_sign_out_removes_the_tag():
    with TestClient(app) as client:
        csrf = _login(client).json()["csrf_token"]
        r = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        assert r.headers["x-vv-account-set"] == "anon"
        assert "vv_tags" not in client.cookies and "vv_sessions" not in client.cookies


def test_fetch_guard_loads_before_every_other_script():
    pages = sorted(STATIC_DIR.glob("*.html"))
    assert pages
    for page in pages:
        srcs = re.findall(r'<script[^>]*\bsrc="([^"]+)"', page.read_text(encoding="utf-8"))
        if not srcs:
            continue
        assert "fetch-guard.js" in srcs[0], f"{page.name}: fetch-guard.js must be the first script, got {srcs[:2]}"


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


def test_browser_guard_discards_answers_meant_for_someone_else(live_server):
    """Simulate the relay: the first /api/auth/me answer belongs to another visitor, later ones are real."""
    stranger = json.dumps({"authenticated": True, "role": "doctor", "user": {"name": "Someone Else"}})
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(live_server + "/about.html")

        calls = {"n": 0}

        def mix_first(route):
            calls["n"] += 1
            if calls["n"] == 1:
                route.fulfill(status=200, body=stranger,
                              headers={"Content-Type": "application/json", "X-VV-Tag": "someone-else"})
            else:
                route.continue_()

        page.route("**/api/auth/me*", mix_first)
        result = page.evaluate("fetch('/api/auth/me').then(r => r.json().then(j => [r.status, j.authenticated]))")
        assert result == [200, False], "the stranger's answer must be replaced by this browser's real one"
        assert calls["n"] >= 2
        page.unroute("**/api/auth/me*")

        def always_mixed(route):
            route.fulfill(status=200, body=stranger,
                          headers={"Content-Type": "application/json", "X-VV-Tag": "someone-else"})

        page.route("**/api/auth/me*", always_mixed)
        result = page.evaluate("fetch('/api/auth/me').then(r => r.json().then(j => [r.status, j.authenticated === true]))")
        assert result == [503, False], "after the retries the page gets an error, never the stranger's data"
        browser.close()
