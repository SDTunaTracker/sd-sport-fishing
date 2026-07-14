"""Single source of truth for mapping a trip to its fishing-window conditions.

The trips table stores `date` as the landing / return date -- the day the boat
posted its catch, not the day it fished. For overnight+ trips those differ.
This module reconstructs the departure date and averages historical_conditions
over the fishing window so downstream code can join a trip to the conditions
it was actually caught under.

Both backtest.py (offline weight calibration) and the corrected V1 offshore
representation call the SAME helpers here. When the live forecaster is
eventually wired to the corrected representation, it will call these too, so
live scoring can no longer drift from calibrated weights.

── Date-shift semantics ──
Match the SQL that backtest._get_daily_tpa has been running since the corpus
was calibrated:

    dep_date  = date(t.date, '-' || CAST(ROUND(trip_length_days - 1) AS INTEGER) || ' days')
    n_days    = CAST(ROUND(trip_length_days) AS INTEGER)   (min 1)

SQLite's ROUND ties AWAY from zero (ROUND(0.5) == 1). Python's built-in
round() uses banker's rounding (round(0.5) == 0). Any Python-side computation
that needs to stay in sync MUST use sql_round() below -- do not use round().

Concrete examples for our trip length buckets:
    0.75-day: shift = ROUND(-0.25) = 0   dep = filed        span = ROUND(0.75) = 1
    1.0 -day: shift = ROUND( 0.00) = 0   dep = filed        span = ROUND(1.00) = 1
    1.5 -day: shift = ROUND( 0.50) = 1   dep = filed - 1d   span = ROUND(1.50) = 2
    2.0 -day: shift = ROUND( 1.00) = 1   dep = filed - 1d   span = ROUND(2.00) = 2
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Iterable


# ── SQL fragments -- interpolate into SELECT / WHERE clauses ──────────────────
# Callers use these instead of copy-pasting the shift math into every query.
DEP_DATE_SQL  = ("date(date, '-' || CAST(ROUND(trip_length_days - 1) "
                 "AS INTEGER) || ' days')")
SPAN_DAYS_SQL = "CAST(ROUND(trip_length_days) AS INTEGER)"


def sql_round(x: float) -> int:
    """SQLite ROUND: ties away from zero.

    Do NOT use Python's built-in round() here -- it rounds ties to even
    (round(0.5) == 0), which would silently drift from the SQL that has been
    running against the DB.
    """
    if x >= 0:
        return int(math.floor(x + 0.5))
    return -int(math.floor(-x + 0.5))


def departure_date(filed_date: date, trip_length_days: float) -> date:
    """Reconstruct the fishing-start (departure) date from the landing-stamped
    return date. Matches the SQL used by backtest._get_daily_tpa."""
    shift = max(0, sql_round(trip_length_days - 1))
    return filed_date - timedelta(days=shift)


def span_days(trip_length_days: float) -> int:
    """Number of fishing days to average conditions over. Minimum 1.
    Matches the n_days argument backtest._get_daily_tpa passes to
    _avg_conditions."""
    return max(1, sql_round(trip_length_days))


def averaged_conditions(
    hc_by_date: dict,
    dep_date: date,
    n_days: int,
    numeric_cols: Iterable[str],
    passthrough_cols: Iterable[str] = ("moon_phase_name",),
) -> dict | None:
    """Average historical_conditions rows over n_days starting from dep_date.

    Returns None when no conditions rows exist for any day in the window.
    Numeric columns are averaged over the days that have a non-null value.
    Passthrough columns (e.g. moon_phase_name) are taken from the first day
    of the window.

    This is the canonical implementation. backtest._avg_conditions and
    backtest._avg_conditions_extended are thin wrappers that supply the
    appropriate column list.
    """
    rows = [hc_by_date.get((dep_date + timedelta(days=i)).isoformat())
            for i in range(max(n_days, 1))]
    rows = [r for r in rows if r]
    if not rows:
        return None
    out: dict = {}
    for col in numeric_cols:
        vals = [r[col] for r in rows if r.get(col) is not None]
        out[col] = round(sum(vals) / len(vals), 4) if vals else None
    for col in passthrough_cols:
        out[col] = rows[0].get(col)
    return out
