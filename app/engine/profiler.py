# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guess the website platform from the home page. Signals live in data/platforms.json."""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PLATFORMS = json.loads((Path(__file__).resolve().parent.parent.parent / "data" / "platforms.json").read_text(encoding="utf-8"))["platforms"]
GENERATOR = re.compile(
    r"<meta[^>]+name=[\"']generator[\"'][^>]*content=[\"']([^\"']+)[\"']"
    r"|<meta[^>]+content=[\"']([^\"']+)[\"'][^>]*name=[\"']generator[\"']", re.I)
THRESHOLD = 2


@dataclass
class Profile:
    id: str = "unknown"
    name: str = "Unknown"
    confidence: str = "none"
    signals: list = field(default_factory=list)
    sitemap_paths: list = field(default_factory=lambda: ["/sitemap.xml", "/sitemap_index.xml"])
    ignore_patterns: list = field(default_factory=list)
    fix_steps: str = ""
    gentle: bool = False
    js_heavy: bool = False

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "confidence": self.confidence, "signals": self.signals,
                "fixSteps": self.fix_steps, "jsHeavy": self.js_heavy}


def profile(headers: dict, html: str) -> Profile:
    headers = {k.lower(): str(v).lower() for k, v in (headers or {}).items()}
    html = html or ""
    low = html[:400_000].lower()
    gens = [g.lower() for m in GENERATOR.finditer(html[:400_000]) for g in m.groups() if g]
    best, best_score, best_signals = None, 0, []
    for p in PLATFORMS:
        score, signals = 0, []
        for g in p.get("generator", []):
            if any(g.lower() in x for x in gens):
                score += 3
                signals.append(f"generator tag: {g}")
        for name, needle in p.get("headers", {}).items():
            if name in headers and needle.lower() in headers[name]:
                score += 2
                signals.append(f"response header: {name}")
        hits = [h for h in p.get("html", []) if h.lower() in low]
        score += min(len(hits), 3)
        signals += [f"page code: {h}" for h in hits[:3]]
        if score > best_score:
            best, best_score, best_signals = p, score, signals
    if not best or best_score < THRESHOLD:
        return Profile()
    return Profile(
        id=best["id"], name=best["name"], confidence="high" if best_score >= 4 else "medium",
        signals=best_signals, sitemap_paths=best.get("sitemap_paths") or ["/sitemap.xml"],
        ignore_patterns=best.get("ignore_patterns", []), fix_steps=best.get("fix_steps", ""),
        gentle=best.get("pacing") == "gentle", js_heavy=bool(best.get("js_heavy")),
    )
