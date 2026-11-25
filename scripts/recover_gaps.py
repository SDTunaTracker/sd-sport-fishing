"""Recover data gaps in tracker.db from archived sources, then rebuild derived tables.

Every step is insert-only or recomputes from stored inputs, so re-running is safe.

    .venv\\Scripts\\python.exe scripts\\recover_gaps.py                     # since 2026-05-25
    .venv\\Scripts\\python.exe scripts\\recover_gaps.py --start 2026-10-01
    .venv\\Scripts\\python.exe scripts\\recover_gaps.py --db C:\\tmp\\copy.db   # dry run on a copy

Steps:
  1. trips            sandiegofishreports.com + socalfishreports.com date archives
  2. ocean_temps      NOAA ERDDAP MUR SST, per (date, location) gaps only
  3. upwelling_obs    NOAA ERDDAP erdUI456hr
     chlorophyll_obs  NOAA ERDDAP VIIRS NOAA-20 daily (nesdisVHNnoaa20chlaDaily)
  4. historical_conditions  rebuilt from 2-3 + Open-Meteo ERA5 wind + NDBC swell
  5. daily_segment_stats    recomputed from trips
  6. forecast_accuracy_log  scored for each missing day
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import db  # noqa: E402
from src.backtest import refresh_recent_conditions  # noqa: E402
from src.deep_backfill import recover_range  # noqa: E402
from src.derived import fill_accuracy_gaps  # noqa: E402
from src.main import DB_PATH, _setup_logging  # noqa: E402
from src.sst import fill_sst_gaps  # noqa: E402
from src.upwelling import fill_upwelling_gaps  # noqa: E402


def _counts(conn, start: str, end: str) -> dict:
    q = {
        "trips": "SELECT COUNT(*) FROM trips WHERE date BETWEEN ? AND ?",
        "ocean_temps": "SELECT COUNT(*) FROM ocean_temps WHERE date BETWEEN ? AND ?",
        "upwelling_obs": "SELECT COUNT(*) FROM upwelling_obs WHERE date BETWEEN ? AND ?",
        "chlorophyll_obs": "SELECT COUNT(*) FROM chlorophyll_obs WHERE obs_date BETWEEN ? AND ?",
        "historical_conditions": "SELECT COUNT(*) FROM historical_conditions WHERE date BETWEEN ? AND ?",
        "daily_segment_stats": "SELECT COUNT(DISTINCT date) FROM daily_segment_stats WHERE date BETWEEN ? AND ?",
        "forecast_accuracy_log": "SELECT COUNT(*) FROM forecast_accuracy_log WHERE date BETWEEN ? AND ?",
    }
    return {k: conn.execute(v, (start, end)).fetchone()[0] for k, v in q.items()}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 5, 25))
    p.add_argument("--end", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    p.add_argument("--db", type=Path, default=DB_PATH)
    p.add_argument("--skip-trips", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    _setup_logging(a.verbose)
    s, e = a.start.isoformat(), a.end.isoformat()
    out: dict = {"ran_at": datetime.now().isoformat(timespec="seconds"),
                 "db": str(a.db), "start": s, "end": e}

    with db.connect(a.db) as conn:
        out["before"] = _counts(conn, s, e)

        if not a.skip_trips:
            print(f"1/6 trips from date archives {s}..{e}")
            rep = recover_range(conn, a.start, a.end)
            conn.commit()
            out["trips"] = rep
            print(f"    inserted {rep['inserted']} rows on {len(rep['by_day'])} days;"
                  f" {len(rep['errors'])} fetch errors")

        print("2/6 ocean_temps gaps (MUR SST)")
        out["ocean_temps"] = fill_sst_gaps(conn, a.start, a.end)
        conn.commit()
        print(f"    {out['ocean_temps']}")

        print("3/6 upwelling_obs")
        out["upwelling_obs"] = fill_upwelling_gaps(conn, a.start - timedelta(days=7), date.today())
        conn.commit()
        print(f"    +{out['upwelling_obs']}")

        print("3b  chlorophyll_obs (VIIRS NOAA-20)")
        from src.chlorophyll import backfill_chlorophyll
        out["chlorophyll_obs"] = backfill_chlorophyll(a.db, start=a.start - timedelta(days=10))
        print(f"    {out['chlorophyll_obs']} obs")

        print("4/6 historical_conditions")
        out["historical_conditions"] = refresh_recent_conditions(conn, a.start, a.end)
        conn.commit()
        print(f"    {out['historical_conditions']}")

        print("5/6 daily_segment_stats")
        out["daily_segment_stats"] = db.update_daily_segment_stats(conn, since_date=s)
        conn.commit()
        print(f"    {out['daily_segment_stats']} rows upserted")

        print("6/6 forecast_accuracy_log")
        filled = fill_accuracy_gaps(conn, a.start, a.end)
        out["forecast_accuracy_log"] = filled
        print(f"    scored {len(filled)} days")

        out["after"] = _counts(conn, s, e)

    log_path = ROOT / "logs" / f"recovery-{date.today():%Y%m%d}.json"
    if a.db == DB_PATH:
        log_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        print(f"report: {log_path}")
    print("before:", out["before"])
    print("after: ", out["after"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
