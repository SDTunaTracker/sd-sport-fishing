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
    region TEXT DEFAULT 'san_diego',
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

CREATE TABLE IF NOT EXISTS forecast_accuracy_log (
    date TEXT PRIMARY KEY,
    predicted_score REAL,
    actual_tpa REAL,
    actual_rating REAL,
    error REAL,
    correct_direction INTEGER
);

CREATE TABLE IF NOT EXISTS reddit_reports (
    id TEXT PRIMARY KEY,
    title TEXT,
    url TEXT,
    subreddit TEXT,
    score INTEGER,
    num_comments INTEGER,
    created_utc INTEGER,
    author TEXT,
    snippet TEXT,
    search_term TEXT,
    boat_mentioned TEXT,
    fetched_date TEXT
);

CREATE TABLE IF NOT EXISTS reddit_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reddit_post_id TEXT UNIQUE,
    processed_date TEXT,
    species_mentioned TEXT,
    species_sentiment TEXT,
    locations_mentioned TEXT,
    primary_location TEXT,
    bait_mentioned TEXT,
    lures_mentioned TEXT,
    techniques TEXT,
    boats_mentioned TEXT,
    boat_sentiment TEXT,
    report_quality INTEGER,
    report_date TEXT,
    confidence TEXT,
    summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_insights_date ON reddit_insights(processed_date);
CREATE INDEX IF NOT EXISTS idx_insights_post  ON reddit_insights(reddit_post_id);

CREATE TABLE IF NOT EXISTS weekly_summaries (
    week_start TEXT PRIMARY KEY,
    week_end TEXT,
    summary_text TEXT,
    top_species TEXT,
    top_location TEXT,
    community_mood TEXT,
    report_count INTEGER,
    generated_at TEXT
);

CREATE TABLE IF NOT EXISTS boat_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    boat TEXT NOT NULL,
    landing TEXT NOT NULL,
    reviewer_name TEXT,
    trip_date TEXT,
    trip_length TEXT,
    overall_rating INTEGER,
    captain_rating INTEGER,
    crew_rating INTEGER,
    fish_finding_rating INTEGER,
    galley_rating INTEGER,
    bunks_rating INTEGER,
    title TEXT,
    body TEXT,
    species_caught TEXT,
    tuna_count INTEGER,
    would_rebook INTEGER,
    verified INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    submitted_at TEXT,
    ip_hash TEXT,
    photos TEXT
);

CREATE TABLE IF NOT EXISTS boat_profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    boat        TEXT NOT NULL,
    landing     TEXT NOT NULL,
    photo_url   TEXT,
    description TEXT,
    captains    TEXT,
    year_built  INTEGER,
    length_ft   INTEGER,
    passenger_capacity INTEGER,
    fishing_areas TEXT,
    tackle_notes  TEXT,
    amenities     TEXT,
    source_url    TEXT,
    scraped_at    TEXT,
    UNIQUE(boat, landing)
);

CREATE INDEX IF NOT EXISTS idx_boat_profiles_landing ON boat_profiles(landing);

CREATE TABLE IF NOT EXISTS ocean_currents (
    date                  TEXT NOT NULL,
    location              TEXT NOT NULL,
    lat                   REAL,
    lon                   REAL,
    water_u_ms            REAL,
    water_v_ms            REAL,
    current_speed_ms      REAL,
    current_speed_knots   REAL,
    current_direction_deg REAL,
    current_is_favorable  INTEGER,
    eddy_detected         INTEGER,
    source_dataset        TEXT,
    fetched_at            TEXT,
    PRIMARY KEY (date, location)
);

CREATE INDEX IF NOT EXISTS idx_currents_date ON ocean_currents(date);

CREATE TABLE IF NOT EXISTS upwelling_obs (
    date                   TEXT NOT NULL,
    station                TEXT NOT NULL DEFAULT '33N117W',
    upwelling_index        REAL,
    upwelling_is_favorable INTEGER,
    fetched_at             TEXT,
    PRIMARY KEY (date, station)
);

CREATE INDEX IF NOT EXISTS idx_upwelling_date ON upwelling_obs(date);

CREATE TABLE IF NOT EXISTS forecast_scores (
    date       TEXT NOT NULL,
    segment    TEXT NOT NULL,
    model_a    REAL,
    model_b    REAL,
    model_c    REAL,
    ensemble   REAL,
    std_dev    REAL,
    confidence TEXT,
    n_days_b   INTEGER,
    created_at TEXT,
    PRIMARY KEY (date, segment)
);

CREATE TABLE IF NOT EXISTS boats (
    name            TEXT PRIMARY KEY,
    landing         TEXT,
    mmsi            TEXT,
    imo             TEXT,
    ais_verified    INTEGER DEFAULT 0,
    ais_last_seen   TEXT,
    vessel_length_m REAL,
    vessel_type     TEXT,
    first_seen      TEXT,
    last_seen       TEXT
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
    ("region",      "TEXT DEFAULT 'san_diego'"),
    ("full_catch",      "TEXT DEFAULT NULL"),
    ("white_sea_bass",  "INTEGER DEFAULT 0"),
    ("source",          "TEXT DEFAULT 'fish_count_page'"),
    ("is_preliminary",  "INTEGER DEFAULT 0"),
    ("written_text",    "TEXT"),
    ("needs_review",    "INTEGER DEFAULT 0"),
    ("reported_at",     "TEXT"),
]


_NEW_SCHED_COLUMNS = [
    ("trip_status",    "TEXT"),
    ("target_species", "TEXT"),
    ("whats_included", "TEXT"),
    ("meals_included", "INTEGER DEFAULT 0"),
    ("meals_value",    "INTEGER DEFAULT 0"),
    ("effective_price", "REAL"),
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
    # boat_reviews: photos stored as a JSON array of URLs
    rev_cols = {row[1] for row in conn.execute("PRAGMA table_info(boat_reviews)").fetchall()}
    if rev_cols and "photos" not in rev_cols:
        conn.execute("ALTER TABLE boat_reviews ADD COLUMN photos TEXT")
    # forecast_scores was redesigned to track per-segment A/B/C ensemble scores.
    # Drop+recreate when the old single-row-per-date schema is detected.
    fs_cols = {row[1] for row in conn.execute("PRAGMA table_info(forecast_scores)").fetchall()}
    if fs_cols and "segment" not in fs_cols:
        conn.execute("DROP TABLE forecast_scores")
        conn.execute("""CREATE TABLE forecast_scores (
            date       TEXT NOT NULL,
            segment    TEXT NOT NULL,
            model_a    REAL,
            model_b    REAL,
            model_c    REAL,
            ensemble   REAL,
            std_dev    REAL,
            confidence TEXT,
            n_days_b   INTEGER,
            created_at TEXT,
            PRIMARY KEY (date, segment)
        )""")


def repair_if_corrupt(db_path: Path) -> bool:
    """Check DB integrity; if malformed, repair in-place via iterdump and return True."""
    import logging
    log = logging.getLogger(__name__)
    try:
        c = sqlite3.connect(str(db_path), timeout=10)
        result = c.execute("PRAGMA integrity_check").fetchone()[0]
        c.close()
        if result == "ok":
            return False
    except Exception:
        pass  # treat any open failure as corrupt

    log.warning("DB integrity check failed — attempting repair")
    tmp = db_path.with_suffix(".db.repairing")
    try:
        src = sqlite3.connect(str(db_path), timeout=10)
        dst = sqlite3.connect(str(tmp), timeout=10)
        for line in src.iterdump():
            try:
                dst.execute(line)
            except Exception:
                pass
        dst.commit()
        src.close()
        dst.close()
        bak = db_path.with_suffix(".db.corrupt-bak")
        db_path.rename(bak)
        tmp.rename(db_path)
        log.warning("DB repaired successfully (corrupt copy saved to %s)", bak.name)
        return True
    except Exception as e:
        log.error("DB repair failed: %s", e)
        if tmp.exists():
            tmp.unlink()
        return False


def backup(db_path: Path) -> None:
    """Copy the DB to tracker.db.bak for use as a recovery point."""
    import shutil
    bak = db_path.with_suffix(".db.bak")
    shutil.copy2(str(db_path), str(bak))


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
    "region", "full_catch", "white_sea_bass",
    "source", "is_preliminary", "written_text", "reported_at",
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
    import logging as _logging
    _log = _logging.getLogger(__name__)
    cutoff = (_date.today() - timedelta(days=upsert_days)).isoformat()

    placeholders = ",".join("?" * len(TRIP_FIELDS))
    sql_replace = (f"INSERT OR REPLACE INTO trips ({','.join(TRIP_FIELDS)})"
                   f" VALUES ({placeholders})")
    sql_ignore  = (f"INSERT OR IGNORE  INTO trips ({','.join(TRIP_FIELDS)})"
                   f" VALUES ({placeholders})")

    # Structured-wins precedence (narrative-only filter)
    # Before inserting any narrative-origin row (source != 'fish_count_page'),
    # check if a structured row already exists for the same (date, boat,
    # landing, trip_length normalized). If so, drop the narrative — the
    # structured page is canonical. trip_length is normalized (case +
    # whitespace + '/' collapsed) so the narrative's "Full Day" can't slip
    # past a structured "FULL  DAY".
    def _norm_tl(s):
        return ' '.join((s or '').lower().split()).replace(' / ', '/')

    trips = list(trips)  # materialize so we can pre-scan and then iterate

    structured_keys: set[tuple] = set()
    # Existing structured rows in DB
    for row in conn.execute(
        "SELECT date, lower(boat), lower(landing), trip_length FROM trips "
        "WHERE source = 'fish_count_page'"
    ):
        structured_keys.add((row[0], row[1], row[2], _norm_tl(row[3])))
    # Same-batch structured rows (so a same-run narrative can't sneak in
    # alongside the just-parsed structured row for the same trip)
    for t in trips:
        if t.get("source") == "fish_count_page":
            structured_keys.add((
                t["date"], (t["boat"] or "").lower(),
                (t["landing"] or "").lower(), _norm_tl(t.get("trip_length")),
            ))

    recent_rows: list[tuple] = []
    old_rows:    list[tuple] = []
    unknown_rows: list[tuple] = []
    skipped_structured_wins = 0

    for t in trips:
        # FIX 3: narrative-only — defer to existing structured rows.
        if t.get("source") and t["source"] != "fish_count_page":
            key = (t["date"], (t["boat"] or "").lower(),
                   (t["landing"] or "").lower(), _norm_tl(t.get("trip_length")))
            if key in structured_keys:
                skipped_structured_wins += 1
                _log.info("structured-wins skip: narrative %s %s %s (%s)",
                          t["date"], t["landing"], t["boat"], t.get("trip_length"))
                continue

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

    if skipped_structured_wins:
        _log.info("structured-wins: dropped %d narrative trip(s)", skipped_structured_wins)

    # Reconciliation: when a structured (fish_count_page) row lands, purge any
    # earlier narrative rows for the same (date, boat, landing). Narrative
    # rows may have carried anglers=0 or a guessed trip_length ("Full Day"
    # default) that produces a different UNIQUE key than the incoming
    # structured row — without this purge, both would coexist as duplicates.
    # Only fires when we actually have structured rows to insert.
    structured_incoming = [t for t in trips if t.get("source") == "fish_count_page"]
    if structured_incoming:
        purge_keys = list({(t["date"], t["boat"], t["landing"]) for t in structured_incoming})
        purged = conn.executemany(
            "DELETE FROM trips WHERE date=? AND boat=? AND landing=? "
            "AND source != 'fish_count_page'",
            purge_keys,
        ).rowcount
        if purged > 0:
            _log.info("narrative-purge: dropped %d superseded narrative row(s)", purged)

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
    "meals_included", "meals_value", "effective_price",
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

    Segment is derived from trip_length_days:
      inshore  — trip_length_days <= 1.0  (day trips, local waters)
      offshore — trip_length_days  > 1.0  (overnight+ trips, distant banks)

    STEP 1 change (dep-date keying, offshore only):
      Offshore rows are keyed on the reconstructed DEPARTURE date, not the
      landing/return date, so downstream forecast joins see the conditions the
      trip was actually caught under. Inshore keeps the same date (shift is 0
      for trip_length_days <= 1.0 by construction). The shift math comes from
      the shared trip_conditions.DEP_DATE_SQL so live scoring and offline
      backtest cannot drift.

    STEP 2 change (angler-weighted aggregation, offshore only):
      Offshore species_tpa columns switch from AVG(species/anglers) (trip-
      weighted) to SUM(species)/SUM(anglers) (angler-weighted), matching the
      response variable that the offline validation used. Inshore aggregation
      is unchanged (byte-identical). This changes only the four species tpa
      columns for offshore rows; avg_tpa / top_quartile_tpa / median_tpa still
      average trophy_per_angler_per_day per trip (formula-agnostic for the
      monthly baseline in forecast._monthly_score, which reads top_quartile_tpa).

    STEP 3 change (span-averaged condition columns, offshore only):
      Offshore rows now also store span-averaged conditions across the fishing
      window (dep_date .. dep_date + span_days - 1), via
      trip_conditions.averaged_conditions. Columns added: sst_offshore_span,
      sst_nearshore_span, sst_anomaly_span, sst_gradient_span, wind_speed_span,
      swell_height_span, moon_illum_span, wind_is_upwelling_span. Inshore
      offshore-only span columns stay NULL (Model B falls back to the HC join
      for inshore, unchanged). wind_is_upwelling_span is taken as the dep_date
      value (binary flag doesn't average meaningfully).

    Uses top-quartile TPA as the primary target variable for the dual forecast model.
    Returns number of rows written.
    """
    from datetime import date as _date
    from .trip_conditions import DEP_DATE_SQL, span_days, averaged_conditions

    conn.executescript(_DAILY_SEGMENT_STATS_SCHEMA)
    _migrate_span_columns(conn)

    # since_date filters trips.date (return date) -- an incremental rebuild may
    # still touch dss rows keyed slightly earlier for offshore multi-day trips
    # whose fishing window started before since_date. That's the correct
    # semantic: the dss row for the fishing day should reflect all trips that
    # fished on it, regardless of when they returned.
    date_filter = f" AND date >= '{since_date}'" if since_date else ""

    # ── Inshore: unchanged from pre-STEP-1 -- filed date + trip-weighted AVG.
    inshore_rows = conn.execute(f"""
        SELECT date AS date, 'inshore' AS segment,
               COUNT(*) as trip_count,
               AVG(trophy_per_angler_per_day) as avg_tpa,
               SUM(trophy_count) as total_tuna,
               SUM(anglers) as total_anglers,
               AVG(bluefin   * 1.0 / NULLIF(anglers,0)) as bluefin_tpa,
               AVG(yellowfin * 1.0 / NULLIF(anglers,0)) as yellowfin_tpa,
               AVG(yellowtail* 1.0 / NULLIF(anglers,0)) as yellowtail_tpa,
               AVG(dorado    * 1.0 / NULLIF(anglers,0)) as dorado_tpa
        FROM trips
        WHERE is_half_day = 0 AND anglers >= 5 AND trip_length_days <= 1.0{date_filter}
        GROUP BY date
        HAVING COUNT(*) >= 2
    """).fetchall()

    # ── Offshore: dep-date keying + angler-weighted SUM/SUM aggregation +
    # avg_trip_length so we can compute span for span-averaged conditions.
    offshore_rows = conn.execute(f"""
        SELECT {DEP_DATE_SQL} AS date, 'offshore' AS segment,
               COUNT(*) as trip_count,
               AVG(trophy_per_angler_per_day) as avg_tpa,
               SUM(trophy_count) as total_tuna,
               SUM(anglers) as total_anglers,
               CAST(SUM(bluefin)    AS REAL) / NULLIF(SUM(anglers), 0) as bluefin_tpa,
               CAST(SUM(yellowfin)  AS REAL) / NULLIF(SUM(anglers), 0) as yellowfin_tpa,
               CAST(SUM(yellowtail) AS REAL) / NULLIF(SUM(anglers), 0) as yellowtail_tpa,
               CAST(SUM(dorado)     AS REAL) / NULLIF(SUM(anglers), 0) as dorado_tpa,
               AVG(trip_length_days) as _avg_trip_length
        FROM trips
        WHERE is_half_day = 0 AND anglers >= 5 AND trip_length_days > 1.0{date_filter}
        GROUP BY {DEP_DATE_SQL}
        HAVING COUNT(*) >= 2
    """).fetchall()

    # Compute span-averaged HC per offshore row using the shared helper.
    span_cols_numeric = (
        "sst_offshore", "sst_nearshore", "sst_anomaly", "sst_gradient",
        "wind_speed", "swell_height", "moon_illum",
    )
    hc_by_date: dict[str, dict] = {}
    for r in conn.execute("SELECT * FROM historical_conditions"):
        hc_by_date[r["date"]] = dict(r)

    span_by_key: dict[tuple[str, str], dict] = {}
    for r in offshore_rows:
        dep_str = r["date"]
        try:
            dep_d = _date.fromisoformat(dep_str)
        except ValueError:
            continue
        n = span_days(r["_avg_trip_length"] or 2.0)
        avg = averaged_conditions(hc_by_date, dep_d, n, span_cols_numeric)
        dep_hc = hc_by_date.get(dep_str) or {}
        span_by_key[(dep_str, "offshore")] = {
            "sst_offshore_span":       (avg or {}).get("sst_offshore"),
            "sst_nearshore_span":      (avg or {}).get("sst_nearshore"),
            "sst_anomaly_span":        (avg or {}).get("sst_anomaly"),
            "sst_gradient_span":       (avg or {}).get("sst_gradient"),
            "wind_speed_span":         (avg or {}).get("wind_speed"),
            "swell_height_span":       (avg or {}).get("swell_height"),
            "moon_illum_span":         (avg or {}).get("moon_illum"),
            # Binary upwelling flag: take dep-date value; averaging a 0/1 across
            # 2 days would produce 0.5 which Model B's `= ?` filter can't use.
            "wind_is_upwelling_span":  dep_hc.get("wind_is_upwelling"),
        }

    base_rows = list(inshore_rows) + list(offshore_rows)

    # Percentiles for top_quartile_tpa / median_tpa keep the pre-STEP-2 semantics
    # (trip-weighted list of trophy_per_angler_per_day). Offshore percentile
    # buckets now key by dep_date; inshore by raw date.
    key_expr = (f"CASE WHEN trip_length_days <= 1.0 THEN date "
                f"ELSE {DEP_DATE_SQL} END")
    seg_expr = "CASE WHEN trip_length_days <= 1.0 THEN 'inshore' ELSE 'offshore' END"

    from collections import defaultdict
    tpa_lists: dict[tuple, list] = defaultdict(list)
    tpa_rows = conn.execute(f"""
        SELECT {key_expr} AS date, {seg_expr} AS segment, trophy_per_angler_per_day
        FROM trips
        WHERE is_half_day = 0 AND anglers >= 5
          AND trophy_per_angler_per_day IS NOT NULL{date_filter}
    """).fetchall()
    for r in tpa_rows:
        tpa_lists[(r["date"], r["segment"])].append(r["trophy_per_angler_per_day"])

    insert_rows = []
    for r in base_rows:
        tpas  = tpa_lists.get((r["date"], r["segment"]), [])
        top_q = _percentile(tpas, 75)
        median = _percentile(tpas, 50)
        sp = span_by_key.get((r["date"], r["segment"]), {})
        insert_rows.append((
            r["date"], r["segment"], r["trip_count"], r["avg_tpa"],
            top_q, median, r["total_tuna"], r["total_anglers"],
            r["bluefin_tpa"], r["yellowfin_tpa"], r["yellowtail_tpa"], r["dorado_tpa"],
            sp.get("sst_offshore_span"), sp.get("sst_nearshore_span"),
            sp.get("sst_anomaly_span"), sp.get("sst_gradient_span"),
            sp.get("wind_speed_span"), sp.get("swell_height_span"),
            sp.get("moon_illum_span"), sp.get("wind_is_upwelling_span"),
        ))

    conn.executemany("""
        INSERT OR REPLACE INTO daily_segment_stats
        (date, segment, trip_count, avg_tpa, top_quartile_tpa, median_tpa,
         total_tuna, total_anglers, bluefin_tpa, yellowfin_tpa, yellowtail_tpa, dorado_tpa,
         sst_offshore_span, sst_nearshore_span, sst_anomaly_span, sst_gradient_span,
         wind_speed_span, swell_height_span, moon_illum_span, wind_is_upwelling_span)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?, ?,?,?,?, ?,?,?,?)
    """, insert_rows)
    return len(insert_rows)


def _migrate_span_columns(conn: sqlite3.Connection) -> None:
    """Idempotent ADD COLUMN for the STEP 3 span-averaged HC columns."""
    existing = {r[1] for r in conn.execute(
        "PRAGMA table_info(daily_segment_stats)"
    ).fetchall()}
    for col in ("sst_offshore_span", "sst_nearshore_span",
                "sst_anomaly_span", "sst_gradient_span",
                "wind_speed_span", "swell_height_span",
                "moon_illum_span", "wind_is_upwelling_span"):
        if col not in existing:
            conn.execute(f"ALTER TABLE daily_segment_stats ADD COLUMN {col} REAL")
