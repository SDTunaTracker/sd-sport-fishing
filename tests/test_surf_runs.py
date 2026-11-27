"""MOP forecast-run archive (src/surf/runs.py)."""
import sqlite3
from datetime import datetime, timezone

from src.surf import runs as R
from src.surf.breaks import BREAKS


def test_run_created_parse():
    das = ('history "2026-11-27T03:28:25Z: dataset created; Net_model version 2.1. Runtime arguments: '
           '/project/f90_bin/net_model_gf -s 202611261500 -h 180";')
    assert R.run_created(das) == datetime(2026, 11, 27, 3, 28, 25, tzinfo=timezone.utc)
    assert R.run_created("nothing") is None


def test_targets_cover_buoy_sites_and_breaks_both_forcings():
    t = R._targets()
    assert len(t) == 2 * (len(R.VALIDATION_SITES) + len(BREAKS)) == 40
    assert ("BP201", "https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/model/MOP_validation/BP201_ecmwf_fc.nc") in t
    assert all(u.endswith(("_ecmwf_fc.nc", "_forecast.nc")) for _, u in t)


def test_archive_schema_is_idempotent(tmp_path):
    c = sqlite3.connect(tmp_path / "r.db")
    c.executescript(R.DDL)
    c.executescript(R.DDL)
    row = "('BP201','ecmwf_fc','2026-11-27T03:28','2026-11-28T03:00',23.5,{},14,270)"
    c.execute("INSERT INTO surf_runs VALUES " + row.format(1.2))
    c.execute("INSERT OR IGNORE INTO surf_runs VALUES " + row.format(9.0))
    assert c.execute("SELECT COUNT(*), MAX(hs) FROM surf_runs").fetchone() == (1, 1.2)


def test_snapshot_skips_failures_without_raising(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(R.C, "attrs", boom)
    c = sqlite3.connect(tmp_path / "r.db")
    assert R.snapshot(c) == {"stored": 0, "skipped": 0, "failed": 40}
