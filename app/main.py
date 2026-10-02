# SPDX-License-Identifier: AGPL-3.0-or-later
"""Broken Link Checker: app entry point."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.scans import MANAGER

VERSION = "1.0.0"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# The Nonprofit Tools Hub embeds tools in an iframe, so allow only those origins.
CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "base-uri 'none'; form-action 'self'; "
    "frame-ancestors https://nonprofittools.org https://*.nonprofittools.org"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    MANAGER.start()
    yield
    MANAGER.stop()


app = FastAPI(title="Broken Link Checker", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    path = request.url.path
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif path.endswith((".png", ".ico", ".woff2")):
        response.headers["Cache-Control"] = "public, max-age=86400"
    else:
        # Pages, scripts and styles: always ask the server if they changed, so updates show up right away
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/healthz")
def healthz():
    return {"status": "ok", "app": "broken-link-checker", "version": VERSION}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
