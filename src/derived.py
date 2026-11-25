"""Rebuild derived tables for days the scheduled run missed.

forecast.score_yesterday() and backtest.daily_accuracy_update() only ever look
at date.today() - 1, so any day the PC was asleep left a permanent hole in
forecast_accuracy_log. These helpers score an arbitrary past day by running
those same functions with `date.today()` shifted, so the scoring logic stays
in one place (src/forecast.py) and is not duplicated here.

forecast_scores is deliberately NOT rebuilt: each row is the forecast the
site published that day. Recomputing it later would be a hindcast built from
data that did not exist yet, which would make the accuracy history look
better than the live model really was.
"""
from __future__ import annotations

import contextlib
import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)


@contextlib.contextmanager
def _today_is(module, fake_today: date):
    real = module.date

    class _ShiftedDate(real):  # type: ignore[misc, valid-type]
        @classmethod
        def today(cls):
            return fake_today

    module.date = _ShiftedDate
    try:
        yield
    finally:
        module.date = real


def score_accuracy_for(conn, day: date) -> dict | None:
    """Write forecast_accuracy_log for `day` (None when data is insufficient)."""
    from . import forecast
    with _today_is(forecast, day + timedelta(days=1)):
        return forecast.score_yesterday(conn)


def fill_accuracy_gaps(conn, start: date, end: date | None = None) -> list[str]:
    """Score every day in [start, end] that has trips but no accuracy row."""
    end = end or (date.today() - timedelta(days=1))
    have = {r[0] for r in conn.execute(
        "SELECT date FROM forecast_accuracy_log WHERE date BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()))}
    filled: list[str] = []
    d = start
    while d <= end:
        if d.isoformat() not in have:
            try:
                if score_accuracy_for(conn, d):
                    filled.append(d.isoformat())
            except Exception as e:  # noqa: BLE001
                log.warning("accuracy scoring failed for %s: %s", d, e)
        d += timedelta(days=1)
    return filled
