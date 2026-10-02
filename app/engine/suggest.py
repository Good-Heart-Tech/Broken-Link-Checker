# SPDX-License-Identifier: AGPL-3.0-or-later
"""Help people fix a link: closest real page, WordPress edit link, archive link."""
import difflib
from urllib.parse import quote, urlsplit

from app.net.urlnorm import host_of, strip_www


def did_you_mean(target: str, known_pages: list[str]) -> str | None:
    """Closest crawled page on the same site by path similarity."""
    t = urlsplit(target)
    want = t.path.strip("/").lower()
    if not want:
        return None
    best, best_ratio = None, 0.0
    for p in known_pages:
        if strip_www(host_of(p)) != strip_www(t.hostname or ""):
            continue
        have = urlsplit(p).path.strip("/").lower()
        if not have or have == want:
            continue
        r = difflib.SequenceMatcher(None, want, have).ratio()
        if r > best_ratio:
            best, best_ratio = p, r
    return best if best_ratio >= 0.72 else None


def wp_edit_url(page_url: str, wp_id: int | None) -> str | None:
    if not wp_id:
        return None
    u = urlsplit(page_url)
    return f"{u.scheme}://{u.netloc}/wp-admin/post.php?post={int(wp_id)}&action=edit"


def archive_url(target: str) -> str:
    return "https://web.archive.org/web/*/" + quote(target, safe=":/?&=%")
