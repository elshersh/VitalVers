"""Playwright verification that all static frontend pages run strictly offline.

Ensures:
- Zero requests leave localhost / 127.0.0.1 (no Google Fonts or external CDN fetches).
- Local Inter (400/500/600/700) and Space Grotesk (500/600/700) woff2 + SIL OFL licenses exist.
- Fonts actually load in Chromium via local @font-face rules with zero page errors.
"""
from __future__ import annotations

import functools
import http.server
from pathlib import Path
import threading
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"

PAGES = [
    "index.html",
    "about.html",
    "todo.html",
    "mental.html",
    "mental.html?view=doctor",
    "login.html",
    "signup.html",
    "astronaut-dashboard.html",
    "doctor-dashboard.html",
    "chatbot.html",
    "404.html",
    "error.html",
]


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def _serve_static():
    handler = functools.partial(_QuietHandler, directory=str(STATIC_DIR))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def test_local_font_files_and_ofl_licenses_present():
    fonts_dir = STATIC_DIR / "fonts"
    expected_files = [
        "Inter-OFL.txt",
        "SpaceGrotesk-OFL.txt",
        "inter-latin-400-normal.woff2",
        "inter-latin-500-normal.woff2",
        "inter-latin-600-normal.woff2",
        "inter-latin-700-normal.woff2",
        "space-grotesk-latin-500-normal.woff2",
        "space-grotesk-latin-600-normal.woff2",
        "space-grotesk-latin-700-normal.woff2",
    ]
    for name in expected_files:
        p = fonts_dir / name
        assert p.is_file() and p.stat().st_size > 1000, f"Missing or empty font/license asset: {p}"

    for html_file in STATIC_DIR.glob("*.html"):
        text = html_file.read_text(encoding="utf-8")
        assert "fonts.googleapis.com" not in text, f"External Google Fonts link remains in {html_file.name}"
        assert "fonts.gstatic.com" not in text, f"External Google Fonts link remains in {html_file.name}"


def test_playwright_zero_external_requests_and_local_fonts_loaded():
    httpd, port = _serve_static()
    base_url = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            for rel_url in PAGES:
                page = context.new_page()
                external_requests: list[str] = []
                page_errors: list[str] = []
                bad_non_api_assets: list[str] = []

                def _on_request(req, ext=external_requests):
                    parsed = urlparse(req.url)
                    if parsed.scheme in ("data", "blob"):
                        return
                    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
                        ext.append(req.url)

                def _on_response(resp, bad=bad_non_api_assets):
                    if resp.status >= 400 and resp.url.startswith(base_url):
                        path_only = urlparse(resp.url).path
                        if not path_only.startswith("/api/"):
                            bad.append(f"{resp.status} {path_only}")

                page.on("request", _on_request)
                page.on("response", _on_response)
                page.on("pageerror", lambda err, errs=page_errors: errs.append(str(err)))

                page.goto(f"{base_url}/{rel_url}", wait_until="load", timeout=10000)
                font_info = page.evaluate(
                    """async () => {
                        await document.fonts.ready;
                        const loaded = [];
                        for (const f of document.fonts) {
                            if (f.status === 'loaded') loaded.push(f.family + ':' + f.weight);
                        }
                        return { total: document.fonts.size, loaded: Array.from(new Set(loaded)) };
                    }"""
                )
                assert not external_requests, f"{rel_url} made external requests: {external_requests}"
                assert not page_errors, f"{rel_url} raised pageerror: {page_errors}"
                assert not bad_non_api_assets, f"{rel_url} failed local assets: {bad_non_api_assets}"
                assert font_info["total"] > 0 and len(font_info["loaded"]) > 0, (
                    f"{rel_url} did not load any local @font-face fonts: {font_info}"
                )
                page.close()
            context.close()
            browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
