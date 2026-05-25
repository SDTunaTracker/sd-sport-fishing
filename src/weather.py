"""Marine weather fetcher for the daily scrape pipeline.

Fetches today's conditions and a 7-day forecast for SD offshore fishing grounds:
  Wind / pressure  — Open-Meteo forecast API (free, no API key required)
  Swell / waves    — Open-Meteo Marine API   (free, no API key required)

Returns merged daily dicts ready for forecast.py to score.
Heights in feet, speeds in knots (converted from API native units where needed).

All network calls wrapped in try/except — never crashes the main pipeline.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import requests

log = logging.getLogger(__name__)

# 60-Mile Bank as the offshore reference point
_LAT = 32.0
_LON = -118.5
_UA  = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

_M2FT = 3.28084   # metres → feet


def _fetch_wind_forecast(lat: float, lon: float, days: int = 8) -> list[dict]:
    """Wind speed (kn) + direction + pressure 8-day forecast from Open-Meteo."""
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "daily": ("wind_speed_10m_max,wind_direction_10m_dominant,"
                          "pressure_msl_max,pressure_msl_min"),
                "wind_speed_unit": "kn",
                "timezone": "UTC",
                "forecast_days": days,
            },
            headers={"User-Agent": _UA},
            timeout=20,
        )
        if r.status_code != 200:
            log.warning("Open-Meteo forecast HTTP %s", r.status_code)
            return []
        daily  = r.json().get("daily", {})
        times  = daily.get("time", [])
        winds  = daily.get("wind_speed_10m_max", [])
        dirs   = daily.get("wind_direction_10m_dominant", [])
        p_max  = daily.get("pressure_msl_max", [])
        p_min  = daily.get("pressure_msl_min", [])
        result = []
        prev_p = None
        for i, d_str in enumerate(times):
            pm = p_max[i] if i < len(p_max) else None
            pn = p_min[i] if i < len(p_min) else None
            avg_p = round((pm + pn) / 2, 1) if pm and pn else None
            trend = round(avg_p - prev_p, 1) if avg_p and prev_p else None
            prev_p = avg_p
            result.append({
                "date":           d_str,
                "wind_speed":     round(winds[i], 1) if i < len(winds) and winds[i] is not None else None,
                "wind_direction": dirs[i] if i < len(dirs) else None,
                "pressure":       avg_p,
                "pressure_trend": trend,
            })
        return result
    except Exception as e:
        log.warning("Open-Meteo wind forecast failed: %s", e)
        return []


def _fetch_swell_forecast(lat: float, lon: float, days: int = 8) -> list[dict]:
    """Wave height (ft) + period 8-day forecast from Open-Meteo Marine API."""
    try:
        r = requests.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": lat, "longitude": lon,
                "daily": "wave_height_max,wave_period_max",
                "timezone": "UTC",
                "forecast_days": days,
            },
            headers={"User-Agent": _UA},
            timeout=20,
        )
        if r.status_code != 200:
            log.warning("Open-Meteo Marine HTTP %s", r.status_code)
            return []
        daily   = r.json().get("daily", {})
        times   = daily.get("time", [])
        heights = daily.get("wave_height_max", [])
        periods = daily.get("wave_period_max", [])
        result = []
        for i, d_str in enumerate(times):
            h_m = heights[i] if i < len(heights) else None
            result.append({
                "date":         d_str,
                "swell_height": round(h_m * _M2FT, 1) if h_m is not None else None,
                "swell_period": periods[i] if i < len(periods) else None,
            })
        return result
    except Exception as e:
        log.warning("Open-Meteo Marine forecast failed: %s", e)
        return []


def fetch_marine_forecast(target_date: date | None = None) -> list[dict]:
    """Fetch and merge 7-day wind + wave forecast starting from target_date.

    Returns list of up to 8 dicts, each with keys:
      date, wind_speed (kn), wind_direction, pressure, pressure_trend,
      swell_height (ft), swell_period (s)

    Returns [] on total failure — never raises.
    """
    if target_date is None:
        target_date = date.today()

    wind_list  = _fetch_wind_forecast(_LAT, _LON, days=8)
    swell_list = _fetch_swell_forecast(_LAT, _LON, days=8)

    swell_by_date = {s["date"]: s for s in swell_list}
    merged: list[dict] = []
    for w in wind_list:
        d_str = w["date"]
        if d_str < target_date.isoformat():
            continue
        sw = swell_by_date.get(d_str, {})
        merged.append({
            "date":           d_str,
            "wind_speed":     w.get("wind_speed"),
            "wind_direction": w.get("wind_direction"),
            "pressure":       w.get("pressure"),
            "pressure_trend": w.get("pressure_trend"),
            "swell_height":   sw.get("swell_height"),
            "swell_period":   sw.get("swell_period"),
        })

    if not merged:
        log.warning("Weather forecast: no data returned for %s+", target_date)
    else:
        log.info("Weather forecast: %d days starting %s (wind=%d swell=%d)",
                 len(merged), target_date,
                 sum(1 for m in merged if m["wind_speed"] is not None),
                 sum(1 for m in merged if m["swell_height"] is not None))
    return merged
