"""Fails when any data feed in tracker.db goes stale.

The rules live in src/completeness.py (the same check the daily run alerts
on). The live-DB test skips when tracker.db is absent; the synthetic tests
pin the rules themselves.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from src import completeness as C

TODAY = date(2026, 11, 24)
NOW = datetime(2026, 11, 24, 20, 0, tzinfo=timezone.utc)


def test_live_db_feeds_are_fresh():
    if not C.DB_PATH.exists():
        pytest.skip("tracker.db not present")
    conn = sqlite3.connect(f"file:{C.DB_PATH}?mode=ro", uri=True)
    # Job heartbeats and CAPTCHA blocks are runtime alerts (sent by the daily
    # run); this test is about the stored data itself. A long block still
    # fails here once the schedule data goes stale (schedule:* rule).
    stale = [p for p in C.check(conn) if not p.key.startswith(("job:", "blocked:"))]
    assert not stale, "stale feeds:\n" + "\n".join(f"  {p.feed}: {p.detail}" for p in stale)


def _fresh_db(tmp_path) -> sqlite3.Connection:
    """Minimal tables holding only the columns completeness.check() reads."""
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.executescript("""
        CREATE TABLE scrape_log (started_at TEXT, landing TEXT, status TEXT);
        CREATE TABLE scheduled_trips (landing TEXT, scraped_at TEXT);
        CREATE TABLE trips (date TEXT, landing TEXT);
        CREATE TABLE ocean_temps (date TEXT, location TEXT);
        CREATE TABLE historical_conditions (date TEXT);
        CREATE TABLE upwelling_obs (date TEXT);
        CREATE TABLE daily_segment_stats (date TEXT);
        CREATE TABLE forecast_scores (date TEXT);
        CREATE TABLE forecast_accuracy_log (date TEXT);
    """)
    ts = (NOW - timedelta(hours=1)).isoformat()
    for ln in C.CORE_LANDINGS:
        conn.execute("INSERT INTO scrape_log VALUES (?,?,'ok')", (ts, ln))
        conn.execute("INSERT INTO scheduled_trips VALUES (?,?)", (ln, ts))
    for i in range(1, 31):
        d = (TODAY - timedelta(days=i)).isoformat()
        conn.execute("INSERT INTO trips VALUES (?,?)", (d, C.CORE_LANDINGS[0]))
        for loc in C.SST_LOCATIONS:
            conn.execute("INSERT INTO ocean_temps VALUES (?,?)", (d, loc))
        for t in ("historical_conditions", "daily_segment_stats",
                  "forecast_accuracy_log", "forecast_scores"):
            conn.execute(f"INSERT INTO {t} VALUES (?)", (d,))
    conn.execute("INSERT INTO upwelling_obs VALUES (?)", ((TODAY - timedelta(days=30)).isoformat(),))
    conn.commit()
    return conn


def test_fresh_synthetic_db_passes(tmp_path):
    conn = _fresh_db(tmp_path)
    assert C.check(conn, today=TODAY, now=NOW) == []


@pytest.mark.parametrize("sql,key", [
    ("DELETE FROM historical_conditions WHERE date > '2026-11-19'", "feed:historical_conditions"),
    ("DELETE FROM ocean_temps WHERE location='60-Mile Bank' AND date > '2026-11-14'", "sst:60-Mile Bank"),
    ("DELETE FROM trips WHERE date = '2026-11-20'", "trips:gap"),
    ("UPDATE scrape_log SET started_at='2026-11-20T00:00:00+00:00' WHERE landing='H&M Landing'",
     "scrape:H&M Landing"),
    ("UPDATE scheduled_trips SET scraped_at='2026-11-20T00:00:00+00:00' WHERE landing like 'Seaforth%'",
     "schedule:Seaforth Sportfishing"),
    ("DELETE FROM upwelling_obs", "feed:upwelling_obs"),
])
def test_each_stale_feed_is_flagged(tmp_path, sql, key):
    conn = _fresh_db(tmp_path)
    conn.execute(sql)
    keys = {p.key for p in C.check(conn, today=TODAY, now=NOW)}
    assert key in keys


def test_missed_or_failed_job_is_flagged(tmp_path):
    conn = _fresh_db(tmp_path)
    old = (NOW - timedelta(hours=40)).isoformat()
    status = {"full": {"finished_at": old, "exit_code": 0},
              "hourly": {"finished_at": NOW.isoformat(), "exit_code": 2, "reason": "core"}}
    keys = {p.key for p in C.check(conn, today=TODAY, now=NOW, run_status=status)}
    assert {"job:full", "job:hourly:exit"} <= keys


def test_job_runs_round_trip(tmp_path):
    conn = _fresh_db(tmp_path)
    C.write_run_status(conn, "full", 0)
    C.write_run_status(conn, "full", 2, "core landing(s) failed")
    st = C.load_run_status(conn)
    assert st["full"]["exit_code"] == 2
