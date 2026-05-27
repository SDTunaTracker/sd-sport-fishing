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
import math as _math
import sqlite3
import statistics as _statistics
from datetime import date, datetime, timedelta, timezone

from .analytics import (
    _BLUEFIN_BREAKS, _OVERALL_BREAKS, _YELLOWFIN_BREAKS,
    _anomaly_boost, _breaks_from_weights, _load_weights, _score,
)
from .backtest import _classify_wind, get_season, load_segment_weights
from .chlorophyll import score_chlorophyll
from .moon import moon_info
from .upwelling import fetch_recent_upwelling

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

# Fallback factor weights used only when backtest_weights.json is absent.
_FALLBACK_WEIGHTS = {
    "sst": 0.35, "moon": 0.10, "wind": 0.20,
    "swell": 0.10, "pressure": 0.10, "historical": 0.15,
}

# Fixed defaults for factors the backtest doesn't directly measure.
_SWELL_DEFAULT    = 0.10
_PRESSURE_DEFAULT = 0.10
_HISTORICAL_DEFAULT = 0.15


def _load_factor_weights() -> dict:
    """Derive proportional factor weights from backtest_weights.json.

    The backtest produces correlation-derived multipliers (sst_weight, moon_weight,
    wind_weight) — higher = stronger real-world correlation.  We normalize these
    alongside fixed defaults for swell/pressure/historical (not measured by the
    backtest) to get weights that sum to 1.0.

    With the current backtest run (sst=1.334, moon=0.091, wind=0.488) this yields
    roughly:  sst≈59%  wind≈22%  historical≈7%  swell≈4%  pressure≈4%  moon≈4%
    — i.e. SST and wind dominate, moon gets credit only for what the data supports.
    """
    bw = _load_weights()
    if not bw or bw == {"sst_weight": 1.0, "anomaly_weight": 1.0, "moon_weight": 0.0, "wind_weight": 0.0}:
        return _FALLBACK_WEIGHTS.copy()

    sst_w  = max(0.05, bw.get("sst_weight",  1.0))
    moon_w = min(0.02, max(0.005, bw.get("moon_weight", 0.0)))  # cap at 2%
    wind_w = max(0.05, bw.get("wind_weight", 0.5))
    # swell / pressure / historical not in backtest — keep fixed
    swell_w = _SWELL_DEFAULT
    pres_w  = _PRESSURE_DEFAULT
    hist_w  = _HISTORICAL_DEFAULT

    total = sst_w + moon_w + wind_w + swell_w + pres_w + hist_w
    return {
        "sst":       round(sst_w  / total, 4),
        "moon":      round(moon_w / total, 4),
        "wind":      round(wind_w / total, 4),
        "swell":     round(swell_w / total, 4),
        "pressure":  round(pres_w  / total, 4),
        "historical": round(hist_w  / total, 4),
    }


# ─── Dual segment helpers ────────────────────────────────────────────────────

def _wind_direction_score(
    is_offshore: int | None,
    is_upwelling: int | None,
    segment: str,
) -> float:
    """Score wind direction for fishing (1–10).

    Offshore: NW upwelling hurts (cold push), E/S offshore wind helps.
    Inshore:  NW upwelling boosts bait/productivity; direction matters less.
    """
    if is_offshore is None and is_upwelling is None:
        return 5.0
    if segment == "offshore":
        if is_upwelling:  return 3.0   # NW — cold upwelling, hurts offshore tuna
        if is_offshore:   return 8.5   # E/S/SE — warm offshore flow, fish up
        return 5.5                     # W neutral
    else:  # inshore
        if is_upwelling:  return 7.5   # NW — productive bait upwelling
        if is_offshore:   return 6.0   # E/SE — decent
        return 5.0


def _sst_gradient_score(gradient: float | None, segment: str) -> float:
    """Score the nearshore/offshore temperature break (1–10).

    A strong gradient concentrates fish at the edge — good for both segments,
    but especially important for offshore where pelagics stack at the break.
    """
    if gradient is None:
        return 5.0
    if segment == "offshore":
        if gradient >= 5.0: return 9.5
        if gradient >= 3.0: return 8.0
        if gradient >= 2.0: return 6.5
        if gradient >= 1.0: return 5.5
        return 4.0   # weak gradient — no clear break
    else:  # inshore
        if gradient >= 3.0: return 7.0   # productive edge close in
        if gradient >= 1.5: return 6.0
        return 5.0


def calculate_consensus(factor_scores: dict, segment: str) -> dict:
    """Compute how much the key factors agree with each other (0–100%).

    Low std-dev across factors = they all point the same direction = high consensus.
    High std-dev = conflicting signals = widen the confidence interval.
    """
    if segment == "offshore":
        keys = ["sst", "wind_dir", "sst_gradient", "chlorophyll"]
    else:  # inshore
        keys = ["sst", "wind_dir", "chlorophyll"]

    key_val_pairs = [(k, factor_scores[k]) for k in keys
                     if k in factor_scores and factor_scores[k] is not None]
    vals = [v for _, v in key_val_pairs]

    if len(vals) < 2:
        return {
            "consensus_pct":       50,
            "consensus_label":     "Moderate",
            "consensus_color":     "#FBBF24",
            "interval_multiplier": 1.0,
            "factors_agreeing":    [],
            "factors_conflicting": [],
        }

    avg = _statistics.mean(vals)
    std = _statistics.stdev(vals)
    pct = max(0, min(100, round((1 - std / 3.0) * 100)))

    if pct >= 80:
        label, color, mult = "Strong",     "#10B981", 0.8
    elif pct >= 60:
        label, color, mult = "Moderate",   "#FBBF24", 1.0
    elif pct >= 40:
        label, color, mult = "Mixed",      "#F97316", 1.3
    else:
        label, color, mult = "Conflicted", "#EF4444", 1.6

    return {
        "consensus_pct":       pct,
        "consensus_label":     label,
        "consensus_color":     color,
        "interval_multiplier": mult,
        "factors_agreeing":    [{"key": k, "score": round(v, 1)}
                                for k, v in key_val_pairs if abs(v - avg) < 1.5],
        "factors_conflicting": [{"key": k, "score": round(v, 1)}
                                for k, v in key_val_pairs if abs(v - avg) >= 1.5],
    }


def _confidence_band(days_out: int) -> tuple[float, str]:
    """Return (±base_width, label) for forecast confidence intervals.

    The base width is multiplied by consensus interval_multiplier in score_segment().
    """
    if days_out <= 1: return 1.5, "High"
    if days_out <= 3: return 2.0, "Medium"
    if days_out <= 5: return 2.5, "Low"
    return 3.0, "Outlook"


def _upwelling_score(upwelling_index: float | None, segment: str) -> float:
    """1-10 score from NOAA upwelling index (m³/s/100m, station 33N117W).

    Positive = upwelling (cold water rises nearshore) → unfavorable for pelagic tuna.
    Negative = downwelling (warm water retained)       → favorable for tuna.
    Effect is stronger inshore (upwelling zone) than offshore.
    """
    if upwelling_index is None:
        return 5.0
    ix = upwelling_index
    if segment == "inshore":
        if ix < -100: return 9.5   # strong downwelling — warm, productive
        if ix <    0: return 7.5   # mild downwelling
        if ix <   50: return 5.5   # near-neutral
        if ix <  150: return 3.5   # moderate upwelling — colder nearshore
        return 2.0                  # strong upwelling — cold, poor for tuna
    else:  # offshore — weaker effect (banks are beyond the upwelling zone)
        if ix < -100: return 7.0
        if ix <    0: return 6.0
        if ix <   50: return 5.0
        if ix <  150: return 4.0
        return 3.0


# ─── Ensemble model ───────────────────────────────────────────────────────────

def _monthly_score(conn: sqlite3.Connection, month: int, segment: str) -> float:
    """Historical average top-quartile TPA for this month → 1-10.

    Normalises against the best and worst months in the historical record so
    the model knows "June is historically harder than October."  Weighted at
    15% in score_segment — it's consistently one of the stronger signals.
    """
    try:
        month_str = f"{month:02d}"
        this_m = conn.execute(
            """SELECT AVG(top_quartile_tpa) FROM daily_segment_stats
               WHERE segment=? AND strftime('%m', date)=? AND trip_count>=2""",
            (segment, month_str),
        ).fetchone()[0]
        if this_m is None:
            return 5.0

        all_months = conn.execute(
            """SELECT AVG(top_quartile_tpa) AS avg_tq
               FROM daily_segment_stats
               WHERE segment=? AND trip_count>=2
               GROUP BY strftime('%m', date)""",
            (segment,),
        ).fetchall()
        vals = [r[0] for r in all_months if r[0] is not None]
        if not vals or max(vals) == min(vals):
            return 5.0

        mn, mx = min(vals), max(vals)
        pct = (this_m - mn) / (mx - mn)
        return round(max(1.0, min(10.0, 1.0 + pct * 9.0)), 1)
    except Exception as e:
        log.debug("_monthly_score failed: %s", e)
        return 5.0


def _model_a_score(conditions: dict, segment: str) -> float:
    """Model A — SST Core: SST (57%) + wind direction (24%) + upwelling (19%).

    Uses the three highest-correlation factors from the backtest.
    SST anomaly modifies the SST score as in the full model.
    """
    sst_val     = (conditions.get("sst_nearshore") if segment == "inshore"
                   else conditions.get("sst_offshore"))
    anomaly     = conditions.get("sst_anomaly")
    is_offshore = conditions.get("wind_is_offshore")
    is_upwelling = conditions.get("wind_is_upwelling")
    upwelling_ix = conditions.get("upwelling_index")

    bw             = _load_weights()
    overall_breaks = _breaks_from_weights(bw, "overall_breaks", _OVERALL_BREAKS)

    f_sst = _score(sst_val, overall_breaks) if sst_val is not None else 5.0
    if sst_val is not None and anomaly is not None:
        anom_m = bw.get("anomaly_weight", 1.0)
        f_sst  = float(min(10.0, max(1.0, f_sst + _anomaly_boost(anomaly) * anom_m * 0.4)))

    f_wdir = _wind_direction_score(is_offshore, is_upwelling, segment)
    f_upw  = _upwelling_score(upwelling_ix, segment)

    return round(min(10.0, max(1.0, f_sst * 0.57 + f_wdir * 0.24 + f_upw * 0.19)), 1)


def _model_b_score(
    conn: sqlite3.Connection,
    conditions: dict,
    segment: str,
) -> dict | None:
    """Model B — Historical Pattern: 20 most similar past days, recency-weighted.

    Matches on: same month (±1) + SST ±2°F + same wind direction regime.
    Falls back to ±4°F / drops wind direction when fewer than 5 days match.
    Recency weighting: exp(-days_ago / 365) so recent regime changes matter more.
    Returns percentile-rank of weighted-avg TPA against all segment days → 1-10.
    """
    month      = conditions.get("month", date.today().month)
    sst_val    = (conditions.get("sst_nearshore") if segment == "inshore"
                  else conditions.get("sst_offshore"))
    is_upwelling = conditions.get("wind_is_upwelling")

    if sst_val is None:
        return None

    sst_col = "sst_nearshore" if segment == "inshore" else "sst_offshore"
    adj_months = sorted({
        (month - 2) % 12 + 1, (month - 1) % 12 + 1,
        month,
        month % 12 + 1, (month + 1) % 12 + 1,
    })
    month_ph  = ",".join("?" * len(adj_months))
    month_fmt = [f"{m:02d}" for m in adj_months]

    try:
        def _fetch(sst_lo: float, sst_hi: float, with_wind_dir: bool) -> list[tuple]:
            where = [
                "dss.segment = ?",
                f"hc.{sst_col} BETWEEN ? AND ?",
                f"strftime('%m', dss.date) IN ({month_ph})",
                "dss.trip_count >= 2",
            ]
            params: list = [segment, sst_lo, sst_hi, *month_fmt]
            if with_wind_dir and is_upwelling is not None:
                where.append("hc.wind_is_upwelling = ?")
                params.append(1 if is_upwelling else 0)
            return conn.execute(
                f"SELECT dss.date, dss.avg_tpa FROM daily_segment_stats dss"
                f" JOIN historical_conditions hc ON hc.date = dss.date"
                f" WHERE {' AND '.join(where)}"
                f" ORDER BY ABS(hc.{sst_col} - ?) LIMIT 20",
                [*params, sst_val],
            ).fetchall()

        rows = _fetch(sst_val - 2.0, sst_val + 2.0, with_wind_dir=True)
        if len(rows) < 5:
            rows = _fetch(sst_val - 4.0, sst_val + 4.0, with_wind_dir=False)
        if not rows:
            return None

        today_d = date.today()
        w_sum, w_tot = 0.0, 0.0
        for row_date_str, tpa in rows:
            if tpa is None:
                continue
            try:
                days_ago = max(0, (today_d - date.fromisoformat(row_date_str)).days)
            except Exception:
                days_ago = 365
            w = _math.exp(-days_ago / 365.0)
            w_sum += tpa * w
            w_tot += w

        if w_tot == 0:
            return None

        weighted_tpa = w_sum / w_tot
        all_tpas = sorted(
            r[0] for r in conn.execute(
                "SELECT avg_tpa FROM daily_segment_stats WHERE segment=? AND trip_count>=2",
                (segment,),
            ).fetchall()
            if r[0] is not None
        )
        if not all_tpas:
            return None

        pct   = sum(1 for v in all_tpas if v <= weighted_tpa) / len(all_tpas)
        score = round(max(1.0, min(10.0, 1.0 + pct * 9.0)), 1)
        return {"score": score, "n_days": len(rows)}

    except Exception as e:
        log.debug("_model_b_score failed: %s", e)
        return None


def score_ensemble(
    conn: sqlite3.Connection,
    conditions: dict,
    segment: str,
    days_out: int = 0,
) -> dict:
    """Three-model weighted ensemble with std-dev confidence.

    Model A — SST Core (40%): SST + wind direction + upwelling
    Model B — Historical Pattern (35%): 20 similar past days, recency-weighted
    Model C — Full Model (25%): all 9 weighted factors via score_segment()

    Weights are fixed per spec — A highest because SST/wind direction are the
    strongest correlating factors; B high because historical reality anchors
    the score; C lowest because additional factors add noise.

    When B is unavailable, A/C weights are rescaled proportionally.
    Confidence is the std dev of [A, B, C]: low std → High, high std → Uncertain.
    """
    a_score = _model_a_score(conditions, segment)

    b_result = _model_b_score(conn, conditions, segment)
    b_score  = b_result["score"]  if b_result else None
    b_n_days = b_result["n_days"] if b_result else 0

    c_result = score_segment(segment, conditions, days_out=days_out)
    c_score  = c_result.get("overall_score")

    # Weighted average — redistribute B weight when unavailable
    if b_score is not None:
        ensemble = a_score * 0.40 + b_score * 0.35 + c_score * 0.25
    else:
        ensemble = a_score * (0.40 / 0.65) + c_score * (0.25 / 0.65)
    ensemble = round(min(10.0, max(1.0, ensemble)), 1)

    # Std dev confidence
    scores_for_std = [s for s in [a_score, b_score, c_score] if s is not None]
    if len(scores_for_std) >= 2:
        mean = sum(scores_for_std) / len(scores_for_std)
        std  = _math.sqrt(sum((s - mean) ** 2 for s in scores_for_std) / len(scores_for_std))
    else:
        std = 0.0
    std = round(std, 2)

    good_n       = sum(1 for s in scores_for_std if s >= 5.5)
    all_same_dir = good_n == len(scores_for_std) or good_n == 0

    if std <= 0.7 and all_same_dir:
        conf, conf_color = "High",      "#10B981"
        note = "All models agree — strong signal."
    elif std <= 1.5 or all_same_dir:
        conf, conf_color = "Moderate",  "#FBBF24"
        note = ("Models mostly agree." if all_same_dir
                else "Some model disagreement — moderate confidence.")
    else:
        conf, conf_color = "Uncertain", "#EF4444"
        note = "Models conflict — treat this forecast with caution."

    return {
        "ensemble_score":   ensemble,
        "std_dev":          std,
        "confidence":       conf,
        "confidence_color": conf_color,
        "note":             note,
        "direction":        "good" if ensemble >= 5.5 else "slow",
        "all_agree":        std <= 0.7 and all_same_dir,
        "models": {
            "A": {
                "score":       a_score,
                "weight":      0.40,
                "label":       "SST Core",
                "description": "SST + wind direction + upwelling",
            },
            "B": {
                "score":       b_score,
                "weight":      0.35,
                "n_days":      b_n_days,
                "label":       "Historical Match",
                "description": f"{b_n_days} similar past days" if b_n_days else "insufficient data",
            },
            "C": {
                "score":       c_score,
                "weight":      0.25,
                "label":       "Full Model",
                "description": "All 9 weighted factors",
            },
        },
        "segment_detail": c_result,
    }


def _load_segment_factor_weights(segment: str, season: str) -> dict[str, float]:
    """Convert segment+season weight multipliers into normalized weights summing to 1.0."""
    sw = load_segment_weights(segment, season)
    if not sw:
        sw = load_segment_weights(segment, "overall")

    sst_m     = max(0.05, sw.get("sst_weight",          1.0))
    # Moon backtested at r=0.019 offshore / r=0.053 inshore — near noise.
    # Cap at 2% so it stays visible in the UI but doesn't move the score.
    moon_m    = min(0.02, max(0.005, sw.get("moon_weight", 0.02)))
    wind_m    = max(0.05, sw.get("wind_weight",          0.3))
    wdir_m    = max(0.05, sw.get("wind_offshore_weight", 0.2))
    grad_m    = max(0.05, sw.get("sst_gradient_weight",  0.15))
    chl_m     = max(0.02, sw.get("chl_weight",           0.1))
    swell_m   = _SWELL_DEFAULT
    upw_m     = min(0.15, max(0.02, sw.get("upwelling_weight", 0.05)))
    monthly_m = 0.15   # fixed 15% — historical monthly baseline is a strong signal

    total = sst_m + moon_m + wind_m + wdir_m + grad_m + chl_m + swell_m + upw_m + monthly_m
    return {
        "sst":         round(sst_m     / total, 4),
        "wind_speed":  round(wind_m    / total, 4),
        "wind_dir":    round(wdir_m    / total, 4),
        "gradient":    round(grad_m    / total, 4),
        "chlorophyll": round(chl_m     / total, 4),
        "moon":        round(moon_m    / total, 4),
        "swell":       round(swell_m   / total, 4),
        "upwelling":   round(upw_m     / total, 4),
        "monthly":     round(monthly_m / total, 4),
    }


def score_segment(
    segment: str,
    conditions: dict,
    season: str | None = None,
    days_out: int = 0,
) -> dict:
    """Full weighted score for one segment (inshore or offshore).

    conditions keys (all optional, neutral fallback applied):
      sst_nearshore, sst_offshore, sst_anomaly, sst_gradient,
      wind_speed, wind_is_offshore, wind_is_upwelling, wind_direction,
      swell_height, moon_illum, chlorophyll_nearshore, chlorophyll_offshore.

    days_out: 0=today, …7 — widens confidence interval per day.
    """
    month = conditions.get("month", date.today().month)
    if season is None:
        season = get_season(month)

    w = _load_segment_factor_weights(segment, season)
    sw = load_segment_weights(segment, season) or load_segment_weights(segment, "overall") or {}

    # Segment-appropriate primary SST
    sst_val = (conditions.get("sst_nearshore") if segment == "inshore"
               else conditions.get("sst_offshore"))
    anomaly = conditions.get("sst_anomaly")

    bw = _load_weights()
    overall_breaks = _breaks_from_weights(bw, "overall_breaks", _OVERALL_BREAKS)

    f_sst    = _score(sst_val, overall_breaks) if sst_val is not None else 5.0
    anom_m   = sw.get("anomaly_weight", bw.get("anomaly_weight", 1.0))
    anom_mod = _anomaly_boost(anomaly) * (anom_m * 0.4)
    f_sst_adj = round(min(10.0, max(1.0, f_sst + anom_mod)), 1)

    # Wind direction classification — use pre-computed flags or compute from degrees
    is_offshore  = conditions.get("wind_is_offshore")
    is_upwelling = conditions.get("wind_is_upwelling")
    if is_offshore is None and is_upwelling is None:
        _, is_offshore, is_upwelling = _classify_wind(conditions.get("wind_direction"))

    f_moon    = _moon_score(conditions.get("moon_illum"))
    f_wind    = _wind_score(conditions.get("wind_speed"))
    f_swe     = _swell_score(conditions.get("swell_height"))
    f_wdir    = _wind_direction_score(is_offshore, is_upwelling, segment)
    f_grad    = _sst_gradient_score(conditions.get("sst_gradient"), segment)
    f_chl     = score_chlorophyll(
                    conditions.get("chlorophyll_nearshore"),
                    conditions.get("chlorophyll_offshore"),
                    segment,
                )
    f_upw     = _upwelling_score(conditions.get("upwelling_index"), segment)
    # Monthly baseline: pre-computed from daily_segment_stats and passed in conditions.
    # Defaults to 5.0 (neutral) when not present — callers should pass monthly_score.
    f_monthly = float(conditions.get("monthly_score", 5.0))

    total_score = (
        f_sst_adj * w["sst"]     +
        f_moon    * w["moon"]    +
        f_wind    * w["wind_speed"] +
        f_swe     * w["swell"]   +
        f_wdir    * w["wind_dir"] +
        f_grad    * w["gradient"] +
        f_chl     * w["chlorophyll"] +
        f_upw     * w["upwelling"] +
        f_monthly * w["monthly"]
    )
    overall = round(min(10.0, max(1.0, total_score)), 1)

    fs = {
        "sst":          f_sst_adj,
        "wind_speed":   round(f_wind, 1),
        "wind_dir":     round(f_wdir, 1),
        "sst_gradient": round(f_grad, 1),
        "chlorophyll":  round(f_chl, 1),
        "moon":         round(f_moon, 1),
        "swell":        round(f_swe, 1),
        "upwelling":    round(f_upw, 1),
        "monthly":      round(f_monthly, 1),
    }
    consensus        = calculate_consensus(fs, segment)
    ci_width, ci_label = _confidence_band(days_out)
    adj_width        = round(ci_width * consensus["interval_multiplier"], 1)

    return {
        "overall_score":    overall,
        "conditions_label": _conditions_label(overall),
        "score_low":        round(max(1.0, overall - adj_width), 1),
        "score_high":       round(min(10.0, overall + adj_width), 1),
        "confidence":       ci_label,
        "consensus":        consensus,
        "season":           season,
        "segment":          segment,
        "factor_scores":    fs,
        "factor_weights":   w,
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
    w = {**_load_factor_weights(), **(weight_overrides or {})}

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

    # Anomaly nudges SST factor; scale by calibrated anomaly_weight (baseline 1.0 → ±0.4 pts)
    anom_mod = _anomaly_boost(anomaly) * (bw.get("anomaly_weight", 1.0) * 0.4)
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

    # ── Today's weather data + extended conditions ────────────────────────────
    today_wx: dict = {}
    today_hc: dict = {}  # full historical_conditions row for dual model
    if weather_forecast:
        today_wx = next((w for w in weather_forecast if w["date"] == today_str), {})
    # Fall back to historical_conditions for today/yesterday
    try:
        hc = conn.execute(
            "SELECT * FROM historical_conditions WHERE date IN (?,?) ORDER BY date DESC LIMIT 1",
            (today_str, (today - timedelta(days=1)).isoformat()),
        ).fetchone()
        if hc:
            today_hc = dict(hc)
            if not today_wx:
                today_wx = {
                    "wind_speed":     hc["wind_speed"],
                    "wind_direction": hc["wind_direction"],
                    "swell_height":   hc["swell_height"],
                    "swell_period":   hc["swell_period"],
                    "pressure":       hc["pressure"],
                    "pressure_trend": hc["pressure_trend"],
                }
                if today_wx.get("swell_height") is not None:
                    today_wx["swell_height"] = round(today_wx["swell_height"] * 3.28084, 1)
    except Exception:
        pass

    # ── Moon ─────────────────────────────────────────────────────────────────
    moon = moon_info(datetime(today.year, today.month, today.day, tzinfo=timezone.utc))

    # ── Live SST gradient (fallback when historical_conditions has no value) ──
    live_gradient: float | None = None
    sst_60   = sst_by_loc.get("60-Mile Bank") or sst_by_loc.get("9-Mile Bank")
    sst_near = sst_by_loc.get("Nearshore")
    if sst_60 is not None and sst_near is not None:
        live_gradient = round(abs(sst_60 - sst_near), 2)
    sst_gradient_val = today_hc.get("sst_gradient") or live_gradient

    # ── 7-day rolling avg SST — for projecting future days ───────────────────
    rolling_sst: dict[str, float | None] = {}
    for loc in ["Nearshore", "9-Mile Bank", "60-Mile Bank"]:
        row = conn.execute(
            "SELECT AVG(sst_fahrenheit) FROM ocean_temps"
            " WHERE location=? AND date >= date('now', '-7 days')",
            (loc,),
        ).fetchone()
        rolling_sst[loc] = (row[0] if row and row[0] else sst_by_loc.get(loc))

    # ── Monthly baseline scores (pre-computed; passed per-segment) ────────────
    monthly_cache: dict[tuple, float] = {}
    for d_offset in range(7):
        d_m = (today + timedelta(days=d_offset)).month
        for seg in ("inshore", "offshore"):
            key = (d_m, seg)
            if key not in monthly_cache:
                monthly_cache[key] = _monthly_score(conn, d_m, seg)

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

    # ── Upwelling — fetch before 7-day strip (used in segment conditions) ──────
    upwelling_row: dict = {}
    try:
        upwelling_row = fetch_recent_upwelling(conn) or {}
    except Exception:
        pass

    # ── 7-day strip (offshore score_segment + legacy species scores) ─────────
    # Uses score_segment(offshore) instead of score_day for richer factor set.
    # Days 0-1: actual SST. Days 2+: 7-day rolling avg SST (flagged in payload).
    # Species scores from legacy score_day for backward-compat with SpeciesGrid.
    wx_by_date = {w["date"]: w for w in (weather_forecast or [])}
    seven_day: list[dict] = []
    for i in range(7):
        d     = today + timedelta(days=i)
        d_str = d.isoformat()
        wx    = wx_by_date.get(d_str, {})
        dmoon = moon_info(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))
        use_actual = i <= 1
        day_sst_off  = primary_sst if use_actual else rolling_sst.get("60-Mile Bank")
        day_sst_near = sst_by_loc.get("Nearshore") if use_actual else rolling_sst.get("Nearshore")
        day_grad = (round(abs((day_sst_off or 0) - (day_sst_near or 0)), 2)
                    if day_sst_off and day_sst_near else sst_gradient_val)
        day_cond = {
            "month":               d.month,
            "sst_nearshore":       day_sst_near,
            "sst_offshore":        day_sst_off,
            "sst_anomaly":         primary_anom if use_actual else None,
            "sst_gradient":        day_grad,
            "wind_speed":          wx.get("wind_speed"),
            "wind_direction":      wx.get("wind_direction"),
            "swell_height":        wx.get("swell_height"),
            "moon_illum":          dmoon.illum,
            "chlorophyll_nearshore": today_hc.get("chlorophyll_nearshore"),
            "chlorophyll_offshore":  today_hc.get("chlorophyll_offshore"),
            "upwelling_index":     upwelling_row.get("upwelling_index"),
            "monthly_score":       monthly_cache.get((d.month, "offshore"), 5.0),
        }
        ds = score_segment("offshore", day_cond, days_out=i)
        # Species scores — legacy score_day (for SpeciesGrid backward compat)
        sp = score_day(
            sst_f=day_sst_off or day_sst_near,
            moon_illum=dmoon.illum,
            wind_speed=wx.get("wind_speed"),
            swell_height_ft=wx.get("swell_height"),
            pressure_trend=wx.get("pressure_trend"),
            anomaly=primary_anom if use_actual else None,
            historical_val=hist_val,
        )
        seven_day.append({
            "date":            d_str,
            "dayName":         d.strftime("%a"),
            **ds,
            "bluefin_score":   sp.get("bluefin_score"),
            "yellowfin_score": sp.get("yellowfin_score"),
            "yellowtail_score":sp.get("yellowtail_score"),
            "dorado_score":    sp.get("dorado_score"),
            "sst":             day_sst_off,
            "sst_source":      "actual" if use_actual else "rolling_avg",
            "wind_speed":      wx.get("wind_speed"),
            "swell_height":    wx.get("swell_height"),
            "moon_phase":      dmoon.illum,
            "moon_phase_name": dmoon.phase,
        })

    # ── Historical match ──────────────────────────────────────────────────────
    hist_match = _historical_match(conn, month, primary_sst, moon.illum)

    # ── Accuracy ──────────────────────────────────────────────────────────────
    accuracy = _accuracy_stats(conn)

    # ── Dual segment forecast ──────────────────────────────────────────────────
    base_conditions = {
        "month":               month,
        "sst_nearshore":       sst_by_loc.get("Nearshore"),
        "sst_offshore":        primary_sst,
        "sst_anomaly":         primary_anom,
        "wind_speed":          today_wx.get("wind_speed"),
        "wind_direction":      today_wx.get("wind_direction"),
        "wind_is_offshore":    today_hc.get("wind_is_offshore"),
        "wind_is_upwelling":   today_hc.get("wind_is_upwelling"),
        "swell_height":        today_wx.get("swell_height"),
        "moon_illum":          moon.illum,
        "sst_gradient":        sst_gradient_val,
        "chlorophyll_nearshore": today_hc.get("chlorophyll_nearshore"),
        "chlorophyll_offshore":  today_hc.get("chlorophyll_offshore"),
        "upwelling_index":     upwelling_row.get("upwelling_index"),
    }

    segment_today: dict[str, dict] = {}
    ensemble_by_seg: dict[str, dict] = {}
    for seg in ("inshore", "offshore"):
        try:
            seg_cond = {**base_conditions, "monthly_score": monthly_cache.get((month, seg), 5.0)}
            ens = score_ensemble(conn, seg_cond, seg, days_out=0)
            ensemble_by_seg[seg] = ens
            segment_today[seg]   = ens.get("segment_detail", {})
        except Exception as e:
            log.debug("score_ensemble %s failed: %s", seg, e)
            segment_today[seg]   = {}
            ensemble_by_seg[seg] = {}

    # Store today's ensemble scores for monitoring
    try:
        now_str = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for seg, ens in ensemble_by_seg.items():
            if ens and ens.get("ensemble_score") is not None:
                m = ens.get("models", {})
                conn.execute(
                    """INSERT OR REPLACE INTO forecast_scores
                       (date, segment, model_a, model_b, model_c, ensemble,
                        std_dev, confidence, n_days_b, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        today_str, seg,
                        m.get("A", {}).get("score"),
                        m.get("B", {}).get("score"),
                        m.get("C", {}).get("score"),
                        ens["ensemble_score"],
                        ens.get("std_dev"),
                        ens.get("confidence"),
                        m.get("B", {}).get("n_days", 0),
                        now_str,
                    ),
                )
    except Exception as e:
        log.debug("forecast_scores insert failed: %s", e)

    # Dual 7-day strip — rolling SST + per-segment monthly baseline
    segment_seven_day: dict[str, list] = {"inshore": [], "offshore": []}
    for i in range(7):
        d          = today + timedelta(days=i)
        wx         = wx_by_date.get(d.isoformat(), {})
        dmoon      = moon_info(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))
        use_actual = i <= 1
        d_sst_off  = primary_sst if use_actual else rolling_sst.get("60-Mile Bank")
        d_sst_near = sst_by_loc.get("Nearshore") if use_actual else rolling_sst.get("Nearshore")
        d_grad     = (round(abs((d_sst_off or 0) - (d_sst_near or 0)), 2)
                      if d_sst_off and d_sst_near else sst_gradient_val)
        for seg in ("inshore", "offshore"):
            try:
                seg_cond = {
                    "month":               d.month,
                    "sst_nearshore":       d_sst_near,
                    "sst_offshore":        d_sst_off,
                    "sst_anomaly":         primary_anom if use_actual else None,
                    "sst_gradient":        d_grad,
                    "wind_speed":          wx.get("wind_speed"),
                    "wind_direction":      wx.get("wind_direction"),
                    "swell_height":        wx.get("swell_height"),
                    "moon_illum":          dmoon.illum,
                    "chlorophyll_nearshore": today_hc.get("chlorophyll_nearshore"),
                    "chlorophyll_offshore":  today_hc.get("chlorophyll_offshore"),
                    "upwelling_index":     upwelling_row.get("upwelling_index"),
                    "monthly_score":       monthly_cache.get((d.month, seg), 5.0),
                }
                seg_score = score_segment(seg, seg_cond, days_out=i)
                segment_seven_day[seg].append({
                    "date":       d.isoformat(),
                    "dayName":    d.strftime("%a"),
                    **seg_score,
                    "sst_source": "actual" if use_actual else "rolling_avg",
                })
            except Exception as e:
                log.debug("score_segment %s day %s failed: %s", seg, i, e)

    # Upwelling label for frontend display
    upw_ix = upwelling_row.get("upwelling_index")
    if upw_ix is None:
        upwelling_label = None
    elif upw_ix < -100:
        upwelling_label = "Strong Downwelling"
    elif upw_ix < 0:
        upwelling_label = "Mild Downwelling"
    elif upw_ix < 50:
        upwelling_label = "Near Neutral"
    elif upw_ix < 150:
        upwelling_label = "Moderate Upwelling"
    else:
        upwelling_label = "Strong Upwelling"

    return {
        "today":           today_out,
        "sevenDay":        seven_day,
        "accuracy":        accuracy,
        "historicalMatch": hist_match,
        "ensemble":        ensemble_by_seg,
        "upwelling": {
            "index":       upw_ix,
            "label":       upwelling_label,
            "is_favorable": upwelling_row.get("upwelling_is_favorable"),
            "date":        upwelling_row.get("date"),
        },
        "inshore":         {
            "today":    segment_today.get("inshore", {}),
            "sevenDay": segment_seven_day["inshore"],
        },
        "offshore": {
            "today":    segment_today.get("offshore", {}),
            "sevenDay": segment_seven_day["offshore"],
        },
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
