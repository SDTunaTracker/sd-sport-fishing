"""Full fishing forecast engine.

Score factors and default weights:
  sst        30%  — temperature vs species-optimal ranges (calibrated breaks)
  moon       20%  — phase alignment with feeding activity
  wind       15%  — surface wind (calm = good offshore access)
  swell      10%  — wave height (calmer = better)
  pressure   10%  — barometric trend (rising = predator activity)
  historical 15%  — avg TPA on similar conditions in DB

Produces:
  today       — full scored day with all conditions and factor breakdown
  sevenDay    — 7-day strip (current SST + forecasted wind/swell/moon)
  accuracy    — direction accuracy + MAE from forecast_accuracy_log / backtest_results
  historicalMatch — similar past days' catch statistics
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone

from .analytics import (
    _BLUEFIN_BREAKS, _OVERALL_BREAKS, _YELLOWFIN_BREAKS,
    _anomaly_boost, _breaks_from_weights, _load_weights, _score,
)
from .moon import moon_info

log = logging.getLogger(__name__)

# ─── Species SST break tables not in analytics.py ─────────────────────────────
# Yellowtail thrive in 60-68°F — cool-water west coast species
_YELLOWTAIL_BREAKS = [
    (57, 1.0), (60, 4.5), (62, 7.5), (64, 9.5),
    (67, 9.0), (70, 7.0), (73, 5.0), (float("inf"), 3.0),
]
# Dorado prefer warmer water — 70-78°F is their sweet spot near SD
_DORADO_BREAKS = [
    (65, 1.0), (68, 2.5), (70, 5.0), (72, 7.0),
    (74, 8.5), (76, 9.5), (78, 8.5), (float("inf"), 5.5),
]

_CONDITIONS_LABELS = [
    (9.0, "🔥 On Fire"),
    (7.0, "⬆️ Excellent"),
    (5.0, "✅ Good"),
    (3.0, "➡️ Average"),
    (0.0, "⬇️ Slow"),
]

_MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun",
                "Jul","Aug","Sep","Oct","Nov","Dec"]

# Default factor weights; override via backtest_weights.json keys
# "fw_sst", "fw_moon", etc. (separate from sst_weight/anomaly_weight multipliers)
_DEFAULT_WEIGHTS = {
    "sst": 0.30, "moon": 0.20, "wind": 0.15,
    "swell": 0.10, "pressure": 0.10, "historical": 0.15,
}


# ─── Scoring helpers ──────────────────────────────────────────────────────────

def _conditions_label(score: float) -> str:
    for threshold, label in _CONDITIONS_LABELS:
        if score >= threshold:
            return label
    return "⬇️ Slow"


def _moon_score(illum: int | None) -> float:
    """1-10 score from moon illumination percent (0=new moon, 100=full moon)."""
    if illum is None:
        return 5.0
    if illum <= 5:    return 10.0   # new moon
    if illum <= 15:   return 8.5
    if illum <= 35:   return 6.0
    if illum <= 45:   return 5.5
    if illum <= 55:   return 7.0    # quarter moons
    if illum <= 65:   return 5.5
    if illum <= 85:   return 6.5
    if illum <= 95:   return 9.0    # near-full
    return 9.5                       # full moon


def _wind_score(speed_kn: float | None) -> float:
    """1-10 score from wind speed in knots."""
    if speed_kn is None:
        return 7.0   # neutral when unknown
    if speed_kn < 5:   return 10.0
    if speed_kn < 10:  return 8.0
    if speed_kn < 15:  return 6.0
    if speed_kn < 20:  return 4.0
    return 2.0


def _swell_score(height_ft: float | None) -> float:
    """1-10 score from swell height in feet."""
    if height_ft is None:
        return 8.0   # assume decent when unknown
    if height_ft < 2:  return 10.0
    if height_ft < 4:  return 8.0
    if height_ft < 6:  return 5.0
    if height_ft < 8:  return 3.0
    return 1.0


def _pressure_score(trend: float | None) -> float:
    """1-10 score from barometric pressure trend (hPa delta from yesterday)."""
    if trend is None:
        return 7.0
    if trend >= 1.0:    return 9.0   # rising steadily
    if trend >= -0.5:   return 7.0   # steady
    if trend >= -2.0:   return 5.0   # falling slowly
    return 2.0                        # falling rapidly


def _historical_score_for_sst(
    conn: sqlite3.Connection, sst_f: float, month: int
) -> float:
    """Historical avg-TPA at similar SST in same month → 1-10 score."""
    try:
        row = conn.execute(
            """SELECT AVG(t.trophy_per_angler_per_day) AS avg_tpa
               FROM trips t
               JOIN ocean_temps o ON t.date = o.date
               WHERE o.location = '60-Mile Bank'
                 AND o.sst_fahrenheit BETWEEN ? AND ?
                 AND strftime('%m', t.date) = ?
                 AND t.is_half_day = 0 AND t.anglers >= 5""",
            (sst_f - 2.0, sst_f + 2.0, f"{month:02d}"),
        ).fetchone()
        overall = conn.execute(
            "SELECT AVG(trophy_per_angler_per_day) FROM trips"
            " WHERE is_half_day=0 AND anglers>=5"
        ).fetchone()
        if (row and row["avg_tpa"] is not None
                and overall and overall[0] is not None and overall[0] > 0):
            ratio = row["avg_tpa"] / overall[0]
            # ratio=1.0→5.5, ratio=2.0→10, ratio=0.5→1
            return round(max(1.0, min(10.0, 5.5 + (ratio - 1.0) * 4.5)), 1)
    except Exception:
        pass
    return 5.5


def score_day(
    sst_f: float | None,
    moon_illum: int | None,
    wind_speed: float | None,
    swell_height_ft: float | None,
    pressure_trend: float | None,
    anomaly: float | None,
    historical_val: float = 5.5,
    weight_overrides: dict | None = None,
) -> dict:
    """Compute full weighted score for one day.

    Returns a dict with overall_score, species scores, conditions_label,
    factor_scores, and factor_weights.
    """
    w = {**_DEFAULT_WEIGHTS, **(weight_overrides or {})}

    bw = _load_weights()
    overall_breaks   = _breaks_from_weights(bw, "overall_breaks",   _OVERALL_BREAKS)
    bluefin_breaks   = _breaks_from_weights(bw, "bluefin_breaks",   _BLUEFIN_BREAKS)
    yellowfin_breaks = _breaks_from_weights(bw, "yellowfin_breaks", _YELLOWFIN_BREAKS)

    # Factor scores
    f_sst  = _score(sst_f, overall_breaks) if sst_f is not None else 5.0
    f_moon = _moon_score(moon_illum)
    f_wind = _wind_score(wind_speed)
    f_swe  = _swell_score(swell_height_ft)
    f_pres = _pressure_score(pressure_trend)
    f_hist = historical_val

    # Anomaly nudges SST factor slightly
    anom_mod = _anomaly_boost(anomaly) * 0.4
    f_sst_adj = round(min(10.0, max(1.0, f_sst + anom_mod)), 1)

    # Weighted average
    total_w = sum(w.values())
    overall = (
        f_sst_adj * w["sst"]  +
        f_moon    * w["moon"] +
        f_wind    * w["wind"] +
        f_swe     * w["swell"] +
        f_pres    * w["pressure"] +
        f_hist    * w["historical"]
    ) / total_w
    overall = round(min(10.0, max(1.0, overall)), 1)

    # Species scores: SST-dominant blend with shared moon/wind/swell
    non_sst_w = w["moon"] + w["wind"] + w["swell"]
    non_sst_avg = (f_moon * w["moon"] + f_wind * w["wind"] + f_swe * w["swell"]) / max(non_sst_w, 0.001)

    def _sp(breaks: list, sp_w: float = 0.65) -> float:
        base = _score(sst_f, breaks) if sst_f is not None else 5.0
        base_adj = round(min(10.0, max(1.0, base + anom_mod)), 1)
        return round(min(10.0, max(1.0, base_adj * sp_w + non_sst_avg * (1 - sp_w))), 1)

    return {
        "overall_score":    overall,
        "bluefin_score":    _sp(bluefin_breaks),
        "yellowfin_score":  _sp(yellowfin_breaks),
        "yellowtail_score": _sp(_YELLOWTAIL_BREAKS),
        "dorado_score":     _sp(_DORADO_BREAKS),
        "conditions_label": _conditions_label(overall),
        "factor_scores": {
            "sst":      f_sst_adj,
            "moon":     round(f_moon, 1),
            "wind":     round(f_wind, 1),
            "swell":    round(f_swe, 1),
            "pressure": round(f_pres, 1),
            "historical": round(f_hist, 1),
        },
        "factor_weights": {k: round(v / total_w, 3) for k, v in w.items()},
    }


# ─── Forecast summary ──────────────────────────────────────────────────────────

def _summary(scores: dict, sst_by_loc: dict, anomaly: float | None, moon_name: str | None) -> str:
    parts = []
    ref = sst_by_loc.get("60-Mile Bank") or next(iter(sst_by_loc.values()), None)
    if ref:
        parts.append(f"60-Mile Bank {ref:.0f}°F")
    if anomaly is not None:
        direction = "above" if anomaly >= 0 else "below"
        parts.append(f"{abs(anomaly):.1f}° {direction} avg")

    bf = scores.get("bluefin_score",    0)
    yf = scores.get("yellowfin_score",  0)
    yt = scores.get("yellowtail_score", 0)
    ov = scores.get("overall_score",    0)

    if bf >= 8.0:   note = "prime bluefin conditions"
    elif yf >= 8.0: note = "prime yellowfin conditions"
    elif yt >= 8.0: note = "prime yellowtail bite"
    elif bf >= 6.5: note = "solid bluefin window"
    elif yf >= 6.5: note = "solid yellowfin opportunity"
    elif ov >= 7.0: note = "good overall conditions"
    elif ov <= 4.0: note = "tough offshore conditions"
    else:           note = "mixed conditions"
    parts.append(note)

    if moon_name:
        parts.append(f"{moon_name} moon")
    return " · ".join(parts[:3])


# ─── Historical match ──────────────────────────────────────────────────────────

def _historical_match(
    conn: sqlite3.Connection,
    month: int,
    sst_f: float | None,
    moon_illum: int | None,
) -> dict:
    """Find historical days with similar SST + moon in same month.

    Requires historical_conditions to have been populated by the backtest.
    Falls back to ocean_temps-only join if historical_conditions is empty.
    """
    if sst_f is None:
        return {}
    month_str = f"{month:02d}"
    sst_lo, sst_hi = sst_f - 3.0, sst_f + 3.0
    moon_buf = 25  # ± illumination percent

    try:
        # Try with historical_conditions (has wind, swell, moon) — may not exist yet
        try:
            hc_count = conn.execute(
                "SELECT COUNT(*) FROM historical_conditions WHERE sst_offshore IS NOT NULL"
            ).fetchone()[0]
        except Exception:
            hc_count = 0

        if hc_count >= 20:
            where = ["strftime('%m', t.date) = ?", "hc.sst_offshore BETWEEN ? AND ?",
                     "t.is_half_day=0", "t.anglers>=5"]
            params: list = [month_str, sst_lo, sst_hi]
            if moon_illum is not None:
                where.append("ABS(hc.moon_illum - ?) <= ?")
                params.extend([moon_illum, moon_buf])

            boat_rows = conn.execute(
                f"""SELECT t.boat, t.landing,
                       AVG(t.trophy_per_angler_per_day)             AS avg_tpa,
                       COUNT(DISTINCT t.date)                        AS trips,
                       AVG(t.bluefin   *1.0/NULLIF(t.anglers,0))   AS bf_pa,
                       AVG(t.yellowfin *1.0/NULLIF(t.anglers,0))   AS yf_pa,
                       AVG(t.yellowtail*1.0/NULLIF(t.anglers,0))   AS yt_pa,
                       AVG(t.dorado    *1.0/NULLIF(t.anglers,0))   AS dor_pa
                   FROM trips t
                   JOIN historical_conditions hc ON hc.date = t.date
                   WHERE {' AND '.join(where)}
                   GROUP BY t.boat, t.landing
                   HAVING COUNT(DISTINCT t.date) >= 2
                   ORDER BY avg_tpa DESC LIMIT 20""",
                params,
            ).fetchall()

            day_stats = conn.execute(
                f"""SELECT COUNT(DISTINCT t.date) AS n_days,
                           AVG(t.trophy_per_angler_per_day) AS avg_tpa,
                           SUM(CASE WHEN t.trophy_per_angler_per_day>=2.0 THEN 1 ELSE 0 END)
                             *1.0/NULLIF(COUNT(*),0) AS pct_2plus
                    FROM trips t
                    JOIN historical_conditions hc ON hc.date = t.date
                    WHERE {' AND '.join(where)}""",
                params,
            ).fetchone()

        else:
            # Fallback: ocean_temps join only
            boat_rows = conn.execute(
                """SELECT t.boat, t.landing,
                       AVG(t.trophy_per_angler_per_day)            AS avg_tpa,
                       COUNT(DISTINCT t.date)                       AS trips,
                       AVG(t.bluefin   *1.0/NULLIF(t.anglers,0))  AS bf_pa,
                       AVG(t.yellowfin *1.0/NULLIF(t.anglers,0))  AS yf_pa,
                       AVG(t.yellowtail*1.0/NULLIF(t.anglers,0))  AS yt_pa,
                       AVG(t.dorado    *1.0/NULLIF(t.anglers,0))  AS dor_pa
                   FROM trips t
                   JOIN ocean_temps o ON o.date = t.date AND o.location='60-Mile Bank'
                   WHERE strftime('%m', t.date) = ?
                     AND o.sst_fahrenheit BETWEEN ? AND ?
                     AND t.is_half_day=0 AND t.anglers>=5
                   GROUP BY t.boat, t.landing
                   HAVING COUNT(DISTINCT t.date) >= 2
                   ORDER BY avg_tpa DESC LIMIT 20""",
                [month_str, sst_lo, sst_hi],
            ).fetchall()

            day_stats = conn.execute(
                """SELECT COUNT(DISTINCT t.date) AS n_days,
                       AVG(t.trophy_per_angler_per_day) AS avg_tpa,
                       SUM(CASE WHEN t.trophy_per_angler_per_day>=2.0 THEN 1 ELSE 0 END)
                         *1.0/NULLIF(COUNT(*),0) AS pct_2plus
                   FROM trips t
                   JOIN ocean_temps o ON o.date=t.date AND o.location='60-Mile Bank'
                   WHERE strftime('%m', t.date) = ?
                     AND o.sst_fahrenheit BETWEEN ? AND ?
                     AND t.is_half_day=0 AND t.anglers>=5""",
                [month_str, sst_lo, sst_hi],
            ).fetchone()

        if not day_stats or not day_stats["n_days"]:
            return {}

        all_tpa = [r["avg_tpa"] for r in boat_rows if r["avg_tpa"] is not None]

        # Best species
        if boat_rows:
            bf_avg  = sum(r["bf_pa"]  or 0 for r in boat_rows) / len(boat_rows)
            yf_avg  = sum(r["yf_pa"]  or 0 for r in boat_rows) / len(boat_rows)
            yt_avg  = sum(r["yt_pa"]  or 0 for r in boat_rows) / len(boat_rows)
            dor_avg = sum(r["dor_pa"] or 0 for r in boat_rows) / len(boat_rows)
            best_sp = max(
                {"Bluefin": bf_avg, "Yellowfin": yf_avg, "Yellowtail": yt_avg, "Dorado": dor_avg}.items(),
                key=lambda x: x[1],
            )[0]
        else:
            best_sp = None

        moon_note = f", moon {moon_illum}%" if moon_illum is not None else ""
        return {
            "matching_days": day_stats["n_days"],
            "avg_tpa":        round(day_stats["avg_tpa"], 2) if day_stats["avg_tpa"] else None,
            "best_boat_avg":  round(boat_rows[0]["avg_tpa"], 2) if boat_rows else None,
            "pct_above_2tpa": round(day_stats["pct_2plus"], 2) if day_stats["pct_2plus"] else None,
            "best_species":   best_sp,
            "top_boats": [
                {
                    "boat": r["boat"], "landing": r["landing"],
                    "avg_tpa": round(r["avg_tpa"], 2), "trips": r["trips"],
                }
                for r in boat_rows[:3]
            ],
            "description": (
                f"Conditions like these in {_MONTH_NAMES[month - 1]}"
                f"{moon_note}: {day_stats['n_days']} historical days"
            ),
        }
    except Exception as e:
        log.debug("historical_match failed: %s", e)
        return {}


# ─── Accuracy stats ────────────────────────────────────────────────────────────

def _accuracy_stats(conn: sqlite3.Connection) -> dict:
    """Direction accuracy + MAE from forecast_accuracy_log, else backtest_results."""
    try:
        rows = conn.execute(
            "SELECT predicted_score, actual_rating, error, correct_direction"
            " FROM forecast_accuracy_log ORDER BY date"
        ).fetchall()
        if rows:
            n    = len(rows)
            mae  = round(sum(r["error"] for r in rows) / n, 2)
            dacc = round(sum(1 for r in rows if r["correct_direction"]) / n * 100, 1)
            cutoff = (date.today() - timedelta(days=30)).isoformat()
            recent = conn.execute(
                "SELECT correct_direction FROM forecast_accuracy_log WHERE date >= ?",
                (cutoff,),
            ).fetchall()
            last30 = round(sum(1 for r in recent if r["correct_direction"]) / len(recent) * 100, 1) if recent else None
            return {"total_days_tested": n, "mae": mae, "direction_accuracy": dacc, "last_30_days_accuracy": last30}
    except Exception:
        pass
    # Fallback to latest backtest_results row
    try:
        bt = conn.execute(
            "SELECT total_days, mae, direction_accuracy FROM backtest_results ORDER BY run_date DESC LIMIT 1"
        ).fetchone()
        if bt:
            return {
                "total_days_tested": bt["total_days"],
                "mae":               bt["mae"],
                "direction_accuracy": bt["direction_accuracy"],
                "last_30_days_accuracy": None,
            }
    except Exception:
        pass
    return {}


# ─── Main builder ─────────────────────────────────────────────────────────────

def build_forecast_payload(
    conn: sqlite3.Connection,
    weather_forecast: list[dict] | None = None,
) -> dict:
    """Build the complete window.SD.FORECAST payload.

    weather_forecast: output of weather.fetch_marine_forecast().
    If None, the 7-day strip scores use SST + moon only (no wind/swell).
    """
    today     = date.today()
    today_str = today.isoformat()
    month     = today.month

    # ── SST (latest available) ────────────────────────────────────────────────
    sst_rows = conn.execute(
        """SELECT location, sst_fahrenheit, anomaly
           FROM ocean_temps
           WHERE date = (SELECT MAX(date) FROM ocean_temps)
           ORDER BY location"""
    ).fetchall()
    sst_by_loc  = {r["location"]: r["sst_fahrenheit"] for r in sst_rows}
    anom_by_loc = {r["location"]: r["anomaly"]         for r in sst_rows}
    sst_date_row = conn.execute("SELECT MAX(date) FROM ocean_temps").fetchone()
    sst_data_date = sst_date_row[0] if sst_date_row else None

    primary_sst  = sst_by_loc.get("60-Mile Bank") or next(iter(sst_by_loc.values()), None)
    primary_anom = anom_by_loc.get("60-Mile Bank")

    # ── Today's weather data ──────────────────────────────────────────────────
    today_wx: dict = {}
    if weather_forecast:
        today_wx = next((w for w in weather_forecast if w["date"] == today_str), {})
    # Fall back to historical_conditions for today/yesterday
    if not today_wx:
        try:
            hc = conn.execute(
                "SELECT * FROM historical_conditions WHERE date IN (?,?) ORDER BY date DESC LIMIT 1",
                (today_str, (today - timedelta(days=1)).isoformat()),
            ).fetchone()
            if hc:
                today_wx = {
                    "wind_speed":     hc["wind_speed"],
                    "wind_direction": hc["wind_direction"],
                    "swell_height":   hc["swell_height"],
                    "swell_period":   hc["swell_period"],
                    "pressure":       hc["pressure"],
                    "pressure_trend": hc["pressure_trend"],
                }
                # NDBC swell_height stored in metres — convert for scoring
                if today_wx.get("swell_height") is not None:
                    today_wx["swell_height"] = round(today_wx["swell_height"] * 3.28084, 1)
        except Exception:
            pass

    # ── Moon ─────────────────────────────────────────────────────────────────
    moon = moon_info(datetime(today.year, today.month, today.day, tzinfo=timezone.utc))

    # ── Historical factor ────────────────────────────────────────────────────
    hist_val = _historical_score_for_sst(conn, primary_sst, month) if primary_sst else 5.5

    # ── Today's score ─────────────────────────────────────────────────────────
    scores = score_day(
        sst_f=primary_sst,
        moon_illum=moon.illum,
        wind_speed=today_wx.get("wind_speed"),
        swell_height_ft=today_wx.get("swell_height"),
        pressure_trend=today_wx.get("pressure_trend"),
        anomaly=primary_anom,
        historical_val=hist_val,
    )

    today_out = {
        "date":     today_str,
        "dataDate": sst_data_date,
        **scores,
        "summary": _summary(scores, sst_by_loc, primary_anom, moon.phase),
        "sst_nearshore":   sst_by_loc.get("Nearshore"),
        "sst_9mile":       sst_by_loc.get("9-Mile Bank"),
        "sst_offshore":    primary_sst,
        "sst_cortez":      sst_by_loc.get("Cortez Bank"),
        "anomaly":         primary_anom,
        "wind_speed":      today_wx.get("wind_speed"),
        "wind_direction":  today_wx.get("wind_direction"),
        "swell_height":    today_wx.get("swell_height"),
        "swell_period":    today_wx.get("swell_period"),
        "pressure":        today_wx.get("pressure"),
        "moon_phase":      moon.illum,
        "moon_phase_name": moon.phase,
    }

    # ── 7-day strip ───────────────────────────────────────────────────────────
    wx_by_date = {w["date"]: w for w in (weather_forecast or [])}
    seven_day: list[dict] = []
    for i in range(7):
        d     = today + timedelta(days=i)
        d_str = d.isoformat()
        wx    = wx_by_date.get(d_str, {})
        dmoon = moon_info(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))
        ds = score_day(
            sst_f=primary_sst,
            moon_illum=dmoon.illum,
            wind_speed=wx.get("wind_speed"),
            swell_height_ft=wx.get("swell_height"),
            pressure_trend=wx.get("pressure_trend"),
            anomaly=primary_anom,
            historical_val=hist_val,
        )
        seven_day.append({
            "date":            d_str,
            "dayName":         d.strftime("%a"),
            **ds,
            "sst":             primary_sst,
            "wind_speed":      wx.get("wind_speed"),
            "swell_height":    wx.get("swell_height"),
            "moon_phase":      dmoon.illum,
            "moon_phase_name": dmoon.phase,
        })

    # ── Historical match ──────────────────────────────────────────────────────
    hist_match = _historical_match(conn, month, primary_sst, moon.illum)

    # ── Accuracy ──────────────────────────────────────────────────────────────
    accuracy = _accuracy_stats(conn)

    return {
        "today":           today_out,
        "sevenDay":        seven_day,
        "accuracy":        accuracy,
        "historicalMatch": hist_match,
    }


# ─── Daily accuracy scoring (call from main.py) ───────────────────────────────

def score_yesterday(conn: sqlite3.Connection) -> dict | None:
    """Record yesterday's forecast accuracy into forecast_accuracy_log.

    Non-fatal — returns None if data is insufficient.
    Called once per daily run after fish scraping.
    """
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    actual = conn.execute(
        """SELECT AVG(trophy_per_angler_per_day) AS avg_tpa, COUNT(*) AS n
           FROM trips WHERE date=? AND is_half_day=0 AND anglers>=5""",
        (yesterday,),
    ).fetchone()
    if not actual or not actual["n"] or actual["n"] < 2:
        return None

    # Get yesterday's conditions
    hc = conn.execute(
        "SELECT * FROM historical_conditions WHERE date=?", (yesterday,)
    ).fetchone()
    if not hc:
        sst_row = conn.execute(
            "SELECT AVG(sst_fahrenheit) AS f, AVG(anomaly) AS a FROM ocean_temps WHERE date=?",
            (yesterday,),
        ).fetchone()
        if not sst_row or not sst_row["f"]:
            return None
        sst_f = sst_row["f"]
        hc_dict = {"sst_offshore": sst_f, "sst_anomaly": sst_row["a"]}
    else:
        sst_f   = hc["sst_offshore"] or hc["sst_9mile"] or hc["sst_nearshore"]
        hc_dict = dict(hc)

    if not sst_f:
        return None

    moon_dt = datetime.fromisoformat(yesterday + "T12:00:00+00:00")
    moon    = moon_info(moon_dt)
    swell_ft = hc_dict.get("swell_height")
    if swell_ft is not None:
        swell_ft = round(swell_ft * 3.28084, 1)  # metres→feet for NDBC data

    sc = score_day(
        sst_f=sst_f,
        moon_illum=moon.illum,
        wind_speed=hc_dict.get("wind_speed"),
        swell_height_ft=swell_ft,
        pressure_trend=hc_dict.get("pressure_trend"),
        anomaly=hc_dict.get("sst_anomaly"),
        historical_val=5.5,   # neutral — avoids data leakage
    )
    predicted = sc["overall_score"]

    all_tpas = [r[0] for r in conn.execute(
        "SELECT AVG(trophy_per_angler_per_day) FROM trips"
        " WHERE is_half_day=0 AND anglers>=5 GROUP BY date HAVING COUNT(*)>=2"
    ).fetchall() if r[0] is not None]
    if not all_tpas:
        return None

    rank          = sum(1 for v in all_tpas if v <= actual["avg_tpa"]) / len(all_tpas)
    actual_rating = round(max(1.0, min(10.0, 1.0 + rank * 9.0)), 1)
    error         = round(abs(predicted - actual_rating), 2)
    correct_dir   = int((predicted >= 5.5) == (actual_rating >= 5.5))

    conn.execute(
        """INSERT OR REPLACE INTO forecast_accuracy_log
           (date, predicted_score, actual_tpa, actual_rating, error, correct_direction)
           VALUES (?,?,?,?,?,?)""",
        (yesterday, predicted, round(actual["avg_tpa"], 4), actual_rating, error, correct_dir),
    )
    log.info("Forecast accuracy %s: predicted=%.1f actual=%.1f error=%.2f",
             yesterday, predicted, actual_rating, error)
    return {"date": yesterday, "predicted": predicted, "actual_rating": actual_rating,
            "actual_tpa": actual["avg_tpa"], "error": error}
