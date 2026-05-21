"""Live ocean conditions: sea-surface temperature + moon phase.

Both pieces are computed once per daily run and written into web/data.js
(under window.SD.META) so the dashboard header can display them without
making any browser-side network calls.

SST source: NOAA NDBC station 46232 "Point Loma South" — the closest
buoy with continuous water-temperature reporting to the San Diego
sportfishing zone. Raw feed: https://www.ndbc.noaa.gov/data/realtime2/46232.txt
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from .moon import MoonInfo, moon_info

log = logging.getLogger(__name__)

# NOAA NDBC realtime2 plain-text feed for Point Loma South.
NDBC_STATION = "46232"
NDBC_URL = f"https://www.ndbc.noaa.gov/data/realtime2/{NDBC_STATION}.txt"
NDBC_NAME = "Point Loma South (NDBC 46232)"

# The realtime2 .txt has a 2-line header (comments starting with `#`) and then
# whitespace-separated columns. WTMP is the 15th column (index 14).
WTMP_COL_INDEX = 14
MISSING_TOKEN = "MM"


def _c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def fetch_sst_f(timeout: float = 20.0) -> tuple[float, str] | None:
    """Return (degrees_fahrenheit, observation_iso) for the latest valid WTMP
    sample from NDBC station 46232, or None if nothing recent is parseable."""
    try:
        r = requests.get(
            NDBC_URL,
            headers={"User-Agent": "sd-sport-fishing/1.0"},
            timeout=timeout,
        )
        r.raise_for_status()
    except Exception as e:
        log.warning("NDBC fetch failed: %s", e)
        return None
    # First non-comment row is the most recent observation.
    for line in r.text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) <= WTMP_COL_INDEX:
            continue
        wtmp = parts[WTMP_COL_INDEX]
        if wtmp == MISSING_TOKEN:
            continue  # buoy was down for that sample, try the next row
        try:
            c = float(wtmp)
        except ValueError:
            continue
        # Build the observation timestamp from cols 0-4 (UTC).
        try:
            yr, mo, dy, hr, mi = (int(x) for x in parts[:5])
            obs = datetime(yr, mo, dy, hr, mi, tzinfo=timezone.utc).isoformat(timespec="seconds")
        except Exception:
            obs = ""
        return round(_c_to_f(c), 1), obs
    return None


def current_moon() -> MoonInfo:
    return moon_info(datetime.now(tz=timezone.utc))


def snapshot() -> dict:
    """Build the conditions blob for export.py to splice into META."""
    sst = fetch_sst_f()
    moon = current_moon()
    out = {
        "moonPhase": moon.phase,
        "moonIllum": moon.illum,
        "sstSource": NDBC_NAME,
    }
    if sst is not None:
        out["sstF"], out["sstObservedAt"] = sst
    else:
        out["sstF"] = None
        out["sstObservedAt"] = None
    return out
