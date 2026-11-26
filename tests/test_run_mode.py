"""src/run_mode.py decides when Daily Scrape runs its full pipeline. The
offshore SST grid went 6 days stale (dated 2026-11-20 on 2026-11-26) because
the old check only looked at the fresh 60-Mile Bank buoy row."""
import json
import sqlite3
from datetime import date, datetime, timezone

from src import run_mode as RM

TODAY = date(2026, 11, 26)
NOW = datetime(2026, 11, 26, 13, 0, tzinfo=timezone.utc)


def _db(tmp_path, latest="2026-11-25"):
    p = tmp_path / "tracker.db"
    c = sqlite3.connect(p)
    c.execute("DROP TABLE IF EXISTS ocean_temps")
    c.execute("CREATE TABLE ocean_temps (date TEXT, location TEXT)")
    if latest:
        c.execute("INSERT INTO ocean_temps VALUES (?, '60-Mile Bank')", (latest,))
    c.commit(); c.close()
    return p


def _json(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


PLACEHOLDER = {"source": None, "refTime": None, "data": None}


def _run(tmp_path, db_latest="2026-11-25", grid_date="2026-11-23", currents=PLACEHOLDER):
    return RM.stale_reasons(_db(tmp_path, db_latest),
                            _json(tmp_path, "sst_grid.json", {"date": grid_date}) if grid_date else tmp_path / "none.json",
                            _json(tmp_path, "currents_grid.json", currents),
                            today=TODAY, now=NOW)


def test_fresh(tmp_path):
    assert _run(tmp_path) == []


def test_stale_grid_with_fresh_buoy_row(tmp_path):
    # The 2026-11-26 case: buoy row fresh, grid dated 2026-11-20.
    r = _run(tmp_path, grid_date="2026-11-20")
    assert r and "sst_grid.json" in r[0]


def test_missing_grid(tmp_path):
    assert any("sst_grid.json missing" in x for x in _run(tmp_path, grid_date=None))


def test_stale_buoy_row(tmp_path):
    assert any("60-Mile Bank" in x for x in _run(tmp_path, db_latest="2026-11-10"))


def test_currents_placeholder_ignored_real_grid_checked(tmp_path):
    assert _run(tmp_path, currents=PLACEHOLDER) == []
    assert _run(tmp_path, currents={"refTime": "2026-11-26T00:00:00Z"}) == []
    r = _run(tmp_path, currents={"refTime": "2026-11-22T00:00:00Z"})
    assert r and "currents_grid.json" in r[0]
