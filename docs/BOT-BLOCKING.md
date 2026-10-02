# Avoiding false 403s (bot blocking)

The screenshot that started this project shows dozens of `403 Forbidden` results on
`ticketing.example.com`, a ticketing site. Those pages are almost certainly fine for a
human in a browser. The site refused the checker. If we report them as broken, partners
lose trust in the whole report.

Two goals, in order:

1. **Never call a link broken because a bot blocker said no.**
2. **Verify as many of them as we honestly can, without slowing the default scan.**

---

## Why plain checkers get blocked

In rough order of how often each is the cause:

1. **TLS and HTTP/2 fingerprint.** A Python `requests` or Node `fetch` handshake does not
   look like Chrome's. Many WAFs score this before reading a single header.
2. **Header shape.** Missing `Accept-Language`, odd `Accept`, wrong header order, no
   `Sec-Fetch-*`, a library `User-Agent`.
3. **No cookies or referer.** Some sites set a cookie on the first visit and block
   requests that arrive without one, or without the page they were linked from.
4. **Rate.** Fifty parallel requests to one host looks like an attack.
5. **IP reputation.** Cloud and datacenter ranges are often pre-blocked. No header trick
   fixes this.
6. **JavaScript or interactive challenges** (Cloudflare "Just a moment", Turnstile,
   DataDome, PerimeterX). Not solvable with an HTTP client, and we will not try.

Items 1 to 4 are fixable cheaply. Item 5 is an infrastructure question. Item 6 is a limit
we report honestly.

---

## The approach: a fast pass, then escalate only where needed

### Tier 0: always on, costs nothing (Quick and Thorough)

- `curl_cffi` with Chrome impersonation: real Chrome TLS fingerprint, HTTP/2 settings, and
  header order. Same speed as a normal client, and it removes most fingerprint blocks.
- A complete, consistent browser header set (`Accept`, `Accept-Language`,
  `Sec-Fetch-Dest/Mode/Site`, `Upgrade-Insecure-Requests`, `Accept-Encoding`).
- `Referer` set to the page the link was found on (what a real click sends).
- A small cookie jar **per host, per scan**, so a cookie handed out on the first response
  is replayed on the next request.
- `HEAD` first, `GET` fallback (cheap, and fixes sites that mishandle `HEAD`).
- Polite per-host concurrency (see PLAN.md section 4, step 5).
- **Host circuit breaker** (below).

### Tier 1: Thorough mode, only for block-like results

Runs after the fast pass, only on URLs that came back block-like (see signatures), one
host at a time on a slow lane (concurrency 1, 1 to 2 s spacing with jitter):

1. **Different browser profile.** Retry with Safari, then Firefox (then Chrome on
   Android) impersonation. Different WAF rules, different results.
2. **Cookie prime.** Fetch the host's root page first to collect cookies, then retry the
   original URL with them.
3. **Range request.** `GET` with `Range: bytes=0-1023` and a normal `Accept`, which some
   rules treat as less scraper-like than a full fetch.
4. **Honor `Retry-After`** on 429 and wait, within a per-host time budget (default 60 s).

Stop at the first attempt that returns a real answer. Max 3 attempts per URL. If the
budget runs out, the remaining URLs for that host go to "Could not verify".

### Tier 2: optional outbound proxy (off by default)

`SCAN_PROXY_URL` routes only the Tier 1 slow lane through a proxy, for the case where M1
measurements show our container IP is the main problem. Costs money, so it is a lever,
not a default. Never used for the fast pass.

### Tier 3: headless browser (explicitly not v1)

A Chromium sidecar would pass some JavaScript checks, at the price of a 400 MB+ image,
much more RAM, and slow scans. If we ever do it, it ships as a separate image tag
(`:browser`) so the default stays one small container. Not in scope now.

### Never

- Solve or bypass CAPTCHAs or interactive challenges.
- Pretend to be Googlebot or any other named crawler.
- Log in, or use credentials, anywhere.
- Hammer a host that is clearly refusing us.

---

## Recognizing a block (instead of a dead link)

A result is **block-like** when either condition holds:

**Status:** `401`, `403`, `406`, `418`, `429`, `503`, `999` (LinkedIn style), or a
Cloudflare `520` to `530`.

**Signature** in headers or the first 4 KB of the body, from `data/known-hosts.json`:

| Vendor | Signals |
|--------|---------|
| Cloudflare | `cf-mitigated: challenge`, `server: cloudflare` with 403 or 503, body "Just a moment", "Attention Required", `cf-chl` |
| Imperva / Incapsula | `x-iinfo`, `x-cdn: Imperva`, body "Request unsuccessful. Incapsula incident ID" |
| Akamai | `server: AkamaiGHost`, body "Access Denied" with reference number |
| DataDome | `x-datadome`, `datadome` cookie, `captcha-delivery.com` |
| PerimeterX / HUMAN | `x-px-*`, `_px` cookies, "Press & Hold" |
| Sucuri | `x-sucuri-id`, body "Access Denied - Sucuri Website Firewall" |
| AWS WAF | `x-amzn-waf-action`, `x-amzn-errortype` |

When a signature matches we can say **who** blocked us ("Blocked by Cloudflare bot
protection") which is far more useful to the user than "403". Without a signature, a bare
`403` or `429` is still "Could not verify", worded more cautiously.

**Always broken, never blocked:** `404`, `410`, DNS failure, refused connection, TLS
certificate error, redirect loop. (Exception: Thorough mode re-verifies 404s on a host
already flagged protected, since some WAFs return fake 404s.)

---

## Host circuit breaker (the biggest speed and noise win)

Blocking is per site, so decide per site, not per URL.

```
for each external host, track the first results:
  if 3 of the first 5 responses are block-like:
      mark host PROTECTED
      stop sending its remaining URLs through the fast lane
      Quick mode:    remaining URLs -> "Could not verify" (no more requests)
      Thorough mode: probe the host root through the ladder once.
                     If a tier works, reuse that profile for the rest at slow-lane pace.
                     If nothing works, remaining URLs -> "Could not verify".
  emit one host_note event: "ticketing.example.com blocked 38 of 38 checks (Cloudflare)"
```

Effects:

- Quick stays fast: we stop knocking on a door that will not open.
- The report shows **one** line for 38 blocked ticketing links instead of 38 red rows.
- The user gets an **Open in browser** button for a sample link to confirm by eye, and a
  one-click "mark this site as OK" (client-side, affects the exports).

---

## Known-hostile hosts

`data/known-hosts.json` lists hosts that block (or lie to) automated checks. Defaults:

- **Social:** facebook.com, instagram.com, linkedin.com, x.com, twitter.com, tiktok.com.
  Reported as "Not checked: social sites block automated checks". A toggle on the page
  lets the user try anyway.
- **Review and local sites** that routinely block: yelp.com and similar.
- Anything we learn from M1 and from soft-launch feedback.

Volunteers can edit the list without touching code. Each entry has a reason and the
date it was verified, so stale entries are visible.

---

## Honest limits (say them in the UI too)

- Some links will land in "Could not verify" no matter what. That is the correct, honest
  result, and the page tells the user how to check them (open in browser).
- Results can vary by day and by our IP. A site that blocks us today may not tomorrow.
- A link that works in a browser may still fail for us, and a link that works for us may
  be blocked for a visitor in another country. We test from one location.

---

## M1 experiment (decides the defaults)

Goal: replace guesses with numbers before building the rest.

1. Collect the 150 flagged URLs from the screenshot scan of example.org, plus about 50
   known-good external links, plus a handful of known-bad ones (real 404s) as controls.
2. Run each of these against the set, from **(a)** a laptop on a normal connection and
   **(b)** a small cloud container, 3 runs each:
   - Naive client (default Python `User-Agent`)
   - Tier 0 (Chrome impersonation, headers, referer, cookies)
   - Tier 0 plus Tier 1 ladder
3. Record per run: counts per bucket, block signatures seen, total time, requests sent.
4. Decide:
   - Is Tier 0 enough that Quick mode needs no escalation for most sites?
   - Which Tier 1 steps actually earn their time?
   - Does the cloud IP lose meaningfully versus the laptop (justifying `SCAN_PROXY_URL`)?
   - Are the per-host thresholds (3 of 5, 60 s budget) right?
5. Write `docs/BOT-BLOCKING-FINDINGS.md` with the table and the final defaults.

Do not advertise a "reduces false positives by X percent" claim until this exists.
