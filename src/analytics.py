"""Fishing Forecast: combines SST data with historical catch rates to score 1–10.

Score composition:
  base   – temperature score from empirical bluefin/yellowfin optimal ranges
  hist   – multiplier from historical trophy-per-angler at similar SST
  anom   – small anomaly boost/penalty (warmer-than-avg → slight boost)
  weights – multipliers from backtest_weights.json (sst_weight, anomaly_weight)

The historical factor starts at 1.0 (neutral) and becomes meaningful once
enough SST+trip overlap accumulates in the DB (weeks to months of daily data).
Backtesting weights are loaded at import time and hot-reloaded if the file
changes (checked once per process start).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

_WEIGHTS_PATH = Path(__file__).resolve().parents[1] / "backtest_weights.json"
_WEIGHTS_DEFAULTS = {
    "sst_weight":    1.0,
    "anomaly_weight": 1.0,
    "moon_weight":   0.0,
    "wind_weight":   0.0,
}


def _load_weights() -> dict:
    """Load backtest_weights.json if present, else return defaults."""
    if _WEIGHTS_PATH.exists():
        try:
            return {**_WEIGHTS_DEFAULTS, **json.loads(_WEIGHTS_PATH.read_text())}
        except Exception:
            pass
    return _WEIGHTS_DEFAULTS.copy()


def _breaks_from_weights(w: dict, key: str, default: list) -> list[tuple[float, float]]:
    """Extract a calibrated break table from the weights dict.

    JSON stores inf as null; converts back to float('inf') here.
    Falls back to the hardcoded default if the key is absent or malformed.
    """
    raw = w.get(key)
    if not raw:
        return default
    try:
        return [(float("inf") if b is None else float(b), float(s)) for b, s in raw]
    except Exception:
        return default


# --- Temperature → score tables ------------------------------------------
# Each list is (upper_bound, score). Evaluated low-to-high; first match wins.

_OVERALL_BREAKS = [
    (55, 1.0), (58, 3.0), (62, 5.5), (65, 7.5),
    (68, 9.0), (72, 8.0), (75, 6.5), (78, 4.5), (float("inf"), 2.5),
]
_BLUEFIN_BREAKS = [
    (58, 1.0), (60, 3.0), (62, 5.5), (65, 8.0),
    (68, 10.0), (71, 7.0), (74, 4.0), (float("inf"), 2.0),
]
_YELLOWFIN_BREAKS = [
    (62, 1.0), (65, 3.0), (67, 5.5), (70, 8.0),
    (73, 10.0), (76, 7.5), (78, 5.5), (float("inf"), 3.0),
]

_CONDITIONS = [
    (8.5, "Excellent"), (7.0, "Good"), (5.0, "Fair"),
    (3.0, "Poor"), (0.0, "Very Poor"),
]


def _score(sst_f: float, breaks: list[tuple[float, float]]) -> float:
    for bound, val in breaks:
        if sst_f < bound:
            return val
    return breaks[-1][1]


def _anomaly_boost(anomaly: float | None) -> float:
    """Convert SST anomaly to a score modifier. Capped to avoid dominating."""
    if anomaly is None:
        return 0.0
    if anomaly >= 0:
        return min(anomaly * 0.25, 1.0)
    return max(anomaly * 0.4, -1.5)


def _historical_factor(conn: sqlite3.Connection, location: str, sst_f: float) -> float:
    """Multiplier (0.6–1.4) from historical trophy catch rate at similar SST.

    Joins ocean_temps ↔ trips for dates where SST was within ±2°F of current,
    then compares that subset's average trophy_per_angler_per_day to the
    overall fleet average. Returns 1.0 when data is insufficient.
    """
    try:
        at_temp = conn.execute(
            """SELECT AVG(t.trophy_per_angler_per_day) AS avg_tpa
               FROM trips t
               JOIN ocean_temps o ON t.date = o.date
               WHERE o.location = ?
                 AND o.sst_fahrenheit BETWEEN ? AND ?
                 AND t.is_half_day = 0
                 AND t.anglers >= 5""",
            (location, sst_f - 2.0, sst_f + 2.0),
        ).fetchone()
        overall = conn.execute(
            "SELECT AVG(trophy_per_angler_per_day) FROM trips"
            " WHERE is_half_day = 0 AND anglers >= 5"
        ).fetchone()
        if (at_temp and at_temp["avg_tpa"] is not None
                and overall and overall[0] is not None and overall[0] > 0):
            ratio = at_temp["avg_tpa"] / overall[0]
            return round(max(0.6, min(ratio, 1.4)), 3)
    except Exception:
        log.debug("historical_factor failed", exc_info=True)
    return 1.0


def _conditions_label(score: float) -> str:
    for threshold, label in _CONDITIONS:
        if score >= threshold:
            return label
    return "Very Poor"


def _summary(
    overall: float, bf: float, yf: float,
    sst_by_loc: dict[str, float], anomaly: float | None,
) -> str:
    parts = []
    ref = sst_by_loc.get("60-Mile Bank") or next(iter(sst_by_loc.values()), None)
    if ref:
        parts.append(f"60-Mile Bank SST {ref:.0f}°F")
    if anomaly is not None:
        direction = "above" if anomaly >= 0 else "below"
        parts.append(f"{abs(anomaly):.1f}° {direction} seasonal average")
    if bf >= 8.5:
        parts.append("prime bluefin conditions")
    elif yf >= 8.5:
        parts.append("prime yellowfin conditions")
    elif bf >= 7.0:
        parts.append("good bluefin window")
    elif yf >= 7.0:
        parts.append("good yellowfin window")
    elif overall <= 4.0:
        parts.append("cold water suppressing offshore bite")
    else:
        parts.append("mixed conditions")
    return " — ".join(parts) if parts else "SST data available; no forecast generated"


def build_forecast(conn: sqlite3.Connection, target_date: date | None = None) -> dict | None:
    """Compute the daily fishing forecast.

    Falls back to the most recent available SST date if target_date has no data.
    Returns None only if the ocean_temps table is completely empty.
    """
    if target_date is None:
        target_date = date.today()

    # Try target date, fall back to latest available
    date_str = target_date.isoformat()
    rows = conn.execute(
        "SELECT location, sst_fahrenheit, anomaly FROM ocean_temps WHERE date = ?",
        (date_str,),
    ).fetchall()
    if not rows:
        latest = conn.execute("SELECT MAX(date) FROM ocean_temps").fetchone()
        if not latest or not latest[0]:
            return None
        date_str = latest[0]
        rows = conn.execute(
            "SELECT location, sst_fahrenheit, anomaly FROM ocean_temps WHERE date = ?",
            (date_str,),
        ).fetchall()
    if not rows:
        return None

    sst_by_loc = {r["location"]: r["sst_fahrenheit"] for r in rows}
    anom_by_loc = {r["location"]: r["anomaly"] for r in rows}

    # 60-Mile Bank drives scores; fall back to any available location
    primary = "60-Mile Bank" if "60-Mile Bank" in sst_by_loc else next(iter(sst_by_loc))
    primary_sst = sst_by_loc[primary]
    primary_anom = anom_by_loc.get(primary)

    avg_sst = sum(sst_by_loc.values()) / len(sst_by_loc)
    valid_anoms = [v for v in anom_by_loc.values() if v is not None]
    avg_anom = round(sum(valid_anoms) / len(valid_anoms), 2) if valid_anoms else None

    # Load backtest-derived weights and calibrated breaks (if available)
    w = _load_weights()
    overall_breaks   = _breaks_from_weights(w, "overall_breaks",   _OVERALL_BREAKS)
    bluefin_breaks   = _breaks_from_weights(w, "bluefin_breaks",   _BLUEFIN_BREAKS)
    yellowfin_breaks = _breaks_from_weights(w, "yellowfin_breaks", _YELLOWFIN_BREAKS)

    # Temperature scores
    overall_base = _score(avg_sst, overall_breaks)
    bf_base      = _score(primary_sst, bluefin_breaks)
    yf_base      = _score(primary_sst, yellowfin_breaks)

    # Historical factor and anomaly modifier
    hist = _historical_factor(conn, primary, primary_sst)
    anom_mod = _anomaly_boost(primary_anom)

    # Apply backtest-derived weights
    sst_w  = w.get("sst_weight", 1.0)
    anom_w = w.get("anomaly_weight", 1.0)

    overall_score   = round(min(10.0, max(1.0, overall_base * hist * sst_w + anom_mod * anom_w)), 1)
    bluefin_score   = round(min(10.0, max(1.0, bf_base  * hist * sst_w + anom_mod * anom_w)), 1)
    yellowfin_score = round(min(10.0, max(1.0, yf_base  * hist * sst_w + anom_mod * anom_w * 0.5)), 1)

    return {
        "date": target_date.isoformat(),
        "data_date": date_str,     # actual SST date (may lag target_date by a few days)
        "overall_score": overall_score,
        "bluefin_score": bluefin_score,
        "yellowfin_score": yellowfin_score,
        "conditions": _conditions_label(overall_score),
        "sst_nearshore": sst_by_loc.get("Nearshore"),
        "sst_9mile": sst_by_loc.get("9-Mile Bank"),
        "sst_offshore": sst_by_loc.get("60-Mile Bank"),
        "sst_cortez": sst_by_loc.get("Cortez Bank"),
        "anomaly": avg_anom,
        "summary": _summary(overall_score, bluefin_score, yellowfin_score, sst_by_loc, avg_anom),
    }
