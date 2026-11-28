"""Results source adapters: one module per source whose terms and robots.txt allow reading.

Checked 2026-11-27 (see the hand-over note):
  catalinaclassicpaddleboardrace.com  robots allows all, no terms page → OK (catalina_classic.py)
  paddleguru.com                      ToS forbids automated access       → never
  webscorer.com                       ToS: scraping without consent prohibited → never (owner may download manually)
  athlinks.com                        ToS forbids robots / automatic means → never
  my.raceresult.com                   robots disallows results lists/details → never

Every adapter fetches through polite_get(): identified user agent, one request
every few seconds, cached on disk, and it stops on any non-200 answer.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import requests

from .. import course as CO

CACHE = CO.ROOT / "data" / "paddle_cache"
UA = "TunaTrackerBot/1.0 (+https://thetunatracker.com; personal non-commercial paddle race results)"
DELAY_S = 4.0
_last = [0.0]


class Blocked(RuntimeError):
    """The site said no (403/429/5xx or a captcha page): stop the whole run."""


def polite_get(url: str, max_age_s: float = 30 * 86400) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest()[:20] + ".html")
    if f.exists() and time.time() - f.stat().st_mtime < max_age_s:
        return f.read_text(encoding="utf-8")
    wait = DELAY_S - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    r = requests.get(url, headers={"User-Agent": UA}, timeout=40)
    _last[0] = time.time()
    if r.status_code != 200 or "captcha" in r.text[:5000].lower():
        raise Blocked(f"{url}: HTTP {r.status_code}; stopping")
    f.write_text(r.text, encoding="utf-8")
    return r.text
