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
    _c_to_f, _compute_anomaly, _fetch_range,
    insert_sst,
)

log = logging.getLogger(__name__)

ROOT     = Path(__file__).resolve().parents[1]
DB_PATH  = ROOT / "tracker.db"
WEIGHTS_PATH = ROOT / "backtest_weights.json"

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

    # Load SST keyed by date then location
    sst_by_date: dict[str, dict] = {}
    for row in conn.execute(
        """SELECT date, location, sst_fahrenheit, anomaly
           FROM ocean_temps WHERE date BETWEEN ? AND ?""",
        (start.isoformat(), end.isoformat()),
    ).fetchall():
        d_str = row["date"]
        sst_by_date.setdefault(d_str, {"anomalies": []})
        sst_by_date[d_str][row["location"]] = row["sst_fahrenheit"]
        if row["anomaly"] is not None:
            sst_by_date[d_str]["anomalies"].append(row["anomaly"])

    n = 0
    for d in _date_range(start, end):
        d_str = d.isoformat()
        sst   = sst_by_date.get(d_str, {})
        anoms = sst.get("anomalies", [])
        moon  = moon_info(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))
        wd    = (wind_data  or {}).get(d_str, {})
        sw    = (swell_data or {}).get(d_str, {})
        conn.execute(
            """INSERT OR REPLACE INTO historical_conditions
               (date, sst_nearshore, sst_9mile, sst_offshore, sst_cortez,
                sst_anomaly, wind_speed, wind_direction, swell_height,
                swell_period, pressure, pressure_trend, moon_illum, moon_phase_name)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                d_str,
                sst.get("Nearshore"),
                sst.get("9-Mile Bank"),
                sst.get("60-Mile Bank"),
                sst.get("Cortez Bank"),
                round(sum(anoms) / len(anoms), 2) if anoms else None,
                wd.get("wind_speed"),
                wd.get("wind_direction"),
                sw.get("swell_height"),
                sw.get("swell_period"),
                wd.get("pressure"),
                wd.get("pressure_trend"),
                moon.illum,
                moon.phase,
            ),
        )
        n += 1
    return n


# ─── Backtest engine ──────────────────────────────────────────────────────────

def _get_daily_tpa(conn: sqlite3.Connection) -> dict[str, dict]:
    """Daily average trophy metrics (full-day trips, ≥5 anglers, ≥2 boats)."""
    rows = conn.execute(
        """SELECT date,
                  AVG(trophy_per_angler_per_day)              AS avg_tpa,
                  AVG(bluefin   * 1.0 / NULLIF(anglers, 0))  AS bf_pa,
                  AVG(yellowfin * 1.0 / NULLIF(anglers, 0))  AS yf_pa,
                  AVG(yellowtail* 1.0 / NULLIF(anglers, 0))  AS yt_pa,
                  AVG(dorado    * 1.0 / NULLIF(anglers, 0))  AS dor_pa,
                  COUNT(*)                                    AS n_boats,
                  SUM(anglers)                                AS total_anglers
           FROM trips
           WHERE is_half_day = 0 AND anglers >= 5
           GROUP BY date
           HAVING COUNT(*) >= 2
           ORDER BY date"""
    ).fetchall()
    return {r["date"]: dict(r) for r in rows}


def _tpa_to_rating(tpa: float, all_values: list[float]) -> float:
    """Percentile-based 1–10 rating: top 10 % of days → ~9-10, median → 5.5."""
    if not all_values:
        return 5.0
    rank = sum(1 for v in all_values if v <= tpa) / len(all_values)
    return round(max(1.0, min(10.0, 1.0 + rank * 9.0)), 1)


def _predict_from_conditions(hc: dict) -> dict:
    """Score from historical_conditions row — SST + anomaly only.
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

    hc_rows = conn.execute(
        "SELECT * FROM historical_conditions WHERE date BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()),
    ).fetchall()

    results = []
    for row in hc_rows:
        d_str = row["date"]
        if d_str not in daily_tpa:
            continue
        actual    = daily_tpa[d_str]
        predicted = _predict_from_conditions(dict(row))
        if predicted["overall"] is None:
            continue
        actual_rating = _tpa_to_rating(actual["avg_tpa"], all_tpa_vals)
        error         = abs(predicted["overall"] - actual_rating)
        results.append({
            "date":               d_str,
            "month":              int(d_str[5:7]),
            "predicted_overall":  predicted["overall"],
            "predicted_bluefin":  predicted["bluefin"],
            "predicted_yellowfin": predicted["yellowfin"],
            "actual_tpa":         round(actual["avg_tpa"], 4),
            "actual_rating":      actual_rating,
            "bf_pa":              actual.get("bf_pa"),
            "yf_pa":              actual.get("yf_pa"),
            "yt_pa":              actual.get("yt_pa"),
            "n_boats":            actual["n_boats"],
            "error":              round(error, 2),
            "correct_direction":  (predicted["overall"] >= 5.5) == (actual_rating >= 5.5),
            "sst_offshore":       row["sst_offshore"],
            "sst_anomaly":        row["sst_anomaly"],
            "wind_speed":         row["wind_speed"],
            "swell_height":       row["swell_height"],
            "pressure_trend":     row["pressure_trend"],
            "moon_illum":         row["moon_illum"],
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

    # Moon correlation over ALL trip dates — far more statistical power
    all_moon = conn.execute(
        """SELECT AVG(moon_illum)                             AS illum,
                  AVG(trophy_per_angler_per_day)             AS tpa,
                  AVG(bluefin    * 1.0 / NULLIF(anglers,0)) AS bf_pa,
                  AVG(yellowfin  * 1.0 / NULLIF(anglers,0)) AS yf_pa,
                  AVG(yellowtail * 1.0 / NULLIF(anglers,0)) AS yt_pa
           FROM trips WHERE is_half_day=0 AND anglers>=5
           GROUP BY date HAVING COUNT(*)>=2"""
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
            " WHERE is_half_day=0 AND anglers>=5"
            " GROUP BY date HAVING COUNT(*)>=2"
        ).fetchall() if r[0] is not None]

    all_tpa = _pool("AVG(trophy_per_angler_per_day)")
    all_bf  = _pool("AVG(bluefin   * 1.0 / NULLIF(anglers,0))")
    all_yf  = _pool("AVG(yellowfin * 1.0 / NULLIF(anglers,0))")
    if len(all_tpa) < 30:
        return None

    # Daily SST + catch metrics, full-day trips, >= 2 boats per day
    rows = conn.execute(
        """SELECT o.sst_fahrenheit AS sst,
                  AVG(t.trophy_per_angler_per_day)              AS tpa,
                  AVG(t.bluefin   * 1.0 / NULLIF(t.anglers,0)) AS bf_pa,
                  AVG(t.yellowfin * 1.0 / NULLIF(t.anglers,0)) AS yf_pa
           FROM ocean_temps o
           JOIN trips t ON t.date = o.date
           WHERE o.location = '60-Mile Bank'
             AND t.is_half_day = 0 AND t.anglers >= 5
           GROUP BY t.date
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
    p.add_argument("--no-wind",   action="store_true", help="Skip Open-Meteo fetch")
    p.add_argument("--no-swell",  action="store_true", help="Skip NDBC fetch")
    p.add_argument("--no-extend-sst", action="store_true", help="Skip SST extension")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    report = run_backtest(
        DB_PATH, args.start, args.end,
        optimize=args.optimize,
        extend_sst=not args.no_extend_sst,
        fetch_wind=not args.no_wind,
        fetch_swell=not args.no_swell,
        output_path=args.output,
    )
    return 0 if "error" not in report else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
