"""Vitalverse FastAPI web application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager
import re
import sqlite3
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.config import STATIC_DIR, TAG_HEADER
from backend.database import get_db, init_web_tables
from backend.routers import alerts, auth, chat, doctor, health, mental, predict, profile, todo, uploads
from backend.security import get_session_user, request_tag
from backend.services.chat_service import ChatService
from backend.services.model_service import ModelService


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialize additive web schema and load AI model + chatbot once at startup."""
    init_web_tables()
    application.state.model_service = ModelService()
    application.state.chat_service = ChatService()
    yield


app = FastAPI(title="Vitalverse Health Monitoring", lifespan=lifespan)


_STATIC_ASSET = re.compile(r"\.(css|js|mjs|map|png|jpe?g|gif|webp|svg|ico|woff2?|ttf|mp3|wav|ogg)$", re.IGNORECASE)


@app.middleware("http")
async def set_cache_headers(request: Request, call_next):
    """Keep answers that depend on the signed-in user out of shared caches, and label whose answer it is.

    The public link can run behind a forwarding relay (GitHub Codespaces) that was seen handing one visitor's
    answer to another. API answers, pages and redirects can differ per user, so only the browser may keep them:
    API answers are never stored, pages are re-checked with the server (ETag) every time. Static assets
    (styles, scripts, images, fonts) are the same for everyone and stay cacheable. Every API answer also
    carries the tag of the session it was made for, which the page compares with its own tag.
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/"):
        # tell the page which session this answer was made for (static/js/fetch-guard.js checks it)
        response.headers[TAG_HEADER] = request_tag(request)
    if not _STATIC_ASSET.search(path):
        if "cache-control" not in response.headers:
            api = path.startswith("/api/")
            response.headers["Cache-Control"] = "no-store, private" if api else "private, no-cache"
        vary = response.headers.get("vary", "")
        if "cookie" not in vary.lower():
            response.headers["Vary"] = f"{vary}, Cookie" if vary else "Cookie"
    return response

app.include_router(auth.router)
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(uploads.router)
app.include_router(alerts.router)
app.include_router(todo.router)
app.include_router(mental.router)
app.include_router(profile.router)
app.include_router(doctor.router)
app.include_router(predict.router)


def _read_static_html(filename: str) -> str:
    return (STATIC_DIR / filename).read_text(encoding="utf-8")


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Serve themed Vitalverse 404 HTML for browser routes; preserve JSON errors for /api/*."""
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if exc.status_code == 404:
        return HTMLResponse(_read_static_html("404.html"), status_code=404)
    return HTMLResponse(_read_static_html("error.html"), status_code=exc.status_code)


@app.exception_handler(Exception)
async def custom_server_error_handler(request: Request, exc: Exception):
    """Serve themed Vitalverse 500 error page for browser routes; JSON for /api/*."""
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Internal server error."}, status_code=500)
    return HTMLResponse(_read_static_html("error.html"), status_code=500)


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
def serve_home():
    """Serve the Vitalverse landing page."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health.html", include_in_schema=False)
def serve_health_dashboard(
    request: Request,
    user: dict[str, Any] | None = Depends(get_session_user),
    _con: sqlite3.Connection = Depends(get_db),
):
    """Route authenticated users by server-side session role; ignore ?view= and ?astronaut= params."""
    if user is None:
        return RedirectResponse(url="/login.html", status_code=302)
    if user["role"] == "doctor":
        return FileResponse(STATIC_DIR / "doctor-dashboard.html")
    return FileResponse(STATIC_DIR / "astronaut-dashboard.html")


@app.get("/astronaut-dashboard.html", include_in_schema=False)
@app.get("/doctor-dashboard.html", include_in_schema=False)
def redirect_direct_dashboards():
    """Always enforce server-side session routing through /health.html."""
    return RedirectResponse(url="/health.html", status_code=302)


def _gated_page(page_name: str, request: Request, con: sqlite3.Connection):
    """Gate authenticated HTML pages and redirect anonymous visitors to /login.html."""
    if get_session_user(request, con) is None:
        return RedirectResponse(url=f"/login.html?next=/{page_name}", status_code=302)
    return FileResponse(STATIC_DIR / page_name)


@app.get("/chatbot.html", include_in_schema=False)
def serve_chatbot():
    """Serve the Offline AI Chatbot page."""
    return FileResponse(STATIC_DIR / "chatbot.html")


@app.get("/todo.html", include_in_schema=False)
def serve_todo(request: Request, con: sqlite3.Connection = Depends(get_db)):
    """Serve the Daily Routine To-Do page for authenticated users."""
    return _gated_page("todo.html", request, con)


@app.get("/mental.html", include_in_schema=False)
def serve_mental(request: Request, con: sqlite3.Connection = Depends(get_db)):
    """Serve the Mental Health Check-In page for authenticated users."""
    return _gated_page("mental.html", request, con)


@app.get("/profile.html", include_in_schema=False)
def serve_profile(request: Request, con: sqlite3.Connection = Depends(get_db)):
    """Serve the Profile & Doctor Access Approval page for authenticated users."""
    return _gated_page("profile.html", request, con)


@app.get("/alerts.html", include_in_schema=False)
def serve_alerts(request: Request, con: sqlite3.Connection = Depends(get_db)):
    """Serve the Alerts Center page for authenticated users."""
    return _gated_page("alerts.html", request, con)


@app.get("/manifest.json", include_in_schema=False)
def serve_manifest():
    """Serve the PWA Web App Manifest."""
    return FileResponse(STATIC_DIR / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def serve_sw():
    """Serve the Web Push Service Worker at root scope."""
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
