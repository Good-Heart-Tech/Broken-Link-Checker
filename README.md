# Broken Link Checker

A free tool by [Good Heart Tech](https://goodhearttech.org/) that scans a nonprofit's website for broken links and shows how to fix them.

**Use it now at [links.nonprofittools.org](https://links.nonprofittools.org)**, or from the [Nonprofit Web Tools](https://nonprofittools.org/?tool=links) hub. No sign-up, nothing about your site is saved.

## What it does

- Quick scan and Thorough scan modes (Thorough double-checks sites that block automated tools)
- Separates **Broken** from **Could not verify**, so bot blockers do not look like dead links
- Detects your site platform (WordPress, Wix, Squarespace, Shopify, and more) to crawl smarter and give platform-specific fix steps
- Results table with the page, link text, and status; working links collapsed below
- Export to CSV, Markdown, JSON, or print to PDF
- One Docker container, no database, no storage volume

## Run it yourself

```bash
docker build -t broken-link-checker .
docker run --rm -p 8080:8080 broken-link-checker
```

Then open <http://localhost:8080>. See [docs/SELF-HOSTING.md](docs/SELF-HOSTING.md) for settings and environment variables.

To work on the code:

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS and Linux
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8080
```

## Documentation

- [docs/SELF-HOSTING.md](docs/SELF-HOSTING.md): run your own copy
- [docs/BOT-BLOCKING.md](docs/BOT-BLOCKING.md): how we avoid false 403s and what we cannot verify
- [docs/BOT-BLOCKING-FINDINGS.md](docs/BOT-BLOCKING-FINDINGS.md): measurements from real scans
- [docs/PLAN.md](docs/PLAN.md): design, architecture, and security notes
- [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md): rules for volunteers and AI assistants

## About Good Heart Tech

[Good Heart Tech](https://goodhearttech.org/) is a 501(c)(3) nonprofit that provides free IT and cybersecurity services to other nonprofits and builds free tools like this one. [Donate](https://goodhearttech.org/donate/) to support the work.

## License

Open source under [AGPL-3.0-or-later](LICENSE). If you run a modified public copy, the AGPL requires you to offer your changes as source. The Good Heart Tech name and logo are trademarks of Good Heart Tech, so please rebrand forks.

The tool is provided as is, may be changed or retired at any time, and is for informational use only.
