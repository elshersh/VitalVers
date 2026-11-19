"""Answers that depend on the signed-in user must never be stored by a shared cache.

The public Codespaces link runs behind a relay that caches GET responses by URL when the server does not
forbid it; without these headers one visitor could receive another visitor's identity or health data.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import app
from backend.config import DEMO_CREDS_PATH


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
