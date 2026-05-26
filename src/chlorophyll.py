"""Chlorophyll-a concentration from NASA ERDDAP CoastWatch (AQUA MODIS 8-day).

Data source: NOAA CoastWatch ERDDAP — erdMH1chla8day (MODIS Aqua 8-day composite).
- Resolution: 0.025° (~2.5 km)
- Lag: 1-8 days depending on cloud cover; we use most recent non-null reading.
- Units: mg/m³ (milligrams per cubic metre)
- Coverage: 2003-present

Chlorophyll interpretation for SD offshore fishing:
  High nearshore + low offshore: classic upwelling — bad for offshore tuna
  Low everywhere:                blue water — good for offshore tuna
  Moderate offshore:             productive water with bait present — good

This module:
  1. Fetches daily chl-a for all 4 SD fishing locations.
  2. Stores in chlorophyll_obs table.
  3. Updates the chlorophyll columns in historical_conditions.
  4. Can backfill from 2015 onward.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# ERDDAP endpoint — MODIS Aqua 8-day composite chlorophyll-a
_ERDDAP_BASE = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/erdMH1chla8day.json"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

# Same 4 SD fishing locations as SST
LOCATIONS: dict[str, tuple[float, float]] = {
    "Nearshore":    (32.7, -117.3),
    "9-Mile Bank":  (32.6, -117.4),
    "60-Mile Bank": (32.0, -118.5),
    "Cortez Bank":  (31.5, -119.0),
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chlorophyll_obs (
  obs_date    TEXT,
  location    TEXT,
  lat         REAL,
  lon         REAL,
  chlorophyll_mgl REAL,
  days_old    INTEGER,
  PRIMARY KEY (obs_date, location)
);
"""

_HC_COLS = """
ALTER TABLE historical_conditions ADD COLUMN chlorophyll_nearshore REAL;
ALTER TABLE historical_conditions ADD COLUMN chlorophyll_offshore  REAL;
ALTER TABLE historical_conditions ADD COLUMN chlorophyll_ratio     REAL;
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    for stmt in _HC_COLS.strip().split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists


def _fetch_chl(lat: float, lon: float, start: date, end: date,
               timeout: float = 30.0) -> list[tuple[date, float]]:
    """Fetch chlorophyll-a from ERDDAP for a single location over a date range.

    Returns [(date, chl_mg_m3)] for non-null observations; [] on failure.
    MODIS 8-day composites have one value per 8-day period — we store against
    the composite start date.
    """
    t0 = f"{start.isoformat()}T00:00:00Z"
    t1 = f"{end.isoformat()}T00:00:00Z"
    url = (
        f"{_ERDDAP_BASE}?chlorophyll"
        f"[({t0}):1:({t1})]"
        f"[({lat - 0.01}):1:({lat + 0.01})]"
        f"[({lon - 0.01}):1:({lon + 0.01})]"
    )
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=timeout)
        if r.status_code == 404:
            log.debug("Chlorophyll 404 %s–%s (%.2f, %.2f)", start, end, lat, lon)
            return []
        if r.status_code != 200:
            log.warning("Chlorophyll HTTP %s (%.2f, %.2f)", r.status_code, lat, lon)
            return []
        tbl = r.json().get("table", {})
        col_names = tbl.get("columnNames", [])
        try:
            t_idx   = col_names.index("time")
            chl_idx = col_names.index("chlorophyll")
        except ValueError:
            log.warning("Chlorophyll unexpected columns: %s", col_names)
            return []
        out: list[tuple[date, float]] = []
        for row in tbl.get("rows", []):
            if row[chl_idx] is None:
                continue
            chl = float(row[chl_idx])
            if chl < 0 or chl > 100:
                continue  # sanity filter (typical ocean: 0.01–10 mg/m³)
            d = date.fromisoformat(row[t_idx][:10])
            out.append((d, round(chl, 4)))
        return out
    except Exception as e:
        log.warning("Chlorophyll fetch error (%.2f, %.2f) %s–%s: %s", lat, lon, start, end, e)
        return []


def fetch_chlorophyll(
    db_path: Path,
    target_date: date | None = None,
    lookback_days: int = 16,
) -> int:
    """Fetch current chlorophyll for all locations and update DB.

    Returns number of rows stored.
    """
    from . import db as dbmod

    if target_date is None:
        target_date = date.today()

    start = target_date - timedelta(days=lookback_days)
    today_iso = target_date.isoformat()

    with dbmod.connect(db_path) as conn:
        _ensure_schema(conn)
        total = 0
        chl_by_loc: dict[str, float | None] = {}

        for name, (lat, lon) in LOCATIONS.items():
            rows = _fetch_chl(lat, lon, start, target_date)
            if not rows:
                log.debug("No chlorophyll data for %s", name)
                chl_by_loc[name] = None
                continue

            rows.sort(key=lambda x: x[0], reverse=True)
            obs_date, chl = rows[0]
            days_old = (target_date - obs_date).days

            conn.execute(
                "INSERT OR REPLACE INTO chlorophyll_obs"
                " (obs_date, location, lat, lon, chlorophyll_mgl, days_old)"
                " VALUES (?,?,?,?,?,?)",
                (obs_date.isoformat(), name, lat, lon, chl, days_old),
            )
            chl_by_loc[name] = chl
            total += 1
            log.info("Chlorophyll %s %s: %.3f mg/m³ (%d days old)",
                     name, obs_date, chl, days_old)

        # Update today's historical_conditions row
        chl_near = chl_by_loc.get("Nearshore")
        chl_off  = chl_by_loc.get("60-Mile Bank")
        ratio    = (round(chl_near / max(chl_off, 0.001), 3)
                    if chl_near is not None and chl_off is not None else None)
        conn.execute(
            """UPDATE historical_conditions
               SET chlorophyll_nearshore=?, chlorophyll_offshore=?, chlorophyll_ratio=?
               WHERE date=?""",
            (chl_near, chl_off, ratio, today_iso),
        )
        return total


def backfill_chlorophyll(
    db_path: Path,
    start: date | None = None,
    chunk_days: int = 30,
) -> int:
    """Backfill chlorophyll_obs and historical_conditions from start date to today.

    MODIS goes back to 2003; we default to 2015-01-01 to match the backtest window.
    Fetches in 30-day chunks to avoid ERDDAP timeouts.
    """
    from . import db as dbmod
    from datetime import timedelta

    if start is None:
        start = date(2015, 1, 1)
    end = date.today() - timedelta(days=1)

    with dbmod.connect(db_path) as conn:
        _ensure_schema(conn)
        total = 0
        chunk_start = start
        chunk_num = 0
        total_chunks = ((end - start).days // chunk_days) + 1

        while chunk_start <= end:
            chunk_end = min(chunk_start + timedelta(days=chunk_days - 1), end)
            chunk_num += 1
            print(f"  Chl chunk {chunk_num}/{total_chunks}: {chunk_start} to {chunk_end}")

            chl_by_date: dict[str, dict[str, float]] = {}
            for name, (lat, lon) in LOCATIONS.items():
                rows = _fetch_chl(lat, lon, chunk_start, chunk_end, timeout=60.0)
                for obs_date, chl in rows:
                    d_str = obs_date.isoformat()
                    days_old = (date.today() - obs_date).days
                    conn.execute(
                        "INSERT OR REPLACE INTO chlorophyll_obs"
                        " (obs_date, location, lat, lon, chlorophyll_mgl, days_old)"
                        " VALUES (?,?,?,?,?,?)",
                        (d_str, name, lat, lon, chl, days_old),
                    )
                    chl_by_date.setdefault(d_str, {})[name] = chl
                    total += 1

            # Update historical_conditions for each date in the chunk
            for d_str, locs in chl_by_date.items():
                chl_near = locs.get("Nearshore")
                chl_off  = locs.get("60-Mile Bank")
                ratio    = (round(chl_near / max(chl_off, 0.001), 3)
                            if chl_near is not None and chl_off is not None else None)
                conn.execute(
                    """UPDATE historical_conditions
                       SET chlorophyll_nearshore=?, chlorophyll_offshore=?, chlorophyll_ratio=?
                       WHERE date=?""",
                    (chl_near, chl_off, ratio, d_str),
                )

            chunk_start = chunk_end + timedelta(days=1)

        print(f"  Chlorophyll backfill complete: {total} obs stored")
        return total


def score_chlorophyll(
    chl_nearshore: float | None,
    chl_offshore: float | None,
    segment: str,
) -> float:
    """Score chlorophyll conditions for inshore or offshore fishing (1–10)."""
    if segment == "offshore":
        if chl_nearshore is None or chl_offshore is None:
            return 5.0
        ratio = chl_nearshore / max(chl_offshore, 0.001)
        if ratio > 3.0:  return 3.0   # strong upwelling — bad
        if ratio > 2.0:  return 5.0   # marginal
        if ratio > 1.0:  return 7.0   # neutral/good
        return 9.0                     # blue water — good
    else:  # inshore
        if chl_nearshore is None:
            return 5.0
        if chl_nearshore > 2.0:  return 8.0  # productive — good bait
        if chl_nearshore > 1.0:  return 6.0  # moderate
        return 4.0                             # low — less bait


if __name__ == "__main__":
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    DB_PATH = ROOT / "tracker.db"
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    print("Running chlorophyll backfill from 2015-01-01...")
    n = backfill_chlorophyll(DB_PATH)
    print(f"Done — {n} records stored.")
    sys.exit(0)
