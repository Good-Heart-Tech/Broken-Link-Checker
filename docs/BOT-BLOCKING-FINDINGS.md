# Bot-blocking findings (first measurements)

Measured on 2026-10-01 from a Windows laptop on a normal connection, using
`python -m app.cli example.org --pages 60`. This is **not** the cloud-IP test from the plan, so
treat results as a lower bound on blocking. Repeat from the production container before quoting numbers.

## Headline

The original screenshot showed dozens of `403 Forbidden` results on `ticketing.example.com`. With the
Chrome-fingerprint client (Tier 0), **those same links came back 200 (OK) or normal redirects**. No
escalation was needed for them.

## Runs (60 page cap)

| Run | Time | Pages | Links | Broken | Could not verify | Worth a look |
|-----|------|-------|-------|--------|------------------|--------------|
| Quick, first | 12 s | 55 | 949 | 19 | 98 | 85 |
| Quick, later | 21 s | 48 | 963 | 24 | 2 | 86 |
| Thorough | 22 s | 56 | 978 | 19 | 2 | 87 |

What the numbers say:

- The first run flagged 98 links as "could not verify". A later run on the same site had only 2
  (TripAdvisor, DataDome). The difference looks like a temporary burst limit on a host early in the
  scan. The circuit breaker treats a burst of blocks as a protected host, so one bad moment can
  hide a whole site. Thorough mode exists for this and recovered them. Worth watching on the
  cloud IP.
- Only genuine bot protection stayed unverifiable: `www.tripadvisor.com` (DataDome).
- Quick and Thorough cost about the same here because few links needed the slow lane. Thorough only
  gets slower when many links are blocked.

## Real problems the scan found on example.org

These are good examples of what the tool is for:

- Editor mistakes: a link whose address is several page links joined by commas, a leftover
  `_wp_link_placeholder` link, and `volunteer/boxoffice@example.org` (an email address missing
  `mailto:`).
- An old staging site (`staging.example.com`) still linked from live pages.
- **A spam link** (`www.mersin24.com`, link text "mersin escort bayan") appears in the page header
  or footer area of every page. That points to an injected link, which usually means the site was
  compromised. Worth telling the organization.

## Things the first real scan taught us (fixed)

- Cloudflare's `/cdn-cgi/l/email-protection` link looked like a 404 on 81 pages. It is Cloudflare's
  own email obfuscation, so we now skip `/cdn-cgi/` paths.
- `www.` to apex redirects (for example `www.example.net` to `example.net`) were noisy "Link has
  moved" warnings. They are now treated as trivial.
- The scanned site returned 504 errors on 39 pages at 8 parallel requests. We now slow down on the
  scanned site automatically when a quarter of recent requests fail or error.

## Caveat about this machine

`tag.simpli.fi` (an advertising tracker) reported "Website not found". This laptop uses DNS
filtering that blocks ad networks, so that result is likely a local artifact, not a dead domain.
On the production container it should resolve normally. Check after deploy.

## Still to measure

- The same scan from the production container (cloud IP reputation).
- How often the circuit breaker trips on a healthy site under the cloud IP.
- Whether Thorough mode's Safari and Firefox profiles recover anything Chrome could not on real
  sites (they do against the test fixture).
