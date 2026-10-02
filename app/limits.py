# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-visitor rate limit and client address lookup. In memory only."""
import time
from collections import defaultdict, deque

from fastapi import Request

from app import config

WINDOW = 3600
_hits: dict[str, deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    """Behind Cloudflare or a host proxy the real address arrives in a header."""
    h = request.headers
    ip = h.get("cf-connecting-ip") or (h.get("x-forwarded-for", "").split(",")[0].strip()) or h.get("x-real-ip")
    return ip or (request.client.host if request.client else "unknown")


def allow(ip: str) -> bool:
    """Record one scan start. False when the visitor is over the hourly limit."""
    now = time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > WINDOW:
        q.popleft()
    if len(q) >= config.CONFIG.rate_limit_per_hour:
        return False
    q.append(now)
    if len(_hits) > 5000:  # keep memory bounded
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > WINDOW]:
            _hits.pop(k, None)
    return True


def reset() -> None:
    _hits.clear()
