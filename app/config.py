# SPDX-License-Identifier: AGPL-3.0-or-later
"""All settings in one place. Every value can be overridden with an environment variable."""
import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _list(name: str, default: str) -> tuple[str, ...]:
    return tuple(x.strip().lower() for x in os.getenv(name, default).split(",") if x.strip())


@dataclass(frozen=True)
class Config:
    env: str = "production"
    max_pages: int = 500
    max_urls: int = 5000
    max_scan_seconds: int = 600
    max_concurrent_scans: int = 3
    queue_size: int = 10
    rate_limit_per_hour: int = 5
    concurrency_global: int = 40
    concurrency_target: int = 8
    concurrency_external: int = 3
    results_ttl_seconds: int = 1800
    thorough_host_budget_seconds: int = 60
    proxy_url: str = ""
    ident_header: str = ""
    deny_hosts: tuple[str, ...] = ("links.nonprofittools.org",)
    allow_private_targets: bool = False
    recheck_max: int = 200


def load() -> Config:
    env = os.getenv("ENV", "production")
    allow_private = os.getenv("ALLOW_PRIVATE_TARGETS", "0") == "1"
    if allow_private and env == "production":
        raise RuntimeError("ALLOW_PRIVATE_TARGETS=1 is for tests only and is refused when ENV=production")
    return Config(
        env=env,
        max_pages=_int("MAX_PAGES", 500),
        max_urls=_int("MAX_URLS", 5000),
        max_scan_seconds=_int("MAX_SCAN_SECONDS", 600),
        max_concurrent_scans=_int("MAX_CONCURRENT_SCANS", 3),
        queue_size=_int("QUEUE_SIZE", 10),
        rate_limit_per_hour=_int("RATE_LIMIT_PER_HOUR", 5),
        concurrency_global=_int("CONCURRENCY_GLOBAL", 40),
        concurrency_target=_int("CONCURRENCY_TARGET", 8),
        concurrency_external=_int("CONCURRENCY_EXTERNAL_HOST", 3),
        results_ttl_seconds=_int("RESULTS_TTL_SECONDS", 1800),
        thorough_host_budget_seconds=_int("THOROUGH_HOST_BUDGET_SECONDS", 60),
        proxy_url=os.getenv("SCAN_PROXY_URL", ""),
        ident_header=os.getenv("SCAN_IDENT_HEADER", ""),
        deny_hosts=_list("DENY_HOSTS", "links.nonprofittools.org"),
        allow_private_targets=allow_private,
    )


CONFIG = load()
