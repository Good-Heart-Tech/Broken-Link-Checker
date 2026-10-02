# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bot-block detection, the per-host circuit breaker, and the Thorough second-chance ladder.

See docs/BOT-BLOCKING.md. Short version: never call a bot-blocker's answer a broken link.
"""
import asyncio
import json
import random
import time
from pathlib import Path

DATA = json.loads((Path(__file__).resolve().parent.parent.parent / "data" / "known-hosts.json").read_text(encoding="utf-8"))
BLOCK_STATUSES = set(DATA["block_like_statuses"])
SIGNATURES = DATA["waf_signatures"]
SOCIAL = {h["host"] for h in DATA["never_check_by_default"]}
PROFILES = ["chrome", "safari", "firefox"]  # browser profile names understood by safe_fetch


def is_social(host: str) -> bool:
    return any(host == s or host.endswith("." + s) for s in SOCIAL)


def detect_waf(headers: dict, body: bytes = b"") -> str | None:
    """Name the bot-protection vendor if the response looks like its block or challenge page."""
    text = body[:4096].decode("utf-8", "ignore") if body else ""
    for sig in SIGNATURES:
        for name, needle in sig["headers"].items():
            if name.endswith("-"):  # prefix match such as x-px-
                if any(k.startswith(name) for k in headers):
                    return sig["vendor"]
            elif name in headers and needle.lower() in headers[name].lower():
                # a bare server header (cloudflare) only counts alongside a block-like status or body
                if name == "server":
                    continue
                return sig["vendor"]
        if any(m.lower() in text.lower() for m in sig["body"]):
            return sig["vendor"]
    return None


def server_matches(headers: dict) -> str | None:
    for sig in SIGNATURES:
        needle = sig["headers"].get("server")
        if needle and needle.lower() in headers.get("server", "").lower():
            return sig["vendor"]
    return None


def block_like(status: int, headers: dict, body: bytes = b"") -> tuple[bool, str | None]:
    """Return (looks like a block, vendor name if recognized)."""
    vendor = detect_waf(headers, body)
    if status in (404, 410):
        return (False, None) if not vendor else (True, vendor)
    if status == 503 and not vendor and not server_matches(headers):
        return False, None  # plain 503 is a real outage, not a block
    if status in BLOCK_STATUSES:
        return True, vendor or (server_matches(headers) if status in (403, 503) else None)
    if vendor and status >= 400:
        return True, vendor
    return False, vendor


class HostState:
    """Circuit breaker: if most of a host's first answers are blocks, stop knocking."""

    def __init__(self) -> None:
        self.total = 0
        self.blocked = 0
        self.protected = False
        self.vendor: str | None = None
        self.sample: str | None = None  # one URL the user can open to confirm

    def record(self, is_block: bool, vendor: str | None, url: str) -> None:
        self.total += 1
        if is_block:
            self.blocked += 1
            self.vendor = self.vendor or vendor
            self.sample = self.sample or url
        if not self.protected and self.total <= 8:
            if self.blocked >= 3 and self.blocked / self.total >= 0.6:
                self.protected = True


async def retry_host(root: str, items: list[str], check_once, budget: float) -> dict:
    """Thorough mode: try other browser profiles, prime cookies, pace gently.

    root: the site's home address (scheme and host), used to collect cookies first.
    items: URLs on this host that came back block-like.
    check_once(url, profile, referer) -> (CheckResult-like with .status/.error/.headers/.body)
    Returns {url: result} for the URLs we managed to get a real answer for.
    """
    deadline = time.monotonic() + budget
    results: dict = {}
    working = None
    for prof in PROFILES:
        r = await check_once(root, prof, None)
        if r is not None and not r["blocked"] and r["status"] and r["status"] < 400:
            working = prof
            break
        await asyncio.sleep(random.uniform(0.4, 1.0))
        if time.monotonic() > deadline:
            return results
    if working is None:
        return results
    order = [working] + [p for p in PROFILES if p != working]
    for url in items:
        if time.monotonic() > deadline:
            break
        for prof in order:
            r = await check_once(url, prof, root)
            if r is not None and not r["blocked"]:
                results[url] = r
                break
            await asyncio.sleep(random.uniform(0.5, 1.2))
    return results
