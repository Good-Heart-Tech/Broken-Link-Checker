# SPDX-License-Identifier: AGPL-3.0-or-later
import dataclasses
import pathlib

import pytest

from app import config
from app.engine import profiler
from app.engine.checker import Check, classify
from app.engine.extract import extract
from app.engine.suggest import did_you_mean
from app.net import ladder
from app.net.safe_fetch import Fetcher, is_public_ip
from app.net.urlnorm import clean_user_input, dedupe_key, normalize, same_site, trivial_redirect


def test_normalize_and_input():
    assert clean_user_input("Example.ORG") == "https://example.org/"
    assert clean_user_input("http://example.org:80/a#frag") == "http://example.org/a"
    assert clean_user_input("not a url") is None
    assert normalize("mailto:a@b.c") is None
    assert normalize("javascript:void(0)") is None
    assert normalize("//cdn.x.org/a.js", "https://x.org/") == "https://cdn.x.org/a.js"
    assert normalize("https://user:pw@x.org/") is None
    assert normalize("../up", "https://x.org/a/b/c") == "https://x.org/a/up"
    assert dedupe_key("https://x.org/a?utm_source=z&id=1") == "https://x.org/a?id=1"
    assert same_site("https://www.x.org/a", "https://x.org/b")
    assert not same_site("https://blog.x.org/", "https://x.org/")
    assert trivial_redirect("https://x.org/about", "https://x.org/about/")


def test_extract_context():
    html = """<html><head><title>About</title><link rel="canonical" href="/about"><link rel="stylesheet" href="/s.css"></head>
    <body class="page-id-7"><nav><a href="/x">Menu item</a></nav>
    <main><h2>Our team</h2><a href="/y"><img src="/p.png" alt="Pat"></a><a href="/z"></a>
    <a href="mailto:a@b.c">mail</a><img src="/n.png"></main><footer><a href="/f">Foot</a></footer></body></html>"""
    info = extract(html, "https://x.org/about")
    by = {l.target: l for l in info.links}
    assert info.title == "About" and info.wp_id == 7
    assert "https://x.org/about" not in by  # canonical is not a link to check
    assert by["https://x.org/s.css"].element == "link"
    assert by["https://x.org/x"].where == "Menu"
    assert by["https://x.org/y"].text == 'Image: alt "Pat"'
    assert by["https://x.org/y"].where == "Main content, under 'Our team'"
    assert by["https://x.org/z"].text == "(no link text)"
    assert by["https://x.org/n.png"].text == "Image (no alt text)"
    assert by["https://x.org/f"].where == "Footer"
    assert not any(l.target.startswith("mailto") for l in info.links)


def _c(status=200, **kw):
    return Check(url=kw.pop("url", "https://x.org/a"), status=status, final_url=kw.pop("final_url", "https://x.org/a"),
                 chain=kw.pop("chain", [("https://x.org/a", status)]), **kw)


def test_classify_rules():
    assert classify(_c(200))[:2] == ("ok", "ok")
    assert classify(_c(404))[:2] == ("broken", "http_404")
    assert classify(_c(410))[:2] == ("broken", "http_410")
    assert classify(_c(500))[:2] == ("broken", "http_5xx")
    assert classify(_c(403, blocked=True, vendor="Cloudflare"))[:2] == ("blocked", "blocked_waf")
    assert classify(_c(403, blocked=True))[:2] == ("blocked", "blocked")
    assert classify(_c(429, blocked=True))[:2] == ("blocked", "rate_limited")
    assert classify(Check(url="u", error="dns_failure"))[:2] == ("broken", "dns_failure")
    assert classify(_c(200, soft404=True))[:2] == ("warning", "soft_404")
    moved = _c(200, chain=[("https://x.org/old", 301), ("https://x.org/new", 200)], url="https://x.org/old", final_url="https://x.org/new")
    assert classify(moved)[:2] == ("warning", "redirect_permanent")
    slash = _c(200, chain=[("https://x.org/old", 301), ("https://x.org/old/", 200)], url="https://x.org/old", final_url="https://x.org/old/")
    assert classify(slash)[:2] == ("ok", "ok")
    home = _c(200, chain=[("https://x.org/old", 302), ("https://x.org/", 200)], url="https://x.org/old", final_url="https://x.org/")
    assert classify(home)[:2] == ("warning", "redirect_home")
    https = _c(200, chain=[("http://x.org/a", 301), ("https://x.org/a", 200)], url="http://x.org/a", final_url="https://x.org/a")
    assert classify(https)[:2] == ("warning", "http_to_https")


def test_block_detection():
    assert ladder.block_like(404, {})[0] is False
    assert ladder.block_like(403, {"cf-mitigated": "challenge"}) == (True, "Cloudflare")
    assert ladder.block_like(403, {"server": "cloudflare"})[0] is True
    assert ladder.block_like(503, {})[0] is False  # plain outage
    assert ladder.block_like(200, {}, b"<html>ok</html>")[0] is False
    assert ladder.block_like(999, {})[0] is True
    assert ladder.block_like(403, {}, b"Request unsuccessful. Incapsula incident ID: 1") == (True, "Imperva")


def test_circuit_breaker():
    st = ladder.HostState()
    for i in range(3):
        st.record(True, "Cloudflare", f"https://h/{i}")
    assert st.protected and st.vendor == "Cloudflare" and st.sample == "https://h/0"
    ok = ladder.HostState()
    for _ in range(6):
        ok.record(False, None, "u")
    ok.record(True, None, "u")
    assert not ok.protected


def test_profiler():
    wp = '<html><head><meta name="generator" content="WordPress 6.5"><link rel="stylesheet" href="/wp-content/a.css"></head></html>'
    p = profiler.profile({"link": '<https://x/wp-json/>; rel="https://api.w.org/"'}, wp)
    assert p.id == "wordpress" and p.confidence == "high" and p.fix_steps
    wix = '<html><script src="https://static.parastorage.com/x.js"></script><img src="https://static.wixstatic.com/a.png"></html>'
    assert profiler.profile({"x-wix-request-id": "1"}, wix).id == "wix"
    assert profiler.profile({}, '<html><a href="https://sites.google.com/x">one mention</a></html>').id == "unknown"
    assert profiler.profile({}, "<html></html>").confidence == "none"


def test_did_you_mean():
    pages = ["https://x.org/about-us/", "https://x.org/contact/", "https://other.org/about-us/"]
    assert did_you_mean("https://x.org/about-uss/", pages) == "https://x.org/about-us/"
    assert did_you_mean("https://x.org/zzzzzz/", pages) is None


@pytest.mark.parametrize("ip,ok", [("8.8.8.8", True), ("127.0.0.1", False), ("10.0.0.5", False), ("192.168.1.1", False),
                                   ("169.254.169.254", False), ("100.64.0.1", False), ("::1", False),
                                   ("::ffff:127.0.0.1", False), ("fe80::1", False), ("fc00::1", False), ("0.0.0.0", False)])
def test_is_public_ip(ip, ok, monkeypatch):
    monkeypatch.setattr(config, "CONFIG", dataclasses.replace(config.CONFIG, allow_private_targets=False))
    assert is_public_ip(ip) is ok


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost/", "http://169.254.169.254/latest/meta-data/",
                                 "http://[::1]/", "http://0x7f000001/", "http://2130706433/", "http://127.0.0.1:8080/",
                                 "ftp://example.com/", "http://example.com:8080/"])
async def test_fetcher_refuses_private_targets(url, monkeypatch):
    monkeypatch.setattr(config, "CONFIG", dataclasses.replace(config.CONFIG, allow_private_targets=False))
    f = Fetcher()
    try:
        r = await f.fetch(url, "HEAD", timeout=5)
    finally:
        await f.close()
    assert r.error in ("unsafe_target", "dns_failure"), (url, r.error, r.status)


def test_only_safe_fetch_imports_http_client():
    root = pathlib.Path(__file__).resolve().parent.parent / "app"
    offenders = [str(p) for p in root.rglob("*.py")
                 if p.name != "safe_fetch.py" and any(w in p.read_text(encoding="utf-8") for w in ("curl_cffi", "import httpx", "import requests", "import aiohttp", "urllib.request"))]
    assert offenders == []
