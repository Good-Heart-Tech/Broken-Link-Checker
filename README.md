# Broken Link Checker

A free tool by [Good Heart Tech](https://goodhearttech.org/) that scans a nonprofit's
website for broken links and shows how to fix them. Planned home:
`links.nonprofittools.org`, alongside the other [Nonprofit Tools](https://nonprofittools.org/).

**Status:** v1 built. Deploys to Sliplane as one container on port 8080.

## Start here

- [docs/PLAN.md](docs/PLAN.md): full implementation plan (UX, pipeline, architecture,
  security, Docker, milestones, risks, open questions)
- [docs/BOT-BLOCKING.md](docs/BOT-BLOCKING.md): how we avoid false 403s and what we
  honestly cannot verify
- [docs/DEPLOY.md](docs/DEPLOY.md): Sliplane settings, environment variables, checks
- [docs/BOT-BLOCKING-FINDINGS.md](docs/BOT-BLOCKING-FINDINGS.md): first real measurements
- [AGENTS.md](AGENTS.md): rules for volunteers and AI agents working in this repo

## Highlights

- Quick scan and Thorough scan modes (Thorough double-checks sites that block automated tools)
- Separates **Broken** from **Could not verify** so bot blockers do not look like dead links
- Detects the site platform (WordPress, Wix, Squarespace, Shopify, and more) to crawl
  smarter and give platform-specific fix steps
- Results table with the page, link text, and status; working links collapsed below
- Export to CSV, Markdown, JSON, or print to PDF
- One Docker container, no storage volume, nothing about your site is saved

## Run it locally

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS and Linux
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8080
```

Then open <http://localhost:8080>. Health check: `/healthz`.

```bash
docker build -t broken-link-checker .
docker run --rm -p 8080:8080 broken-link-checker
```

## License

Open source under [AGPL-3.0-or-later](LICENSE). If you run a modified public copy, the AGPL
requires you to offer your changes as source. The Good Heart Tech name and logo remain
trademarks of Good Heart Tech, so please rebrand forks. See [CONTRIBUTING.md](CONTRIBUTING.md).
