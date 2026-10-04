# Implementation plan: Free Broken Link Checker

Status: **v1 built** (all milestones M0 to M5 and the code side of M6). Owner: Greg (Good Heart Tech).
See [DEPLOY.md](DEPLOY.md) to run it on Sliplane and [BOT-BLOCKING-FINDINGS.md](BOT-BLOCKING-FINDINGS.md) for measured results.
Target home: `links.nonprofittools.org`, listed in the [Nonprofit Tools Hub](https://nonprofittools.org/).
Repo: public, AGPL-3.0-or-later (see [Open source readiness](#13-open-source-readiness)).

Companion doc: [BOT-BLOCKING.md](BOT-BLOCKING.md) (how we avoid false 403s, in detail).

---

## 1. What we are building

A free web tool where a nonprofit staffer pastes their website address and gets back a
clear, fixable list of broken links. It replaces the experience of
[deadlinkchecker.com](https://www.deadlinkchecker.com/website-dead-link-checker.asp)
with something modern, honest about what it could not verify, and aimed at fixing
problems instead of just listing them.

### Goals

1. Scan a whole site (or one page) and show live progress.
2. Show a clear table of **broken** links at the top: the page the link is on, the link
   text or element so a human can find it, and a plain-English status.
3. Show working links in a collapsed list at the bottom.
4. **Stop reporting false alarms.** Many "403 Forbidden" results are bot blockers, not dead
   links. We separate "broken" from "we could not verify this" and work hard to reduce the
   second group without slowing the default scan.
5. Detect the website platform first (WordPress, Wix, Squarespace, etc.) and use it to
   crawl smarter and to tell the user exactly where to click to fix each problem.
6. Export results (CSV first) so a volunteer or web person can work through the list.
7. Look like Good Heart Tech: light, airy, easy. Matches the
   [GHT brand kit](https://github.com/Good-Heart-Tech/Good-Heart-Tech-Branding-Marketing).
8. Ship as **one Docker container, no storage volume.**

### Non-goals (v1)

- No accounts, no saved history, no scheduled re-scans, no email reports. (Possible later
  as a separate "monitoring" product; it would need storage, so it is out of this scope.)
- No headless-browser rendering of JavaScript-only sites in v1 (see Risks).
- No CAPTCHA solving, no login bypass, no spoofing search-engine crawlers. Ever.
- No SEO audit features (titles, meta, speed). Links only.

---

## 2. Decisions at a glance

| Topic | Decision | Why |
|-------|----------|-----|
| Language / framework | Python 3.12, FastAPI, one uvicorn worker | Volunteers know Python; same shape as the Fleet app Dockerfile; async fits link checking |
| HTTP client | `curl_cffi` (Chrome TLS and HTTP/2 impersonation) | Single biggest cheap fix for false 403s. Plain Python/Node clients have a bot-like TLS fingerprint |
| HTML parsing | `selectolax` | Very fast, tiny, simple API |
| Frontend | Vanilla HTML, CSS, JS. No build step | Matches the Tools Hub rules; easy for future volunteers and AI |
| Progress transport | Server-Sent Events (SSE), polling fallback | One-way stream, works through Cloudflare, no websocket complexity |
| State | In memory only, results expire 30 min after a scan ends | "No storage volume" requirement |
| Exports | Generated in the browser from results already on the page | Server never stores or re-serves results |
| Scan modes | **Quick** (default) and **Thorough** | Speed matters; blocker evasion is slower. User chooses |
| Result buckets | Broken, Could not verify, Worth a look, Working | Honest reporting is the whole point |
| Abuse protection | Per-IP rate limit, global scan cap with a visible queue, per-site pacing. No Turnstile (Greg's call) | Public free tool that makes outbound requests |
| Hosting | Any Docker host with HTTPS. Sliplane is the likely fit (existing GHT/HH precedent) | Single container, env-var config |
| License | AGPL-3.0-or-later, applied at open-source time. SPDX headers from day one | Planned |

---

## 3. User experience

### 3.1 Flow

1. **Landing.** One big input ("Enter your website address"), two choices:
   *Check whole website* / *Check single page*, and a mode switch:
   *Quick scan* / *Thorough scan (slower, double-checks sites that block automated tools)*.
   One friendly sentence on privacy: "We do not store your results or your site."
2. **Scanning.** Progress card with a bar, live counters, current page, elapsed time, and
   **Pause** and **Stop and show results** buttons. The broken-links table fills in live
   as problems are found (the original tool does this and people like it).
3. **Done.** Summary strip, results sections, export buttons.
4. **Fix and re-check.** After fixing, "Re-check these links" re-tests only the problem
   URLs (a few seconds) instead of re-crawling the whole site.

### 3.2 Progress that does not lie

The total grows while crawling, so a naive percentage jumps backwards. Plan:

- Crawl and check are **pipelined**: links are verified while pages are still being
  discovered. This is also why Quick scans feel fast.
- Show two honest counters: `Pages scanned: 212` and `Links checked: 1,708 of 2,000 found`.
- Bar = checked / found so far. Label it "found so far" until crawling finishes, then it
  becomes a true percentage.
- Phase label: Profiling site, Finding pages, Checking links, Double-checking blocked links
  (Thorough only), Done.

### 3.3 Results layout (top to bottom)

1. **Summary strip:** platform chip ("WordPress detected"), pages scanned, links checked,
   counts for each bucket, scan time, mode used.
2. **Broken links table** (always open, the main event).
3. **Could not verify** (open if any). Grouped by website, because blocking is per-site.
   Example row: "ticketing.example.com blocked our checks (38 links). This is usually
   bot protection, not a broken link. Open one to confirm."
4. **Worth a look** (collapsed): redirects worth updating, possible soft 404s, slow links,
   `http` links that should be `https`.
5. **Working links** (collapsed, searchable): the "correct links" list.

### 3.4 Broken links table columns

| Column | Content |
|--------|---------|
| Status | Badge with icon and words: "Page not found (404)", "Site not found", "Server error (500)", "Security certificate problem", "Did not respond (timeout)", "Redirect loop". Never color alone |
| Broken link | The URL that failed. Copy button |
| Link text or element | Visible link text, or for non-text: `Image: alt "Donate"`, `Button`, `Image (no alt text)`, `Stylesheet`, `Script`, `Embedded frame` |
| Where on the page | Landmark and nearest heading, for example "Footer, under 'Get involved'" or "Main menu" |
| Page it is on | Page title and URL. Open-page button |
| How to fix | Short suggestion plus platform-specific steps (see 3.5) |

Controls: search box, filter (internal / external / images and files), sort by any
column, **Group by broken link** toggle (one dead URL used on 12 pages becomes one row
you can expand, instead of 12 rows), and **Ignore** per row (hides it and removes it from
exports, client-side only).

An expandable "Show HTML" per row reveals the raw anchor snippet for web developers.

### 3.5 Helping people actually fix things

This is where we beat the original tool.

- **Did you mean?** For a broken internal link, fuzzy-match the path against pages we
  crawled and suggest the closest real page.
- **Corrected URL.** For permanent redirects (301/308), show the destination with a copy
  button ("Update this link to https://...").
- **Look in the archive.** For a dead external page, link to the Wayback Machine for that
  URL (a plain link; we do not call it from the server).
- **Platform steps.** From the platform profile, add one or two sentences such as
  "In Squarespace, open this page, click Edit, select the text, click the link icon."
  Starter wording lives in `data/platforms.json` and is easy to edit.
- **WordPress deep link.** WordPress pages usually reveal their post ID (`rel="shortlink"`,
  `page-id-123` body class, or the `wp-json` alternate link). When found, offer
  "Edit this page in WordPress" (`/wp-admin/post.php?post=123&action=edit`). The user is
  prompted to log in on their own site; we never touch their credentials.
- **Work by page.** CSV and the on-screen toggle can sort by page so a web person fixes
  one page at a time.

### 3.6 Exports (all generated in the browser)

| Format | Use |
|--------|-----|
| **CSV** (UTF-8 with BOM so Excel behaves) | Default. Broken links only, with an "Include everything" checkbox. Columns match the table plus platform and suggested fix. Cells starting with `=`, `+`, `-`, `@` get a leading `'` to prevent spreadsheet formula injection |
| **Copy for email or ticket** | Markdown table of broken links, paste into Halo, email, Teams |
| **JSON** | For scripts and other tools |
| **Print or Save as PDF** | Print stylesheet with the summary and broken table |
| Copy as table | Tab separated, pastes cleanly into Google Sheets |

XLSX is deliberately skipped in v1 (needs a library, CSV opens in Excel and Sheets fine).
Revisit if partners ask.

### 3.7 Visual direction

Light and airy. White page, lots of space, rich black headings, charcoal body text, hudu
light (`#D6DDFF`) for soft cards and borders, primary (`#7189FF`) only for the main
button and accents. Hudu primary (`#586CD0`) for small text links (contrast rules in the
brand kit). System UI sans stack per `BRAND.md` (the Tools Hub uses Noto Sans; see Open
questions). Heart icon top left. Friendly, nonprofit-partner voice, no em dashes, no
jargon in user-facing text.

Status colors are not in the brand kit. We add three soft tints with dark text and an
icon (danger, caution, success), each verified to 4.5:1 text contrast, and propose them
back to the brand kit repo so other tools can share them.

Accessibility target: WCAG 2.2 AA. Keyboard-only usable, `aria-live="polite"` for
throttled progress updates, real `<table>` markup with `scope`, `prefers-reduced-motion`
respected, status never conveyed by color alone.

---

## 4. Scan pipeline

```
 [1 Normalize + SSRF check]
          |
 [2 Profile the site]  -> platform, sitemap hints, ignore rules, fix steps
          |
 [3 Discover pages]  sitemap seeds + link-following (same site only)
          |
 [4 Extract links]   a, img, link, script, iframe, video/audio/source, with context
          |
 [5 Check links]     pipelined with 3 and 4, per-host pacing, fast tier first
          |
 [6 Classify]        broken / could not verify / worth a look / ok
          |
 [7 Second chance]   Thorough mode only, for block-like results (see BOT-BLOCKING.md)
          |
 [8 Report]          SSE events to the browser, results held in memory
```

### Step details

**1. Normalize and validate.** Accept `example.org`, `https://example.org/path`. Default to
`https`, fall back to `http`. Strip fragments. Reject non-http(s), credentials in the URL,
non-standard ports (only 80 and 443), and the tool's own host. Full SSRF rules in section 8.

**2. Profile the site.** One request for the home page (plus `robots.txt`). Match against
`data/platforms.json`: response headers, `<meta name="generator">`, asset hostnames, and
HTML markers. Output a platform id with a confidence and the signals that matched, shown
to the user ("WordPress detected: wp-content paths, api.w.org header"). Then the profile
tunes the scan:

| Profile output | Effect |
|----------------|--------|
| Sitemap paths | Where to look first (`/wp-sitemap.xml`, `/sitemap.xml`, `/sitemap_index.xml`, plus whatever `robots.txt` lists) |
| Ignore patterns | Skip crawl traps and junk: WordPress `/wp-admin`, `?replytocom`, `/feed/`, `/wp-json`, `/xmlrpc.php`; Shopify `/cart`, `/checkout`, `/account`; Squarespace `?format=json`; Wix `?lang=` variants |
| Pacing hint | Shopify and some hosts throttle with 429 sooner, so lower per-host concurrency |
| Fix steps | Platform text for the "How to fix" column |
| Deep links | WordPress edit URL when a post ID is found |

Unknown platform is fine: the generic path works, the user just gets generic fix text.
Profiling must never block the scan; if it fails, continue as "Unknown".

**3. Discover pages.** Seed with sitemap URLs, then follow same-site links from each page.
Same site means same host ignoring a leading `www.`. Safeguards against infinite crawls:
page cap, max depth, max 20 query-string variants per path, skip file extensions that are
not HTML, skip calendar and archive patterns, `Content-Type` check before parsing, parse
at most the first 2 MB of a page. `robots.txt` `Disallow` rules are respected for
**crawling into pages** (politeness). They are not used to skip **checking** a link's
status, which is what every link checker does and what the site owner expects.

**4. Extract links.** For each link record: target URL (resolved against `<base>`), element
type, visible text (trimmed, collapsed whitespace; for images the `alt`; for icon-only
links the `aria-label` or `title`), nearest landmark (header, nav, main, footer, aside),
nearest heading text, and a short outer-HTML snippet. Ignore `mailto:`, `tel:`,
`javascript:`, `data:`, and `#fragment` only links (a stretch goal later: check that the
`#id` exists on the target page, a common silent breakage on nonprofit sites).

**5. Check links.** Deduplicate by normalized URL so each URL is requested once, then fan
results back out to every place it appears.

- Internal pages are checked by the crawl fetch itself (no second request).
- External and asset URLs: `HEAD` first. Fall back to `GET` (read headers, abort the body,
  except a small sniff for soft 404s) when `HEAD` returns 403, 404, 405, 501, or errors,
  because many servers answer `HEAD` wrongly.
- Redirects are followed **manually**, up to 10 hops, so we can record the chain and
  re-run the SSRF check on every hop.
- Timeouts: connect 5 s, total 15 s. One retry on timeout, connection reset, 5xx.
- 429: honor `Retry-After` (capped), slow that host down.
- Concurrency (env-tunable defaults): 40 global, 8 on the scanned site, 3 per external
  host, 1 for hosts flagged protected. Adaptive: if a host's latency spikes or 5xx rate
  climbs, back off. A free public tool must never knock over a small nonprofit's shared
  hosting.

**6. Classify** (see 5 for the taxonomy).

**7. Second chance** (Thorough only). See [BOT-BLOCKING.md](BOT-BLOCKING.md).

**8. Report.** Rows stream to the browser in small batches (every 250 ms or 25 rows).
The server keeps the result set only for reconnects and re-checks, then purges it.

---

## 5. Status taxonomy

| Bucket | Meaning | Examples |
|--------|---------|----------|
| **Broken** | We are confident the link does not work | 404, 410, DNS "site not found", connection refused, certificate error, redirect loop, repeated 5xx, timeout on both attempts |
| **Could not verify** | The site refused automated checks, so we cannot tell | 401, 403, 429, 999 with or without a recognized bot-protection signature; challenge pages |
| **Worth a look** | Works, but should be tidied | Permanent redirect, redirect to the home page, probable soft 404 (200 with "page not found" title), `http` that redirects to `https`, very slow (over 8 s) |
| **Working** | 2xx, or 3xx that lands on a 2xx with no concern | |
| Skipped | Not checked on purpose | mailto, tel, social sites that always block (configurable), user-ignored patterns |

Human wording is the contract. Each machine reason (`http_404`, `dns_failure`,
`tls_error`, `timeout`, `redirect_loop`, `blocked_waf`, ...) maps to a short title, a
one-sentence explanation, and a fix hint in one lookup table (`app/messages.py`) so the
words are easy to edit without touching logic.

Rule worth remembering: **404 and 410 are broken, always.** Block-style statuses are never
reported as broken. The one exception: on a host the circuit breaker flagged as
protected, Thorough mode re-verifies 404s too, because some WAFs fake them.

---

## 6. Architecture

### 6.1 Repo layout

```
Broken-Link-Checker/
  Dockerfile
  requirements.txt
  AGENTS.md
  README.md
  app/
    main.py            FastAPI app, security headers, static mount, health check
    config.py          Env vars and defaults in one place
    api.py             Routes: start, events, snapshot, cancel, pause, recheck
    scans.py           Scan lifecycle, in-memory registry, TTL purge, queue
    limits.py          Per-IP rate limit and client address lookup
    net/
      urlnorm.py       Normalization, same-site test, dedupe key
      safe_fetch.py    THE ONLY place outbound requests happen. SSRF guard, pinning, manual redirects
      ladder.py        Bot-blocking tiers and host circuit breaker
    engine/
      profiler.py      Platform detection from data/platforms.json
      crawler.py       Page discovery, sitemap, robots
      extract.py       Link extraction with context
      checker.py       Per-URL check, HEAD to GET, soft-404 sniff
      classify.py      Buckets and reasons
      suggest.py       Did-you-mean, corrected URL, WordPress deep link
    messages.py        Human wording for every reason
    cli.py             `python -m app.cli https://example.org` for dev and tests
  data/
    platforms.json     Platform signals, sitemap paths, ignore rules, fix steps
    known-hosts.json   Hosts that always block bots, social sites, WAF header signatures
  static/
    index.html  styles.css  app.js  favicon.svg  ght-icon.svg
  tests/
    fixtures/          Saved HTML and header snapshots per platform
    fakesite.py        Local test server with scripted behavior (404, 403 + WAF headers, 429, loops, slow)
  docs/
    PLAN.md  BOT-BLOCKING.md
```

Rules for future volunteers and AI: no ORM, no queue, no cache server, no dependency
injection framework, no background workers outside the single process. One file per
concern, plain functions, dataclasses for rows.

### 6.2 Why one process, in memory

State (running scans, buffered rows, SSE subscribers, rate-limit counters) lives in
Python dicts. That is why the container runs **one uvicorn worker**. A single asyncio
event loop comfortably handles dozens of concurrent connections, and selectolax parsing
is milliseconds per page. If we ever need to scale, we scale by adding containers with
sticky routing, not by adding shared storage.

### 6.3 API

| Route | Purpose |
|-------|---------|
| `POST /api/scans` | Body: `{url, scope: "site"\|"page", mode: "quick"\|"thorough", turnstile}`. Returns `{id, position}` (position greater than 0 means queued) |
| `GET /api/scans/{id}/events` | SSE stream. Supports `Last-Event-ID` replay from the in-memory buffer so refresh or reconnect resumes |
| `GET /api/scans/{id}` | Snapshot JSON of everything so far (polling fallback, export data) |
| `POST /api/scans/{id}/pause` and `/resume` | `asyncio.Event` gate in the worker loops |
| `POST /api/scans/{id}/cancel` | Stop and keep results so far |
| `POST /api/recheck` | Body: list of up to 200 URLs and a mode. Starts a mini scan of just those URLs. Same limits |
| `GET /healthz` | Container health check |

SSE event types: `profile`, `phase`, `progress`, `rows` (batched), `host_note`
(circuit-breaker verdicts), `done`, `error`. Send a comment line every 15 s to keep
proxies from closing the stream. Rows carry only data, never HTML, and the frontend
renders with `textContent` (no `innerHTML` with scanned content, ever, since it is
attacker-controlled).

### 6.4 Row shape

```json
{
  "id": "r123",
  "bucket": "broken",
  "reason": "http_404",
  "code": 404,
  "target": "https://example.org/old-page",
  "final": null,
  "chain": [],
  "element": "a",
  "text": "Read our annual report",
  "where": "Footer, under 'About us'",
  "page": "https://example.org/about/",
  "pageTitle": "About us",
  "snippet": "<a href=\"/old-page\">Read our annual report</a>",
  "suggest": {"kind": "did_you_mean", "url": "https://example.org/annual-report/"},
  "ms": 212
}
```

Titles and fix text come from `messages.py` on the server so CSV, Markdown, and the UI all
say the same thing.

### 6.5 Limits (env-tunable defaults)

| Limit | Default |
|-------|---------|
| Pages per scan | 500 |
| Unique URLs per scan | 5,000 |
| Wall time per scan | 10 min (then partial results, clearly labeled) |
| Concurrent scans (global) | 3, then queue up to 10 |
| Scans per IP | 5 per hour |
| Memory per scan | roughly under 50 MB at the caps (bounded by row and snippet size) |
| Results kept after finish | 30 min, then purged |

The original free tool caps at 2,000 links. We are more generous per scan but bounded,
and the numbers are config, not code.

---

## 7. Speed budget

Targets on a typical 200 page WordPress site, from a small container (1 vCPU):

| Mode | Target | How |
|------|--------|-----|
| Quick | Under 90 s for 200 pages and 2,000 links | Pipelined crawl and check, HTTP/2 connection reuse, DNS cache, `HEAD` first, circuit breaker stops wasting time on protected hosts |
| Thorough | Under 5 min, bounded by a per-host time budget (60 s) on slow lanes | Same fast pass first, then only block-like URLs get the slow ladder |

Thorough is never "everything slow". It is "fast pass, then slow only where needed", so
the cost is proportional to how protected the links are, not to site size.

Measure in Milestone 1 against the example.org screenshot (1,708 URLs, 150 flagged) and
record real numbers in `docs/BOT-BLOCKING-FINDINGS.md`. Do not promise these targets to
users until measured.

---

## 8. Security and abuse

A public tool that fetches arbitrary URLs is a classic SSRF target. This section is
mandatory reading before coding `safe_fetch.py`.

### 8.1 SSRF controls

- **Single choke point.** Every outbound request goes through `net/safe_fetch.py`. Nothing
  else imports `curl_cffi`. Enforced by a unit test that greps the codebase.
- Allow only `http` and `https`, ports 80 and 443.
- Resolve DNS ourselves, reject if **any** resolved address is private, loopback,
  link-local (including `169.254.169.254` cloud metadata), CGNAT, multicast, reserved, or
  IPv4-mapped IPv6 of any of those. Use Python's `ipaddress` on the resolved result, so
  decimal, octal, and hex IP tricks in the hostname are neutralized.
- **Pin the connection** to the validated IP (curl `RESOLVE`) to defeat DNS rebinding between
  check and connect. Verified in M1: `curl_cffi` supports this per session, not per request,
  so the fetcher keeps one pinned session per host and browser profile. The peer IP is also
  re-checked after connect.
- Manual redirects: re-validate scheme, port, and resolved IP on **every** hop.
- Response caps: max body read (2 MB pages, 64 KB sniff), max headers, max redirect hops,
  decompression bomb guard (cap decoded bytes).
- Test-only escape hatch `ALLOW_PRIVATE_TARGETS=1` so the fake test site on localhost
  works. The app refuses to start with it set when `ENV=production`.

### 8.2 Abuse and politeness

- Per-IP rate limit, global concurrent-scan cap with a visible queue.
- No CAPTCHA or Turnstile (decided). If abuse shows up, add one later behind an env switch.
- Per-target-host rate ceiling regardless of how many scans point at it.
- Cannot be pointed at our own domains (denylist from env).
- Honest identity: a custom request header identifying the tool and a contact page
  (`SCAN_IDENT_HEADER`) so site owners can recognize us in their logs. See Open questions.

### 8.3 Web app security

- Strict CSP (self only), `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`.
- `frame-ancestors https://nonprofittools.org https://*.nonprofittools.org` so the Tools
  Hub iframe works but random sites cannot frame it.
- All scanned content treated as hostile: never `innerHTML`, CSV formula-injection guard,
  length caps on every stored string, snippets HTML-escaped and truncated server-side.
- Run as non-root, read-only root filesystem compatible, no secrets in the image.

### 8.4 Privacy

- No database, no volume, no analytics cookies. Results exist in memory for the scan
  and 30 minutes after.
- Logs go to stdout only and contain scan id, host, counts, and timings. They do **not**
  contain full URLs, link text, or page content.
- Plain-language privacy note on the page. Consider the GHT privacy policy link.

### 8.5 Testing the security

- Unit tests for the SSRF guard with a table of nasty inputs (`127.1`, `0x7f000001`,
  `[::ffff:127.0.0.1]`, `169.254.169.254`, redirect to localhost, DNS name resolving to
  private IP, rebinding simulation).
- HawkScan DAST pass against a staging container before launch (the skill is already in
  our toolbox), and again before the AGPL release.

---

## 9. Docker and deployment

### 9.1 Image

- Base `python:3.12-slim` (Debian glibc, required for `curl_cffi` wheels; avoid Alpine).
- Non-root user, `PYTHONUNBUFFERED=1`, no `VOLUME`, no writable paths required.
- `HEALTHCHECK` hits `/healthz` using the standard library (no curl in the image).
- `ENTRYPOINT` runs uvicorn with **one worker**, host `0.0.0.0`, port from `$PORT`
  (default 8080). Keep the exec-form pattern used in the Fleet app so a host's command
  override cannot leave a container "up" with nothing running.
- Expected size: under 200 MB.

### 9.2 Configuration (all env vars, none required)

| Var | Default | Purpose |
|-----|---------|---------|
| `PORT` | 8080 | Listen port |
| `ENV` | production | `development` enables friendlier errors |
| `MAX_PAGES` / `MAX_URLS` / `MAX_SCAN_SECONDS` | 500 / 5000 / 600 | Per-scan limits |
| `MAX_CONCURRENT_SCANS` / `QUEUE_SIZE` | 3 / 10 | Global capacity |
| `RATE_LIMIT_PER_HOUR` | 5 | Per-IP scans |
| `CONCURRENCY_GLOBAL` / `_TARGET` / `_EXTERNAL_HOST` | 40 / 8 / 3 | Request pacing |
| `SCAN_PROXY_URL` | unset | Optional outbound proxy for the Thorough ladder (off by default) |
| `SCAN_IDENT_HEADER` | unset | Optional identity header value |
| `DENY_HOSTS` | `links.nonprofittools.org` | Never scan these (the tool itself) |
| `ALLOW_PRIVATE_TARGETS` | 0 | Tests only; refused in production |

Secrets (proxy credentials, if ever used) go in the host's environment settings,
never in git.

### 9.3 Sizing and resilience

- Start at 1 vCPU and 512 MB to 1 GB RAM. Memory is bounded by scan caps. Verify with the
  load test in Milestone 6 and size from data.
- Stateless restart: a deploy or crash loses in-flight scans. The UI detects a dropped
  stream, tries to resume via `Last-Event-ID`, and if the scan is gone says so plainly
  with a "Start again" button. Acceptable for a free tool; avoid deploying during known
  busy periods.
- Graceful shutdown: on SIGTERM stop accepting scans, let running ones finish up to 60 s.

### 9.4 Go-live

1. Build from GitHub on the host (Dockerfile build, deploy on push to `main`).
2. DNS: `links.nonprofittools.org` CNAME to the host, proxied by Cloudflare (gives us DDoS
   protection and `CF-Connecting-IP`). Confirm SSE is not buffered (disable response
   buffering or compression on `/api/scans/*/events`).
3. Add the nav item to the Tools Hub following its existing pattern:
   `<a href="https://links.nonprofittools.org/" class="nav-item" data-url="https://links.nonprofittools.org/" data-label="Broken Link Checker" data-slug="links">`
   plus a line in its `sitemap.xml`. That is a separate PR in the Hub repo (the Hub's
   AGENTS.md says to ask before structural changes; a new nav item is the sanctioned
   pattern).
4. Also works standalone, so deep links and the "Open in new tab" case are fine.

---

## 10. Testing strategy

| Layer | What |
|-------|------|
| Unit | URL normalization and dedupe, same-site test, link extraction with context (HTML fixtures), classifier table, messages, CSV escaping, SSRF guard table |
| Platform profiler | Saved header and HTML-head snapshots per platform in `tests/fixtures/`. No live network in CI. Add a fixture whenever a site is misdetected |
| Engine integration | `tests/fakesite.py` serves a scripted site: 404s, 410, 403 with Cloudflare headers, 429 with Retry-After, redirect loop, slow responses, soft 404, huge body, HEAD-hostile endpoints. Asserts buckets, not just codes |
| API | SSE ordering, `Last-Event-ID` resume, queueing, rate limit, cancel and pause |
| Frontend | Manual checklist plus an axe accessibility pass on the results page with 0, 10, and 1,500 rows |
| Live acceptance (manual, not CI) | Scan example.org. Compare to the screenshot baseline. Success looks like: genuine 404s such as the `staging.example.com` and `lostgrovebrewing.com` links still flagged; the dozens of `ticketing.example.com` 403s are either verified OK or grouped as one "could not verify" host note |
| Security | SSRF table tests, HawkScan on staging, dependency audit (`pip-audit`) |
| Load | 10 concurrent scans of a fake site at the caps; watch memory and event loop lag |

---

## 11. Milestones

Sizes: S is an evening, M is a few evenings, L is a couple of weeks of evenings.

### M0. Shell repo (done in this session)
- [x] Private repo, README, AGENTS.md, this plan, bot-blocking doc
- [x] Minimal FastAPI app with `/healthz`, branded placeholder page, Dockerfile
- [x] Starter `data/platforms.json` and `data/known-hosts.json`

### M1. Spike and measure (M)
- [ ] `safe_fetch.py` with SSRF guard and IP pinning; confirm `curl_cffi` supports pinning
- [ ] Run the experiment in BOT-BLOCKING.md on example.org: naive client vs Tier 0 vs
      full ladder, from a laptop and from a cloud container (IP reputation matters)
- [ ] Write results to `docs/BOT-BLOCKING-FINDINGS.md`; lock default tiers and limits
- Exit: we know how many false 403s each tier removes and what each costs in time

### M2. Core engine plus CLI (L)
- [ ] URL normalization, crawler with sitemap seeding and traps guards, extractor, checker,
      classifier, messages, fake test site
- [ ] `python -m app.cli https://example.org` prints the same buckets the UI will
- Exit: scans the fake site correctly; scans example.org end to end in Quick mode

### M3. API, SSE, limits (M)
- [ ] Routes, scan registry, queue, TTL purge, pause and cancel, rate limit
- Exit: two browsers can scan at once, reconnect resumes, caps enforced

### M4. Platform profiler and fix helpers (M)
- [ ] Profiler against fixtures for the top platforms, then validate signals on real sites
- [ ] Platform pacing and ignore rules, fix text, did-you-mean, corrected URL, WordPress
      edit deep link
- Exit: correct platform on at least 15 real nonprofit sites we spot check, with a
  fixture saved for each miss

### M5. Frontend (L)
- [ ] Landing, progress, results sections, filters, group-by, ignore, show-HTML
- [ ] Exports: CSV, Markdown, JSON, copy table, print stylesheet
- [ ] Brand pass and accessibility pass; mobile layout
- Exit: a non-technical staffer can scan, understand, export, with no help

### M6. Hardening and launch prep (M)
- [ ] Docker image tested (this machine has no Docker; build in CI or on the host)
- [ ] CSP and iframe verification inside the Tools Hub, SSE through Cloudflare
- [ ] HawkScan on staging, `pip-audit`, load test, memory sizing
- [ ] Privacy note, disclaimer text, Hub nav PR

### M7. Soft launch (S)
- [ ] 3 nonprofit partners scan their real sites; collect "was anything wrong or missing"
- [ ] Tune messages, ignore rules, platform text from their feedback
- Then list it publicly in the Hub.

### M8. Open source (S)
- [ ] Checklist in the next section, then flip the repo public under AGPL-3.0

---

## 12. Risks and honest limits

| Risk | Reality | Mitigation |
|------|---------|------------|
| Some sites cannot be verified automatically | Cloudflare JS challenges, Turnstile, DataDome, and datacenter-IP blocks beat any simple HTTP client | We do not pretend. They go to "Could not verify" with an open-in-browser button, grouped per site. Optional proxy lever and a possible v2 browser sidecar |
| Our container IP is flagged by WAFs | Cloud IP ranges are often pre-blocked | Measure in M1 from a real cloud host. `SCAN_PROXY_URL` exists for this |
| JavaScript-rendered sites | Links that exist only after JS runs will not be seen by an HTTP-only crawler (some Wix, Framer, and Google Sites pages) | Show a notice when a page has almost no links but heavy scripts. Sitemap seeding helps. Browser sidecar is v2 |
| Platform detection is heuristic | Signals change over time | Confidence shown, "Unknown" is fine, signals live in a data file, fixtures catch regressions |
| Becoming a DDoS toy | Free public fetcher | Per-host ceilings, adaptive backoff, global caps |
| Memory growth | Large pages, many rows | Hard caps on pages, URLs, row size, snippet size, 30 min purge |
| Restart loses scans | No storage by design | Clear UI message, resume where possible |
| `curl_cffi` is a native dependency | Wheels track libcurl-impersonate releases | Pin versions, Dependabot, glibc base image, document upgrade steps |
| Impersonation ethics | Making a link check look like a browser | Low rate, one request per URL, respects crawl politeness, no login or CAPTCHA bypass, identity header available. Same practice as established link checkers |

---

## 13. Open source readiness

Do these from day one so flipping the repo public is boring:

- [x] `# SPDX-License-Identifier: AGPL-3.0-or-later` at the top of every source file
- [x] `LICENSE` (AGPL-3.0 text) added at release time, copyright "Good Heart Tech"
- [x] No secrets, customer names, or internal URLs in code, docs, fixtures, or git history
      (the example.org scans stay as notes, not saved page copies of a real org)
- [x] Dependency license audit (FastAPI, uvicorn, curl_cffi, selectolax are MIT or
      compatible with AGPL)
- [x] AGPL section 13 means anyone running a modified public copy must offer the source.
      Add a visible "Source code" link in the footer at release
- [x] `CONTRIBUTING.md` with the simple-code rules from `AGENTS.md`
- [x] Brand assets note: AGPL covers the code; the GHT logo and name stay trademarks. Say
      so in the README so forks rebrand
- [ ] Public README that explains the bot-blocking approach and its limits honestly

---

## 14. Open questions (defaults assumed so work can start)

| # | Question | Assumed default |
|---|----------|-----------------|
| 1 | Subdomain and name | **Decided:** `links.nonprofittools.org` |
| 2 | Docker host | **Decided:** Sliplane, published through a Cloudflare tunnel route |
| 3 | Cloudflare Turnstile | **Decided: not needed** |
| 4 | Per-scan caps | **Decided:** 5,000 URLs in 10 minutes (500 pages) |
| 5 | Budget for a rotating or residential outbound proxy | None. Off by default; revisit only if M1 shows IP reputation is the main cause |
| 6 | Send an identity header so site owners can see who we are | Yes, optional via env |
| 7 | Font | **Resolved by the updated brand kit:** system stack, no font files |
| 8 | Social links (Facebook, Instagram, LinkedIn, X) | Marked "Not checked, social sites block automated checks", toggle to try anyway |
| 9 | GitHub org | `Good-Heart-Tech`, private |
