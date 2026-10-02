# SPDX-License-Identifier: AGPL-3.0-or-later
"""URL cleanup helpers. Pure functions, no network."""
import re
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:", "about:", "blob:", "file:", "ftp:", "whatsapp:", "skype:")
TRACKING_PARAMS = {"fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "_ga"}
ASSET_EXT = re.compile(
    r"\.(?:jpe?g|png|gif|webp|svg|ico|avif|bmp|css|js|mjs|json|xml|txt|pdf|docx?|xlsx?|pptx?|zip|gz|rar|7z|mp[34]|mov|avi|wmv|wav|ogg|webm|woff2?|ttf|eot|otf|csv|ics|rss|atom|epub)$",
    re.I,
)


def clean_user_input(raw: str) -> str | None:
    """Turn what a person typed into a full URL, or None if it is not usable."""
    raw = (raw or "").strip()
    if not raw or len(raw) > 2048 or " " in raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    return normalize(raw)


def normalize(url: str, base: str | None = None) -> str | None:
    """Resolve against base, drop fragment, lowercase host, drop default port. None if unusable."""
    url = (url or "").strip()
    if not url or url.lower().startswith(SKIP_SCHEMES) or url.startswith("#"):
        return None
    try:
        full = urljoin(base, url) if base else url
        parts = urlsplit(full)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    try:
        host = parts.hostname.encode("idna").decode("ascii").lower()
        port = parts.port
    except (UnicodeError, ValueError):
        return None
    scheme = parts.scheme.lower()
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host_part = f"{host}:{port}"
    else:
        host_part = host
    path = parts.path or "/"
    path = path.replace(" ", "%20")
    return urlunsplit((scheme, host_part, path, parts.query, ""))


def dedupe_key(url: str) -> str:
    """Same page reached by different tracking params counts once."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def netloc_of(url: str) -> str:
    return urlsplit(url).netloc.lower()


def strip_www(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def same_site(a: str, b: str) -> bool:
    """Same website means the same host, ignoring a leading www."""
    return strip_www(host_of(a)) == strip_www(host_of(b))


def looks_like_page(url: str) -> bool:
    return not ASSET_EXT.search(urlsplit(url).path)


def trivial_redirect(a: str, b: str) -> bool:
    """True when two URLs differ only by trailing slash, host letter case, or a leading www."""
    pa, pb = urlsplit(a), urlsplit(b)
    return (pa.scheme == pb.scheme and strip_www(pa.netloc.lower()) == strip_www(pb.netloc.lower())
            and pa.path.rstrip("/") == pb.path.rstrip("/") and pa.query == pb.query)
