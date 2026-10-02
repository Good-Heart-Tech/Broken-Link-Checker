# SPDX-License-Identifier: AGPL-3.0-or-later
"""Broken Link Checker: app entry point.

Shell only. Scan routes arrive in Milestone 3, see docs/PLAN.md.
"""
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# The Nonprofit Tools Hub embeds tools in an iframe, so allow only those origins.
CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors https://nonprofittools.org https://*.nonprofittools.org"
)

app = FastAPI(title="Broken Link Checker", docs_url=None, redoc_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/healthz")
def healthz():
    return {"status": "ok", "env": os.getenv("ENV", "production")}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
