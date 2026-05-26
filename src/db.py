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
    rockfish INTEGER DEFAULT 0,
    sheephead INTEGER DEFAULT 0,
    calico_bass INTEGER DEFAULT 0,
    sand_bass INTEGER DEFAULT 0,
    halibut INTEGER DEFAULT 0,
    lingcod INTEGER DEFAULT 0,
    whitefish INTEGER DEFAULT 0,
    bonito INTEGER DEFAULT 0,
    barracuda INTEGER DEFAULT 0,
    other_fish INTEGER DEFAULT 0,
    is_half_day INTEGER DEFAULT 0,
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
    trip_status TEXT,
    target_species TEXT,
    whats_included TEXT,
    source_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    scraped_at TEXT NOT NULL,
    UNIQUE(landing, source_id)
);

CREATE INDEX IF NOT EXISTS idx_sched_departure ON scheduled_trips(departure_at);
CREATE INDEX IF NOT EXISTS idx_sched_landing   ON scheduled_trips(landing);

CREATE TABLE IF NOT EXISTS ocean_temps (
    date TEXT NOT NULL,
    location TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    sst_celsius REAL,
    sst_fahrenheit REAL,
    anomaly REAL,
    PRIMARY KEY (date, location)
);

CREATE INDEX IF NOT EXISTS idx_ocean_temps_date ON ocean_temps(date);

CREATE TABLE IF NOT EXISTS unknown_species (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    species_name TEXT NOT NULL,
    count INTEGER NOT NULL,
    date TEXT NOT NULL,
    boat TEXT NOT NULL,
    landing TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_unknown_species ON unknown_species(species_name);

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

CREATE TABLE IF NOT EXISTS forecast_scores (
    date TEXT PRIMARY KEY,
    overall_score REAL,
    bluefin_score REAL,
    yellowfin_score REAL,
    yellowtail_score REAL,
    dorado_score REAL,
    conditions_label TEXT,
    summary TEXT,
    sst_nearshore REAL,
    sst_offshore REAL,
    anomaly REAL,
    wind_speed REAL,
    swell_height REAL,
    moon_phase REAL,
    moon_phase_name TEXT,
    weights_used TEXT
);

CREATE TABLE IF NOT EXISTS forecast_accuracy_log (
    date TEXT PRIMARY KEY,
    predicted_score REAL,
    actual_tpa REAL,
    actual_rating REAL,
    error REAL,
    correct_direction INTEGER
);
"""


# Columns added after the initial schema — applied at connect time so existing
# databases are silently upgraded without needing a separate migration script.
_NEW_TRIP_COLUMNS = [
    ("rockfish",    "INTEGER DEFAULT 0"),
    ("sheephead",   "INTEGER DEFAULT 0"),
    ("calico_bass", "INTEGER DEFAULT 0"),
    ("sand_bass",   "INTEGER DEFAULT 0"),
    ("halibut",     "INTEGER DEFAULT 0"),
    ("lingcod",     "INTEGER DEFAULT 0"),
    ("whitefish",   "INTEGER DEFAULT 0"),
    ("bonito",      "INTEGER DEFAULT 0"),
    ("barracuda",   "INTEGER DEFAULT 0"),
    ("other_fish",  "INTEGER DEFAULT 0"),
    ("is_half_day", "INTEGER DEFAULT 0"),
]


_NEW_SCHED_COLUMNS = [
    ("trip_status",    "TEXT"),
    ("target_species", "TEXT"),
    ("whats_included", "TEXT"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(trips)").fetchall()}
    for col, defn in _NEW_TRIP_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE trips ADD COLUMN {col} {defn}")
    sched_existing = {row[1] for row in conn.execute("PRAGMA table_info(scheduled_trips)").fetchall()}
    for col, defn in _NEW_SCHED_COLUMNS:
        if col not in sched_existing:
            conn.execute(f"ALTER TABLE scheduled_trips ADD COLUMN {col} {defn}")


@contextmanager
def connect(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # concurrent readers don't block writers
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
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
    "rockfish", "sheephead", "calico_bass", "sand_bass", "halibut",
    "lingcod", "whitefish", "bonito", "barracuda", "other_fish", "is_half_day",
)


def insert_trips(
    conn: sqlite3.Connection,
    trips: Iterable[dict],
    upsert: bool = False,
    upsert_days: int = 3,
) -> int:
    """Insert trips. Returns number of rows actually inserted/replaced.

    upsert=True  — rows dated within the last `upsert_days` days use
                   INSERT OR REPLACE so updated fish counts on a re-scrape
                   overwrite the existing row. Rows older than the cutoff
                   always use INSERT OR IGNORE, protecting historical data
                   from accidental overwrites (e.g. a future parsing bug
                   that misassigns a date).
    upsert=False — INSERT OR IGNORE for all rows (backfill / safe mode).

    Trip dicts may carry a temporary '_unknowns' key — a list of
    (species_name, count) tuples for unrecognized species encountered while
    parsing the fish-count string. These are logged to unknown_species and
    stripped before the trips INSERT.
    """
    from datetime import date as _date, timedelta
    cutoff = (_date.today() - timedelta(days=upsert_days)).isoformat()

    placeholders = ",".join("?" * len(TRIP_FIELDS))
    sql_replace = (f"INSERT OR REPLACE INTO trips ({','.join(TRIP_FIELDS)})"
                   f" VALUES ({placeholders})")
    sql_ignore  = (f"INSERT OR IGNORE  INTO trips ({','.join(TRIP_FIELDS)})"
                   f" VALUES ({placeholders})")

    recent_rows: list[tuple] = []
    old_rows:    list[tuple] = []
    unknown_rows: list[tuple] = []

    for t in trips:
        for species_name, count in t.get("_unknowns", []):
            unknown_rows.append((species_name, count, t["date"], t["boat"], t["landing"]))
        row = tuple(
            json.dumps(t[k]) if k == "other_species_json" and not isinstance(t[k], str) else t[k]
            for k in TRIP_FIELDS
        )
        if upsert and t.get("date", "") >= cutoff:
            recent_rows.append(row)
        else:
            old_rows.append(row)

    inserted = 0
    if recent_rows:
        inserted += conn.executemany(sql_replace, recent_rows).rowcount
    if old_rows:
        inserted += conn.executemany(sql_ignore, old_rows).rowcount

    if unknown_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO unknown_species (species_name, count, date, boat, landing)"
            " VALUES (?,?,?,?,?)",
            unknown_rows,
        )
    return inserted


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
    "trip_status", "target_species", "whats_included",
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


_DAILY_SEGMENT_STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_segment_stats (
  date              TEXT,
  segment           TEXT,
  trip_count        INTEGER,
  avg_tpa           REAL,
  top_quartile_tpa  REAL,
  median_tpa        REAL,
  total_tuna        INTEGER,
  total_anglers     INTEGER,
  bluefin_tpa       REAL,
  yellowfin_tpa     REAL,
  yellowtail_tpa    REAL,
  dorado_tpa        REAL,
  PRIMARY KEY (date, segment)
);
"""


def _percentile(vals: list[float], pct: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    idx = (len(s) - 1) * pct / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def update_daily_segment_stats(
    conn: sqlite3.Connection,
    since_date: str | None = None,
) -> int:
    """Upsert daily_segment_stats for all dates >= since_date (or all dates if None).

    Uses top-quartile TPA as the primary target variable for the dual forecast model.
    Returns number of rows written.
    """
    conn.executescript(_DAILY_SEGMENT_STATS_SCHEMA)

    where = f"WHERE segment IS NOT NULL AND anglers >= 5"
    if since_date:
        where += f" AND date >= '{since_date}'"

    base_rows = conn.execute(f"""
        SELECT date, segment,
               COUNT(*) as trip_count,
               AVG(trophy_per_angler_per_day) as avg_tpa,
               SUM(trophy_count) as total_tuna,
               SUM(anglers) as total_anglers,
               AVG(bluefin   * 1.0 / NULLIF(anglers,0)) as bluefin_tpa,
               AVG(yellowfin * 1.0 / NULLIF(anglers,0)) as yellowfin_tpa,
               AVG(yellowtail* 1.0 / NULLIF(anglers,0)) as yellowtail_tpa,
               AVG(dorado    * 1.0 / NULLIF(anglers,0)) as dorado_tpa
        FROM trips {where}
        GROUP BY date, segment
        HAVING COUNT(*) >= 2
    """).fetchall()

    from collections import defaultdict
    tpa_lists: dict[tuple, list] = defaultdict(list)
    tpa_rows = conn.execute(f"""
        SELECT date, segment, trophy_per_angler_per_day
        FROM trips {where} AND trophy_per_angler_per_day IS NOT NULL
    """).fetchall()
    for r in tpa_rows:
        tpa_lists[(r["date"], r["segment"])].append(r["trophy_per_angler_per_day"])

    insert_rows = []
    for r in base_rows:
        tpas  = tpa_lists.get((r["date"], r["segment"]), [])
        top_q = _percentile(tpas, 75)
        median = _percentile(tpas, 50)
        insert_rows.append((
            r["date"], r["segment"], r["trip_count"], r["avg_tpa"],
            top_q, median, r["total_tuna"], r["total_anglers"],
            r["bluefin_tpa"], r["yellowfin_tpa"], r["yellowtail_tpa"], r["dorado_tpa"],
        ))

    conn.executemany("""
        INSERT OR REPLACE INTO daily_segment_stats
        (date, segment, trip_count, avg_tpa, top_quartile_tpa, median_tpa,
         total_tuna, total_anglers, bluefin_tpa, yellowfin_tpa, yellowtail_tpa, dorado_tpa)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, insert_rows)
    return len(insert_rows)
