"""Tuna-only count and rate: what best-boat rankings use (owner decision 2026-11-26)."""
import sqlite3

from src import db
from src.parse import TROPHY_SPECIES, TUNA_SPECIES, trophy_metrics, tuna_metrics


def test_tuna_species_match_the_app():
    assert TUNA_SPECIES == ("Bluefin", "Yellowfin", "Bigeye", "Albacore")
    assert "Yellowtail" in TROPHY_SPECIES and "Yellowtail" not in TUNA_SPECIES


def test_tuna_metrics():
    sp = {"Bluefin": 4, "Yellowfin": 6, "Yellowtail": 50, "Dorado": 10, "Bigeye": 1, "Albacore": 9}
    m = tuna_metrics(sp, anglers=20, trip_days=2.5)
    assert m.tuna_count == 20
    assert m.tuna_per_angler == 1.0
    assert m.tuna_per_angler_per_day == 0.5          # same floor-day divisor as trophy
    assert trophy_metrics(sp, 20, 2.5).trophy_count == 70
    assert tuna_metrics(sp, 0, 1).tuna_per_angler_per_day == 0.0
    assert tuna_metrics({}, 10, 0.75).tuna_count == 0


def test_db_adds_generated_tuna_columns(tmp_path):
    path = tmp_path / "t.db"
    with db.connect(path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_xinfo(trips)")}
        assert {"tuna_count", "tuna_per_angler_per_day"} <= cols
        conn.execute("""INSERT INTO trips (date, boat, landing, trip_length, trip_length_days,
            anglers, bluefin, yellowfin, yellowtail, bigeye, albacore, scraped_at, source_url)
            VALUES ('2026-11-01','A','H&M Landing','1.5 Day',1.5,10,2,3,40,1,4,'x','x')""")
        r = conn.execute("SELECT tuna_count, tuna_per_angler_per_day FROM trips").fetchone()
        assert tuple(r) == (10, 1.0)
    # Reconnecting (migration runs again) is a no-op.
    with db.connect(path) as conn:
        assert conn.execute("SELECT tuna_count FROM trips").fetchone()[0] == 10


def test_migration_upgrades_an_old_db(tmp_path):
    path = tmp_path / "old.db"
    with db.connect(path):
        pass
    # Simulate a DB from before the tuna columns: rebuild trips without them.
    c = sqlite3.connect(path)
    c.execute("ALTER TABLE trips DROP COLUMN tuna_per_angler_per_day")
    c.execute("ALTER TABLE trips DROP COLUMN tuna_count")
    c.commit()
    c.close()
    with db.connect(path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_xinfo(trips)")}
        assert {"tuna_count", "tuna_per_angler_per_day"} <= cols
