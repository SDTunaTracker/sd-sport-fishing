"""Fetch HYCOM ocean current velocities for SD offshore fishing grounds.

Sources (all via PFEG ERDDAP griddap, no API key required):
  2014-2016: nrlHycomGLBu008e911D_LonPM180
  2016-2018: nrlHycomGLBu008e912D_LonPM180

Coverage note: PFEG ERDDAP HYCOM ends ~Nov 2018. Historical backtest uses
2014-2018 data only. Live forecast does not include currents.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

ERDDAP_BASE = "https://coastwatch.pfeg.noaa.gov/erddap/griddap"

# HYCOM datasets by coverage period — LonPM180 variants accept -180..+180 longitudes
_DATASETS: list[tuple[str, date, date]] = [
    ("nrlHycomGLBu008e911D_LonPM180", date(2014, 1, 1),  date(2016, 4, 30)),
    ("nrlHycomGLBu008e912D_LonPM180", date(2016, 4, 18), date(2018, 11, 30)),
]

LOCATIONS: dict[str, tuple[float, float]] = {
    "60-Mile Bank": (32.0, -118.5),
    "Cortez Bank":  (31.5, -119.0),
    "9-Mile Bank":  (32.6, -117.4),
}

_CHUNK_DAYS = 60
_TIMEOUT    = 60.0

# Favorable: southward current component (water_v < threshold) signals
# California Current weakening → warmer offshore water → better for tuna.
_FAVORABLE_V_THRESHOLD = -0.10  # m/s

# Eddy flag: current speed >= 0.4 m/s (~0.8 kt) is anomalously strong here.
_EDDY_SPEED_MS = 0.40

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")


def _ms_to_knots(ms: float) -> float:
    return round(ms * 1.94384, 3)


def _current_direction(u: float, v: float) -> float:
    """Direction the current flows TOWARD, degrees clockwise from North."""
    deg = math.degrees(math.atan2(u, v))
    return round((deg + 360) % 360, 1)


def _fetch_hycom(
    dataset: str, lat: float, lon: float,
    start: date, end: date,
) -> list[tuple[date, float, float]]:
    """Return [(date, water_u_ms, water_v_ms)] daily averages from HYCOM ERDDAP.

    Requests [start, end] at noon UTC; groups multiple time-steps per day.
    Returns [] on any error or 404.
    """
    t0 = f"{start.isoformat()}T12:00:00Z"
    t1 = f"{end.isoformat()}T12:00:00Z"
    url = (
        f"{ERDDAP_BASE}/{dataset}.json"
        f"?water_u[({t0}):1:({t1})][(0.0):1:(0.0)][({lat}):1:({lat})][({lon}):1:({lon})]"
        f",water_v[({t0}):1:({t1})][(0.0):1:(0.0)][({lat}):1:({lat})][({lon}):1:({lon})]"
    )
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=_TIMEOUT)
        if r.status_code == 404:
            log.debug("HYCOM 404 (beyond coverage): %s %s–%s", dataset, start, end)
            return []
        if r.status_code != 200:
            log.warning("HYCOM HTTP %s: %s…", r.status_code, r.text[:120])
            return []
        tbl = r.json().get("table", {})
        cols = tbl.get("columnNames", [])
        t_i = cols.index("time")
        u_i = cols.index("water_u")
        v_i = cols.index("water_v")

        by_date: dict[str, list[tuple[float, float]]] = {}
        for row in tbl.get("rows", []):
            if row[u_i] is None or row[v_i] is None:
                continue
            d_str = row[t_i][:10]
            by_date.setdefault(d_str, []).append((float(row[u_i]), float(row[v_i])))

        out: list[tuple[date, float, float]] = []
        for d_str, vals in sorted(by_date.items()):
            avg_u = sum(u for u, _ in vals) / len(vals)
            avg_v = sum(v for _, v in vals) / len(vals)
            out.append((date.fromisoformat(d_str), avg_u, avg_v))
        return out
    except Exception as e:
        log.warning("HYCOM fetch error %s %s–%s: %s", dataset, start, end, e)
        return []


def _records_for_location(
    name: str, lat: float, lon: float,
    start: date, end: date,
) -> list[dict]:
    """Fetch and convert HYCOM current records for one location over a date range."""
    now = datetime.now(timezone.utc).isoformat()
    records: list[dict] = []

    for ds_id, ds_start, ds_end in _DATASETS:
        seg_start = max(start, ds_start)
        seg_end   = min(end, ds_end)
        if seg_start > seg_end:
            continue
        d = seg_start
        while d <= seg_end:
            chunk_end = min(d + timedelta(days=_CHUNK_DAYS - 1), seg_end)
            rows = _fetch_hycom(ds_id, lat, lon, d, chunk_end)
            for row_d, u, v in rows:
                speed_ms = math.sqrt(u**2 + v**2)
                records.append({
                    "date":                  row_d.isoformat(),
                    "location":              name,
                    "lat":                   lat,
                    "lon":                   lon,
                    "water_u_ms":            round(u, 4),
                    "water_v_ms":            round(v, 4),
                    "current_speed_ms":      round(speed_ms, 4),
                    "current_speed_knots":   _ms_to_knots(speed_ms),
                    "current_direction_deg": _current_direction(u, v),
                    "current_is_favorable":  1 if v < _FAVORABLE_V_THRESHOLD else 0,
                    "eddy_detected":         1 if speed_ms >= _EDDY_SPEED_MS else 0,
                    "source_dataset":        ds_id,
                    "fetched_at":            now,
                })
            d = chunk_end + timedelta(days=1)
    return records


def insert_currents(conn, records: list[dict]) -> int:
    if not records:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO ocean_currents"
        " (date, location, lat, lon, water_u_ms, water_v_ms,"
        "  current_speed_ms, current_speed_knots, current_direction_deg,"
        "  current_is_favorable, eddy_detected, source_dataset, fetched_at)"
        " VALUES (:date, :location, :lat, :lon, :water_u_ms, :water_v_ms,"
        "  :current_speed_ms, :current_speed_knots, :current_direction_deg,"
        "  :current_is_favorable, :eddy_detected, :source_dataset, :fetched_at)",
        records,
    )
    return len(records)


def backfill_currents(db_path: Path) -> None:
    """Fetch HYCOM currents for the full available coverage window (2014-2018)."""
    from . import db as dbmod

    overall_start = date(2014, 1, 1)
    overall_end   = date(2018, 11, 30)
    print(f"Currents backfill: {overall_start} to {overall_end} "
          f"({len(LOCATIONS)} locations)")

    with dbmod.connect(db_path) as conn:
        total = 0
        for name, (lat, lon) in LOCATIONS.items():
            existing = {r[0] for r in conn.execute(
                "SELECT date FROM ocean_currents WHERE location=? AND date BETWEEN ? AND ?",
                (name, overall_start.isoformat(), overall_end.isoformat()),
            ).fetchall()}
            records  = _records_for_location(name, lat, lon, overall_start, overall_end)
            new_recs = [r for r in records if r["date"] not in existing]
            if new_recs:
                insert_currents(conn, new_recs)
                total += len(new_recs)
            d_min = min(r["date"] for r in records) if records else "—"
            d_max = max(r["date"] for r in records) if records else "—"
            print(f"  {name}: {len(records)} days ({d_min} to {d_max}), "
                  f"{len(new_recs)} new stored")
        print(f"\nCurrents backfill complete: {total} total records stored.")
