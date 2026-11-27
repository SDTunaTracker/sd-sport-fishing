"""Wind and swell grids for /charts -> web/api/v1/met_grid.json.

Charts animates 10 m wind and swell over a 9x9 grid at 0.5° (35°N..31°N,
121°W..117°W, the same grid as web/charts.jsx _WIND_*). Every browser used to
ask Open-Meteo for both grids the first time a layer was switched on (0.4-1.1 s
on a phone, one call per visitor per hour). The hourly scrape now makes the
two batched requests once and Pages serves the result from the CDN;
web/charts.jsx still calls Open-Meteo itself when this file is missing, fails,
or doesn't cover the current hour.

Open-Meteo's free API is for non-commercial use, which this site is.

    python -m src.met_grid            # write web/api/v1/met_grid.json
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# Must match web/charts.jsx (_WIND_NX/_NY/_LO1/_LA1/_DX/_DY).
GRID = {"nx": 9, "ny": 9, "lo1": -121.0, "la1": 35.0, "dx": 0.5, "dy": 0.5}
HOURS = 30            # from the current UTC hour on; the file is rebuilt hourly
OUT = Path(__file__).resolve().parents[1] / "web" / "api" / "v1" / "met_grid.json"
UA = {"User-Agent": "thetunatracker.com/met-grid"}

WIND_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"


def grid_points() -> tuple[list[str], list[str]]:
    """Row-major (north to south, west to east), as charts.jsx builds them."""
    lats, lons = [], []
    for j in range(GRID["ny"]):
        for i in range(GRID["nx"]):
            lats.append(f"{GRID['la1'] - j * GRID['dy']:.2f}")
            lons.append(f"{GRID['lo1'] + i * GRID['dx']:.2f}")
    return lats, lons


def _fetch(url: str, hourly: str, extra: str = "") -> list[dict]:
    lats, lons = grid_points()
    full = (f"{url}?latitude={','.join(lats)}&longitude={','.join(lons)}"
            f"&hourly={hourly}&forecast_days=3&timezone=UTC{extra}")
    r = requests.get(full, headers=UA, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else [data]


def _round(v, nd):
    return None if v is None else round(float(v), nd)


def build(wind_locs: list[dict], marine_locs: list[dict], now: datetime) -> dict:
    """Pure: Open-Meteo responses -> payload. Hour 0 is now's UTC hour."""
    n = GRID["nx"] * GRID["ny"]
    if len(wind_locs) != n or len(marine_locs) != n:
        raise ValueError(f"expected {n} grid points, got {len(wind_locs)} wind / {len(marine_locs)} marine")
    start = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    key = start.strftime("%Y-%m-%dT%H:%M")

    def frames(locs, field, nd):
        times = (locs[0].get("hourly") or {}).get("time") or []
        if key not in times:
            raise ValueError(f"{key} not in the forecast times ({times[:1]}..{times[-1:]})")
        i0 = times.index(key)
        out = []
        for h in range(i0, min(i0 + HOURS, len(times))):
            out.append([_round(((loc.get("hourly") or {}).get(field) or [None] * len(times))[h], nd)
                        for loc in locs])
        return out

    return {
        "generated": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "start": start.isoformat().replace("+00:00", "Z"),
        "stepHours": 1,
        "grid": GRID,
        # m/s and degrees the wind comes FROM (Open-Meteo convention)
        "wind": {"speed": frames(wind_locs, "windspeed_10m", 1),
                 "dir": frames(wind_locs, "winddirection_10m", 0)},
        # metres, degrees FROM, seconds; null over land
        "swell": {"height": frames(marine_locs, "swell_wave_height", 2),
                  "dir": frames(marine_locs, "swell_wave_direction", 0),
                  "period": frames(marine_locs, "swell_wave_period", 1)},
    }


def run(out: Path = OUT, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    wind = _fetch(WIND_URL, "windspeed_10m,winddirection_10m", "&wind_speed_unit=ms")
    marine = _fetch(MARINE_URL, "swell_wave_height,swell_wave_direction,swell_wave_period")
    payload = build(wind, marine, now)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    log.info("met_grid: %d hours from %s -> %s", len(payload["wind"]["speed"]), payload["start"], out)
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        run()
    except Exception as e:  # keep the last good file; charts.jsx falls back to Open-Meteo
        log.warning("met_grid failed, keeping the existing file: %s", e)
        sys.exit(1)
