"""Backtesting framework for the fishing forecast model.

Data sources (all free, no API key required):
  SST        – NOAA ERDDAP jplMURSST41 (already in ocean_temps; extended here)
  Wind/Pres  – Open-Meteo ERA5 reanalysis (archive-api.open-meteo.com)
  Wave/Swell – NDBC buoy 46047 Tanner Bank yearly stdmet files
  Moon       – computed locally from moon_info() for every date

Usage:
    python -m src.backtest                        # last 90 days
    python -m src.backtest --start 2024-01-01     # longer range (extends SST)
    python -m src.backtest --optimize             # tune + save weights
    python -m src.backtest --output report.json   # write report file
"""
from __future__ import annotations

import gzip
import json
import logging
import math
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import requests

from . import db as dbmod
from .analytics import (
    _BLUEFIN_BREAKS, _OVERALL_BREAKS, _YELLOWFIN_BREAKS,
    _anomaly_boost, _score,
)
from .moon import moon_info
from .sst import (
    LOCATIONS as SST_LOCATIONS,
    _c_to_f, _compute_anomaly, _fetch_mur as _fetch_range,
    insert_sst,
)

log = logging.getLogger(__name__)

ROOT     = Path(__file__).resolve().parents[1]
DB_PATH  = ROOT / "tracker.db"
WEIGHTS_PATH = ROOT / "backtest_weights.json"
SEGMENT_WEIGHTS_DIR = ROOT / "segment_weights"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

# ─── Schema ──────────────────────────────────────────────────────────────────

BACKTEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_conditions (
    date             TEXT PRIMARY KEY,
    sst_nearshore    REAL,
    sst_9mile        REAL,
    sst_offshore     REAL,
    sst_cortez       REAL,
    sst_anomaly      REAL,
    wind_speed       REAL,
    wind_direction   REAL,
    swell_height     REAL,
    swell_period     REAL,
    pressure         REAL,
    pressure_trend   REAL,
    moon_illum       REAL,
    moon_phase_name  TEXT
);

CREATE TABLE IF NOT EXISTS backtest_results (
    run_date          TEXT NOT NULL,
    model_version     TEXT NOT NULL DEFAULT '1.0',
    date_range_start  TEXT NOT NULL,
    date_range_end    TEXT NOT NULL,
    total_days        INTEGER NOT NULL,
    mae               REAL,
    rmse              REAL,
    direction_accuracy REAL,
    by_month          TEXT,
    by_species        TEXT,
    weights           TEXT,
    PRIMARY KEY (run_date, model_version)
);
"""


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(BACKTEST_SCHEMA)


# ─── Utilities ───────────────────────────────────────────────────────────────

def _date_range(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _pearson_r(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num   = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    denom = den_x * den_y
    return round(num / denom, 4) if denom > 0 else 0.0


# ─── External data: Open-Meteo wind/pressure ─────────────────────────────────

def _fetch_openmeteo_wind(
    start: date, end: date,
    lat: float = 32.0, lon: float = -118.5,
) -> dict[str, dict]:
    """Daily wind (knots), dominant direction, and mean sea-level pressure from
    Open-Meteo ERA5 reanalysis. Returns {date_str: {...}} or {} on failure."""
    try:
        r = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude":  lat,
                "longitude": lon,
                "start_date": start.isoformat(),
                "end_date":   end.isoformat(),
                "daily": ("wind_speed_10m_max,wind_direction_10m_dominant,"
                          "pressure_msl_max,pressure_msl_min"),
                "timezone":        "UTC",
                "wind_speed_unit": "kn",
            },
            timeout=30,
        )
        if r.status_code != 200:
            log.warning("Open-Meteo HTTP %s", r.status_code)
            return {}
        daily = r.json().get("daily", {})
        times   = daily.get("time", [])
        winds   = daily.get("wind_speed_10m_max", [])
        dirs    = daily.get("wind_direction_10m_dominant", [])
        p_max   = daily.get("pressure_msl_max", [])
        p_min   = daily.get("pressure_msl_min", [])
        result: dict[str, dict] = {}
        prev_pres = None
        for i, d_str in enumerate(times):
            pm = p_max[i] if i < len(p_max) else None
            pn = p_min[i] if i < len(p_min) else None
            avg_pres = round((pm + pn) / 2, 1) if pm and pn else None
            # Pressure trend = today's mean minus yesterday's (rising → +, falling → -)
            trend = round(avg_pres - prev_pres, 1) if avg_pres and prev_pres else None
            prev_pres = avg_pres
            result[d_str] = {
                "wind_speed":    winds[i] if i < len(winds) else None,
                "wind_direction": dirs[i] if i < len(dirs)  else None,
                "pressure":      avg_pres,
                "pressure_trend": trend,
            }
        return result
    except Exception as e:
        log.warning("Open-Meteo fetch failed: %s", e)
        return {}


# ─── External data: NDBC buoy swell ─────────────────────────────────────────

def _parse_ndbc_text(
    text: str, start: date, end: date
) -> dict[str, dict]:
    """Parse NDBC stdmet text file into daily averaged swell observations."""
    lines = [l for l in text.splitlines() if l and not l.startswith("##")]
    if len(lines) < 3:
        return {}
    header = lines[0].lstrip("#").upper().split()

    def col(*names: str) -> int | None:
        for n in names:
            try:
                return header.index(n)
            except ValueError:
                pass
        return None

    yr_i   = col("YY", "YYYY")
    mo_i   = col("MM")
    dd_i   = col("DD")
    wvht_i = col("WVHT")
    dpd_i  = col("DPD")
    if None in (yr_i, mo_i, dd_i):
        return {}

    daily: dict[str, list] = {}
    for line in lines[2:]:
        parts = line.split()
        try:
            yr = int(parts[yr_i])
            if yr < 100:
                yr = 2000 + yr if yr <= 30 else 1900 + yr
            d = date(yr, int(parts[mo_i]), int(parts[dd_i]))
            if not (start <= d <= end):
                continue
        except (ValueError, IndexError):
            continue

        def safe(idx: int | None, sentinel: float = 99.0) -> float | None:
            if idx is None or idx >= len(parts):
                return None
            try:
                v = float(parts[idx])
                return None if v >= sentinel else v
            except ValueError:
                return None

        daily.setdefault(d.isoformat(), []).append(
            (safe(wvht_i), safe(dpd_i))
        )

    result: dict[str, dict] = {}
    for d_str, obs in daily.items():
        heights = [h for h, _ in obs if h is not None]
        periods = [p for _, p in obs if p is not None]
        result[d_str] = {
            "swell_height": round(sum(heights) / len(heights), 2) if heights else None,
            "swell_period": round(sum(periods) / len(periods), 1) if periods else None,
        }
    return result


def _fetch_ndbc_swell(
    buoy_id: str, start: date, end: date
) -> dict[str, dict]:
    """Fetch daily swell from NDBC buoy yearly archive files.
    Tries the realtime endpoint for the current year if yearly file is missing.
    """
    result: dict[str, dict] = {}
    for year in range(start.year, end.year + 1):
        url = (f"https://www.ndbc.noaa.gov/data/historical/stdmet/"
               f"{buoy_id}h{year}.txt.gz")
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            if r.status_code == 404 and year == date.today().year:
                # Current year not yet archived — try realtime (last 45 days)
                rt = requests.get(
                    f"https://www.ndbc.noaa.gov/data/realtime2/{buoy_id}.txt",
                    headers={"User-Agent": UA}, timeout=20,
                )
                if rt.status_code == 200:
                    result.update(_parse_ndbc_text(rt.text, start, end))
                continue
            if r.status_code != 200:
                log.debug("NDBC HTTP %s buoy=%s year=%s", r.status_code, buoy_id, year)
                continue
            text = gzip.decompress(r.content).decode("latin-1", errors="replace")
            result.update(_parse_ndbc_text(text, start, end))
            log.info("NDBC buoy %s %s: %d days parsed", buoy_id, year,
                     sum(1 for d in _date_range(
                         max(start, date(year, 1, 1)),
                         min(end, date(year, 12, 31))
                     ) if d.isoformat() in result))
        except Exception as e:
            log.debug("NDBC error buoy=%s year=%s: %s", buoy_id, year, e)
    return result


# ─── SST extension ────────────────────────────────────────────────────────────

_SST_CHUNK_DAYS = 90  # max days per ERDDAP request to avoid timeouts


def _extend_sst(conn: sqlite3.Connection, start: date, end: date) -> int:
    """Fetch ocean_temps for any dates in [start, end] not yet in the DB.

    Fetches in _SST_CHUNK_DAYS-day chunks so each ERDDAP request stays fast.
    """
    safe_end = min(end, date.today() - timedelta(days=5))
    if safe_end < start:
        return 0
    existing = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM ocean_temps WHERE date BETWEEN ? AND ?",
            (start.isoformat(), safe_end.isoformat()),
        ).fetchall()
    }
    needed = sorted(
        d.isoformat() for d in _date_range(start, safe_end)
        if d.isoformat() not in existing
    )
    if not needed:
        return 0

    # Build contiguous chunks from the needed dates
    chunks: list[tuple[date, date]] = []
    chunk_start = date.fromisoformat(needed[0])
    prev = chunk_start
    for d_str in needed[1:]:
        d = date.fromisoformat(d_str)
        if (d - prev).days > 1 or (prev - chunk_start).days >= _SST_CHUNK_DAYS:
            chunks.append((chunk_start, prev))
            chunk_start = d
        prev = d
    chunks.append((chunk_start, prev))

    log.info("SST extension: %d gaps => %d chunks", len(needed), len(chunks))
    total = 0
    for chunk_i, (cs, ce) in enumerate(chunks, 1):
        print(f"  SST chunk {chunk_i}/{len(chunks)}: {cs} to {ce}")
        for name, (lat, lon) in SST_LOCATIONS.items():
            rows = _fetch_range(lat, lon, cs, ce, timeout=120.0)
            records = [
                {
                    "date":           d.isoformat(),
                    "location":       name,
                    "lat":            lat,
                    "lon":            lon,
                    "sst_celsius":    round(sst_c, 2),
                    "sst_fahrenheit": _c_to_f(sst_c),
                    "anomaly":        _compute_anomaly(conn, name, d, _c_to_f(sst_c)),
                }
                for d, sst_c in rows
                if d.isoformat() not in existing
            ]
            if records:
                insert_sst(conn, records)
                total += len(records)
                log.info("SST extended %s chunk %s-%s: +%d", name, cs, ce, len(records))
    return total


# ─── Historical conditions table ─────────────────────────────────────────────

def build_historical_conditions(
    conn: sqlite3.Connection,
    start: date, end: date,
    wind_data: dict | None = None,
    swell_data: dict | None = None,
) -> int:
    """Populate historical_conditions by joining ocean_temps + moon + wind + swell.
    Returns number of rows written."""
    _apply_schema(conn)

    # Load SST keyed by date then location (wider window for 7-day avg/trend)
    sst_window_start = (start - timedelta(days=10)).isoformat()
    sst_by_date: dict[str, dict] = {}
    for row in conn.execute(
        """SELECT date, location, sst_fahrenheit, anomaly
           FROM ocean_temps WHERE date BETWEEN ? AND ?""",
        (sst_window_start, end.isoformat()),
    ).fetchall():
        d_str = row["date"]
        sst_by_date.setdefault(d_str, {"anomalies": []})
        sst_by_date[d_str][row["location"]] = row["sst_fahrenheit"]
        if row["anomaly"] is not None:
            sst_by_date[d_str]["anomalies"].append(row["anomaly"])

    # Load chlorophyll keyed by obs_date/location (8-day composites; look back up to 10 days)
    chl_by_date: dict[str, dict[str, float]] = {}
    try:
        for row in conn.execute(
            "SELECT obs_date, location, chlorophyll_mgl FROM chlorophyll_obs "
            "WHERE obs_date BETWEEN ? AND ?",
            (sst_window_start, end.isoformat()),
        ).fetchall():
            chl_by_date.setdefault(row["obs_date"], {})[row["location"]] = row["chlorophyll_mgl"]
    except Exception:
        pass  # table may not exist on first run

    n = 0
    for d in _date_range(start, end):
        d_str = d.isoformat()
        sst   = sst_by_date.get(d_str, {})
        anoms = sst.get("anomalies", [])
        moon  = moon_info(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))
        wd    = (wind_data  or {}).get(d_str, {})
        sw    = (swell_data or {}).get(d_str, {})
        wind_deg = wd.get("wind_direction")
        wind_label, wind_is_offshore, wind_is_upwelling = _classify_wind(wind_deg)

        # SST gradient and warming trend
        sst_offshore  = sst.get("60-Mile Bank")
        sst_nearshore = sst.get("Nearshore")
        sst_gradient  = (round(abs(sst_offshore - sst_nearshore), 2)
                         if sst_offshore is not None and sst_nearshore is not None else None)
        sst_7ago = (d - timedelta(days=7)).isoformat()
        sst_7ago_val  = sst_by_date.get(sst_7ago, {}).get("60-Mile Bank")
        sst_warming   = (round(sst_offshore - sst_7ago_val, 2)
                         if sst_offshore is not None and sst_7ago_val is not None else None)
        window_vals   = [sst_by_date.get((d - timedelta(days=i)).isoformat(), {}).get("60-Mile Bank")
                         for i in range(7)]
        window_vals   = [v for v in window_vals if v is not None]
        sst_7day_avg  = round(sum(window_vals) / len(window_vals), 2) if window_vals else None

        # Chlorophyll: find most recent 8-day composite within 10 days
        chl_near = chl_off = None
        for lookback in range(10):
            d_back = (d - timedelta(days=lookback)).isoformat()
            if d_back in chl_by_date:
                chl_near = chl_by_date[d_back].get("Nearshore")
                chl_off  = chl_by_date[d_back].get("60-Mile Bank")
                if chl_near is not None or chl_off is not None:
                    break
        chl_ratio = (round(chl_near / max(chl_off, 0.001), 3)
                     if chl_near is not None and chl_off is not None else None)

        conn.execute(
            """INSERT OR REPLACE INTO historical_conditions
               (date, sst_nearshore, sst_9mile, sst_offshore, sst_cortez,
                sst_anomaly, wind_speed, wind_direction, swell_height,
                swell_period, pressure, pressure_trend, moon_illum, moon_phase_name,
                wind_direction_deg, wind_direction_label, wind_is_offshore, wind_is_upwelling,
                sst_gradient, sst_warming_trend, sst_7day_avg,
                chlorophyll_nearshore, chlorophyll_offshore, chlorophyll_ratio)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                d_str,
                sst_nearshore,
                sst.get("9-Mile Bank"),
                sst_offshore,
                sst.get("Cortez Bank"),
                round(sum(anoms) / len(anoms), 2) if anoms else None,
                wd.get("wind_speed"),
                wind_deg,
                sw.get("swell_height"),
                sw.get("swell_period"),
                wd.get("pressure"),
                wd.get("pressure_trend"),
                moon.illum,
                moon.phase,
                wind_deg,
                wind_label,
                wind_is_offshore,
                wind_is_upwelling,
                sst_gradient,
                sst_warming,
                sst_7day_avg,
                chl_near,
                chl_off,
                chl_ratio,
            ),
        )
        n += 1
    return n


def _classify_wind(deg: float | None) -> tuple[str | None, int, int]:
    """Classify wind direction for SD fishing: returns (label, is_offshore, is_upwelling)."""
    if deg is None:
        return None, 0, 0
    d = float(deg) % 360
    if d >= 315 or d < 45:
        return "NW (Upwelling)", 0, 1
    if 45 <= d < 135:
        return "E (Offshore)", 1, 0
    if 135 <= d < 225:
        return "S/SE (Baja Push)", 1, 0
    return "W (Neutral)", 0, 0


# ─── Backtest engine ──────────────────────────────────────────────────────────

_HC_NUMERIC_COLS = (
    "sst_nearshore", "sst_9mile", "sst_offshore", "sst_cortez",
    "sst_anomaly", "wind_speed", "wind_direction",
    "swell_height", "swell_period", "pressure", "pressure_trend", "moon_illum",
)

# Extended factor set for the dual segment model
_SEGMENT_HC_FACTORS = _HC_NUMERIC_COLS + (
    "sst_gradient", "sst_warming_trend", "sst_7day_avg",
    "wind_is_offshore", "wind_is_upwelling",
    "chlorophyll_nearshore", "chlorophyll_offshore", "chlorophyll_ratio",
)


def _get_daily_tpa(conn: sqlite3.Connection) -> dict[str, dict]:
    """Catch metrics keyed by *departure* date, trips ≤ 2.5 days.

    Each trip is shifted to its departure date so conditions are matched to
    the start of the trip, not the return.  avg_days records how many days
    of conditions to average when building the conditions vector.
    trophy_per_angler_per_day already normalises for trip length.
    """
    rows = conn.execute(
        """SELECT date(date, '-' || CAST(ROUND(trip_length_days - 1) AS INTEGER) || ' days') AS dep_date,
                  AVG(trophy_per_angler_per_day)              AS avg_tpa,
                  AVG(bluefin   * 1.0 / NULLIF(anglers, 0))  AS bf_pa,
                  AVG(yellowfin * 1.0 / NULLIF(anglers, 0))  AS yf_pa,
                  AVG(yellowtail* 1.0 / NULLIF(anglers, 0))  AS yt_pa,
                  AVG(dorado    * 1.0 / NULLIF(anglers, 0))  AS dor_pa,
                  COUNT(*)                                    AS n_boats,
                  SUM(anglers)                                AS total_anglers,
                  CAST(ROUND(AVG(trip_length_days)) AS INTEGER) AS avg_days
           FROM trips
           WHERE is_half_day = 0 AND anglers >= 5 AND trip_length_days <= 2.5
           GROUP BY dep_date
           HAVING COUNT(*) >= 2
           ORDER BY dep_date"""
    ).fetchall()
    return {r["dep_date"]: dict(r) for r in rows}


def _avg_conditions(hc_by_date: dict, dep_date: date, n_days: int) -> dict | None:
    """Average historical_conditions over n_days starting from dep_date.

    Returns None if no conditions rows are found for any day in the range.
    All numeric columns are averaged; moon_phase_name is taken from day 1.
    """
    rows = [hc_by_date.get((dep_date + timedelta(days=i)).isoformat())
            for i in range(max(n_days, 1))]
    rows = [r for r in rows if r]
    if not rows:
        return None
    result: dict = {}
    for col in _HC_NUMERIC_COLS:
        vals = [r[col] for r in rows if r.get(col) is not None]
        result[col] = round(sum(vals) / len(vals), 4) if vals else None
    result["moon_phase_name"] = rows[0].get("moon_phase_name")
    return result


def _tpa_to_rating(tpa: float, all_values: list[float]) -> float:
    """Percentile-based 1–10 rating: top 10 % of days → ~9-10, median → 5.5."""
    if not all_values:
        return 5.0
    rank = sum(1 for v in all_values if v <= tpa) / len(all_values)
    return round(max(1.0, min(10.0, 1.0 + rank * 9.0)), 1)


def _predict_from_conditions(hc: dict) -> dict:
    """Score from averaged conditions dict — SST + anomaly only.
    Historical factor is omitted to prevent data leakage in backtesting."""
    sst_f = (hc.get("sst_offshore") or hc.get("sst_9mile") or hc.get("sst_nearshore"))
    if sst_f is None:
        return {"overall": None, "bluefin": None, "yellowfin": None}
    boost = _anomaly_boost(hc.get("sst_anomaly"))
    return {
        "overall":   round(min(10.0, max(1.0, _score(sst_f, _OVERALL_BREAKS)   + boost)),       1),
        "bluefin":   round(min(10.0, max(1.0, _score(sst_f, _BLUEFIN_BREAKS)   + boost)),       1),
        "yellowfin": round(min(10.0, max(1.0, _score(sst_f, _YELLOWFIN_BREAKS) + boost * 0.5)), 1),
    }


def backtest_model(
    conn: sqlite3.Connection, start: date, end: date
) -> list[dict]:
    """Run backtest for date range. Returns per-day dicts with predicted vs actual."""
    _apply_schema(conn)
    daily_tpa = _get_daily_tpa(conn)
    if not daily_tpa:
        return []
    all_tpa_vals = [v["avg_tpa"] for v in daily_tpa.values() if v["avg_tpa"] is not None]

    # Fetch a slightly wider window so multi-day trips' return dates are covered.
    hc_start = (start - timedelta(days=3)).isoformat()
    hc_end   = (end   + timedelta(days=3)).isoformat()
    hc_by_date = {
        r["date"]: dict(r)
        for r in conn.execute(
            "SELECT * FROM historical_conditions WHERE date BETWEEN ? AND ?",
            (hc_start, hc_end),
        ).fetchall()
    }

    results = []
    for dep_date_str, actual in daily_tpa.items():
        dep_date = date.fromisoformat(dep_date_str)
        if not (start <= dep_date <= end):
            continue
        n_days = actual.get("avg_days") or 1
        cond = _avg_conditions(hc_by_date, dep_date, n_days)
        if cond is None:
            continue
        predicted = _predict_from_conditions(cond)
        if predicted["overall"] is None:
            continue
        actual_rating = _tpa_to_rating(actual["avg_tpa"], all_tpa_vals)
        error         = abs(predicted["overall"] - actual_rating)
        results.append({
            "date":                dep_date_str,
            "month":               dep_date.month,
            "predicted_overall":   predicted["overall"],
            "predicted_bluefin":   predicted["bluefin"],
            "predicted_yellowfin": predicted["yellowfin"],
            "actual_tpa":          round(actual["avg_tpa"], 4),
            "actual_rating":       actual_rating,
            "bf_pa":               actual.get("bf_pa"),
            "yf_pa":               actual.get("yf_pa"),
            "yt_pa":               actual.get("yt_pa"),
            "n_boats":             actual["n_boats"],
            "error":               round(error, 2),
            "correct_direction":   (predicted["overall"] >= 5.5) == (actual_rating >= 5.5),
            "sst_offshore":        cond.get("sst_offshore"),
            "sst_anomaly":         cond.get("sst_anomaly"),
            "wind_speed":          cond.get("wind_speed"),
            "swell_height":        cond.get("swell_height"),
            "pressure_trend":      cond.get("pressure_trend"),
            "moon_illum":          cond.get("moon_illum"),
        })
    return sorted(results, key=lambda x: x["date"])


# ─── Correlation analysis ─────────────────────────────────────────────────────

def correlate_factors(
    conn: sqlite3.Connection, results: list[dict]
) -> dict[str, dict[str, float | None]]:
    """Pearson r between each condition factor and actual fishing quality.
    Also runs an all-trips moon correlation for better statistical coverage."""
    factors = {
        "sst_offshore":    [r["sst_offshore"]    for r in results],
        "sst_anomaly":     [r["sst_anomaly"]     for r in results],
        "wind_speed":      [r["wind_speed"]      for r in results],
        "swell_height":    [r["swell_height"]    for r in results],
        "pressure_trend":  [r["pressure_trend"]  for r in results],
        "moon_illum":      [r["moon_illum"]      for r in results],
        "month_num":       [float(r["month"])    for r in results],
    }
    targets = {
        "overall":   [r["actual_rating"]    for r in results],
        "bluefin":   [r["bf_pa"] or 0.0     for r in results],
        "yellowfin": [r["yf_pa"] or 0.0     for r in results],
        "yellowtail":[r["yt_pa"] or 0.0     for r in results],
    }
    matrix: dict[str, dict] = {}
    for fname, fvals in factors.items():
        matrix[fname] = {}
        for tname, tvals in targets.items():
            pairs = [(f, t) for f, t in zip(fvals, tvals) if f is not None and t is not None]
            matrix[fname][tname] = _pearson_r(*zip(*pairs)) if len(pairs) >= 10 else None

    # Moon correlation over all departure dates — more statistical power
    all_moon = conn.execute(
        """SELECT AVG(moon_illum)                             AS illum,
                  AVG(trophy_per_angler_per_day)             AS tpa,
                  AVG(bluefin    * 1.0 / NULLIF(anglers,0)) AS bf_pa,
                  AVG(yellowfin  * 1.0 / NULLIF(anglers,0)) AS yf_pa,
                  AVG(yellowtail * 1.0 / NULLIF(anglers,0)) AS yt_pa
           FROM trips WHERE is_half_day=0 AND anglers>=5 AND trip_length_days<=2.5
           GROUP BY date(date, '-' || CAST(ROUND(trip_length_days - 1) AS INTEGER) || ' days')
           HAVING COUNT(*)>=2"""
    ).fetchall()
    if len(all_moon) >= 30:
        illums = [r["illum"] for r in all_moon]
        matrix["moon_illum_all_trips"] = {
            "overall":   _pearson_r(illums, [r["tpa"]   for r in all_moon]),
            "bluefin":   _pearson_r(illums, [r["bf_pa"] for r in all_moon]),
            "yellowfin": _pearson_r(illums, [r["yf_pa"] for r in all_moon]),
            "yellowtail":_pearson_r(illums, [r["yt_pa"] for r in all_moon]),
        }
    return matrix


# ─── Score-break calibration ─────────────────────────────────────────────────

def calibrate_score_breaks(conn: sqlite3.Connection) -> dict | None:
    """Derive empirical SST -> score mappings from actual catch data.

    For each interval in the existing break tables, queries the average
    percentile-ranked fishing quality on days when 60-Mile Bank SST fell in
    that bin.  Falls back to the hardcoded default score when a bin has fewer
    than MIN_N paired days.

    Returns {"overall_breaks": [[upper, score], ...], "bluefin_breaks": [...],
             "yellowfin_breaks": [...]}, with null for the inf upper bound so
    the dict round-trips through JSON cleanly.
    Returns None when < 20 paired SST+trip days exist.
    """
    from .analytics import _OVERALL_BREAKS, _BLUEFIN_BREAKS, _YELLOWFIN_BREAKS

    MIN_N = 5  # minimum observations per bin before we trust empirical data

    def _pool(metric_sql: str) -> list[float]:
        return [r[0] for r in conn.execute(
            f"SELECT {metric_sql} FROM trips"
            " WHERE is_half_day=0 AND anglers>=5 AND trip_length_days<=2.5"
            " GROUP BY date(date, '-' || CAST(ROUND(trip_length_days - 1) AS INTEGER) || ' days')"
            " HAVING COUNT(*)>=2"
        ).fetchall() if r[0] is not None]

    all_tpa = _pool("AVG(trophy_per_angler_per_day)")
    all_bf  = _pool("AVG(bluefin   * 1.0 / NULLIF(anglers,0))")
    all_yf  = _pool("AVG(yellowfin * 1.0 / NULLIF(anglers,0))")
    if len(all_tpa) < 30:
        return None

    # Daily SST + catch metrics joined on departure date, trips <= 2.5 days
    rows = conn.execute(
        """SELECT o.sst_fahrenheit AS sst,
                  AVG(t.trophy_per_angler_per_day)              AS tpa,
                  AVG(t.bluefin   * 1.0 / NULLIF(t.anglers,0)) AS bf_pa,
                  AVG(t.yellowfin * 1.0 / NULLIF(t.anglers,0)) AS yf_pa
           FROM ocean_temps o
           JOIN trips t ON date(t.date, '-' || CAST(ROUND(t.trip_length_days - 1) AS INTEGER) || ' days') = o.date
           WHERE o.location = '60-Mile Bank'
             AND t.is_half_day = 0 AND t.anglers >= 5 AND t.trip_length_days <= 2.5
           GROUP BY o.date
           HAVING COUNT(DISTINCT t.id) >= 2"""
    ).fetchall()
    if len(rows) < 20:
        return None

    obs = [(r["sst"], r["tpa"] or 0.0, r["bf_pa"] or 0.0, r["yf_pa"] or 0.0)
           for r in rows]

    def _empirical_score(
        breaks: list[tuple[float, float]],
        field_idx: int,       # 1=tpa, 2=bf_pa, 3=yf_pa in obs tuple
        pool: list[float],
    ) -> list[list]:
        """Replace score values with data-driven percentile ratings."""
        out = []
        lo = -float("inf")
        for bound, default_score in breaks:
            in_bin = [o[field_idx] for o in obs if lo <= o[0] < bound]
            if len(in_bin) >= MIN_N:
                avg = sum(in_bin) / len(in_bin)
                score = _tpa_to_rating(avg, pool)
            else:
                score = default_score
            # Store null for inf so the result is JSON-serialisable
            out.append([None if bound == float("inf") else bound, round(score, 1)])
            lo = bound
        return out

    result = {
        "overall_breaks":   _empirical_score(_OVERALL_BREAKS,   1, all_tpa),
        "bluefin_breaks":   _empirical_score(_BLUEFIN_BREAKS,   2, all_bf),
        "yellowfin_breaks": _empirical_score(_YELLOWFIN_BREAKS, 3, all_yf),
    }

    # Diagnostic: show bin coverage
    print("\nScore break calibration (60-Mile Bank SST bins):")
    print(f"  {'Bin':12s} {'N':>4}  {'Overall':>8}  {'Bluefin':>8}  {'Yellowfin':>9}")
    lo = -float("inf")
    for (bound, _), ov, bf, yf in zip(
        _OVERALL_BREAKS[:len(result["overall_breaks"])],
        result["overall_breaks"],
        # bluefin/yellowfin may have different boundaries — pad with dashes
        result["bluefin_breaks"]   + [[None, "-"]] * 10,
        result["yellowfin_breaks"] + [[None, "-"]] * 10,
    ):
        n = sum(1 for o in obs if lo <= o[0] < bound)
        b_str = f"{lo:.0f}-{bound:.0f}" if bound != float("inf") else f"{lo:.0f}+"
        flag = "" if n >= MIN_N else " *"
        print(f"  {b_str:12s} {n:>4}  {ov[1]:>8}  "
              f"{bf[1] if isinstance(bf[1], float) else bf[1]:>8}  "
              f"{yf[1] if isinstance(yf[1], float) else yf[1]:>9}{flag}")
        lo = bound
    print("  (* = insufficient data, kept default score)")
    return result


# ─── Weight optimization ──────────────────────────────────────────────────────

def optimize_weights(
    correlations: dict, existing: dict | None = None
) -> dict:
    """Derive weight adjustments from correlation analysis.
    Returns a weight dict to be saved to backtest_weights.json."""
    weights = (existing or {}).copy()
    weights.setdefault("sst_weight",    1.0)
    weights.setdefault("anomaly_weight", 1.0)
    weights.setdefault("moon_weight",    0.0)
    weights.setdefault("wind_weight",    0.0)

    def _adj(r: float | None, center: float = 0.3) -> float:
        if r is None:
            return 1.0
        return round(max(0.4, min(2.0, 1.0 + (abs(r) - center) * 2.0)), 3)

    sst_r  = correlations.get("sst_offshore",  {}).get("overall")
    anom_r = correlations.get("sst_anomaly",   {}).get("overall")
    moon_r = (correlations.get("moon_illum_all_trips", {}).get("overall")
              or correlations.get("moon_illum", {}).get("overall"))
    wind_r = correlations.get("wind_speed",    {}).get("overall")

    if sst_r  is not None: weights["sst_weight"]    = _adj(sst_r,  0.3)
    if anom_r is not None: weights["anomaly_weight"] = _adj(anom_r, 0.2)
    if moon_r is not None: weights["moon_weight"]    = round(min(1.0, abs(moon_r) * 3), 3)
    if wind_r is not None: weights["wind_weight"]    = round(min(1.0, abs(wind_r) * 3), 3)

    return weights


def save_weights(weights: dict, path: Path = WEIGHTS_PATH) -> None:
    path.write_text(json.dumps(weights, indent=2), encoding="utf-8")
    log.info("Weights saved to %s", path)


def load_segment_weights(segment: str, season: str) -> dict:
    """Load weight file for segment+season combination; returns {} if not found."""
    p = SEGMENT_WEIGHTS_DIR / f"weights_{segment}_{season}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_segment_weights(weights: dict, segment: str, season: str) -> None:
    SEGMENT_WEIGHTS_DIR.mkdir(exist_ok=True)
    p = SEGMENT_WEIGHTS_DIR / f"weights_{segment}_{season}.json"
    p.write_text(json.dumps(weights, indent=2), encoding="utf-8")
    log.info("Segment weights saved: %s", p.name)


# ─── Accuracy metrics ─────────────────────────────────────────────────────────

def compute_metrics(results: list[dict]) -> dict:
    if not results:
        return {}
    errors  = [r["error"] for r in results]
    mae     = round(sum(errors) / len(errors), 3)
    rmse    = round(math.sqrt(sum(e ** 2 for e in errors) / len(errors)), 3)
    dir_acc = round(sum(1 for r in results if r["correct_direction"]) / len(results) * 100, 1)

    by_month: dict[str, list] = {}
    for r in results:
        by_month.setdefault(str(r["month"]), []).append(r["error"])
    monthly_mae = {m: round(sum(v) / len(v), 3) for m, v in by_month.items()}

    # SST range breakdown
    def _bucket(sst: float | None) -> str:
        if sst is None: return "no_sst"
        if sst < 60:    return "<60F"
        if sst < 64:    return "60-64F"
        if sst < 68:    return "64-68F"
        if sst < 72:    return "68-72F"
        return "72F+"
    by_sst: dict[str, list] = {}
    for r in results:
        by_sst.setdefault(_bucket(r.get("sst_offshore")), []).append(r["error"])
    sst_mae = {b: round(sum(v) / len(v), 3) for b, v in by_sst.items()}

    return {
        "total_days":        len(results),
        "mae":               mae,
        "rmse":              rmse,
        "direction_accuracy": dir_acc,
        "by_month":          monthly_mae,
        "by_sst_range":      sst_mae,
    }


# ─── Report ───────────────────────────────────────────────────────────────────

def generate_report(
    results: list[dict], metrics: dict,
    correlations: dict, weights: dict,
    start: date, end: date,
    run_secs: float = 0.0,
) -> dict:
    _MONTH_NAMES = {
        "1":"January","2":"February","3":"March","4":"April",
        "5":"May","6":"June","7":"July","8":"August",
        "9":"September","10":"October","11":"November","12":"December",
    }
    by_month_mae = metrics.get("by_month", {})
    sorted_months = sorted(by_month_mae.items(), key=lambda x: x[1])
    best_month  = _MONTH_NAMES.get(sorted_months[0][0])  if sorted_months else None
    worst_month = _MONTH_NAMES.get(sorted_months[-1][0]) if sorted_months else None

    # Top factors by |r|
    top_factors = sorted(
        [{"factor": f, "correlation": v.get("overall")}
         for f, v in correlations.items() if v.get("overall") is not None],
        key=lambda x: abs(x["correlation"]),
        reverse=True,
    )[:6]

    # Sample: best/worst/recent predictions
    by_err = sorted(results, key=lambda r: r["error"])
    sample = {
        "best_predictions":  by_err[:3],
        "worst_predictions": by_err[-3:],
        "recent": [r for r in results
                   if r["date"] >= (date.today() - timedelta(days=14)).isoformat()][-5:],
    }

    return {
        "run_date":         date.today().isoformat(),
        "model_version":    "1.0",
        "date_range_start": start.isoformat(),
        "date_range_end":   end.isoformat(),
        "metrics":          metrics,
        "correlations":     correlations,
        "weights":          weights,
        "top_factors":      top_factors,
        "best_month":       best_month,
        "worst_month":      worst_month,
        "sample_predictions": sample,
        "run_duration_seconds": round(run_secs, 1),
    }


def _print_summary(report: dict) -> None:
    m = report["metrics"]
    print()
    print("=" * 60)
    print("BACKTEST SUMMARY")
    print("=" * 60)
    print(f"Period : {report['date_range_start']} to {report['date_range_end']}")
    print(f"Days   : {m['total_days']}")
    print()
    print("ACCURACY")
    print(f"  MAE               : {m['mae']}  (target <1.5)")
    print(f"  RMSE              : {m['rmse']}")
    print(f"  Direction accuracy: {m['direction_accuracy']}%  (target >65%)")
    print(f"  MAE target met    : {'YES' if m['mae'] < 1.5 else 'NO'}")
    print(f"  Direction met     : {'YES' if m['direction_accuracy'] >= 65 else 'NO'}")
    if report.get("best_month"):
        print(f"\n  Best month  : {report['best_month']}")
    if report.get("worst_month"):
        print(f"  Worst month : {report['worst_month']}")
    print()
    print("MOST PREDICTIVE FACTORS")
    for f in report.get("top_factors", []):
        r = f["correlation"]
        print(f"  {f['factor']:35s}  r = {r:+.3f}")
    print()
    print("WEIGHTS")
    for k, v in report.get("weights", {}).items():
        print(f"  {k}: {v}")
    sst_mae = m.get("by_sst_range", {})
    if sst_mae:
        print()
        print("MAE BY SST RANGE")
        for bucket, mae in sorted(sst_mae.items()):
            print(f"  {bucket:10s}: {mae}")


# ─── Dual segment backtest engine ────────────────────────────────────────────

def get_season(month: int) -> str:
    """Map calendar month to fishing season bucket."""
    if 3 <= month <= 5:  return "early"
    if 6 <= month <= 8:  return "peak"
    if 9 <= month <= 11: return "late"
    return "early"  # Dec–Feb: treat as early (pre-season)


def _get_segment_daily_tpa(conn: sqlite3.Connection, segment: str) -> dict[str, dict]:
    """Top-quartile TPA per date for a given segment from daily_segment_stats."""
    rows = conn.execute(
        """SELECT date, top_quartile_tpa, avg_tpa, trip_count,
                  bluefin_tpa, yellowfin_tpa, yellowtail_tpa, dorado_tpa
           FROM daily_segment_stats
           WHERE segment = ?
           ORDER BY date""",
        (segment,),
    ).fetchall()
    return {r["date"]: dict(r) for r in rows}


def _avg_conditions_extended(hc_by_date: dict, dep_date: date, n_days: int = 1) -> dict | None:
    """Like _avg_conditions but includes all extended dual-model columns."""
    rows = [hc_by_date.get((dep_date + timedelta(days=i)).isoformat())
            for i in range(max(n_days, 1))]
    rows = [r for r in rows if r]
    if not rows:
        return None
    result: dict = {}
    for col in _SEGMENT_HC_FACTORS:
        vals = [r[col] for r in rows if r.get(col) is not None]
        result[col] = round(sum(vals) / len(vals), 4) if vals else None
    result["moon_phase_name"] = rows[0].get("moon_phase_name")
    return result


def backtest_segment(
    conn: sqlite3.Connection,
    segment: str,
    start: date, end: date,
) -> list[dict]:
    """Backtest against top-quartile TPA for one segment.

    Target: top_quartile_tpa from daily_segment_stats (75th-pct TPA across boats).
    SST: sst_nearshore for inshore, sst_offshore for offshore.
    New factors included: sst_gradient, wind_is_offshore, wind_is_upwelling, chlorophyll.
    """
    _apply_schema(conn)
    daily_tpa = _get_segment_daily_tpa(conn, segment)
    if not daily_tpa:
        return []
    all_top_q = [v["top_quartile_tpa"] for v in daily_tpa.values()
                 if v["top_quartile_tpa"] is not None]

    hc_start = (start - timedelta(days=3)).isoformat()
    hc_end   = (end   + timedelta(days=3)).isoformat()
    hc_by_date = {
        r["date"]: dict(r)
        for r in conn.execute(
            "SELECT * FROM historical_conditions WHERE date BETWEEN ? AND ?",
            (hc_start, hc_end),
        ).fetchall()
    }

    sst_key = "sst_nearshore" if segment == "inshore" else "sst_offshore"

    results = []
    for d_str, actual in daily_tpa.items():
        dep_date = date.fromisoformat(d_str)
        if not (start <= dep_date <= end):
            continue
        top_q = actual.get("top_quartile_tpa")
        if top_q is None:
            continue
        cond = _avg_conditions_extended(hc_by_date, dep_date)
        if cond is None:
            continue
        sst_val = cond.get(sst_key)
        if sst_val is None:
            continue

        # Baseline prediction (SST + anomaly) — refined in Part 5 forecast engine
        boost = _anomaly_boost(cond.get("sst_anomaly"))
        predicted = round(min(10.0, max(1.0, _score(sst_val, _OVERALL_BREAKS) + boost)), 1)
        actual_rating = _tpa_to_rating(top_q, all_top_q)
        error = abs(predicted - actual_rating)

        chl_key = "chlorophyll_nearshore" if segment == "inshore" else "chlorophyll_ratio"
        results.append({
            "date":               d_str,
            "month":              dep_date.month,
            "season":             get_season(dep_date.month),
            "segment":            segment,
            "predicted":          predicted,
            "actual_tpa_topq":    round(top_q, 4),
            "actual_tpa_avg":     round(actual.get("avg_tpa") or 0, 4),
            "actual_rating":      actual_rating,
            "error":              round(error, 2),
            "correct_direction":  (predicted >= 5.5) == (actual_rating >= 5.5),
            # Condition factors for correlation analysis
            "sst_primary":        sst_val,
            "sst_anomaly":        cond.get("sst_anomaly"),
            "sst_gradient":       cond.get("sst_gradient"),
            "sst_warming_trend":  cond.get("sst_warming_trend"),
            "wind_speed":         cond.get("wind_speed"),
            "wind_is_offshore":   cond.get("wind_is_offshore"),
            "wind_is_upwelling":  cond.get("wind_is_upwelling"),
            "swell_height":       cond.get("swell_height"),
            "moon_illum":         cond.get("moon_illum"),
            "chl_primary":        cond.get(chl_key),
        })
    return sorted(results, key=lambda x: x["date"])


def correlate_segment_factors(
    conn: sqlite3.Connection,
    results: list[dict],
    segment: str,
) -> dict[str, dict[str, float | None]]:
    """Pearson r between each extended factor and top-quartile TPA rating."""
    factors = {
        "sst_primary":       [r["sst_primary"]      for r in results],
        "sst_anomaly":       [r["sst_anomaly"]      for r in results],
        "sst_gradient":      [r["sst_gradient"]     for r in results],
        "sst_warming_trend": [r["sst_warming_trend"]for r in results],
        "wind_speed":        [r["wind_speed"]       for r in results],
        "wind_is_offshore":  [r["wind_is_offshore"] for r in results],
        "wind_is_upwelling": [r["wind_is_upwelling"]for r in results],
        "swell_height":      [r["swell_height"]     for r in results],
        "moon_illum":        [r["moon_illum"]       for r in results],
        "chl_primary":       [r["chl_primary"]      for r in results],
        "month_num":         [float(r["month"])     for r in results],
    }
    targets = {"overall": [r["actual_rating"] for r in results]}
    matrix: dict[str, dict] = {}
    for fname, fvals in factors.items():
        matrix[fname] = {}
        for tname, tvals in targets.items():
            pairs = [(f, t) for f, t in zip(fvals, tvals) if f is not None and t is not None]
            matrix[fname][tname] = _pearson_r(*zip(*pairs)) if len(pairs) >= 10 else None
    return matrix


def optimize_segment_weights(
    correlations: dict,
    segment: str,
    existing: dict | None = None,
) -> dict:
    """Derive factor weights from correlation analysis for a segment+season."""
    weights = (existing or {}).copy()
    weights.setdefault("sst_weight",          1.0)
    weights.setdefault("anomaly_weight",       1.0)
    weights.setdefault("moon_weight",          0.0)
    weights.setdefault("wind_weight",          0.0)
    weights.setdefault("sst_gradient_weight",  0.0)
    weights.setdefault("wind_offshore_weight", 0.0)
    weights.setdefault("chl_weight",           0.0)

    def _adj(r: float | None, center: float = 0.3) -> float:
        if r is None:
            return 1.0
        return round(max(0.4, min(2.0, 1.0 + (abs(r) - center) * 2.0)), 3)

    sst_r  = correlations.get("sst_primary",       {}).get("overall")
    anom_r = correlations.get("sst_anomaly",        {}).get("overall")
    moon_r = correlations.get("moon_illum",         {}).get("overall")
    wind_r = correlations.get("wind_speed",         {}).get("overall")
    grad_r = correlations.get("sst_gradient",       {}).get("overall")
    woff_r = correlations.get("wind_is_offshore",   {}).get("overall")
    wup_r  = correlations.get("wind_is_upwelling",  {}).get("overall")
    chl_r  = correlations.get("chl_primary",        {}).get("overall")

    if sst_r  is not None: weights["sst_weight"]          = _adj(sst_r,  0.3)
    if anom_r is not None: weights["anomaly_weight"]       = _adj(anom_r, 0.2)
    if moon_r is not None: weights["moon_weight"]          = round(min(1.0, abs(moon_r) * 3), 3)
    if wind_r is not None: weights["wind_weight"]          = round(min(1.0, abs(wind_r) * 3), 3)
    if grad_r is not None: weights["sst_gradient_weight"]  = round(min(1.0, abs(grad_r) * 3), 3)
    best_wdir = max(abs(woff_r or 0), abs(wup_r or 0))
    if best_wdir > 0:      weights["wind_offshore_weight"] = round(min(1.0, best_wdir * 3), 3)
    if chl_r  is not None: weights["chl_weight"]           = round(min(1.0, abs(chl_r)  * 3), 3)

    weights["segment"] = segment
    return weights


def run_dual_backtest(
    db_path: Path,
    start: date, end: date,
    optimize: bool = False,
    extend_sst: bool = True,
    fetch_wind: bool = True,
    fetch_swell: bool = True,
) -> dict:
    """Run inshore + offshore backtests, saving 8 season-specific weight files."""
    import time
    t0 = time.time()
    print(f"Dual segment backtest: {start} to {end}")

    with dbmod.connect(db_path) as conn:
        _apply_schema(conn)

        if extend_sst:
            print("Step 1/4: Extending SST history...")
            n = _extend_sst(conn, start, end)
            print(f"  {'+' + str(n) + ' new records' if n else 'SST already current'}")

        wind_data: dict = {}
        if fetch_wind:
            print("Step 2/4: Fetching wind/pressure (Open-Meteo ERA5)...")
            wind_data = _fetch_openmeteo_wind(start, end)
            print(f"  {len(wind_data)} days of wind data")

        swell_data: dict = {}
        if fetch_swell:
            print("Step 3/4: Fetching swell (NDBC buoy 46047)...")
            swell_data = _fetch_ndbc_swell("46047", start, end)
            print(f"  {len(swell_data)} days of swell data")

        print("Step 4/4: Building historical_conditions table...")
        n_hc = build_historical_conditions(conn, start, end, wind_data, swell_data)
        print(f"  {n_hc} rows written")

        summary: dict = {
            "run_date":         date.today().isoformat(),
            "date_range_start": start.isoformat(),
            "date_range_end":   end.isoformat(),
        }

        for segment in ("inshore", "offshore"):
            print(f"\n{'-' * 55}")
            print(f"  {segment.upper()} SEGMENT")
            print(f"{'-' * 55}")
            results = backtest_segment(conn, segment, start, end)
            summary[f"{segment}_days"] = len(results)
            print(f"  {len(results)} days with paired conditions + {segment} catch data")

            if len(results) < 20:
                print(f"  Skipping — not enough data")
                continue

            metrics = compute_metrics(results)
            summary[f"{segment}_mae"]       = metrics["mae"]
            summary[f"{segment}_direction"] = metrics["direction_accuracy"]
            print(f"  MAE: {metrics['mae']}  Direction: {metrics['direction_accuracy']}%")

            all_corrs = correlate_segment_factors(conn, results, segment)
            print(f"\n  {'Factor':35s}  {'r':>8}")
            print("  " + "-" * 46)
            for fname, vals in sorted(
                all_corrs.items(),
                key=lambda x: abs(x[1].get("overall") or 0), reverse=True,
            ):
                r = vals.get("overall")
                print(f"  {fname:35s}  {f'{r:+.3f}' if r is not None else 'N/A':>8}")

            if optimize:
                for season in ("overall", "early", "peak", "late"):
                    if season == "overall":
                        season_results = results
                    else:
                        season_results = [r for r in results if r["season"] == season]
                    if len(season_results) < 20:
                        print(f"  Skipping {season} — only {len(season_results)} days")
                        continue
                    season_corrs = correlate_segment_factors(conn, season_results, segment)
                    existing = load_segment_weights(segment, season)
                    weights = optimize_segment_weights(season_corrs, segment, existing)
                    save_segment_weights(weights, segment, season)
                    print(f"  Saved weights: {segment}/{season}  "
                          f"sst={weights.get('sst_weight')}  "
                          f"anomaly={weights.get('anomaly_weight')}  "
                          f"wind={weights.get('wind_weight')}")

                # Store in backtest_results with a v2 model tag
                mv = f"2.0-{segment}"
                conn.execute(
                    """INSERT OR REPLACE INTO backtest_results
                       (run_date, model_version, date_range_start, date_range_end,
                        total_days, mae, rmse, direction_accuracy, by_month, weights)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (date.today().isoformat(), mv,
                     start.isoformat(), end.isoformat(),
                     metrics["total_days"], metrics["mae"], metrics["rmse"],
                     metrics["direction_accuracy"],
                     json.dumps(metrics.get("by_month", {})),
                     json.dumps(load_segment_weights(segment, "overall"))),
                )

        summary["run_duration_seconds"] = round(time.time() - t0, 1)
        return summary


# ─── Weekly recalibration (called from main.py) ──────────────────────────────

def weekly_recalibrate(
    db_path: Path,
    window_years: int = 3,
    min_days_between_runs: int = 30,
) -> dict | None:
    """Re-optimize forecast weights on a rolling window if ≥30 days since last run.

    Skips itself if a recalibration already ran recently (checks backtest_results).
    Non-fatal — all exceptions are caught and logged.
    Returns the full report dict (with report["metrics"]) or None if skipped/failed.
    """
    try:
        with dbmod.connect(db_path) as conn:
            _apply_schema(conn)
            row = conn.execute(
                "SELECT MAX(run_date) FROM backtest_results"
            ).fetchone()
            last_run = row[0] if row else None

        if last_run:
            days_since = (date.today() - date.fromisoformat(last_run)).days
            if days_since < min_days_between_runs:
                log.info(
                    "Monthly recalibration skipped — last run %d day(s) ago (%s)",
                    days_since, last_run,
                )
                return None

        start = date.today() - timedelta(days=window_years * 365)
        end   = date.today()
        log.info("Monthly recalibration: %s → %s (%d-year window)", start, end, window_years)

        return run_backtest(
            db_path=db_path,
            start=start,
            end=end,
            optimize=True,
            extend_sst=True,
            fetch_wind=True,
            fetch_swell=True,
        )
    except Exception as e:
        log.warning("Weekly recalibration failed (non-fatal): %s", e, exc_info=True)
        return None


# ─── Daily accuracy update (called from main.py) ──────────────────────────────

def daily_accuracy_update(conn: sqlite3.Connection) -> dict | None:
    """Score yesterday's forecast vs actual. Non-fatal — returns None if not enough data."""
    _apply_schema(conn)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    actual = conn.execute(
        """SELECT AVG(trophy_per_angler_per_day) AS avg_tpa, COUNT(*) AS n
           FROM trips WHERE date=? AND is_half_day=0 AND anglers>=5""",
        (yesterday,),
    ).fetchone()
    if not actual or not actual["n"] or actual["n"] < 2:
        return None

    # Try historical_conditions first, fall back to ocean_temps
    hc = conn.execute(
        "SELECT * FROM historical_conditions WHERE date=?", (yesterday,)
    ).fetchone()
    if hc:
        predicted = _predict_from_conditions(dict(hc))
    else:
        sst_row = conn.execute(
            "SELECT AVG(sst_fahrenheit) AS f, AVG(anomaly) AS a FROM ocean_temps WHERE date=?",
            (yesterday,),
        ).fetchone()
        if not sst_row or not sst_row["f"]:
            return None
        predicted = _predict_from_conditions({"sst_offshore": sst_row["f"], "sst_anomaly": sst_row["a"]})
    if predicted["overall"] is None:
        return None

    all_tpas = [r[0] for r in conn.execute(
        "SELECT AVG(trophy_per_angler_per_day) FROM trips WHERE is_half_day=0 AND anglers>=5"
        " GROUP BY date HAVING COUNT(*)>=2"
    ).fetchall() if r[0] is not None]
    actual_rating = _tpa_to_rating(actual["avg_tpa"], all_tpas)
    result = {
        "date":          yesterday,
        "predicted":     predicted["overall"],
        "actual_tpa":    round(actual["avg_tpa"], 4),
        "actual_rating": actual_rating,
        "error":         round(abs(predicted["overall"] - actual_rating), 2),
        "n_boats":       actual["n"],
    }
    log.info("Daily accuracy %s: predicted=%.1f actual=%.1f error=%.2f",
             yesterday, result["predicted"], result["actual_rating"], result["error"])
    return result


# ─── Main entry point ─────────────────────────────────────────────────────────

def run_backtest(
    db_path: Path, start: date, end: date,
    optimize: bool = False,
    extend_sst: bool = True,
    fetch_wind: bool = True,
    fetch_swell: bool = True,
    output_path: Path | None = None,
) -> dict:
    import time
    t0 = time.time()

    print(f"Backtest: {start} to {end}")

    with dbmod.connect(db_path) as conn:
        _apply_schema(conn)

        # 1. Extend SST history
        if extend_sst:
            print("Step 1/4: Extending SST history...")
            n = _extend_sst(conn, start, end)
            if n:
                print(f"  +{n} new SST records inserted")
            else:
                existing_ct = conn.execute(
                    "SELECT COUNT(DISTINCT date) FROM ocean_temps WHERE date BETWEEN ? AND ?",
                    (start.isoformat(), end.isoformat()),
                ).fetchone()[0]
                print(f"  SST already covers {existing_ct} dates in range (no new data needed)")

        # 2. Wind + pressure (Open-Meteo ERA5)
        wind_data: dict = {}
        if fetch_wind:
            print("Step 2/4: Fetching wind/pressure (Open-Meteo ERA5)...")
            wind_data = _fetch_openmeteo_wind(start, end)
            print(f"  {len(wind_data)} days of wind data")

        # 3. Wave/swell (NDBC buoy 46047 Tanner Bank)
        swell_data: dict = {}
        if fetch_swell:
            print("Step 3/4: Fetching swell (NDBC buoy 46047)...")
            swell_data = _fetch_ndbc_swell("46047", start, end)
            print(f"  {len(swell_data)} days of swell data")

        # 4. Build historical_conditions
        print("Step 4/4: Building historical_conditions table...")
        n_hc = build_historical_conditions(conn, start, end, wind_data, swell_data)
        print(f"  {n_hc} rows written")

        # 5. Backtest
        print("\nRunning backtest engine...")
        results = backtest_model(conn, start, end)
        print(f"  {len(results)} days with paired SST + catch data")

        if not results:
            print("\nNo results — SST and trip data must overlap for backtesting.")
            print("Tip: try a more recent --start date, or check ocean_temps coverage.")
            return {"error": "no_results"}

        # 6. Metrics
        metrics = compute_metrics(results)
        print(f"\n  MAE: {metrics['mae']}  RMSE: {metrics['rmse']}"
              f"  Direction: {metrics['direction_accuracy']}%")

        # 7. Correlations
        print("\nRunning correlation analysis...")
        correlations = correlate_factors(conn, results)
        print(f"\n  {'Factor':35s}  {'Overall':>8}  {'Bluefin':>8}  {'Yellowfin':>9}  {'Yellowtail':>10}")
        print("  " + "-" * 78)
        for fname, vals in sorted(
            correlations.items(),
            key=lambda x: abs(x[1].get("overall") or 0), reverse=True,
        ):
            def _f(v): return f"{v:+8.3f}" if v is not None else "     N/A"
            print(f"  {fname:35s}  {_f(vals.get('overall'))}  {_f(vals.get('bluefin'))}"
                  f"  {_f(vals.get('yellowfin'))}  {_f(vals.get('yellowtail'))}")

        # 8. Weights + calibrated score breaks
        existing = {}
        if WEIGHTS_PATH.exists():
            try:
                existing = json.loads(WEIGHTS_PATH.read_text())
            except Exception:
                pass
        weights = optimize_weights(correlations, existing)
        if optimize:
            calibrated = calibrate_score_breaks(conn)
            if calibrated:
                weights.update(calibrated)
            save_weights(weights)
            print(f"\nWeights saved to {WEIGHTS_PATH}")

        # 9. Store run in DB
        conn.execute(
            """INSERT OR REPLACE INTO backtest_results
               (run_date, model_version, date_range_start, date_range_end,
                total_days, mae, rmse, direction_accuracy, by_month, weights)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (date.today().isoformat(), "1.0",
             start.isoformat(), end.isoformat(),
             metrics["total_days"], metrics["mae"], metrics["rmse"],
             metrics["direction_accuracy"],
             json.dumps(metrics.get("by_month", {})),
             json.dumps(weights)),
        )

        # 10. Report
        report = generate_report(results, metrics, correlations, weights,
                                 start, end, time.time() - t0)
        _print_summary(report)
        if output_path:
            output_path.write_text(
                json.dumps(report, indent=2, default=str), encoding="utf-8"
            )
            print(f"\nFull report saved to {output_path}")
        return report


def main(argv=None) -> int:
    import argparse
    import sys
    p = argparse.ArgumentParser(description="Backtest the fishing forecast model")
    p.add_argument("--start", type=date.fromisoformat,
                   default=date.today() - timedelta(days=90),
                   help="Start date YYYY-MM-DD (default: 90 days ago)")
    p.add_argument("--end",   type=date.fromisoformat,
                   default=date.today(),
                   help="End date YYYY-MM-DD (default: today)")
    p.add_argument("--optimize",  action="store_true",
                   help="Save optimized weights to backtest_weights.json")
    p.add_argument("--output",    type=Path,
                   help="Write full JSON report to this file")
    p.add_argument("--segment", choices=["inshore", "offshore", "both"],
                   default=None,
                   help="Run dual segment backtest (both = inshore + offshore).")
    p.add_argument("--no-wind",   action="store_true", help="Skip Open-Meteo fetch")
    p.add_argument("--no-swell",  action="store_true", help="Skip NDBC fetch")
    p.add_argument("--no-extend-sst", action="store_true", help="Skip SST extension")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    kwargs = dict(
        extend_sst=not args.no_extend_sst,
        fetch_wind=not args.no_wind,
        fetch_swell=not args.no_swell,
    )
    if args.segment in ("inshore", "offshore", "both"):
        report = run_dual_backtest(
            DB_PATH, args.start, args.end,
            optimize=args.optimize,
            **kwargs,
        )
    else:
        report = run_backtest(
            DB_PATH, args.start, args.end,
            optimize=args.optimize,
            output_path=args.output,
            **kwargs,
        )
    return 0 if "error" not in report else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
