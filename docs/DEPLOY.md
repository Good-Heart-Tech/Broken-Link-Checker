# Deploying to Sliplane

One container, no volume. Live at `links.nonprofittools.org`.

## Settings

| Setting | Value |
|---------|-------|
| Source | This GitHub repo, `main` branch, build from the `Dockerfile` |
| Port | **8080** (the image reads `PORT` and defaults to 8080) |
| Volume | None. Do not add one |
| Health check path | `/healthz` (returns `{"status":"ok","app":"broken-link-checker","version":"..."}`) |
| Replicas | 1. Scan state is in memory, so do not scale out |
| Resources | Start at 1 vCPU and 1 GB RAM. Watch memory during the first busy day |
| Environment | None required. Defaults are right. See the table below to tune |

## Traffic path

Browser -> Cloudflare -> published application route (tunnel) -> Sliplane container on port 8080.

- The app reads the visitor's address from `CF-Connecting-IP` (then `X-Forwarded-For`) for the
  hourly rate limit. **Do not also expose the Sliplane public URL**, or someone could send a fake
  header and dodge the limit. Use only the Cloudflare route.
- Scans stream progress with Server-Sent Events. If progress ever stalls in the browser, check that
  Cloudflare is not buffering `/api/scans/*/events` (the app sends `X-Accel-Buffering: no` and a
  keep-alive every 15 seconds).
- The app sets `frame-ancestors` so the Nonprofit Tools Hub can embed it. Other sites cannot.

## Optional environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `MAX_PAGES` | 500 | Pages crawled per scan |
| `MAX_URLS` | 5000 | Unique links checked per scan |
| `MAX_SCAN_SECONDS` | 600 | Wall time per scan before partial results |
| `MAX_CONCURRENT_SCANS` | 3 | Scans running at once (others wait in line) |
| `QUEUE_SIZE` | 10 | How many can wait |
| `RATE_LIMIT_PER_HOUR` | 5 | Scans per visitor per hour |
| `CONCURRENCY_GLOBAL` | 40 | Simultaneous requests per scan |
| `CONCURRENCY_TARGET` | 8 | Simultaneous requests to the site being scanned |
| `CONCURRENCY_EXTERNAL_HOST` | 3 | Simultaneous requests to any other site |
| `THOROUGH_HOST_BUDGET_SECONDS` | 60 | Time Thorough mode spends per blocked site |
| `SCAN_PROXY_URL` | unset | Optional outbound proxy for Thorough mode only |
| `SCAN_IDENT_HEADER` | unset | Adds an `X-Scanner` header so site owners can identify us |
| `DENY_HOSTS` | `links.nonprofittools.org` | Never scan these (the tool itself, so it cannot scan itself in a loop). Your own domains are fine to scan |
| `PORT` | 8080 | Listen port |

Never set `ALLOW_PRIVATE_TARGETS`. It exists for tests and the app refuses to start with it when
`ENV` is `production` (the default).

## Checking a deploy

1. `https://links.nonprofittools.org/healthz` shows the new `version`.
2. Scan a small site you know. Expect results in under a minute.
3. Open the Tools Hub (`?tool=links`) and confirm the tool loads in the frame.
4. Logs show only scan ids, hosts, and counts. They never contain full URLs or page text.

## Rolling back

Redeploy the previous commit from the Sliplane Events tab. There is no data to migrate.
