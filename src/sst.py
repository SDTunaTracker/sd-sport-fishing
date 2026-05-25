"""Fetch Sea Surface Temperature for SD fishing grounds.

Source priority per location:
  1. NDBC buoy 46232 (Nearshore only) — real-time, hourly updates.
  2. UKMO OSTIA SST — 0.05° L4 analyzed, ~1-2 day lag.
  3. JPL MUR SST v4.1 — 0.01° L4 analyzed, 3-6 day lag (fallback).

ERDDAP endpoints: https://coastwatch.pfeg.noaa.gov/erddap/griddap/
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# ── ERDDAP endpoints ──────────────────────────────────────────────────────────
MUR_BASE   = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.json"
OSTIA_BASE = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplOSTIASSTv20.json"

# NOAA NDBC realtime2 feed — Point Loma South buoy (nearshore SD).
NDBC_URL = "https://www.ndbc.noaa.gov/data/realtime2/46232.txt"
NDBC_WTMP_COL = 14   # WTMP is column index 14 in realtime2 plain-text
NDBC_MISSING  = "MM"

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

# OSTIA: typically available within 1-2 days; look back up to 7 days.
_OSTIA_SAFE_LAG  = 2
_OSTIA_LOOKBACK  = 7
# MUR SST: 3-6 day lag; reduced from 5 to 3 to grab data sooner when available.
_MUR_SAFE_LAG    = 3
_MUR_LOOKBACK    = 10


def _c_to_f(c: float) -> float:
    return round(c * 9 / 5 + 32, 2)


def _baseline_f(location: str, month: int) -> float:
    return _CLIM_F.get(location, _CLIM_F["Nearshore"])[month]


# ── ERDDAP fetch helpers ──────────────────────────────────────────────────────

def _erddap_url(base: str, time_suffix: str, lat: float, lon: float,
                start: date, end: date) -> str:
    t0 = f"{start.isoformat()}{time_suffix}"
    t1 = f"{end.isoformat()}{time_suffix}"
    return (
        f"{base}?analysed_sst"
        f"[({t0}):1:({t1})]"
        f"[({lat}):1:({lat})]"
        f"[({lon}):1:({lon})]"
    )


def _fetch_erddap(
    base: str, time_suffix: str,
    lat: float, lon: float,
    start: date, end: date,
    timeout: float = 45.0,
    label: str = "ERDDAP",
) -> list[tuple[date, float]]:
    """Fetch analysed_sst from any ERDDAP griddap endpoint.

    Returns [(date, sst_celsius)] for non-null rows; [] on any error.
    """
    url = _erddap_url(base, time_suffix, lat, lon, start, end)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        if r.status_code == 404:
            log.debug("%s 404 (beyond coverage?): %s–%s at (%.2f, %.2f)",
                      label, start, end, lat, lon)
            return []
        if r.status_code != 200:
            log.warning("%s HTTP %s for (%.2f, %.2f): %s…",
                        label, r.status_code, lat, lon, r.text[:120])
            return []
        tbl = r.json().get("table", {})
        col_names = tbl.get("columnNames", [])
        try:
            t_idx   = col_names.index("time")
            sst_idx = col_names.index("analysed_sst")
        except ValueError:
            log.warning("%s unexpected columns: %s", label, col_names)
            return []
        out: list[tuple[date, float]] = []
        for row in tbl.get("rows", []):
            if row[sst_idx] is None:
                continue
            sst_c = float(row[sst_idx])
            if sst_c > 200:      # Kelvin guard
                sst_c -= 273.15
            d = date.fromisoformat(row[t_idx][:10])
            out.append((d, sst_c))
        return out
    except Exception as e:
        log.warning("%s fetch error (%.2f, %.2f) %s–%s: %s",
                    label, lat, lon, start, end, e)
        return []


# Convenience wrappers with dataset-specific time suffixes.
def _fetch_mur(lat: float, lon: float, start: date, end: date,
               timeout: float = 45.0) -> list[tuple[date, float]]:
    return _fetch_erddap(MUR_BASE, "T09:00:00Z", lat, lon, start, end,
                         timeout=timeout, label="MUR")


def _fetch_ostia(lat: float, lon: float, start: date, end: date,
                 timeout: float = 30.0) -> list[tuple[date, float]]:
    return _fetch_erddap(OSTIA_BASE, "T12:00:00Z", lat, lon, start, end,
                         timeout=timeout, label="OSTIA")


# ── NDBC buoy (nearshore only) ────────────────────────────────────────────────

def _fetch_ndbc_nearshore(timeout: float = 15.0) -> tuple[date, float] | None:
    """Return (today, sst_celsius) from NDBC buoy 46232 if WTMP is current.

    Returns None if fetch fails or the most recent observation is > 3 hours old.
    """
    try:
        r = requests.get(NDBC_URL, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        log.debug("NDBC fetch failed: %s", e)
        return None

    now_utc = datetime.now(tz=timezone.utc)
    for line in r.text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) <= NDBC_WTMP_COL:
            continue
        wtmp = parts[NDBC_WTMP_COL]
        if wtmp == NDBC_MISSING:
            continue
        try:
            sst_c = float(wtmp)
        except ValueError:
            continue
        # Parse observation time (cols 0-4: YY MM DD hh mm UTC).
        try:
            yr, mo, dy, hr, mi = (int(x) for x in parts[:5])
            obs_dt = datetime(yr, mo, dy, hr, mi, tzinfo=timezone.utc)
            age_h  = (now_utc - obs_dt).total_seconds() / 3600
            if age_h > 3:
                log.debug("NDBC obs is %.1f h old — skipping as nearshore SST", age_h)
                return None
            return obs_dt.date(), sst_c
        except Exception:
            return None
    return None


# ── Anomaly ───────────────────────────────────────────────────────────────────

def _compute_anomaly(conn, location: str, sst_date: date, sst_f: float) -> float:
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


# ── Per-location SST fetch (NDBC → OSTIA → MUR) ───────────────────────────────

def _fetch_location(
    name: str, lat: float, lon: float,
    target_date: date, conn=None,
) -> dict | None:
    """Fetch the freshest available SST for one location, trying sources in order."""

    # 1. NDBC buoy (nearshore only, real-time)
    if name == "Nearshore":
        result = _fetch_ndbc_nearshore()
        if result is not None:
            data_date, sst_c = result
            sst_f = _c_to_f(sst_c)
            log.info("SST %s %s (NDBC buoy): %.1f°F", data_date, name, sst_f)
            return {
                "date": data_date.isoformat(),
                "location": name,
                "lat": lat, "lon": lon,
                "sst_celsius":   round(sst_c, 2),
                "sst_fahrenheit": sst_f,
                "anomaly": _compute_anomaly(conn, name, data_date, sst_f),
            }

    # 2. OSTIA (~1-2 day lag)
    ostia_end   = min(target_date, date.today() - timedelta(days=_OSTIA_SAFE_LAG))
    ostia_start = ostia_end - timedelta(days=_OSTIA_LOOKBACK)
    rows = _fetch_ostia(lat, lon, ostia_start, ostia_end)
    if rows:
        rows.sort(key=lambda x: x[0], reverse=True)
        data_date, sst_c = rows[0]
        sst_f = _c_to_f(sst_c)
        log.info("SST %s %s (OSTIA): %.1f°F", data_date, name, sst_f)
        return {
            "date": data_date.isoformat(),
            "location": name,
            "lat": lat, "lon": lon,
            "sst_celsius":   round(sst_c, 2),
            "sst_fahrenheit": sst_f,
            "anomaly": _compute_anomaly(conn, name, data_date, sst_f),
        }

    # 3. MUR SST (3-6 day lag, most reliable fallback)
    mur_end   = min(target_date, date.today() - timedelta(days=_MUR_SAFE_LAG))
    mur_start = mur_end - timedelta(days=_MUR_LOOKBACK)
    rows = _fetch_mur(lat, lon, mur_start, mur_end)
    if rows:
        rows.sort(key=lambda x: x[0], reverse=True)
        data_date, sst_c = rows[0]
        sst_f = _c_to_f(sst_c)
        log.info("SST %s %s (MUR fallback): %.1f°F", data_date, name, sst_f)
        return {
            "date": data_date.isoformat(),
            "location": name,
            "lat": lat, "lon": lon,
            "sst_celsius":   round(sst_c, 2),
            "sst_fahrenheit": sst_f,
            "anomaly": _compute_anomaly(conn, name, data_date, sst_f),
        }

    log.warning("No SST data from any source for %s around %s", name, target_date)
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_daily_sst(target_date: date, conn=None) -> list[dict]:
    """Fetch the freshest SST for each location, trying NDBC → OSTIA → MUR."""
    results: list[dict] = []
    for name, (lat, lon) in LOCATIONS.items():
        record = _fetch_location(name, lat, lon, target_date, conn)
        if record:
            results.append(record)
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

    Uses MUR SST for the full history (OSTIA has the same depth but MUR is more
    established for backfills). Range request per location is efficient.
    """
    from . import db as dbmod

    end   = date.today() - timedelta(days=_MUR_SAFE_LAG)
    start = end - timedelta(days=days - 1)
    print(f"SST backfill: {start} to {end} for {len(LOCATIONS)} locations (MUR SST)")

    with dbmod.connect(db_path) as conn:
        total = 0
        for name, (lat, lon) in LOCATIONS.items():
            rows = _fetch_mur(lat, lon, start, end, timeout=60.0)
            if not rows:
                print(f"  {name}: no data")
                continue
            records = []
            for d, sst_c in rows:
                sst_f = _c_to_f(sst_c)
                records.append({
                    "date": d.isoformat(),
                    "location": name,
                    "lat": lat, "lon": lon,
                    "sst_celsius":    round(sst_c, 2),
                    "sst_fahrenheit": sst_f,
                    "anomaly": _compute_anomaly(conn, name, d, sst_f),
                })
            insert_sst(conn, records)
            total += len(records)
            d_min = min(r["date"] for r in records)
            d_max = max(r["date"] for r in records)
            print(f"  {name}: {len(records)} days ({d_min} to {d_max})")
        print(f"\nSST backfill complete: {total} records stored.")
