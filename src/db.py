"""SQLite schema + insert helpers for trip records.

Schema is intentionally flat: one row per (date, boat, landing, trip_type, anglers).
The UNIQUE constraint lets the daily scraper safely re-run for the same date
(INSERT OR IGNORE) without polluting the table.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    boat TEXT NOT NULL,
    landing TEXT NOT NULL,
    trip_type_raw TEXT,
    trip_length TEXT NOT NULL,
    trip_length_days REAL NOT NULL,
    anglers INTEGER NOT NULL,
    bluefin INTEGER NOT NULL DEFAULT 0,
    yellowfin INTEGER NOT NULL DEFAULT 0,
    yellowtail INTEGER NOT NULL DEFAULT 0,
    dorado INTEGER NOT NULL DEFAULT 0,
    skipjack INTEGER NOT NULL DEFAULT 0,
    bigeye INTEGER NOT NULL DEFAULT 0,
    albacore INTEGER NOT NULL DEFAULT 0,
    trophy_count INTEGER NOT NULL DEFAULT 0,
    trophy_per_angler REAL NOT NULL DEFAULT 0,
    trophy_per_angler_per_day REAL NOT NULL DEFAULT 0,
    other_species_json TEXT NOT NULL DEFAULT '{}',
    moon_phase TEXT,
    moon_illum INTEGER,
    days_from_new REAL,
    days_from_full REAL,
    scraped_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    UNIQUE(date, boat, landing, trip_length, anglers)
);

CREATE INDEX IF NOT EXISTS idx_trips_date    ON trips(date);
CREATE INDEX IF NOT EXISTS idx_trips_landing ON trips(landing);
CREATE INDEX IF NOT EXISTS idx_trips_boat    ON trips(boat);

-- Upcoming open-party trips. Refreshed each daily run by DELETE-then-INSERT
-- since the source is forward-looking and we don't keep historical snapshots.
CREATE TABLE IF NOT EXISTS scheduled_trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    landing TEXT NOT NULL,
    boat TEXT NOT NULL,
    trip_type_raw TEXT NOT NULL,
    trip_length TEXT NOT NULL,
    trip_length_days REAL NOT NULL,
    departure_at TEXT NOT NULL,
    return_at TEXT,
    price REAL,
    capacity INTEGER,
    open_spots INTEGER,
    reserved_spots INTEGER,
    note TEXT,
    source_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    scraped_at TEXT NOT NULL,
    UNIQUE(landing, source_id)
);

CREATE INDEX IF NOT EXISTS idx_sched_departure ON scheduled_trips(departure_at);
CREATE INDEX IF NOT EXISTS idx_sched_landing   ON scheduled_trips(landing);

CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    landing TEXT NOT NULL,
    source_url TEXT NOT NULL,
    target_date TEXT,
    trips_seen INTEGER DEFAULT 0,
    trips_kept INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    error TEXT
);
"""


@contextmanager
def connect(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


# Field order matches the INSERT statement below.
TRIP_FIELDS = (
    "date", "boat", "landing", "trip_type_raw", "trip_length", "trip_length_days",
    "anglers", "bluefin", "yellowfin", "yellowtail", "dorado",
    "skipjack", "bigeye", "albacore",
    "trophy_count", "trophy_per_angler", "trophy_per_angler_per_day",
    "other_species_json", "moon_phase", "moon_illum",
    "days_from_new", "days_from_full", "scraped_at", "source_url",
)


def insert_trips(conn: sqlite3.Connection, trips: Iterable[dict]) -> int:
    """Insert trips, ignoring duplicates on the UNIQUE constraint.
    Returns number of rows actually inserted."""
    placeholders = ",".join("?" * len(TRIP_FIELDS))
    sql = f"INSERT OR IGNORE INTO trips ({','.join(TRIP_FIELDS)}) VALUES ({placeholders})"
    rows = []
    for t in trips:
        rows.append(tuple(
            json.dumps(t[k]) if k == "other_species_json" and not isinstance(t[k], str) else t[k]
            for k in TRIP_FIELDS
        ))
    cur = conn.executemany(sql, rows)
    return cur.rowcount


def log_scrape(conn: sqlite3.Connection, **fields) -> int:
    cols = ",".join(fields.keys())
    placeholders = ",".join("?" * len(fields))
    cur = conn.execute(
        f"INSERT INTO scrape_log ({cols}) VALUES ({placeholders})",
        tuple(fields.values()),
    )
    return cur.lastrowid


def update_scrape_log(conn: sqlite3.Connection, log_id: int, **fields) -> None:
    sets = ",".join(f"{k}=?" for k in fields)
    conn.execute(
        f"UPDATE scrape_log SET {sets} WHERE id=?",
        (*fields.values(), log_id),
    )


SCHEDULED_FIELDS = (
    "landing", "boat", "trip_type_raw", "trip_length", "trip_length_days",
    "departure_at", "return_at", "price", "capacity",
    "open_spots", "reserved_spots", "note",
    "source_id", "source_url", "scraped_at",
)


def replace_scheduled_trips(conn: sqlite3.Connection, trips: Iterable[dict]) -> int:
    """DELETE + INSERT semantics for the scheduled_trips table — schedules are
    snapshots, not history."""
    conn.execute("DELETE FROM scheduled_trips")
    placeholders = ",".join("?" * len(SCHEDULED_FIELDS))
    sql = f"INSERT INTO scheduled_trips ({','.join(SCHEDULED_FIELDS)}) VALUES ({placeholders})"
    rows = [tuple(t.get(k) for k in SCHEDULED_FIELDS) for t in trips]
    cur = conn.executemany(sql, rows)
    return cur.rowcount


def latest_trip_date(conn: sqlite3.Connection) -> date | None:
    row = conn.execute("SELECT MAX(date) AS d FROM trips").fetchone()
    if row and row["d"]:
        return date.fromisoformat(row["d"])
    return None
