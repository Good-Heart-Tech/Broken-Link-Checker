# SPDX-License-Identifier: AGPL-3.0-or-later
"""End to end scans of the fake site, through the engine and through the HTTP API."""
import time

import pytest
from fastapi.testclient import TestClient

from app import limits
from app.main import app
from app.scans import Scan


def by_target(rows, bucket):
    return {r["target"].split("//", 1)[1].split("/", 1)[-1] if False else r["target"]: r for r in rows if r["bucket"] == bucket}


def tails(rows, bucket):
    return {r["target"].rsplit("/", 1)[-1] or "/" for r in rows if r["bucket"] == bucket}


@pytest.mark.asyncio
async def test_quick_scan(site):
    scan = Scan("scan", site.url, "site", "quick", {})
    await scan.execute()
    assert scan.state == "done", scan.error
    rows = scan.rows
    broken = tails(rows, "broken")
    assert {"missing", "gone", "loop1", "ext-404", "missing.png", "deadinsitemap", "deadinsitemap-link"} <= broken
    assert any("nonexistent-host" in r["target"] and r["reason"] == "dns_failure" for r in rows)
    blocked = tails(rows, "blocked")
    assert {"blocked", "ratelimited", "firefox-only"} <= blocked
    assert any(r["reason"] == "blocked_waf" and r["vendor"] == "Cloudflare" for r in rows)
    warn = {r["target"].rsplit("/", 1)[-1]: r["reason"] for r in rows if r["bucket"] == "warning"}
    assert warn.get("moved") == "redirect_permanent" and warn.get("soft404") == "soft_404"
    ok = tails(rows, "ok")
    assert {"head-hostile", "ext-ok", "report.pdf", "a", "b", "private"} <= ok
    skipped = {r["reason"] for r in rows if r["bucket"] == "skipped"}
    assert "social_skipped" in skipped
    assert not any(r["target"].startswith("mailto") for r in rows)
    assert not any("cdn-cgi" in r["target"] for r in rows)  # Cloudflare's own link, not a real page
    # robots.txt keeps /private from being crawled but it is still checked
    assert scan.stats["pages_scanned"] >= 4
    # every broken row carries what a person needs
    row = next(r for r in rows if r["target"].endswith("/missing") and r["page"].endswith("/"))
    assert row["text"] == "Old page" and row["where"] == "Menu" and row["title"].startswith("Page not found")
    assert scan.profile_data["id"] == "unknown"
    # WordPress edit link only appears on WordPress sites
    assert not any(r.get("editUrl") for r in rows)


@pytest.mark.asyncio
async def test_single_page_scope(site):
    scan = Scan("scan", site.url, "page", "quick", {})
    await scan.execute()
    assert scan.state == "done"
    assert scan.stats["pages_scanned"] == 1
    assert "deadinsitemap-link" not in tails(scan.rows, "broken")  # lives on /a, which is not crawled


@pytest.mark.asyncio
async def test_thorough_second_chance(site):
    scan = Scan("scan", site.url, "site", "thorough", {})
    await scan.execute()
    assert scan.state == "done", scan.error
    # a Firefox-only page is verified by the ladder; the Cloudflare challenge stays "could not verify"
    assert "firefox-only" not in tails(scan.rows, "blocked")
    assert "firefox-only" in tails(scan.rows, "ok")
    assert "blocked" in tails(scan.rows, "blocked")
    assert any(n["host"] == "localhost" for n in scan.host_notes)


@pytest.mark.asyncio
async def test_start_errors():
    scan = Scan("scan", "https://nonexistent-host-for-tests.invalid/", "site", "quick", {})
    await scan.execute()
    assert scan.state == "error" and scan.error["code"] == "dns_failure"


@pytest.mark.asyncio
async def test_recheck(site):
    items = [{"target": site.url + "missing", "page": site.url, "text": "Old page", "element": "a", "where": "Menu", "snippet": ""},
             {"target": site.url + "a", "page": site.url, "text": "About", "element": "a", "where": "Menu", "snippet": ""}]
    scan = Scan("recheck", site.url, "page", "quick", {"items": items, "site": site.url})
    await scan.execute()
    assert scan.state == "done"
    assert tails(scan.rows, "broken") == {"missing"}
    assert "a" in tails(scan.rows, "ok")


def test_api_flow(site):
    limits.reset()
    with TestClient(app) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        r = client.post("/api/scans", json={"url": site.url, "mode": "quick", "scope": "site"})
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        snap = {}
        for _ in range(100):
            snap = client.get(f"/api/scans/{sid}").json()
            if snap["state"] in ("done", "error"):
                break
            time.sleep(0.2)
        assert snap["state"] == "done"
        assert snap["stats"]["broken"] >= 5
        # the live stream replays everything and ends
        with client.stream("GET", f"/api/scans/{sid}/events") as s:
            body = "".join(s.iter_text())
        assert "event: profile" in body and "event: rows" in body and "event: done" in body
        # reconnect after the first event only replays later ones
        with client.stream("GET", f"/api/scans/{sid}/events", headers={"Last-Event-ID": "5"}) as s:
            later = "".join(s.iter_text())
        assert "id: 5\n" not in later and "event: done" in later
        assert client.get("/api/scans/nope").status_code == 404
        bad = client.post("/api/scans", json={"url": "not a url"})
        assert bad.status_code == 400
        denied = client.post("/api/scans", json={"url": "https://nonprofittools.org"})
        assert denied.status_code == 400
        rc = client.post("/api/recheck", json={"items": [{"target": site.url + "missing", "page": site.url}], "site": site.url})
        assert rc.status_code == 200


def test_rate_limit(site, monkeypatch):
    import dataclasses
    from app import config
    limits.reset()
    monkeypatch.setattr(config, "CONFIG", dataclasses.replace(config.CONFIG, rate_limit_per_hour=2))
    with TestClient(app) as client:
        codes = [client.post("/api/scans", json={"url": site.url, "scope": "page"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    limits.reset()
