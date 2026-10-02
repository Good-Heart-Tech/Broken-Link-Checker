# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pull links out of a page, with enough context for a person to find each one."""
import re
from dataclasses import dataclass, field

from selectolax.lexbor import LexborHTMLParser

from app.net.urlnorm import normalize

SNIPPET_MAX = 200
TEXT_MAX = 120
LANDMARK_TAGS = {"header": "Header", "nav": "Menu", "main": "Main content", "footer": "Footer", "aside": "Sidebar"}
LANDMARK_HINTS = (("footer", "Footer"), ("header", "Header"), ("menu", "Menu"), ("nav", "Menu"), ("sidebar", "Sidebar"))
SKIP_REL = {"preconnect", "dns-prefetch", "canonical", "alternate", "next", "prev", "preload", "prefetch",
            "pingback", "shortlink", "edituri", "wlwmanifest", "profile", "author", "me", "search"}
KEEP_REL = {"stylesheet", "icon", "shortcut", "apple-touch-icon", "manifest"}
SOFT_404 = re.compile(r"(not found|doesn'?t exist|does not exist|no longer available|can'?t be found|\b404\b)", re.I)
WP_ID = re.compile(r"(?:page-id-|postid-)(\d+)")
SELECTOR = ("h1,h2,h3,h4,h5,h6,a[href],area[href],img[src],img[data-src],script[src],link[href],"
            "iframe[src],video[src],video[poster],audio[src],source[src]")


@dataclass
class LinkRef:
    target: str
    element: str  # a, img, script, link, iframe, video, audio, source
    text: str
    where: str
    snippet: str


@dataclass
class PageInfo:
    title: str = ""
    links: list = field(default_factory=list)
    wp_id: int | None = None
    soft_404: bool = False
    few_links_heavy_js: bool = False


def _clean(s: str, n: int = TEXT_MAX) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[: n - 3] + "..." if len(s) > n else s


def _ancestors(node):
    cur, depth = node.parent, 0
    while cur is not None and depth < 40:
        yield cur
        cur, depth = cur.parent, depth + 1


def _where(node, heading: str) -> str:
    place = ""
    for cur in _ancestors(node):
        if cur.tag in LANDMARK_TAGS:
            place = LANDMARK_TAGS[cur.tag]
            if cur.tag == "nav" and any(a.tag == "footer" for a in _ancestors(cur)):
                place = "Footer"
            break
        attrs = cur.attributes
        ident = ((attrs.get("id") or "") + " " + (attrs.get("class") or "")).lower()
        for hint, label in LANDMARK_HINTS:
            if hint in ident:
                place = label
                break
        if place:
            break
    if heading and place not in ("Footer", "Menu", "Header"):
        return f"{place or 'Page body'}, under '{heading}'"
    return place or "Page body"


def _describe(node, tag: str) -> str:
    attrs = node.attributes
    if tag in ("a", "area"):
        text = _clean(node.text(separator=" "))
        if text:
            return text
        img = node.css_first("img")
        if img is not None:
            alt = _clean(img.attributes.get("alt") or "")
            return f'Image: alt "{alt}"' if alt else "Image (no alt text)"
        label = _clean(attrs.get("aria-label") or attrs.get("title") or "")
        return f'Icon or button: "{label}"' if label else "(no link text)"
    if tag == "img":
        alt = _clean(attrs.get("alt") or "")
        return f'Image: alt "{alt}"' if alt else "Image (no alt text)"
    return {"script": "Script file", "link": "Stylesheet or icon", "iframe": "Embedded frame",
            "video": "Video", "audio": "Audio", "source": "Media file"}.get(tag, tag)


def _snippet(node) -> str:
    html = re.sub(r"\s+", " ", node.html or "")
    return html[: SNIPPET_MAX - 3] + "..." if len(html) > SNIPPET_MAX else html


def extract(html: str, page_url: str) -> PageInfo:
    """Parse one page. html is already size-capped by the caller."""
    tree = LexborHTMLParser(html)
    info = PageInfo()
    title = tree.css_first("title")
    info.title = _clean(title.text() if title else "", 160)
    h1 = tree.css_first("h1")
    probe = f"{info.title} {h1.text() if h1 else ''}"
    info.soft_404 = bool(SOFT_404.search(probe)) and len(probe) < 200

    base_node = tree.css_first("base[href]")
    base = (normalize(base_node.attributes.get("href"), page_url) if base_node else None) or page_url

    body = tree.css_first("body")
    m = WP_ID.search((body.attributes.get("class") or "") if body else "")
    if m:
        info.wp_id = int(m.group(1))
    else:
        short = tree.css_first("link[rel=shortlink]")
        mm = re.search(r"[?&]p=(\d+)", (short.attributes.get("href") or "") if short else "")
        if mm:
            info.wp_id = int(mm.group(1))

    heading = ""
    scripts = 0
    for node in tree.css(SELECTOR):
        tag = node.tag
        if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
            heading = _clean(node.text(separator=" "), 60)
            continue
        attrs = node.attributes
        if tag == "script":
            scripts += 1
        if tag == "link":
            rels = set((attrs.get("rel") or "").lower().split())
            if not (rels & KEEP_REL) or (rels & SKIP_REL):
                continue
        if tag in ("a", "area", "link"):
            raw = attrs.get("href")
        else:
            raw = attrs.get("src") or attrs.get("data-src") or attrs.get("poster")
        target = normalize(raw or "", base)
        if not target:
            continue
        info.links.append(LinkRef(target, tag, _describe(node, tag), _where(node, heading), _snippet(node)))

    anchors = sum(1 for link in info.links if link.element == "a")
    info.few_links_heavy_js = anchors < 3 and scripts >= 8
    return info
