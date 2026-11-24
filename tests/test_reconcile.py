"""reconcile_daily_counts: text-harvested rows that duplicate a structured row."""
from __future__ import annotations

import sqlite3
from datetime import timedelta

from src import db as DB
from src import scrape
from src.dates import pacific_today


def _make_db(tmp_path):
    path = tmp_path / "t.db"
    with DB.connect(path):
        pass
    return str(path)


def _add(path, d, source, trip_length="Full Day", anglers=15, yt=61, boat="Vendetta 2"):
    c = sqlite3.connect(path)
    c.execute(
        """INSERT INTO trips (date, boat, landing, trip_type_raw, trip_length,
               trip_length_days, anglers, bluefin, yellowfin, yellowtail, dorado,
               trophy_count, source, scraped_at, source_url)
           VALUES (?, ?, 'H&M Landing', ?, ?, 0.75, ?, 0, 0, ?, 0, ?, ?,
                   '2026-01-01T00:00:00+00:00', '')""",
        (d.isoformat(), boat, trip_length, trip_length, anglers, yt, yt, source),
    )
    c.commit()
    c.close()


def _sources(path):
    c = sqlite3.connect(path)
    rows = c.execute("SELECT date, source FROM trips ORDER BY date, source").fetchall()
    c.close()
    return rows


def test_next_day_text_copy_with_other_trip_length_is_removed(tmp_path):
    path = _make_db(tmp_path)
    d = pacific_today() - timedelta(days=3)
    _add(path, d, "fish_count_page", trip_length="1.5 Day")
    _add(path, d + timedelta(days=1), "text_fallback", trip_length="Full Day", anglers=0)
    r = scrape.reconcile_daily_counts(path)
    assert r["matched"] == 1
    assert _sources(path) == [(d.isoformat(), "fish_count_page")]


def test_stale_reharvest_of_large_catch_is_removed(tmp_path):
    path = _make_db(tmp_path)
    d = pacific_today() - timedelta(days=12)
    _add(path, d, "fish_count_page")
    _add(path, d + timedelta(days=6), "text_fallback", anglers=0)
    r = scrape.reconcile_daily_counts(path, lookback_days=14)
    assert r["matched"] == 1


def test_small_identical_catch_days_apart_is_kept(tmp_path):
    path = _make_db(tmp_path)
    d = pacific_today() - timedelta(days=6)
    _add(path, d, "fish_count_page", yt=12)
    _add(path, d + timedelta(days=4), "text_fallback", yt=12)
    r = scrape.reconcile_daily_counts(path)
    assert (r["matched"], r["flagged"]) == (0, 1)


def test_different_catch_is_kept(tmp_path):
    path = _make_db(tmp_path)
    d = pacific_today() - timedelta(days=2)
    _add(path, d, "fish_count_page", yt=61)
    _add(path, d + timedelta(days=1), "text_fallback", yt=40)
    r = scrape.reconcile_daily_counts(path)
    assert (r["matched"], r["flagged"]) == (0, 1)


def test_full_history_pass_runs_once(tmp_path):
    path = _make_db(tmp_path)
    old = pacific_today() - timedelta(days=120)
    _add(path, old, "fish_count_page")
    _add(path, old + timedelta(days=5), "text_fallback", anglers=0)
    first = scrape.reconcile_daily_counts(path)
    assert first["full_history"] is True
    assert first["matched"] == 1  # 120 days back, outside the 7-day window

    _add(path, old + timedelta(days=6), "text_fallback", anglers=0)
    second = scrape.reconcile_daily_counts(path)
    assert second["full_history"] is False
    assert second["matched"] == 0  # back to the 7-day window
