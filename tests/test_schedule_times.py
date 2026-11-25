"""Schedule times: one format (ISO 8601 with a Pacific offset) for every
landing, and H&M return times from the trip's real duration."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone

import pytest

from src import db as D
from src import schedule as S
from src.dates import to_pacific_iso


@pytest.mark.parametrize("value, expected", [
    # Naive = Pacific wall clock (fishingreservations.net pages).
    ("2026-11-27T11:00:00", "2026-11-27T11:00:00-08:00"),
    ("2026-07-04T05:30:00", "2026-07-04T05:30:00-07:00"),
    # H&M/Xola UTC: 04:00Z on Nov 28 is 8 PM Nov 27 in San Diego.
    ("2026-11-28T04:00:00+00:00", "2026-11-27T20:00:00-08:00"),
    ("2026-11-28T04:00:00.000Z", "2026-11-27T20:00:00-08:00"),
    # Fall back, 2026-11-01: 01:30 happens twice.
    ("2026-11-01T08:30:00Z", "2026-11-01T01:30:00-07:00"),
    ("2026-11-01T09:30:00Z", "2026-11-01T01:30:00-08:00"),
    # Spring forward, 2026-03-08: 01:59 PST, then 03:00 PDT.
    ("2026-03-08T09:59:00Z", "2026-03-08T01:59:00-08:00"),
    ("2026-03-08T10:00:00Z", "2026-03-08T03:00:00-07:00"),
    # Already normalized: unchanged.
    ("2026-11-27T20:00:00-08:00", "2026-11-27T20:00:00-08:00"),
    (None, None),
])
def test_to_pacific_iso(value, expected):
    assert to_pacific_iso(value) == expected


def _xola(trips, exps):
    return "/**/ typeof cb === 'function' && cb(" + json.dumps({"trips": trips, "experiences": exps}) + ");"


def _trip(exp_id, dt):
    return {"expId": exp_id, "datetime": dt, "price": 100, "open_spots": 10, "reserved_spots": 5}


@pytest.fixture
def frozen_today(monkeypatch):
    monkeypatch.setattr(S, "pacific_today", lambda: date(2026, 10, 1))


def test_hm_full_day_return_uses_duration(frozen_today):
    body = _xola([_trip("fd", "2026-11-28T15:30:00.000Z")],
                 {"fd": {"name": "Malihini - Full Day - Offshore", "duration": 570}})
    (row,) = S.parse_xola_jsonp(body, "H&M Landing", "x")
    assert row["departure_at"] == "2026-11-28T07:30:00-08:00"
    assert row["return_at"] == "2026-11-28T17:00:00-08:00"      # 9.5 h, not 18 h
    assert row["source_id"] == "fd@2026-11-28T15:30:00+00:00"   # unchanged key


def test_hm_evening_departure_keeps_local_date(frozen_today):
    body = _xola([_trip("on", "2026-11-28T04:00:00.000Z")],
                 {"on": {"name": "Producer - Overnight - Offshore", "duration": 1320}})
    (row,) = S.parse_xola_jsonp(body, "H&M Landing", "x")
    assert row["departure_at"].startswith("2026-11-27T20:00")
    assert row["return_at"] == "2026-11-28T18:00:00-08:00"


def test_hm_return_across_dst_boundary(frozen_today):
    # Leaves 8 PM PDT Oct 31, 22 h trip, clocks fall back overnight.
    body = _xola([_trip("on", "2026-11-01T03:00:00.000Z")],
                 {"on": {"name": "Producer - Overnight - Offshore", "duration": 1320}})
    (row,) = S.parse_xola_jsonp(body, "H&M Landing", "x")
    assert row["departure_at"] == "2026-10-31T20:00:00-07:00"
    assert row["return_at"] == "2026-11-01T17:00:00-08:00"


def test_hm_without_duration_leaves_return_empty(frozen_today):
    body = _xola([_trip("x", "2026-11-28T15:30:00.000Z")],
                 {"x": {"name": "Malihini - Full Day - Offshore"}})
    (row,) = S.parse_xola_jsonp(body, "H&M Landing", "x")
    assert row["return_at"] is None


_REQ = {"trip_type_raw": "Full Day", "trip_length": "Full Day", "trip_length_days": 0.75,
        "source_url": "x", "scraped_at": "2026-11-25T00:00:00+00:00"}


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(D.SCHEMA)
    D._migrate(conn)
    return conn


def test_stored_rows_are_normalized_once():
    conn = _conn()
    base = {**{k: None for k in D.SCHEDULED_FIELDS}, **_REQ}
    rows = [
        {**base, "landing": "Seaforth Sportfishing", "boat": "A", "source_id": "1",
         "departure_at": "2026-11-27T11:00:00", "return_at": "2026-11-27T21:00:00"},
        {**base, "landing": "H&M Landing", "boat": "B", "source_id": "2",
         "departure_at": "2026-11-28T04:00:00+00:00", "return_at": None},
    ]
    cols = ",".join(D.SCHEDULED_FIELDS)
    conn.executemany(f"INSERT INTO scheduled_trips ({cols}) VALUES ({','.join('?' * len(D.SCHEDULED_FIELDS))})",
                     [tuple(r[k] for k in D.SCHEDULED_FIELDS) for r in rows])
    assert D.normalize_schedule_times(conn) == 2
    got = conn.execute("SELECT departure_at, return_at FROM scheduled_trips ORDER BY boat").fetchall()
    assert [tuple(r) for r in got] == [
        ("2026-11-27T11:00:00-08:00", "2026-11-27T21:00:00-08:00"),
        ("2026-11-27T20:00:00-08:00", None),
    ]
    assert D.normalize_schedule_times(conn) == 0


def test_replace_scheduled_trips_normalizes_on_insert():
    conn = _conn()
    trip = {**{k: None for k in D.SCHEDULED_FIELDS}, **_REQ}
    trip.update(landing="Point Loma Sportfishing", boat="C", source_id="3",
                departure_at=datetime(2026, 7, 4, 5, 30).isoformat(),
                return_at=datetime(2026, 7, 4, 13, 0, tzinfo=timezone.utc).isoformat())
    D.replace_scheduled_trips(conn, [trip])
    r = conn.execute("SELECT departure_at, return_at FROM scheduled_trips").fetchone()
    assert tuple(r) == ("2026-07-04T05:30:00-07:00", "2026-07-04T06:00:00-07:00")
