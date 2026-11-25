"""Daily SST and wind for the OC/LA region, one row per (date, point).

Kept in its own table, not ocean_temps: several San Diego forecast queries
average every ocean_temps row for a date, so OC/LA points there would shift
SD scores.

Sources (same as San Diego): NOAA ERDDAP MUR SST (jplMURSST41, ~2-day lag)
and Open-Meteo ERA5 archive for wind and pressure (~5-day lag).

    .venv\\Scripts\\python.exe -m src.ocla_conditions --start 2015-01-01
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from .backtest import _fetch_openmeteo_wind
from .sst import _c_to_f, _fetch_mur

log = logging.getLogger(__name__)

# Offshore of each harbor so MUR's land mask doesn't blank the point.
POINTS: dict[str, tuple[float, float]] = {
    "Ventura / Channel Islands": (34.15, -119.35),
    "Santa Monica Bay":          (33.85, -118.60),
    "Catalina Channel":          (33.55, -118.35),
    "Huntington Flats":          (33.55, -118.05),
    "Dana Point":                (33.40, -117.75),
}

# Which point describes each OC/LA landing's home water.
LANDING_POINT: dict[str, str] = {
    "Channel Islands Sportfishing": "Ventura / Channel Islands",
    "Ventura Harbor Sportfishing":  "Ventura / Channel Islands",
    "Marina Del Rey Sportfishing":  "Santa Monica Bay",
    "Redondo Beach Sportfishing":   "Santa Monica Bay",
    "22nd Street Landing":          "Catalina Channel",
    "LA Waterfront Sportfishing":   "Catalina Channel",
    "Pierpoint Landing":            "Catalina Channel",
    "Long Beach Sportfishing":      "Huntington Flats",
    "Newport Landing":              "Huntington Flats",
    "Davey's Locker":               "Huntington Flats",
    "Dana Wharf Sportfishing":      "Dana Point",
}

DDL = """CREATE TABLE IF NOT EXISTS ocla_conditions (
    date            TEXT NOT NULL,
    location        TEXT NOT NULL,
    lat             REAL NOT NULL,
    lon             REAL NOT NULL,
    sst_celsius     REAL,
    sst_fahrenheit  REAL,
    wind_speed_kn   REAL,
    wind_dir_deg    REAL,
    pressure        REAL,
    PRIMARY KEY (date, location)
)"""

_UPSERT = """INSERT INTO ocla_conditions
    (date, location, lat, lon, sst_celsius, sst_fahrenheit, wind_speed_kn, wind_dir_deg, pressure)
    VALUES (?,?,?,?,?,?,?,?,?)
    ON CONFLICT(date, location) DO UPDATE SET
      sst_celsius    = COALESCE(excluded.sst_celsius, sst_celsius),
      sst_fahrenheit = COALESCE(excluded.sst_fahrenheit, sst_fahrenheit),
      wind_speed_kn  = COALESCE(excluded.wind_speed_kn, wind_speed_kn),
      wind_dir_deg   = COALESCE(excluded.wind_dir_deg, wind_dir_deg),
      pressure       = COALESCE(excluded.pressure, pressure)"""


def _chunks(start: date, end: date, days: int):
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=days - 1), end)
        yield cur, nxt
        cur = nxt + timedelta(days=1)


def fill_ocla_conditions(conn: sqlite3.Connection, start: date, end: date | None = None,
                         sst_chunk_days: int = 92, wind_chunk_days: int = 366) -> dict[str, int]:
    """Fetch SST + wind for every point over [start, end] and upsert.

    Existing values are never replaced by a missing one, so a failed fetch
    can't erase stored data. Only chunks still missing SST (or wind) are
    requested; MUR is asked for ~3 months at a time because year-long point
    requests time out. Returns {point: rows written}.
    """
    conn.execute(DDL)
    end = min(end or date.today(), date.today() - timedelta(days=1))
    out: dict[str, int] = {}
    for name, (lat, lon) in POINTS.items():
        have = {r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT date, sst_celsius, wind_speed_kn FROM ocla_conditions"
            " WHERE location=? AND date BETWEEN ? AND ?",
            (name, start.isoformat(), end.isoformat()))}
        n = 0

        def _days(a: date, b: date) -> list[str]:
            return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]

        for a, b in _chunks(start, end, wind_chunk_days):
            if all(have.get(d, (None, None))[1] is not None for d in _days(a, b)):
                continue
            wind = _fetch_openmeteo_wind(a, b, lat=lat, lon=lon)
            rows = [(d, name, lat, lon, None, None, w.get("wind_speed"),
                     w.get("wind_direction"), w.get("pressure"))
                    for d, w in wind.items() if w and w.get("wind_speed") is not None]
            if rows:
                conn.executemany(_UPSERT, rows)
                conn.commit()
                n += len(rows)

        for a, b in _chunks(start, end, sst_chunk_days):
            if all(have.get(d, (None, None))[0] is not None for d in _days(a, b)):
                continue
            try:
                sst = _fetch_mur(lat, lon, a, b, timeout=90.0)
            except Exception as e:  # noqa: BLE001 — one bad chunk shouldn't stop the rest
                log.warning("OC/LA SST %s %s..%s failed: %s", name, a, b, e)
                continue
            rows = [(d.isoformat(), name, lat, lon, round(c, 2), _c_to_f(c), None, None, None)
                    for d, c in sst if c is not None]
            if rows:
                conn.executemany(_UPSERT, rows)
                conn.commit()
                n += len(rows)
        out[name] = n
    return out


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=date.fromisoformat, default=date.today() - timedelta(days=30))
    ap.add_argument("--end", type=date.fromisoformat, default=None)
    ap.add_argument("--db", type=Path, default=Path(__file__).resolve().parents[1] / "tracker.db")
    a = ap.parse_args(argv)
    conn = sqlite3.connect(a.db)
    print(fill_ocla_conditions(conn, a.start, a.end))
    return 0


if __name__ == "__main__":
    sys.exit(main())
