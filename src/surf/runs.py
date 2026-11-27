"""Archive every MOP forecast run, so skill can be scored by lead time.

CDIP keeps no archive of past forecast runs: each `_ecmwf_fc` / `_forecast`
file is overwritten when it rebuilds, and the MOP_validation archive is one
spliced series with no lead time. So each scrape we snapshot the current
runs at the validation buoy sites (BP{site}) and at every break's MOP point,
keyed by the run's creation time. After a few weeks this gives bias / RMSE /
skill by lead-time bucket against the buoys (scored by the surf verification
harness, src/surf/verify.py on the surf-forecast branch).

Table surf_runs (tracker.db):
  point, kind, run_created, valid_ts, lead_h, hs, tp, dp

    python -m src.surf.runs              # snapshot now (skips runs already stored)
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import cdip as C
from .breaks import BREAKS

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "tracker.db"
KINDS = ("ecmwf_fc", "forecast")
VALIDATION_SITES = ("264", "045", "262", "153", "100", "201", "220", "191")
KEEP_DAYS = 400
MAX_LEAD_H = 7 * 24

DDL = """
CREATE TABLE IF NOT EXISTS surf_runs (
    point TEXT NOT NULL, kind TEXT NOT NULL, run_created TEXT NOT NULL,
    valid_ts TEXT NOT NULL, lead_h REAL NOT NULL, hs REAL, tp REAL, dp REAL,
    PRIMARY KEY (point, kind, run_created, valid_ts)
);
CREATE INDEX IF NOT EXISTS idx_surf_runs_valid ON surf_runs(point, kind, valid_ts);
"""


def run_created(das: str) -> datetime | None:
    m = re.search(r'history "(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ): dataset created', das)
    if not m:
        m = re.search(r'date_created "(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)"', das)
    return datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if m else None


def _targets() -> list[tuple[str, str]]:
    out = [(f"BP{s}", C.validation_url(s, k)) for s in VALIDATION_SITES for k in KINDS]
    out += [(b["mop"], C.mop_url(b["mop"], k)) for b in BREAKS for k in KINDS]
    return out


def snapshot(conn: sqlite3.Connection) -> dict[str, int]:
    """Store any forecast run not yet stored. Never raises per target."""
    conn.executescript(DDL)
    stored, skipped, failed = 0, 0, 0
    for point, url in _targets():
        kind = "ecmwf_fc" if url.endswith("_ecmwf_fc.nc") else "forecast"
        try:
            created = run_created(C.attrs(url, max_age_s=1800))
            if created is None:
                failed += 1
                continue
            cid = created.isoformat(timespec="minutes")
            if conn.execute("SELECT 1 FROM surf_runs WHERE point=? AND kind=? AND run_created=? LIMIT 1",
                            (point, kind, cid)).fetchone():
                skipped += 1
                continue
            d = C.series(url, ["waveHs", "waveTp", "waveDp", "waveFlagPrimary"],
                         since=created - timedelta(hours=3), until=created + timedelta(hours=MAX_LEAD_H),
                         max_age_s=1800)
            rows = []
            for t, hs, tp, dp, fl in zip(d["waveTime"], d["waveHs"], d["waveTp"], d["waveDp"],
                                         d["waveFlagPrimary"]):
                if fl != 1:
                    continue
                vt = datetime.fromtimestamp(t, timezone.utc)
                rows.append((point, kind, cid, vt.isoformat(timespec="minutes"),
                             round((vt - created).total_seconds() / 3600, 2), hs, tp, dp))
            conn.executemany("INSERT OR IGNORE INTO surf_runs VALUES (?,?,?,?,?,?,?,?)", rows)
            stored += 1
        except Exception:  # noqa: BLE001 — one point down shouldn't stop the rest
            failed += 1
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat(timespec="minutes")
    conn.execute("DELETE FROM surf_runs WHERE run_created < ?", (cutoff,))
    conn.commit()
    return {"stored": stored, "skipped": skipped, "failed": failed}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB)
    a = ap.parse_args(argv)
    conn = sqlite3.connect(a.db)
    print(snapshot(conn))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
