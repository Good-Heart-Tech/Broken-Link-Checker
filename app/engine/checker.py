# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check one URL and sort the answer into a bucket.

Buckets: broken, blocked (could not verify), warning (worth a look), ok, skipped.
Rule worth remembering: 404 and 410 are always broken, bot-blocker answers never are.
"""
import asyncio
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.engine.extract import SOFT_404
from app.net.ladder import block_like
from app.net.safe_fetch import Fetcher, Followed
from app.net.urlnorm import host_of, strip_www, trivial_redirect

SLOW_MS = 8000
TITLE = re.compile(rb"<title[^>]*>(.*?)</title>", re.I | re.S)


@dataclass
class Check:
    url: str
    status: int = 0
    error: str | None = None
    chain: list = field(default_factory=list)
    final_url: str = ""
    headers: dict = field(default_factory=dict)
    ms: int = 0
    blocked: bool = False
    vendor: str | None = None
    soft404: bool = False
    body: bytes = b""


def build_check(url: str, f: Followed) -> Check:
    r = f.final
    c = Check(url=url, status=r.status, error=f.error or r.error, chain=f.chain,
              final_url=r.url, headers=r.headers, ms=r.ms, body=r.body)
    if not c.error:
        c.blocked, c.vendor = block_like(c.status, r.headers, r.body)
        ctype = r.headers.get("content-type", "")
        if c.status == 200 and "html" in ctype and r.body:
            m = TITLE.search(r.body[:16384])
            if m:
                c.soft404 = bool(SOFT_404.search(m.group(1).decode("utf-8", "ignore")[:200]))
    return c


async def check_url(fetcher: Fetcher, url: str, referer: str | None = None, *, profile: str = "chrome",
                    ranged: bool = False, proxy: bool = False) -> Check:
    """HEAD first, then GET when HEAD is refused or fails. One retry for timeouts and server errors."""
    kw = {"profile": profile, "referer": referer, "proxy": proxy}
    f = await fetcher.fetch_follow(url, "HEAD", timeout=12, **kw)
    r = f.final
    if not f.error and not r.error and 200 <= r.status < 300:
        return build_check(url, f)
    if r.error in ("dns_failure", "connection_refused", "tls_error", "unsafe_target"):
        return build_check(url, f)

    headers = {"Range": "bytes=0-1023"} if ranged else None
    f = await fetcher.fetch_follow(url, "GET", body_limit=8192, timeout=15, headers=headers, **kw)
    r = f.final
    if r.error in ("timeout", "error") or r.status >= 500:
        await asyncio.sleep(0.6)
        f = await fetcher.fetch_follow(url, "GET", body_limit=8192, timeout=15, headers=headers, **kw)
    return build_check(url, f)


def classify(c: Check) -> tuple[str, str, int]:
    """Return (bucket, reason, code) for a finished check."""
    if c.error in ("redirect_loop", "too_many_redirects", "dns_failure", "connection_refused", "tls_error", "timeout", "error"):
        return "broken", c.error, 0
    if c.error == "unsafe_target":
        return "skipped", "unsafe_target", 0
    s = c.status
    if c.blocked:
        if s == 429:
            return "blocked", "rate_limited", s
        if s == 401:
            return "blocked", "auth_required", s
        return "blocked", ("blocked_waf" if c.vendor else "blocked"), s
    if s in (404, 410):
        return "broken", f"http_{s}", s
    if s >= 500:
        return "broken", "http_5xx", s
    if s >= 400:
        return "broken", "http_4xx", s
    if 300 <= s < 400:  # redirect without a usable Location header
        return "broken", "http_4xx", s
    if s == 0:
        return "broken", "error", 0

    orig, final = c.url, c.final_url or c.url
    o, f = urlsplit(orig), urlsplit(final)
    if c.soft404:
        return "warning", "soft_404", s
    if len(c.chain) > 1:
        if o.scheme == "http" and f.scheme == "https" and strip_www(host_of(orig)) == strip_www(host_of(final)):
            return "warning", "http_to_https", s
        if (f.path in ("", "/") and o.path not in ("", "/") and strip_www(host_of(orig)) == strip_www(host_of(final))):
            return "warning", "redirect_home", s
        if c.chain[0][1] in (301, 308) and not trivial_redirect(orig, final):
            return "warning", "redirect_permanent", s
    if c.ms > SLOW_MS:
        return "warning", "slow", s
    return "ok", "ok", s
