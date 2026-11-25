"""Network resilience helpers: wait for DNS after wake, retry with backoff.

Why: the scraper runs on a laptop in Modern Standby. Task Scheduler fires the
missed 06:00/07:00 triggers 2-4 seconds after a power-button wake, before
Wi-Fi and DNS are back, so every host failed with NameResolutionError
(Nov 17, 19, 20 2026). Waiting for DNS and retrying turns those runs into
normal ones.
"""
from __future__ import annotations

import logging
import socket
import time
from typing import Iterable

import requests

log = logging.getLogger(__name__)

# Error substrings that mean "the network was down", not "the page changed".
_NETWORK_MARKERS = (
    "NameResolutionError", "getaddrinfo failed", "ConnectionError",
    "ConnectTimeout", "ReadTimeout", "Timeout", "Max retries exceeded",
    "Connection aborted", "Connection reset", "RemoteDisconnected",
    "Temporary failure in name resolution", "SSLError",
)


def is_network_error(err: str | BaseException | None) -> bool:
    if err is None:
        return False
    text = err if isinstance(err, str) else f"{type(err).__name__}: {err}"
    return any(m in text for m in _NETWORK_MARKERS)


def dns_ok(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def wait_for_network(hosts: Iterable[str], timeout: float = 180.0,
                     interval: float = 5.0, sleep=time.sleep,
                     resolver=dns_ok) -> float | None:
    """Block until every host resolves, up to `timeout` seconds.

    Returns seconds waited, or None if the network never came up.
    """
    hosts = list(dict.fromkeys(hosts))
    waited = 0.0
    while True:
        missing = [h for h in hosts if not resolver(h)]
        if not missing:
            if waited:
                log.info("network up after %.0fs", waited)
            return waited
        if waited >= timeout:
            log.error("network still down after %.0fs: %s", waited, missing)
            return None
        sleep(interval)
        waited += interval


def get_with_retry(url: str, *, session: requests.Session | None = None,
                   attempts: int = 4, backoff: float = 5.0, timeout: float = 30.0,
                   sleep=time.sleep, **kwargs) -> requests.Response:
    """GET with exponential backoff on network errors and HTTP 5xx/429.

    4xx other than 429 raise immediately (retrying will not help).
    """
    getter = (session or requests).get
    last: BaseException | None = None
    for i in range(attempts):
        try:
            r = getter(url, timeout=timeout, **kwargs)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code} for {url}", response=r)
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status and status != 429 and status < 500:
                raise
            last = e
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
        if i < attempts - 1:
            delay = backoff * (2 ** i)
            log.warning("GET %s failed (%s); retry %d/%d in %.0fs",
                        url, type(last).__name__, i + 1, attempts - 1, delay)
            sleep(delay)
    assert last is not None
    raise last
