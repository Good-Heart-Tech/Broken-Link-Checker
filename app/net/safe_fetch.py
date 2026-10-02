# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ONLY place this app makes outbound requests.

Safety rules (see docs/PLAN.md section 8):
- http and https only, ports 80 and 443 only
- DNS is resolved here and every address must be public
- each connection is pinned to the validated addresses (no DNS rebinding)
- redirects are followed by hand so every hop is validated again
- bodies are read only up to a small cap
"""
import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from curl_cffi import CurlOpt, requests
from curl_cffi.requests.exceptions import RequestException

from app import config
from app.net.urlnorm import normalize

MAX_HOPS = 10
MAX_SESSIONS = 100
REDIRECT_CODES = {301, 302, 303, 307, 308}

# curl error numbers worth naming
CURL_DNS = {6}
CURL_REFUSED = {7}
CURL_TIMEOUT = {28}
CURL_TLS = {35, 51, 53, 54, 58, 59, 60, 64, 66, 77, 80, 82, 83, 90, 91}


@dataclass
class Resp:
    url: str
    status: int = 0
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    error: str | None = None  # dns_failure, connection_refused, timeout, tls_error, unsafe_target, error
    ms: int = 0
    ip: str = ""


@dataclass
class Followed:
    final: Resp
    chain: list  # [(url, status), ...] for every hop including the last
    error: str | None = None  # redirect_loop or too_many_redirects


def is_public_ip(ip: str) -> bool:
    if config.CONFIG.allow_private_targets:
        return True
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


class Fetcher:
    """One per scan. Holds pinned sessions (one per host and browser profile) and a DNS cache."""

    def __init__(self) -> None:
        self._sessions: dict[tuple, requests.AsyncSession] = {}
        self._inflight: dict[tuple, int] = {}
        self._dns: dict[tuple, list[str] | str] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}
        self._global = asyncio.Semaphore(config.CONFIG.concurrency_global)

    async def close(self) -> None:
        sessions, self._sessions = list(self._sessions.values()), {}
        for s in sessions:
            try:
                await s.close()
            except Exception:
                pass

    async def _resolve(self, host: str, port: int):
        """Return a list of public IPs, or an error string."""
        key = (host, port)
        if key in self._dns:
            return self._dns[key]
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            self._dns[key] = "dns_failure"
            return "dns_failure"
        ips = list(dict.fromkeys(i[4][0] for i in infos))
        if not ips:
            self._dns[key] = "dns_failure"
        elif not all(is_public_ip(ip) for ip in ips):
            self._dns[key] = "unsafe_target"
        else:
            self._dns[key] = ips
        return self._dns[key]

    async def _session(self, host: str, port: int, profile: str, ips: list[str], proxy: bool):
        key = (host, port, profile, proxy)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            sess = self._sessions.get(key)
            if sess is None:
                await self._evict()
                opts = {CurlOpt.RESOLVE: [f"{host}:{port}:{','.join(ips)}"]}
                sess = requests.AsyncSession(
                    impersonate=profile, curl_options=opts, max_clients=10,
                    proxy=config.CONFIG.proxy_url if proxy and config.CONFIG.proxy_url else None,
                )
                self._sessions[key] = sess
                self._inflight[key] = 0
            return key, sess

    async def _evict(self) -> None:
        if len(self._sessions) < MAX_SESSIONS:
            return
        for key in list(self._sessions):
            if self._inflight.get(key, 0) == 0:
                sess = self._sessions.pop(key)
                try:
                    await sess.close()
                except Exception:
                    pass
                return

    async def fetch(self, url: str, method: str = "GET", *, profile: str = "chrome", referer: str | None = None,
                    body_limit: int = 0, headers: dict | None = None, timeout: float = 15,
                    proxy: bool = False) -> Resp:
        """One request, no redirects. Never raises: problems come back in Resp.error."""
        parts = urlsplit(url)
        host = parts.hostname or ""
        scheme = parts.scheme
        port = parts.port or (443 if scheme == "https" else 80)
        if scheme not in ("http", "https") or not host:
            return Resp(url, error="unsafe_target")
        if port not in (80, 443) and not config.CONFIG.allow_private_targets:
            return Resp(url, error="unsafe_target")
        ips = await self._resolve(host, port)
        if isinstance(ips, str):
            return Resp(url, error=ips)

        key, sess = await self._session(host, port, profile, ips, proxy)
        h = dict(headers or {})
        if config.CONFIG.ident_header:
            h["X-Scanner"] = config.CONFIG.ident_header
        self._inflight[key] = self._inflight.get(key, 0) + 1
        t0 = time.monotonic()
        try:
            async with self._global:
                r = await sess.request(method, url, headers=h, referer=referer, timeout=timeout,
                                       allow_redirects=False, stream=True)
                try:
                    ip = getattr(r, "primary_ip", "") or ""
                    if ip and not is_public_ip(ip):
                        return Resp(url, error="unsafe_target")
                    body = b""
                    if body_limit and method != "HEAD" and r.status_code not in REDIRECT_CODES:
                        async for chunk in r.aiter_content():
                            body += chunk
                            if len(body) >= body_limit:
                                body = body[:body_limit]
                                break
                    hdrs = {k.lower(): v for k, v in r.headers.items()}
                    return Resp(url, r.status_code, hdrs, body, None, int((time.monotonic() - t0) * 1000), ip)
                finally:
                    try:
                        await r.aclose()
                    except Exception:
                        pass
        except RequestException as e:
            return Resp(url, error=_map_error(e), ms=int((time.monotonic() - t0) * 1000))
        except Exception:
            return Resp(url, error="error", ms=int((time.monotonic() - t0) * 1000))
        finally:
            self._inflight[key] = max(0, self._inflight.get(key, 1) - 1)

    async def fetch_follow(self, url: str, method: str = "GET", *, max_hops: int = MAX_HOPS, **kw) -> Followed:
        """Follow redirects by hand, re-validating every hop."""
        chain: list = []
        seen = {url}
        cur = url
        for _ in range(max_hops + 1):
            r = await self.fetch(cur, method, **kw)
            chain.append((cur, r.status))
            loc = r.headers.get("location") if r.status in REDIRECT_CODES else None
            if r.error or not loc:
                return Followed(r, chain)
            nxt = normalize(urljoin(cur, loc))
            if not nxt:
                return Followed(r, chain)
            if nxt in seen:
                return Followed(r, chain, "redirect_loop")
            seen.add(nxt)
            if r.status == 303:
                method = "GET"
            cur = nxt
        return Followed(r, chain, "too_many_redirects")


def _map_error(e: RequestException) -> str:
    code = getattr(e, "code", None)
    text = str(e).lower()
    if code in CURL_DNS or "could not resolve" in text:
        return "dns_failure"
    if code in CURL_REFUSED:
        return "connection_refused"
    if code in CURL_TIMEOUT or "timed out" in text:
        return "timeout"
    if code in CURL_TLS or "ssl" in text or "certificate" in text:
        return "tls_error"
    return "error"
