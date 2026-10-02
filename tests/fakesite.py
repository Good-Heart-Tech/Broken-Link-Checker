# SPDX-License-Identifier: AGPL-3.0-or-later
"""A tiny scripted website for tests: 404s, bot blocks, redirects, loops, soft 404s."""
import asyncio
import socket
import threading
import time

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route


def make_app(port_holder: dict) -> Starlette:
    def ext(path: str) -> str:
        # "localhost" counts as a different website than "127.0.0.1"
        return f"http://localhost:{port_holder['port']}{path}"

    async def home(request: Request):
        return HTMLResponse(f"""<html><head><title>Fake Nonprofit</title></head>
<body class="home page-id-42"><header><nav><a href="/a">About us</a> <a href="/missing">Old page</a></nav></header>
<main><h2>Get involved</h2>
<a href="/gone">Gone page</a> <a href="/moved">Moved page</a> <a href="/loop1">Loopy</a>
<a href="/head-hostile">Head hostile</a> <a href="/soft404">Soft</a> <a href="/private">Private</a>
<a href="/files/report.pdf">Report</a>
<img src="/img/missing.png" alt="Our logo">
<a href="{ext('/ext-ok')}">Partner</a> <a href="{ext('/ext-404')}">Dead partner</a>
<a href="{ext('/blocked')}">Tickets</a> <a href="{ext('/ratelimited')}">Busy</a>
<a href="{ext('/firefox-only')}">Picky</a>
<a href="http://nonexistent-host-for-tests.invalid/">Nowhere</a>
<a href="https://www.facebook.com/example">Facebook</a>
<a href="mailto:hello@example.org">Email us</a> <a href="/cdn-cgi/l/email-protection#abc">[email protected]</a>
</main><footer><a href="/b">Footer link</a></footer></body></html>""")

    async def page_a(request):
        return HTMLResponse('<html><head><title>About</title></head><body><main><a href="/b">B</a> <a href="/deadinsitemap-link">x</a></main></body></html>')

    async def page_b(request):
        return HTMLResponse('<html><head><title>B</title></head><body><a href="/">Home</a> <a href="/a">A</a></body></html>')

    async def robots(request):
        return PlainTextResponse(f"User-agent: *\nDisallow: /private\nSitemap: http://127.0.0.1:{port_holder['port']}/sitemap.xml\n")

    async def sitemap(request):
        base = f"http://127.0.0.1:{port_holder['port']}"
        return Response(f"<urlset><url><loc>{base}/a</loc></url><url><loc>{base}/deadinsitemap</loc></url></urlset>",
                        media_type="application/xml")

    async def missing(request):
        return PlainTextResponse("nope", status_code=404)

    async def gone(request):
        return PlainTextResponse("gone", status_code=410)

    async def moved(request):
        return RedirectResponse("/a", status_code=301)

    async def loop1(request):
        return RedirectResponse("/loop2", status_code=302)

    async def loop2(request):
        return RedirectResponse("/loop1", status_code=302)

    async def head_hostile(request):
        if request.method == "HEAD":
            return PlainTextResponse("", status_code=405)
        return HTMLResponse("<html><head><title>fine</title></head><body>ok</body></html>")

    async def soft404(request):
        return HTMLResponse("<html><head><title>Page Not Found</title></head><body>Sorry</body></html>")

    async def private(request):
        return HTMLResponse("<html><head><title>Private</title></head><body>hidden</body></html>")

    async def pdf(request):
        return Response(b"%PDF-1.4", media_type="application/pdf")

    async def ext_ok(request):
        return HTMLResponse("<html><head><title>Partner</title></head><body>hello</body></html>")

    async def blocked(request):
        return HTMLResponse("<html><title>Just a moment...</title></html>", status_code=403,
                            headers={"cf-mitigated": "challenge", "server": "cloudflare"})

    async def ratelimited(request):
        return PlainTextResponse("slow down", status_code=429, headers={"retry-after": "1"})

    async def firefox_only(request):
        ua = request.headers.get("user-agent", "")
        if "Firefox" in ua:
            return HTMLResponse("<html><head><title>Hi</title></head><body>welcome</body></html>")
        return PlainTextResponse("forbidden", status_code=403)

    async def slow(request):
        await asyncio.sleep(0.2)
        return HTMLResponse("<html><body>slow</body></html>")

    return Starlette(routes=[
        Route("/", home), Route("/a", page_a), Route("/b", page_b), Route("/robots.txt", robots),
        Route("/sitemap.xml", sitemap), Route("/missing", missing), Route("/gone", gone), Route("/moved", moved),
        Route("/loop1", loop1), Route("/loop2", loop2), Route("/head-hostile", head_hostile, methods=["GET", "HEAD"]),
        Route("/soft404", soft404), Route("/private", private), Route("/files/report.pdf", pdf),
        Route("/ext-ok", ext_ok), Route("/ext-404", missing), Route("/blocked", blocked),
        Route("/ratelimited", ratelimited), Route("/firefox-only", firefox_only), Route("/slow", slow),
        Route("/deadinsitemap", missing), Route("/deadinsitemap-link", missing),
        Route("/img/missing.png", missing), Route("/cdn-cgi/l/email-protection", missing),
    ])


class FakeSite:
    def __init__(self) -> None:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.holder = {"port": self.port}
        cfg = uvicorn.Config(make_app(self.holder), host="127.0.0.1", port=self.port, log_level="error")
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("fake site did not start")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"
