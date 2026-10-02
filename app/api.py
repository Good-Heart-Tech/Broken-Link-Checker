# SPDX-License-Identifier: AGPL-3.0-or-later
"""HTTP routes. See docs/PLAN.md section 6.3."""
import asyncio
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import config, limits
from app.messages import START_ERRORS
from app.net.urlnorm import clean_user_input, host_of, normalize, strip_www
from app.scans import MANAGER, Busy, Scan

router = APIRouter(prefix="/api")


class StartBody(BaseModel):
    url: str = Field(max_length=2048)
    scope: Literal["site", "page"] = "site"
    mode: Literal["quick", "thorough"] = "quick"
    check_social: bool = False


class RecheckItem(BaseModel):
    target: str = Field(max_length=2048)
    page: str = Field("", max_length=2048)
    text: str = Field("", max_length=300)
    element: str = Field("a", max_length=12)
    where: str = Field("", max_length=300)
    snippet: str = Field("", max_length=400)


class RecheckBody(BaseModel):
    items: list[RecheckItem]
    mode: Literal["quick", "thorough"] = "quick"
    site: str = Field("", max_length=2048)


def _denied(url: str) -> bool:
    h = strip_www(host_of(url))
    return any(h == d or h.endswith("." + d) for d in config.CONFIG.deny_hosts)


def _submit(request: Request, scan: Scan) -> dict:
    if not limits.allow(limits.client_ip(request)):
        raise HTTPException(429, "You have started a few scans in the last hour. Please try again a little later.")
    try:
        position = MANAGER.submit(scan)
    except Busy:
        raise HTTPException(503, "We are busy right now. Please try again in a few minutes.")
    return {"id": scan.id, "position": position}


@router.post("/scans")
async def start_scan(body: StartBody, request: Request):
    url = clean_user_input(body.url)
    if not url:
        raise HTTPException(400, START_ERRORS["invalid"])
    if _denied(url):
        raise HTTPException(400, START_ERRORS["denied"])
    scan = Scan("scan", url, body.scope, body.mode, {"check_social": body.check_social}, scheme_given="://" in body.url)
    return _submit(request, scan)


@router.post("/recheck")
async def recheck(body: RecheckBody, request: Request):
    items = []
    for it in body.items[: config.CONFIG.recheck_max]:
        target = normalize(it.target)
        if target and not _denied(target):
            items.append({**it.model_dump(), "target": target})
    if not items:
        raise HTTPException(400, "Nothing to check.")
    site = normalize(body.site) or ""
    scan = Scan("recheck", site, "page", body.mode, {"items": items, "site": site})
    return _submit(request, scan)


def _get(scan_id: str) -> Scan:
    scan = MANAGER.get(scan_id)
    if not scan:
        raise HTTPException(404, "This scan has expired or does not exist. Please start again.")
    return scan


@router.get("/scans/{scan_id}")
async def snapshot(scan_id: str):
    scan = _get(scan_id)
    return {**scan.snapshot(), "position": MANAGER.position(scan)}


@router.post("/scans/{scan_id}/pause")
async def pause(scan_id: str):
    _get(scan_id).pause()
    return {"ok": True}


@router.post("/scans/{scan_id}/resume")
async def resume(scan_id: str):
    _get(scan_id).resume()
    return {"ok": True}


@router.post("/scans/{scan_id}/cancel")
async def cancel(scan_id: str):
    MANAGER.cancel(_get(scan_id))
    return {"ok": True}


@router.get("/scans/{scan_id}/events")
async def events(scan_id: str, request: Request):
    scan = _get(scan_id)
    try:
        last = int(request.headers.get("last-event-id", "0"))
    except ValueError:
        last = 0

    async def stream():
        sub = scan.subscribe()
        idx = last
        try:
            yield "retry: 2000\n\n"
            while True:
                sub.clear()
                batch = scan.events_after(idx)
                for eid, etype, data in batch:
                    idx = eid
                    yield f"id: {eid}\nevent: {etype}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
                if scan.finished and not scan.events_after(idx):
                    return
                try:
                    await asyncio.wait_for(sub.wait(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            scan.unsubscribe(sub)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
