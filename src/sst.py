"""Fetch Sea Surface Temperature from NOAA ERDDAP (MUR SST) for SD fishing grounds.

Data source: JPL MUR SST v4.1 — 0.01° resolution, daily at 09:00 UTC.
Endpoint: https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41

Typical data lag is 3–6 days. Range fetches degrade gracefully if the
requested end date is beyond the dataset's current coverage.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import requests

log = logging.getLogger(__name__)

ERDDAP_BASE = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.json"

# Key SD offshore fishing locations. Nearshore pushed slightly west (-117.3
# instead of -117.2) so the coordinate clears the coastal land mask in MUR SST.
LOCATIONS: dict[str, tuple[float, float]] = {
    "Nearshore":    (32.7, -117.3),
    "9-Mile Bank":  (32.6, -117.4),
    "60-Mile Bank": (32.0, -118.5),
    "Cortez Bank":  (31.5, -119.0),
}

# Monthly SST climatology (°F) per location — 30-year baseline used for the
# anomaly calculation when the DB history is < 30 days deep.
# Values reflect long-term NOAA/SIO records for San Diego offshore waters.
_CLIM_F: dict[str, dict[int, float]] = {
    "Nearshore": {
        1: 59.0, 2: 58.0, 3: 58.5, 4: 60.5, 5: 63.0, 6: 66.5,
        7: 70.5, 8: 72.5, 9: 73.0, 10: 71.5, 11: 67.0, 12: 62.5,
    },
    "9-Mile Bank": {
        1: 58.5, 2: 57.5, 3: 58.0, 4: 60.0, 5: 62.5, 6: 66.0,
        7: 70.0, 8: 72.0, 9: 72.5, 10: 71.0, 11: 66.5, 12: 62.0,
    },
    "60-Mile Bank": {
        1: 58.0, 2: 57.0, 3: 57.5, 4: 59.5, 5: 62.0, 6: 64.5,
        7: 69.0, 8: 71.0, 9: 71.5, 10: 70.0, 11: 65.5, 12: 61.0,
    },
    "Cortez Bank": {
        1: 58.5, 2: 57.5, 3: 58.0, 4: 59.5, 5: 62.0, 6: 64.5,
        7: 69.0, 8: 71.0, 9: 71.5, 10: 70.0, 11: 65.5, 12: 61.0,
    },
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

# How many days to look back when no data exists for recent dates.
_MAX_LAG_DAYS = 10
# Safe end-date offset: stay this many days behind today to avoid ERDDAP 404
# when the requested date is beyond the dataset's current coverage.
_SAFE_LAG = 5


def _c_to_f(c: float) -> float:
    return round(c * 9 / 5 + 32, 2)


def _baseline_f(location: str, month: int) -> float:
    return _CLIM_F.get(location, _CLIM_F["Nearshore"])[month]


def _erddap_url(lat: float, lon: float, start: date, end: date) -> str:
    t0 = f"{start.isoformat()}T09:00:00Z"
    t1 = f"{end.isoformat()}T09:00:00Z"
    return (
        f"{ERDDAP_BASE}?analysed_sst"
        f"[({t0}):1:({t1})]"
        f"[({lat}):1:({lat})]"
        f"[({lon}):1:({lon})]"
    )


def _fetch_range(
    lat: float, lon: float, start: date, end: date, timeout: float = 45.0
) -> list[tuple[date, float]]:
    """Fetch SST (°C) for one lat/lon over a date range via ERDDAP.

    Returns [(date, sst_celsius)] for rows with non-null values.
    Returns [] on HTTP error or parse failure — never raises.
    """
    url = _erddap_url(lat, lon, start, end)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        if r.status_code == 404:
            log.debug("ERDDAP 404 (beyond coverage?): %s to %s at (%.2f, %.2f)", start, end, lat, lon)
            return []
        if r.status_code != 200:
            log.warning("ERDDAP HTTP %s for (%.2f, %.2f): %s...", r.status_code, lat, lon, r.text[:120])
            return []
        tbl = r.json().get("table", {})
        col_names = tbl.get("columnNames", [])
        try:
            t_idx = col_names.index("time")
            sst_idx = col_names.index("analysed_sst")
        except ValueError:
            log.warning("Unexpected ERDDAP columns: %s", col_names)
            return []
        out: list[tuple[date, float]] = []
        for row in tbl.get("rows", []):
            if row[sst_idx] is None:
                continue
            sst_c = float(row[sst_idx])
            if sst_c > 200:      # Kelvin — should not happen with jplMURSST41
                sst_c -= 273.15
            d = date.fromisoformat(row[t_idx][:10])
            out.append((d, sst_c))
        return out
    except Exception as e:
        log.warning("ERDDAP fetch error (%.2f, %.2f) %s–%s: %s", lat, lon, start, end, e)
        return []


def _compute_anomaly(conn, location: str, sst_date: date, sst_f: float) -> float:
    """SST departure from seasonal norm.

    Prefers a DB-derived average when we have ≥ 30 same-month observations;
    otherwise falls back to the hardcoded monthly climatology.
    """
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT AVG(sst_fahrenheit) AS avg_f, COUNT(*) AS n"
                " FROM ocean_temps"
                " WHERE location = ? AND strftime('%m', date) = ?",
                (location, f"{sst_date.month:02d}"),
            ).fetchone()
            if row and row["n"] and row["n"] >= 30:
                return round(sst_f - row["avg_f"], 2)
        except Exception:
            pass
    return round(sst_f - _baseline_f(location, sst_date.month), 2)


def fetch_daily_sst(target_date: date, conn=None) -> list[dict]:
    """Fetch the most recent available SST for each location near target_date.

    Because MUR SST has a 3–6 day lag, we request a window ending at
    min(target_date, today - _SAFE_LAG) and take the latest non-null row.
    Returns a list of dicts ready for insert_sst().
    """
    safe_end = min(target_date, date.today() - timedelta(days=_SAFE_LAG))
    safe_start = safe_end - timedelta(days=_MAX_LAG_DAYS)
    results: list[dict] = []
    for name, (lat, lon) in LOCATIONS.items():
        rows = _fetch_range(lat, lon, safe_start, safe_end)
        if not rows:
            log.warning("No SST data for %s around %s", name, target_date)
            continue
        rows.sort(key=lambda x: x[0], reverse=True)
        data_date, sst_c = rows[0]
        sst_f = _c_to_f(sst_c)
        anomaly = _compute_anomaly(conn, name, data_date, sst_f)
        results.append({
            "date": data_date.isoformat(),
            "location": name,
            "lat": lat,
            "lon": lon,
            "sst_celsius": round(sst_c, 2),
            "sst_fahrenheit": sst_f,
            "anomaly": anomaly,
        })
        log.info("SST %s %s: %.1f°F (anomaly %+.1f°)", data_date, name, sst_f, anomaly)
    return results


def insert_sst(conn, records: list[dict]) -> int:
    """Upsert SST records (INSERT OR REPLACE on PRIMARY KEY date+location)."""
    if not records:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO ocean_temps"
        " (date, location, lat, lon, sst_celsius, sst_fahrenheit, anomaly)"
        " VALUES (:date, :location, :lat, :lon, :sst_celsius, :sst_fahrenheit, :anomaly)",
        records,
    )
    return len(records)


def backfill_sst(db_path: Path, days: int = 90) -> None:
    """Fetch and store SST for the past `days` days for all locations.

    Uses a single range request per location (efficient). Stops at today minus
    _SAFE_LAG to avoid requesting dates beyond the dataset's coverage.
    """
    from . import db as dbmod

    end = date.today() - timedelta(days=_SAFE_LAG)
    start = end - timedelta(days=days - 1)
    print(f"SST backfill: {start} to {end} for {len(LOCATIONS)} locations")

    with dbmod.connect(db_path) as conn:
        total = 0
        for name, (lat, lon) in LOCATIONS.items():
            rows = _fetch_range(lat, lon, start, end, timeout=60.0)
            if not rows:
                print(f"  {name}: no data")
                continue
            records = []
            for d, sst_c in rows:
                sst_f = _c_to_f(sst_c)
                records.append({
                    "date": d.isoformat(),
                    "location": name,
                    "lat": lat,
                    "lon": lon,
                    "sst_celsius": round(sst_c, 2),
                    "sst_fahrenheit": sst_f,
                    "anomaly": _compute_anomaly(conn, name, d, sst_f),
                })
            insert_sst(conn, records)
            total += len(records)
            d_min = min(r["date"] for r in records)
            d_max = max(r["date"] for r in records)
            print(f"  {name}: {len(records)} days ({d_min} to {d_max})")
        print(f"\nSST backfill complete: {total} records stored.")
