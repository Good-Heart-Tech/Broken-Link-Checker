# Broken Link Checker: Agent Guidelines

Read [docs/PLAN.md](docs/PLAN.md) before making design changes and
[docs/BOT-BLOCKING.md](docs/BOT-BLOCKING.md) before touching anything that makes
outbound requests.

## What this is

A free website broken-link scanner for nonprofits, hosted at `links.nonprofittools.org`
and listed in the Nonprofit Tools Hub. Single Docker container, **no storage volume**,
in-memory state only. Public repo, AGPL-3.0-or-later.

## Do

- Keep it simple: plain functions, dataclasses, one file per concern, no ORM, no task
  queue, no cache server, no dependency-injection framework.
- Python 3.12, FastAPI, one uvicorn worker (state is in memory on purpose).
- Frontend is vanilla HTML, CSS, and JS with **no build step**. Serve from `static/`.
- Use the GHT brand tokens already in `static/styles.css`. Do not add a second palette.
- Put human wording in `app/messages.py` and editable detection data in `data/*.json`.
- Add `# SPDX-License-Identifier: AGPL-3.0-or-later` to every new source file.
- Write for non-technical nonprofit staff in all user-facing text. Say "nonprofit
  partners", never "clients". No em dashes anywhere.
- Add a test fixture whenever a platform is misdetected or a result is misclassified.

## Do not

- Make outbound requests anywhere except `app/net/safe_fetch.py`. It owns the SSRF guard.
- Render scanned content with `innerHTML`. Scanned pages are hostile input. Use `textContent`.
- Write results, logs with full URLs, or anything else to disk.
- Report a bot-blocker status (401, 403, 429, 999) as "broken". See the status taxonomy
  in the plan.
- Solve CAPTCHAs, spoof named crawlers, or log in to anything.
- Add heavy dependencies (headless browsers, databases) without approval.
- Commit secrets. Proxy settings are environment variables only.

## Run locally

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash (.venv/bin/activate on macOS and Linux)
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8080
pytest                          # runs against a scripted fake site, no internet needed
python -m app.cli example.org --pages 60   # scan from the terminal
```

Layout: `app/engine/` is the pipeline (runner, checker, extract, profiler), `app/net/` is the only
code that talks to the network, `app/scans.py` and `app/api.py` serve the browser, `static/` is the UI.

## Cache note

Cloudflare keeps CSS and JS for up to 4 hours no matter what the app says. When you change `styles.css`, `app.js` or `embed.js`, bump the `?v=` number on their tags in `static/index.html` so visitors get the new file at once.

## Ask first

- Changing limits, the status taxonomy, or the SSRF rules.
- Anything that adds storage, accounts, or third-party scripts.
