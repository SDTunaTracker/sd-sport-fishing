"""Low-footprint access to the fish-report network (TECK.net sites).

sportfishingreport.com's terms (updated 2026-09-01) forbid automated access
without written permission; it runs socalfishreports.com and
sandiegofishreports.com too. The owner chose to continue (2026-11-25) on
these terms:

* an honest, stable User-Agent (no browser impersonation),
* at least MIN_INTERVAL seconds between requests to one host,
* stop on a block (CAPTCHA, 403, repeated 429) instead of working around it.

Landing sites (fishcounts.com, fishingreservations, landing homepages) are
not covered by this and keep their existing fetch code.
"""
from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

BOT_UA = "TunaTrackerBot/1.0 (+https://thetunatracker.com; daily fish-count summary)"
MIN_INTERVAL = 4.0  # seconds between requests to the same host

TECK_DOMAINS = (
    "socalfishreports.com",
    "sandiegofishreports.com",
    "sportfishingreport.com",
    "976-tuna.com",
)

_last: dict[str, float] = {}
_lock = threading.Lock()


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def is_teck(url: str) -> bool:
    h = host(url)
    return any(h == d or h.endswith("." + d) for d in TECK_DOMAINS)


def wait_turn(url: str, sleep=time.sleep, clock=time.monotonic) -> float:
    """Block until MIN_INTERVAL has passed since the last request to url's host.

    Returns the seconds waited. Hosts are grouped by registered domain so
    www. and bare names share one budget.
    """
    h = host(url)
    key = next((d for d in TECK_DOMAINS if h == d or h.endswith("." + d)), h)
    with _lock:
        now = clock()
        due = _last.get(key, 0.0) + MIN_INTERVAL
        wait = max(0.0, due - now)
        _last[key] = max(now, due)
    if wait:
        sleep(wait)
    return wait


def headers(url: str, base: dict | None = None) -> dict:
    """Request headers for url: the bot UA for TECK hosts, else base unchanged."""
    h = dict(base or {})
    if is_teck(url):
        h["User-Agent"] = BOT_UA
    return h
