# Contributing

Thanks for helping nonprofits find and fix broken links. This project is built to be simple for future volunteers and AI assistants to read and change.

1. Read [AGENTS.md](AGENTS.md). It lists the simple-code rules (plain functions, no build step, one uvicorn worker, no disk writes) and the safety rules (all outbound requests go through `app/net/safe_fetch.py`, never render scanned content with `innerHTML`).
2. Add `# SPDX-License-Identifier: AGPL-3.0-or-later` to every new source file.
3. Add a test fixture whenever a platform is misdetected or a result is misclassified.
4. Run `pytest` before opening a pull request.
5. Contributions are licensed under AGPL-3.0-or-later. The Good Heart Tech name and logo are trademarks and are not covered by the license.
