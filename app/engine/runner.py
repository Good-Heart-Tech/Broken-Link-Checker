# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scan pipeline: profile, find pages, extract links, check links, second chance, report.

Pages and link checks run together through one scheduler, so results appear while crawling continues.
"""
import asyncio
import re
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from app import config
from app.engine import profiler, suggest
from app.engine.checker import Check, build_check, check_url, classify
from app.engine.extract import LinkRef, extract
from app.engine.scheduler import HostScheduler
from app.messages import START_ERRORS, describe
from app.net import ladder
from app.net.safe_fetch import Fetcher
from app.net.urlnorm import dedupe_key, host_of, looks_like_page, netloc_of, normalize, same_site, strip_www

PAGE_LIMIT = 1_500_000
MAX_OCC_PER_URL = 100
MAX_PROBLEM_ROWS = 20000
MAX_QUERY_VARIANTS = 20
MAX_DEPTH = 10
# Cloudflare adds these for every visitor (email protection, challenges). They are not real pages.
SKIP_PATHS = ("/cdn-cgi/",)
LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.I | re.S)


class StartError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


async def run(scan) -> None:
    fetcher = Fetcher()
    try:
        await _Run(scan, fetcher).execute()
    finally:
        await fetcher.close()


class _Run:
    def __init__(self, scan, fetcher: Fetcher) -> None:
        self.scan = scan
        self.fetcher = fetcher
        self.cfg = config.CONFIG
        self.site_url = ""
        self.site_netloc = ""
        self.profile = profiler.Profile()
        self.robots: RobotFileParser | None = None
        self.urls: dict[str, str] = {}  # key -> first URL seen
        self.occ: dict[str, list] = defaultdict(list)  # key -> [(page, LinkRef)]
        self.occ_total: dict[str, int] = defaultdict(int)
        self.res: dict[str, tuple] = {}  # key -> (Check, bucket, reason, code)
        self.pages: dict[str, object] = {}  # page url -> PageInfo
        self.known_pages: list[str] = []
        self.hosts: dict[str, ladder.HostState] = {}
        self.query_variants: dict[str, set] = defaultdict(set)
        self.pages_enqueued = 0
        self.problem_rows = 0
        self.sched: HostScheduler | None = None
        self.dym_cache: dict[str, str | None] = {}
        self.recent_bad: deque = deque(maxlen=20)  # recent outcomes on the scanned site: True when slow or failing
        self.processed: set[str] = set()  # pages already read, so a redirect to a known page is not read twice

    # ---------- entry points ----------
    async def execute(self) -> None:
        scan = self.scan
        self.sched = HostScheduler(self._limit_for, scan.gate)
        if scan.kind == "recheck":
            await self._recheck()
        else:
            await self._scan()

    async def _scan(self) -> None:
        scan = self.scan
        scan.set_phase("profile")
        first = await self._fetch_start()
        self.site_url = first.final.url
        self.site_netloc = netloc_of(self.site_url)
        if any(strip_www(host_of(self.site_url)) == d or strip_www(host_of(self.site_url)).endswith("." + d) for d in self.cfg.deny_hosts):
            raise StartError("denied")

        html = first.final.body.decode("utf-8", "replace") if first.final.body else ""
        self.profile = profiler.profile(first.final.headers, html)
        scan.emit("profile", self.profile.public())
        await self._load_robots()

        scan.set_phase("crawl")
        workers = [asyncio.create_task(self._worker()) for _ in range(self.cfg.concurrency_global)]
        watchdog = asyncio.create_task(self._watchdog())
        try:
            key = dedupe_key(self.site_url)
            self.urls[key] = self.site_url
            scan.stats["links_found"] += 1
            self.pages_enqueued += 1
            c = build_check(self.site_url, first)
            scan.stats["pages_found"] += 1
            self._finish(key, c)
            await self._process_page(self.site_url, first, c)
            if scan.scope == "site":
                await self._seed_from_sitemaps()
            await self.sched.idle.wait()

            if scan.mode == "thorough" and not scan.cancelled:
                await self._second_chance()
        finally:
            watchdog.cancel()
            await self.sched.close()
            await asyncio.gather(*workers, return_exceptions=True)
        self._finish_report()

    async def _recheck(self) -> None:
        scan = self.scan
        scan.set_phase("crawl")
        self.site_url = scan.params.get("site", "")
        self.site_netloc = netloc_of(self.site_url) if self.site_url else ""
        workers = [asyncio.create_task(self._worker()) for _ in range(self.cfg.concurrency_global)]
        watchdog = asyncio.create_task(self._watchdog())
        try:
            for item in scan.params["items"]:
                ref = LinkRef(item["target"], item.get("element", "a"), item.get("text", ""), item.get("where", ""), item.get("snippet", ""))
                await self._add_occurrence(item.get("page", ""), ref, crawl=False)
            await self.sched.idle.wait()
            if scan.mode == "thorough" and not scan.cancelled:
                await self._second_chance()
        finally:
            watchdog.cancel()
            await self.sched.close()
            await asyncio.gather(*workers, return_exceptions=True)
        self._finish_report()

    # ---------- start page ----------
    async def _fetch_start(self):
        scan = self.scan
        url = scan.start_url
        tries = [url]
        if not scan.scheme_given and url.startswith("https://"):
            tries.append("http://" + url[len("https://"):])
        last = None
        for u in tries:
            f = await self.fetcher.fetch_follow(u, "GET", body_limit=PAGE_LIMIT, timeout=20)
            last = f
            if not f.error and not f.final.error:
                break
        r = last.final
        if last.error or r.error:
            raise StartError(last.error or r.error)
        blocked, _ = ladder.block_like(r.status, r.headers, r.body)
        if blocked:
            # one gentle second try with another browser profile before giving up
            f2 = await self.fetcher.fetch_follow(last.final.url, "GET", body_limit=PAGE_LIMIT, timeout=20, profile="safari")
            if not f2.error and not f2.final.error and not ladder.block_like(f2.final.status, f2.final.headers, f2.final.body)[0]:
                last, r = f2, f2.final
            else:
                raise StartError("blocked")
        if r.status >= 400:
            raise StartError("http_error", str(r.status))
        return last

    async def _load_robots(self) -> None:
        u = f"{urlsplit(self.site_url).scheme}://{self.site_netloc}/robots.txt"
        f = await self.fetcher.fetch_follow(u, "GET", body_limit=200_000, timeout=10, max_hops=3)
        rp = RobotFileParser()
        if f.final.status == 200 and not f.final.error:
            rp.parse(f.final.body.decode("utf-8", "replace").splitlines())
            self.robots = rp
        self.robots_sitemaps = list(rp.site_maps() or []) if self.robots else []

    async def _seed_from_sitemaps(self) -> None:
        base = f"{urlsplit(self.site_url).scheme}://{self.site_netloc}"
        queue = list(dict.fromkeys(self.robots_sitemaps + [base + p for p in self.profile.sitemap_paths]))
        seen_maps, found = set(), []
        while queue and len(seen_maps) < 12 and len(found) < self.cfg.max_pages * 2:
            sm = queue.pop(0)
            if sm in seen_maps or sm.endswith(".gz") or not same_site(sm, self.site_url):
                continue
            seen_maps.add(sm)
            f = await self.fetcher.fetch_follow(sm, "GET", body_limit=3_000_000, timeout=15, max_hops=3)
            if f.error or f.final.error or f.final.status != 200:
                continue
            for loc in LOC.findall(f.final.body.decode("utf-8", "replace")):
                loc = loc.replace("&amp;", "&")
                if loc.lower().split("?")[0].endswith(".xml") and "sitemap" in loc.lower():
                    queue.append(loc)
                else:
                    found.append((sm, loc))
        for sm, loc in found:
            n = normalize(loc)
            if n and same_site(n, self.site_url):
                await self._add_occurrence(sm, LinkRef(n, "sitemap", "Listed in your sitemap", "Sitemap", ""))

    # ---------- scheduling ----------
    def _limit_for(self, netloc: str) -> int:
        if self.site_netloc and strip_www(netloc.split(":")[0]) == strip_www(self.site_netloc.split(":")[0]):
            if self.profile.gentle:
                return max(2, self.cfg.concurrency_target // 2)
            if len(self.recent_bad) >= 10 and sum(self.recent_bad) / len(self.recent_bad) >= 0.25:
                return 2  # the site is struggling, so go easy on it
            return self.cfg.concurrency_target
        st = self.hosts.get(netloc)
        return 1 if st and st.protected else self.cfg.concurrency_external

    def _crawlable(self, url: str) -> bool:
        if self.scan.scope != "site" or self.pages_enqueued >= self.cfg.max_pages:
            return False
        if not same_site(url, self.site_url) or not looks_like_page(url):
            return False
        parts = urlsplit(url)
        low = (parts.path + ("?" + parts.query if parts.query else "")).lower()
        if any(p.lower() in low for p in self.profile.ignore_patterns):
            return False
        if parts.path.count("/") > MAX_DEPTH:
            return False
        if parts.query:
            variants = self.query_variants[parts.path]
            if parts.query not in variants and len(variants) >= MAX_QUERY_VARIANTS:
                return False
            variants.add(parts.query)
        if self.robots and not self.robots.can_fetch("*", url):
            return False
        return True

    async def _add_occurrence(self, page: str, ref: LinkRef, crawl: bool = True) -> None:
        url = ref.target
        if any(p in urlsplit(url).path for p in SKIP_PATHS) and same_site(url, self.site_url or url):
            return
        key = dedupe_key(url)
        scan = self.scan
        self.occ_total[key] += 1
        occ = (page, ref)
        if len(self.occ[key]) < MAX_OCC_PER_URL:
            self.occ[key].append(occ)
            if key in self.res:
                self._emit_for(key, occ)
        if key in self.urls:
            return
        if len(self.urls) >= self.cfg.max_urls:
            scan.truncated = True
            return
        self.urls[key] = url
        scan.stats["links_found"] += 1
        if crawl and self._crawlable(url):
            self.pages_enqueued += 1
            scan.stats["pages_found"] += 1
            await self.sched.add(netloc_of(url), ("page", key))
        else:
            await self.sched.add(netloc_of(url), ("check", key))

    async def _worker(self) -> None:
        while True:
            item = await self.sched.get()
            if item is None:
                return
            host, (kind, key) = item
            try:
                if kind == "page":
                    await self._do_page(key)
                else:
                    await self._do_check(key)
            except Exception as e:  # never let one bad URL stop a scan
                print(f"scan={self.scan.id} job error {type(e).__name__}")
                if key not in self.res:
                    self._finish(key, Check(self.urls[key], blocked=True))
            finally:
                await self.sched.done(host)

    async def _watchdog(self) -> None:
        start = time.monotonic()
        while True:
            await asyncio.sleep(0.5)
            if self.scan.cancelled:
                await self.sched.close()
                return
            if time.monotonic() - start > self.cfg.max_scan_seconds:
                self.scan.partial_reason = "time"
                self.scan.cancelled = True
                await self.sched.close()
                return

    # ---------- jobs ----------
    async def _do_page(self, key: str) -> None:
        url = self.urls[key]
        referer = self.occ[key][0][0] if self.occ.get(key) else None
        f = await self.fetcher.fetch_follow(url, "GET", body_limit=PAGE_LIMIT, timeout=20, referer=referer or None)
        c = build_check(url, f)
        if c.error in ("timeout", "error") or c.status >= 500:
            await asyncio.sleep(0.6)
            f = await self.fetcher.fetch_follow(url, "GET", body_limit=PAGE_LIMIT, timeout=20, referer=referer or None)
            c = build_check(url, f)
        self.recent_bad.append(bool(c.error) or c.status >= 500)
        self._finish(key, c)
        await self._process_page(url, f, c)

    async def _process_page(self, url: str, f, c: Check) -> None:
        """Extract links from a fetched page and queue them."""
        r = f.final
        ctype = r.headers.get("content-type", "")
        if c.error or not (200 <= r.status < 300) or "html" not in ctype or not r.body:
            return
        if not same_site(r.url, self.site_url) or dedupe_key(r.url) in self.processed:
            return
        self.processed.add(dedupe_key(r.url))
        info = extract(_decode(r.body, ctype), r.url)
        self.pages[r.url] = info
        self.known_pages.append(r.url)
        self.scan.stats["pages_scanned"] += 1
        self.scan.current = r.url
        if info.few_links_heavy_js and not self.scan.js_notice:
            self.scan.js_notice = True
            self.scan.emit("notice", {"kind": "js_heavy", "page": r.url})
        if dedupe_key(r.url) not in self.urls:
            self.urls[dedupe_key(r.url)] = r.url
        await self._queue_links(r.url, info)

    async def _queue_links(self, page: str, info) -> None:
        for ref in info.links:
            await self._add_occurrence(page, ref)

    async def _do_check(self, key: str) -> None:
        url = self.urls[key]
        host, nl = host_of(url), netloc_of(url)
        if ladder.is_social(host) and not self.scan.params.get("check_social"):
            self._finish(key, Check(url), ("skipped", "social_skipped", 0))
            return
        st = self.hosts.setdefault(nl, ladder.HostState())
        external = not same_site(url, self.site_url) if self.site_url else True
        if external and st.protected:
            self._finish(key, Check(url, blocked=True, vendor=st.vendor))
            return
        referer = self.occ[key][0][0] if self.occ.get(key) and self.occ[key][0][0].startswith("http") else None
        c = await check_url(self.fetcher, url, referer)
        if external:
            was = st.protected
            st.record(c.blocked, c.vendor, url)
            if st.protected and not was:
                self.scan.emit("host_note", {"host": host, "vendor": st.vendor, "sample": st.sample})
        self._finish(key, c)

    # ---------- results ----------
    def _finish(self, key: str, c: Check, forced: tuple | None = None) -> None:
        bucket, reason, code = forced or classify(c)
        self.res[key] = (c, bucket, reason, code)
        st = self.scan.stats
        st["links_checked"] += 1
        st[bucket] = st.get(bucket, 0) + 1
        if bucket not in ("ok", "skipped"):
            for occ in self.occ.get(key, []):
                self._emit_for(key, occ)

    def _emit_for(self, key: str, occ: tuple) -> None:
        c, bucket, reason, code = self.res[key]
        if bucket in ("ok", "skipped") or self.problem_rows >= MAX_PROBLEM_ROWS:
            return
        self.problem_rows += 1
        self.scan.add_row(self._row(key, occ, c, bucket, reason, code))

    def _row(self, key: str, occ: tuple, c: Check, bucket: str, reason: str, code: int) -> dict:
        page, ref = occ
        d = describe(reason)
        target = self.urls[key]
        info = self.pages.get(page)
        row = {
            "bucket": bucket, "reason": reason, "code": code, "title": d["title"], "explain": d["explain"], "fix": d["fix"],
            "target": target, "final": c.final_url if c.final_url and c.final_url != target else None,
            "chain": [list(x) for x in c.chain[:6]] if len(c.chain) > 1 else [],
            "vendor": c.vendor, "element": ref.element, "text": ref.text, "where": ref.where, "page": page,
            "pageTitle": info.title if info else "", "snippet": ref.snippet, "ms": c.ms,
            "external": bool(self.site_url) and not same_site(target, self.site_url),
        }
        if reason in ("redirect_permanent", "http_to_https", "redirect_home") and c.final_url:
            row["suggest"] = {"kind": "new_address", "url": c.final_url}
        elif reason in ("http_404", "http_410") and not row["external"]:
            if target not in self.dym_cache:
                self.dym_cache[target] = suggest.did_you_mean(target, self.known_pages)
            if self.dym_cache[target]:
                row["suggest"] = {"kind": "did_you_mean", "url": self.dym_cache[target]}
        elif reason in ("http_404", "http_410", "dns_failure") and row["external"]:
            row["suggest"] = {"kind": "archive", "url": suggest.archive_url(target)}
        if self.profile.id == "wordpress" and info and info.wp_id:
            row["editUrl"] = suggest.wp_edit_url(page, info.wp_id)
        return row

    # ---------- thorough mode ----------
    async def _second_chance(self) -> None:
        scan = self.scan
        by_host: dict[str, list] = defaultdict(list)
        for key, (c, bucket, reason, code) in self.res.items():
            if bucket == "blocked" and reason != "auth_required":
                by_host[netloc_of(self.urls[key])].append(key)
        if not by_host:
            return
        scan.set_phase("second_chance")
        sem = asyncio.Semaphore(4)

        async def one_host(netloc: str, keys: list) -> None:
            async with sem:
                if scan.cancelled:
                    return
                url_to_key = {self.urls[k]: k for k in keys}

                async def check_once(url, prof, referer):
                    c = await check_url(self.fetcher, url, referer, profile=prof, ranged=True, proxy=bool(self.cfg.proxy_url))
                    return {"blocked": c.blocked or c.error in ("timeout",), "status": c.status, "check": c}

                sample = next(iter(url_to_key))
                root = f"{urlsplit(sample).scheme}://{netloc}/"
                got = await ladder.retry_host(root, list(url_to_key), check_once, self.cfg.thorough_host_budget_seconds)
                removed = list(got)
                if removed:
                    scan.remove_targets(removed)  # drop the old "could not verify" rows first
                    self.problem_rows = max(0, self.problem_rows - sum(len(self.occ.get(url_to_key[u], [])) for u in removed))
                st = scan.stats
                for url, r in got.items():
                    key = url_to_key[url]
                    old = self.res[key][1]
                    st[old] = max(0, st.get(old, 1) - 1)
                    st["links_checked"] -= 1
                    self._finish(key, r["check"])  # emits fresh rows if it turned out broken or worth a look

        await asyncio.gather(*(one_host(n, k) for n, k in by_host.items()))

    # ---------- wrap up ----------
    def _finish_report(self) -> None:
        scan = self.scan
        counts: dict[str, int] = defaultdict(int)
        agg = []
        blocked_by_host: dict[str, dict] = {}
        for key, (c, bucket, reason, code) in self.res.items():
            if bucket in ("ok", "skipped"):
                occ = self.occ.get(key, [])
                d = describe(reason)
                agg.append({"bucket": bucket, "reason": reason, "code": code, "title": d["title"], "target": self.urls[key],
                            "pages": self.occ_total.get(key, 0), "page": occ[0][0] if occ else "",
                            "external": bool(self.site_url) and not same_site(self.urls[key], self.site_url)})
            elif bucket == "blocked":
                h = host_of(self.urls[key])
                b = blocked_by_host.setdefault(h, {"host": h, "count": 0, "vendor": None, "sample": self.urls[key]})
                b["count"] += 1
                b["vendor"] = b["vendor"] or c.vendor
        scan.add_aggregates(agg)
        scan.host_notes = sorted(blocked_by_host.values(), key=lambda x: -x["count"])
        scan.finish_stats()


def _decode(body: bytes, ctype: str) -> str:
    m = re.search(r"charset=([\w-]+)", ctype, re.I)
    for enc in ([m.group(1)] if m else []) + ["utf-8"]:
        try:
            return body.decode(enc, "replace")
        except LookupError:
            continue
    return body.decode("utf-8", "replace")
