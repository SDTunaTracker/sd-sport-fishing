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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import db
from .export import export
from .scrape import SOURCES, scrape_all
from .schedule import scrape_all_schedules
from .backtest import daily_accuracy_update, weekly_recalibrate
from .sst import fetch_daily_sst, insert_sst
from .forecast import score_yesterday as forecast_score_yesterday
from .weather import fetch_marine_forecast

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "tracker.db"
DATA_JS_PATH = ROOT / "web" / "data.js"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def run(target_date: date | None, export_only: bool, hourly: bool = False) -> int:
    summary_lines: list[str] = []
    repaired = db.repair_if_corrupt(DB_PATH)
    if repaired:
        summary_lines.append("  WARNING: DB was corrupt — repaired automatically")
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
                kept = db.insert_trips(conn, trips, upsert=True)
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

        # Segment stats — keep daily_segment_stats current after each scrape.
        try:
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            n_seg = db.update_daily_segment_stats(conn, since_date=yesterday)
            summary_lines.append(f"  Segment stats updated: {n_seg} rows")
        except Exception as e:
            summary_lines.append(f"  Segment stats ERROR (non-fatal): {e}")

        if not hourly:
            # SST — skip on hourly runs to avoid hammering NOAA 24×/day.
            try:
                sst_records = fetch_daily_sst(target_date or date.today(), conn)
                n_sst = insert_sst(conn, sst_records)
                summary_lines.append(f"  SST fetched: {n_sst} location-days stored")
            except Exception as e:
                summary_lines.append(f"  SST fetch ERROR (non-fatal): {e}")

            # Upwelling index (NOAA ERDDAP erdUI456hr, 33N117W, ~30-day lag in practice)
            try:
                from .upwelling import fetch_upwelling_range, insert_upwelling
                upw_lag_end = date.today() - timedelta(days=30)
                upw_start   = upw_lag_end - timedelta(days=14)
                upw_records = fetch_upwelling_range(upw_start, upw_lag_end)
                n_upw       = insert_upwelling(conn, upw_records)
                summary_lines.append(f"  Upwelling fetched: {n_upw} days stored")
            except Exception as e:
                summary_lines.append(f"  Upwelling fetch ERROR (non-fatal): {e}")

            # Chlorophyll-a — MODIS Aqua 8-day composite; failure is non-fatal.
            try:
                from .chlorophyll import fetch_chlorophyll
                n_chl = fetch_chlorophyll(DB_PATH, target_date or date.today())
                summary_lines.append(f"  Chlorophyll fetched: {n_chl} location-days stored")
            except Exception as e:
                summary_lines.append(f"  Chlorophyll fetch ERROR (non-fatal): {e}")

            # Daily accuracy check — score yesterday's forecast vs actual catch.
            try:
                acc = daily_accuracy_update(conn)
                if acc:
                    summary_lines.append(
                        f"  Accuracy {acc['date']}: predicted={acc['predicted']:.1f}"
                        f"  actual={acc['actual_rating']:.1f}  error={acc['error']:.2f}"
                        f"  ({acc['n_boats']} boats)"
                    )
            except Exception as e:
                summary_lines.append(f"  Accuracy update ERROR (non-fatal): {e}")

            # Forecast accuracy log (new 6-factor scoring)
            try:
                fa = forecast_score_yesterday(conn)
                if fa:
                    summary_lines.append(
                        f"  Forecast accuracy {fa['date']}: predicted={fa['predicted']:.1f}"
                        f"  actual={fa['actual_rating']:.1f}  error={fa['error']:.2f}"
                    )
            except Exception as e:
                summary_lines.append(f"  Forecast scoring ERROR (non-fatal): {e}")

        if not hourly:
            # Reddit fishing reports — once per day, rate-limited inside fetch.
            try:
                from .reddit import fetch_reddit_reports
                n_reddit = fetch_reddit_reports(conn)
                summary_lines.append(f"  Reddit: {n_reddit} posts fetched/updated")
            except Exception as e:
                summary_lines.append(f"  Reddit fetch ERROR (non-fatal): {e}")

            # Reddit intelligence — Claude API analysis of fetched posts.
            try:
                from .reddit_insights import process_unanalyzed_posts, generate_weekly_summary
                n_insights = process_unanalyzed_posts(conn)
                summary_lines.append(f"  Reddit insights: {n_insights} posts analyzed")
                # Weekly summary on Mondays
                if datetime.now().weekday() == 0:
                    ws_start = (date.today() - timedelta(days=7)).isoformat()
                    ws_end   = (date.today() - timedelta(days=1)).isoformat()
                    ws = generate_weekly_summary(conn, ws_start, ws_end)
                    if ws:
                        summary_lines.append(
                            f"  Weekly summary generated: {ws['report_count']} reports"
                        )
            except Exception as e:
                summary_lines.append(f"  Reddit insights ERROR (non-fatal): {e}")

        # Weather + swell forecast (for 7-day strip in data.js)
        weather_fc: list = []
        if not hourly:
            try:
                target_dt = target_date or date.today()
                weather_fc = fetch_marine_forecast(target_dt)
                summary_lines.append(f"  Weather forecast: {len(weather_fc)} days fetched")
            except Exception as e:
                summary_lines.append(f"  Weather fetch ERROR (non-fatal): {e}")

        n = export(conn, DATA_JS_PATH, weather_forecast=weather_fc)
        summary_lines.append(f"  data.js written: {DATA_JS_PATH}  ({n} trips total)")

    # Rolling backup — written after a successful export so we always have a
    # clean recovery point that's at most one run old.
    try:
        db.backup(DB_PATH)
    except Exception as e:
        summary_lines.append(f"  Backup ERROR (non-fatal): {e}")

    if not hourly:
        # Weekly recalibration — runs after the main connection closes to avoid locking.
        # Skips itself if a backtest ran < 7 days ago; otherwise re-optimizes weights
        # on a rolling 3-year window and saves updated backtest_weights.json.
        try:
            recap = weekly_recalibrate(DB_PATH)
            if recap:
                m = recap.get("metrics", {})
                summary_lines.append(
                    f"  Recalibration complete: MAE={m.get('mae')}  "
                    f"direction={m.get('direction_accuracy')}%  weights updated"
                )
        except Exception as e:
            summary_lines.append(f"  Recalibration ERROR (non-fatal): {e}")

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
    p.add_argument("--hourly", action="store_true",
                   help="Light run: scrape trips + export only. Skips SST/weather/chlorophyll/backtest.")
    p.add_argument("--backfill", action="store_true",
                   help="Scrape per-boat history pages to backfill all available historical data.")
    p.add_argument("--backfill-sst", action="store_true",
                   help="Fetch 90 days of SST history from NOAA ERDDAP.")
    p.add_argument("--backfill-chl", action="store_true",
                   help="Backfill chlorophyll-a from NASA ERDDAP (2015-present).")
    p.add_argument("--backfill-upwelling", action="store_true",
                   help="Backfill NOAA upwelling index from ERDDAP (2015-present).")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    _setup_logging(args.verbose)

    if args.backfill:
        from .backfill import run_backfill
        run_backfill(DB_PATH)
        return 0

    if args.backfill_sst:
        from .sst import backfill_sst
        backfill_sst(DB_PATH)
        return 0

    if args.backfill_chl:
        from .chlorophyll import backfill_chlorophyll
        backfill_chlorophyll(DB_PATH)
        return 0

    if args.backfill_upwelling:
        from .upwelling import backfill_upwelling
        backfill_upwelling(DB_PATH)
        return 0

    return run(args.date, args.export_only, hourly=args.hourly)


if __name__ == "__main__":
    sys.exit(main())
