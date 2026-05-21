"""Entry point: scrape all landings -> SQLite -> export web/data.js.

Usage:
    python -m src.main                  # scrape latest date available per landing
    python -m src.main --date 2026-05-19  # scrape a specific date (skips other dates)
    python -m src.main --export-only    # skip scraping, just regenerate data.js
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import db
from .export import export
from .scrape import SOURCES, scrape_all
from .schedule import scrape_all_schedules

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "tracker.db"
DATA_JS_PATH = ROOT / "web" / "data.js"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def run(target_date: date | None, export_only: bool) -> int:
    summary_lines: list[str] = []
    with db.connect(DB_PATH) as conn:
        if not export_only:
            for src, trips, page_date, err in scrape_all(SOURCES, target_date=target_date):
                started = datetime.now(timezone.utc).isoformat(timespec="seconds")
                if err:
                    db.log_scrape(
                        conn, started_at=started, finished_at=started,
                        landing=src.name, source_url=src.url,
                        target_date=target_date.isoformat() if target_date else None,
                        trips_seen=0, trips_kept=0, status="error", error=err,
                    )
                    summary_lines.append(f"  {src.name:30s} ERROR  {err}")
                    continue
                kept = db.insert_trips(conn, trips)
                db.log_scrape(
                    conn, started_at=started, finished_at=started,
                    landing=src.name, source_url=src.url,
                    target_date=(target_date or page_date).isoformat() if (target_date or page_date) else None,
                    trips_seen=len(trips), trips_kept=kept, status="ok", error=None,
                )
                summary_lines.append(
                    f"  {src.name:30s} page_date={page_date}  parsed={len(trips):3d}  inserted={kept:3d}"
                )

            # Schedules: forward-looking, snapshot semantics (delete + reinsert).
            summary_lines.append("Schedule scrape:")
            all_scheduled: list[dict] = []
            for src, sched, err in scrape_all_schedules():
                if err:
                    summary_lines.append(f"  {src.name:30s} ERROR  {err}")
                    continue
                summary_lines.append(f"  {src.name:30s} upcoming={len(sched)}")
                all_scheduled.extend(sched)
            db.replace_scheduled_trips(conn, all_scheduled)
            summary_lines.append(f"  scheduled_trips refreshed: {len(all_scheduled)} rows")

        n = export(conn, DATA_JS_PATH)
        summary_lines.append(f"  data.js written: {DATA_JS_PATH}  ({n} trips total)")

    print("Daily run summary:")
    for line in summary_lines:
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", type=date.fromisoformat,
                   help="Target ISO date (YYYY-MM-DD). Default: keep whatever the page reports.")
    p.add_argument("--export-only", action="store_true",
                   help="Skip scraping, only regenerate web/data.js.")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    _setup_logging(args.verbose)
    return run(args.date, args.export_only)


if __name__ == "__main__":
    sys.exit(main())
