# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run a scan from the terminal: python -m app.cli https://example.org --mode quick --pages 50

Handy for development and for measuring bot blocking (see docs/BOT-BLOCKING.md).
"""
import argparse
import asyncio
import dataclasses
import json
import time

from app import config
from app.net.urlnorm import clean_user_input
from app.scans import Scan


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--mode", choices=["quick", "thorough"], default="quick")
    ap.add_argument("--scope", choices=["site", "page"], default="site")
    ap.add_argument("--pages", type=int, default=None, help="page cap for this run")
    ap.add_argument("--json", action="store_true", help="print full JSON instead of a summary")
    a = ap.parse_args()
    if a.pages:
        config.CONFIG = dataclasses.replace(config.CONFIG, max_pages=a.pages)
    url = clean_user_input(a.url)
    scan = Scan("scan", url, a.scope, a.mode, {}, scheme_given="://" in a.url)
    t0 = time.monotonic()
    await scan.execute()
    snap = scan.snapshot()
    if a.json:
        print(json.dumps(snap, indent=2))
        return
    if scan.error:
        print("Error:", scan.error["message"])
        return
    p = snap["profile"] or {}
    s = snap["stats"]
    print(f"{url}  platform={p.get('name')}  mode={a.mode}  {time.monotonic() - t0:.1f}s")
    print(f"pages={s['pages_scanned']} links={s['links_checked']} ok={s['ok']} broken={s['broken']} "
          f"blocked={s['blocked']} warning={s['warning']} skipped={s['skipped']}")
    for r in snap["rows"]:
        if r["bucket"] in ("broken", "blocked"):
            print(f"[{r['bucket']:7}] {r['code'] or '-':>3} {r['title']:32} {r['target']}\n          on {r['page']}  ({r['text']})")
    for n in snap["hostNotes"]:
        print(f"host note: {n['host']} blocked {n['count']} checks ({n['vendor'] or 'unknown protection'})")


if __name__ == "__main__":
    asyncio.run(main())
