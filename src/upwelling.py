"""Fetch NOAA upwelling index for the San Diego region (33°N 117°W).

Source: NOAA ERDDAP tabledap dataset 'erdUI456hr'
  https://coastwatch.pfeg.noaa.gov/erddap/tabledap/erdUI456hr
  6-hourly observations, aggregated to daily mean.
  Coverage: 2015-01-01 to present (~2 day lag).

Positive index = upwelling  (cold, nutrient-rich water rising) → bad for offshore tuna.
Negative index = downwelling (warm water retained)             → good for offshore tuna.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

ERDDAP_TABLEDAP = "https://coastwatch.pfeg.noaa.gov/erddap/tabledap/erdUI456hr.csv"
STATION         = "33N117W"
COVERAGE_START  = date(2015, 1, 1)

_TIMEOUT    = 30.0
_CHUNK_DAYS = 180
_LAG_DAYS   = 2  # NOAA processing lag

# Favorable for pelagic tuna: weak/negative upwelling means warmer water retained.
_FAVORABLE_THRESHOLD = 50.0  # upwelling_index < 50 → favorable

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")


def _fetch_chunk(start: date, end: date) -> dict[str, list[float]]:
    """Fetch 6-hourly upwelling values; returns {date_str: [values]}."""
    url = (
        f"{ERDDAP_TABLEDAP}"
        f"?time,upwelling_index"
        f"&time>={start.isoformat()}T00:00:00Z"
        f"&time<={end.isoformat()}T23:59:59Z"
    )
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=_TIMEOUT)
        if r.status_code != 200:
            log.warning("Upwelling HTTP %s for %s–%s: %s…",
                        r.status_code, start, end, r.text[:120])
            return {}
        by_date: dict[str, list[float]] = {}
        for line in r.text.splitlines()[2:]:  # skip header + units rows
            parts = line.strip().split(",")
            if len(parts) < 2:
                continue
            d_str = parts[0][:10]
            try:
                by_date.setdefault(d_str, []).append(float(parts[1]))
            except (ValueError, IndexError):
                continue
        return by_date
    except Exception as e:
        log.warning("Upwelling fetch error %s–%s: %s", start, end, e)
        return {}


def fetch_upwelling_range(start: date, end: date) -> list[dict]:
    """Fetch and aggregate upwelling to daily means for [start, end]."""
    now = datetime.now(timezone.utc).isoformat()
    records: list[dict] = []
    d = max(start, COVERAGE_START)
    while d <= end:
        chunk_end = min(d + timedelta(days=_CHUNK_DAYS - 1), end)
        by_date = _fetch_chunk(d, chunk_end)
        for d_str, vals in sorted(by_date.items()):
            avg = round(sum(vals) / len(vals), 3)
            records.append({
                "date":                   d_str,
                "station":                STATION,
                "upwelling_index":        avg,
                "upwelling_is_favorable": 1 if avg < _FAVORABLE_THRESHOLD else 0,
                "fetched_at":             now,
            })
        d = chunk_end + timedelta(days=1)
    return records


def insert_upwelling(conn, records: list[dict]) -> int:
    if not records:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO upwelling_obs"
        " (date, station, upwelling_index, upwelling_is_favorable, fetched_at)"
        " VALUES (:date, :station, :upwelling_index, :upwelling_is_favorable, :fetched_at)",
        records,
    )
    return len(records)


def backfill_upwelling(db_path: Path, start: date | None = None) -> None:
    """Fetch upwelling from 2015-01-01 to today and store in upwelling_obs."""
    from . import db as dbmod

    end   = date.today() - timedelta(days=_LAG_DAYS)
    start = start or COVERAGE_START
    print(f"Upwelling backfill: {start} to {end}")

    with dbmod.connect(db_path) as conn:
        existing = {r[0] for r in conn.execute(
            "SELECT date FROM upwelling_obs WHERE date BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ).fetchall()}
        records  = fetch_upwelling_range(start, end)
        new_recs = [r for r in records if r["date"] not in existing]
        if new_recs:
            insert_upwelling(conn, new_recs)
        d_min = min(r["date"] for r in records) if records else "—"
        d_max = max(r["date"] for r in records) if records else "—"
        print(f"  {len(records)} days fetched ({d_min} to {d_max}), "
              f"{len(new_recs)} new stored.")


def fetch_recent_upwelling(conn) -> dict | None:
    """Most recent upwelling observation from DB — for daily pipeline."""
    row = conn.execute(
        "SELECT date, upwelling_index, upwelling_is_favorable"
        " FROM upwelling_obs ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def fetch_daily_upwelling(target_date: date) -> dict | None:
    """Fetch today's upwelling value live from ERDDAP (no DB write).

    Used by the daily forecast pipeline when upwelling_obs may not yet have today.
    Returns None if data unavailable.
    """
    lag_start = target_date - timedelta(days=5)
    by_date = _fetch_chunk(lag_start, target_date)
    if not by_date:
        return None
    latest_d = max(by_date.keys())
    vals = by_date[latest_d]
    avg = round(sum(vals) / len(vals), 3)
    return {
        "date":                   latest_d,
        "station":                STATION,
        "upwelling_index":        avg,
        "upwelling_is_favorable": 1 if avg < _FAVORABLE_THRESHOLD else 0,
    }
