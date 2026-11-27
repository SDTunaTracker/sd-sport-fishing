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
from .scrape import SOURCES, scrape_all, reconcile_daily_counts
from .schedule import scrape_all_schedules
from .backtest import daily_accuracy_update, weekly_recalibrate
from .sst import fetch_daily_sst, fetch_hourly_sst, insert_sst
from .forecast import score_yesterday as forecast_score_yesterday
from .weather import fetch_marine_forecast
from . import completeness
from .net import is_network_error, wait_for_network

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "tracker.db"
DATA_JS_PATH = ROOT / "web" / "data.js"

# Retry schedule for landings that fail with a network error (seconds).
# Hourly runs have a 5-minute Task Scheduler limit, so they wait less.
SCRAPE_RETRY_DELAYS = (20, 60, 120)
SCRAPE_RETRY_DELAYS_HOURLY = (15, 45)
# Days re-checked against the fishreports date archives on every run.
ROLLING_DAYS = 2


def _setup_logging(verbose: bool) -> None:
    fmt = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format=fmt,
        datefmt="%H:%M:%S",
    )
    # Task Scheduler launches us hidden via run-hidden.vbs, so stderr (every
    # log line and any traceback) was discarded and crashed runs left only
    # "exit=1" in logs/full-*.log. Keep a per-day copy on disk.
    try:
        logs = ROOT / "logs"
        logs.mkdir(exist_ok=True)
        fh = logging.FileHandler(logs / f"python-{date.today():%Y%m%d}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S"))
        fh.setLevel(logging.INFO)
        logging.getLogger().addHandler(fh)
    except OSError:
        pass


def _scraped_within(conn, landing: str, hours: float) -> bool:
    row = conn.execute("SELECT MAX(started_at) FROM scrape_log WHERE landing=? AND status='ok'",
                       (landing,)).fetchone()
    return bool(row and row[0] and datetime.fromisoformat(row[0])
                > datetime.now(timezone.utc) - timedelta(hours=hours))


def _scrape_with_retry(sources, target_date, known_boats, sleep=None,
                       delays=SCRAPE_RETRY_DELAYS):
    """scrape_all, then re-try landings that failed with a network error.

    Returns the same (src, trips, page_date, err) tuples as scrape_all.
    """
    import time
    sleep = sleep or time.sleep
    results = list(scrape_all(sources, target_date=target_date, known_boats=known_boats))
    for delay in delays:
        retry = [i for i, (_, _, _, err) in enumerate(results) if err and is_network_error(err)]
        if not retry:
            break
        logging.getLogger(__name__).warning(
            "%d landing(s) hit network errors; retrying in %ds", len(retry), delay)
        sleep(delay)
        for i in retry:
            results[i] = scrape_all([results[i][0]], target_date=target_date,
                                    known_boats=known_boats)[0]
    return results


def run(target_date: date | None, export_only: bool, hourly: bool = False) -> int:
    summary_lines: list[str] = []
    core_failures: list[str] = []
    today = date.today()
    repaired = db.repair_if_corrupt(DB_PATH)
    if repaired:
        summary_lines.append("  WARNING: DB was corrupt — repaired automatically")
    with db.connect(DB_PATH) as conn:
        if not export_only:
            # Load all historically-seen boat names so _harvest_narrative_reports
            # can match multi-day boats not in today's structured fish-count table.
            known_boats_all = [
                r['boat'] for r in conn.execute('SELECT DISTINCT boat FROM trips')
            ]
            # After a wake from sleep, DNS can take 10-60s to come back.
            hosts = sorted({s.url.split("/")[2] for s in SOURCES})
            waited = wait_for_network(hosts, timeout=90 if hourly else 180)
            if waited:
                summary_lines.append(f"  Network came up after {waited:.0f}s")
            elif waited is None:
                summary_lines.append("  WARNING: DNS still failing; scraping anyway")
            # Fish-report network pages (socalfishreports: the OC/LA landings) are
            # fetched at most every 2 hours on 15-minute runs. See src/polite.py.
            from . import polite
            from .deep_backfill import ARCHIVE_SOURCE
            teck_block = completeness.active_block(conn, ARCHIVE_SOURCE)
            if teck_block:
                summary_lines.append(f"  Fish-report network SKIPPED: blocked at {teck_block}")
            run_sources = [s for s in SOURCES
                           if not (polite.is_teck(s.url) and (
                               teck_block or (hourly and _scraped_within(conn, s.name, hours=2))))]
            for src, trips, page_date, err in _scrape_with_retry(
                run_sources, target_date, known_boats_all,
                delays=SCRAPE_RETRY_DELAYS_HOURLY if hourly else SCRAPE_RETRY_DELAYS,
            ):
                started = datetime.now(timezone.utc).isoformat(timespec="seconds")
                if err:
                    db.log_scrape(
                        conn, started_at=started, finished_at=started,
                        landing=src.name, source_url=src.url,
                        target_date=target_date.isoformat() if target_date else None,
                        trips_seen=0, trips_kept=0, status="error", error=err,
                    )
                    summary_lines.append(f"  {src.name:30s} ERROR  {err}")
                    if polite.is_teck(src.url) and completeness.is_block_error(err):
                        completeness.record_block(conn, ARCHIVE_SOURCE, f"{src.url}: {err}")
                    if src.name in completeness.CORE_LANDINGS:
                        core_failures.append(src.name)
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
            # Only landings that scraped cleanly are replaced; a failed or
            # blocked landing keeps its last good snapshot instead of dropping
            # to zero (Seaforth vanished from Trip Planner this way).
            all_scheduled: list[dict] = []
            refreshed: list[str] = []
            # Don't hammer the booking sites: skip a landing for BLOCK_COOLDOWN
            # after it served a CAPTCHA / bot check to this machine, and on
            # 15-minute runs refresh each SD landing at most every 2 hours and
            # each OC/LA landing at most every 12 hours.
            from .schedule import SOURCES as SCHED_SOURCES
            sched_sources = []
            for s in SCHED_SOURCES:
                blk = completeness.active_block(conn, s.name)
                if blk:
                    summary_lines.append(f"  {s.name:30s} SKIPPED  blocked at {blk} (cooling down)")
                    continue
                last = completeness.last_schedule_refresh(conn, s.name)
                every = timedelta(hours=12 if s.region == "oc_la" else 2)
                if hourly and last and last > datetime.now(timezone.utc) - every:
                    continue
                sched_sources.append(s)
            for src, sched, err in (scrape_all_schedules(sched_sources) if sched_sources else []):
                if err:
                    kept = conn.execute(
                        "SELECT COUNT(*) FROM scheduled_trips WHERE landing = ?", (src.name,)
                    ).fetchone()[0]
                    summary_lines.append(f"  {src.name:30s} ERROR  {err}  (kept {kept} previous rows)")
                    if completeness.is_block_error(err):
                        completeness.record_block(conn, src.name, err)
                    continue
                summary_lines.append(f"  {src.name:30s} upcoming={len(sched)}")
                completeness.mark_schedule_refresh(conn, src.name)
                refreshed.append(src.name)
                all_scheduled.extend(sched)
            db.replace_scheduled_trips(conn, all_scheduled, landings=refreshed)
            total_sched = conn.execute("SELECT COUNT(*) FROM scheduled_trips").fetchone()[0]
            summary_lines.append(
                f"  scheduled_trips refreshed: {len(all_scheduled)} rows from {len(refreshed)} landings"
                f" ({total_sched} total)"
            )

            # Rolling re-check: fill any trips the live pages dropped (or that a
            # missed/asleep run never saw) from the date archives. Insert-only.
            # Full (daily) runs only, so each archive day is fetched at most twice.
            try:
                if not hourly:
                    from .deep_backfill import recover_range
                    rr = recover_range(conn, today - timedelta(days=ROLLING_DAYS),
                                       today - timedelta(days=1))
                    summary_lines.append(
                        f"  Rolling archive check ({ROLLING_DAYS}d): +{rr['inserted']} trips"
                        + (f", {len(rr['errors'])} fetch errors" if rr["errors"] else "")
                        + (f"; STOPPED: {rr['blocked']}" if rr.get("blocked") else ""))
            except Exception as e:
                summary_lines.append(f"  Rolling archive check ERROR (non-fatal): {e}")

            # reconcile_daily_counts opens its own connection; commit first or
            # it waits on our open write transaction and fails "database is locked".
            conn.commit()

            # Remove text_fallback rows that now have a real fish_count_page row.
            try:
                rec = reconcile_daily_counts(str(DB_PATH))
                summary_lines.append(
                    f"  Reconcile: {rec['matched']} text rows replaced, {rec['flagged']} flagged"
                )
            except Exception as e:
                summary_lines.append(f"  Reconcile ERROR (non-fatal): {e}")

        # Segment stats — re-aggregate a week so late/recovered trips are counted.
        try:
            since = (date.today() - timedelta(days=7)).isoformat()
            n_seg = db.update_daily_segment_stats(conn, since_date=since)
            summary_lines.append(f"  Segment stats updated: {n_seg} rows")
        except Exception as e:
            summary_lines.append(f"  Segment stats ERROR (non-fatal): {e}")

        if not hourly:
            # SST — full sweep (Nearshore buoy + 3 offshore satellite banks).
            try:
                sst_records = fetch_daily_sst(target_date or date.today(), conn)
                n_sst = insert_sst(conn, sst_records)
                summary_lines.append(f"  SST fetched: {n_sst} location-days stored")
            except Exception as e:
                summary_lines.append(f"  SST fetch ERROR (non-fatal): {e}")
            # The fetch above stores only the newest satellite day; fill any
            # (date, location) holes from the last two weeks.
            try:
                from .sst import fill_sst_gaps
                added = fill_sst_gaps(conn, today - timedelta(days=14))
                summary_lines.append(f"  SST gap fill: +{sum(added.values())} location-days")
            except Exception as e:
                summary_lines.append(f"  SST gap fill ERROR (non-fatal): {e}")
        else:
            # Hourly: pull just the NDBC Nearshore buoy so the homepage temp
            # refreshes through the day. Offshore satellites only publish
            # once/day so we don't re-hit them here.
            try:
                sst_records = fetch_hourly_sst(target_date or date.today(), conn)
                n_sst = insert_sst(conn, sst_records)
                summary_lines.append(f"  SST hourly (Nearshore): {n_sst} record(s)")
            except Exception as e:
                summary_lines.append(f"  SST hourly fetch ERROR (non-fatal): {e}")

        # Conditions inputs — both modes, each self-limiting.
        try:
            from .upwelling import fill_upwelling_gaps
            n_upw = fill_upwelling_gaps(conn)
            summary_lines.append(f"  Upwelling gap fill: +{n_upw} days")
        except Exception as e:
            summary_lines.append(f"  Upwelling fetch ERROR (non-fatal): {e}")
        try:
            last_hc = conn.execute("SELECT MAX(date) FROM historical_conditions").fetchone()[0]
            if not hourly or not last_hc or last_hc < (today - timedelta(days=1)).isoformat():
                from .backtest import refresh_recent_conditions
                hc = refresh_recent_conditions(conn, today - timedelta(days=21))
                summary_lines.append(f"  historical_conditions refreshed: {hc['rows']} days")
        except Exception as e:
            summary_lines.append(f"  historical_conditions refresh ERROR (non-fatal): {e}")
        # OC/LA SST + wind (own table). Full runs, or 15-minute runs when behind.
        try:
            from . import ocla_conditions as oc
            conn.execute(oc.DDL)
            last_oc = conn.execute(
                "SELECT MAX(date) FROM ocla_conditions WHERE sst_celsius IS NOT NULL").fetchone()[0]
            if not hourly or not last_oc or last_oc < (today - timedelta(days=4)).isoformat():
                added = oc.fill_ocla_conditions(conn, today - timedelta(days=14))
                summary_lines.append(f"  OC/LA conditions: {sum(added.values())} point-days written")
        except Exception as e:
            summary_lines.append(f"  OC/LA conditions ERROR (non-fatal): {e}")
        # Trip-day marine conditions (NWS zones + alerts, tides, NDBC/CDIP buoys).
        # Each source has its own refresh interval inside src.marine.
        try:
            from . import marine
            res = marine.refresh(conn)
            if res:
                summary_lines.append("  Marine: " + "; ".join(f"{k} {v}" for k, v in res.items()))
            # Charts buoy pins + 48 h history (web/api/v1/buoys.json).
            n_live = marine.write_buoys_json(conn)
            summary_lines.append(f"  Buoys JSON: {n_live} of {len(marine.BUOY_PINS)} with data")
        except Exception as e:
            summary_lines.append(f"  Marine conditions ERROR (non-fatal): {e}")
        conn.commit()  # chlorophyll below opens its own connection

        # Chlorophyll-a — VIIRS NOAA-20 daily (~8-day lag). Full runs always;
        # 15-minute runs only when the newest reading is over 10 days old.
        try:
            last_chl = conn.execute("SELECT MAX(obs_date) FROM chlorophyll_obs").fetchone()[0]
        except Exception:
            last_chl = None
        if not hourly or not last_chl or last_chl < (today - timedelta(days=10)).isoformat():
            try:
                from .chlorophyll import fetch_chlorophyll
                n_chl = fetch_chlorophyll(DB_PATH, target_date or date.today())
                summary_lines.append(f"  Chlorophyll fetched: {n_chl} location-days stored")
            except Exception as e:
                summary_lines.append(f"  Chlorophyll fetch ERROR (non-fatal): {e}")

        # ENSO context (NOAA CPC ONI + alert), refreshed weekly. Co-Captain context
        # only, not a forecast input (see src/enso.py).
        if not hourly:
            try:
                from .enso import update as enso_update
                summary_lines.append("  " + enso_update(DB_PATH))
            except Exception as e:
                summary_lines.append(f"  ENSO fetch ERROR (non-fatal): {e}")

        if hourly:
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

        # Score any recent day the scheduled runs missed (the call above only
        # ever scores yesterday).
        try:
            from .derived import fill_accuracy_gaps
            filled = fill_accuracy_gaps(conn, today - timedelta(days=14))
            if filled:
                summary_lines.append(f"  Forecast accuracy back-scored: {', '.join(filled)}")
        except Exception as e:
            summary_lines.append(f"  Forecast accuracy gap fill ERROR (non-fatal): {e}")

        # Reddit fetch + Claude "community insights" steps removed 2026-11-24: the
        # site no longer shows Reddit content. src/reddit.py, src/reddit_insights.py
        # and the reddit_reports / reddit_insights / weekly_summaries tables are
        # left in place (history kept), just no longer run or exported.

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

        # SF Bay Area (norcalfishreports.com): own table + own export file, so
        # nothing here can affect San Diego / OC-LA. At most every 6h, 2 pages.
        # A block stops the feed until the owner clears it (docs/sfbay/LAUNCH_PLAN.md).
        try:
            from . import scrape_norcal, export_sfbay
            if not export_only:
                seeded = scrape_norcal.load_seed(conn)   # one-time 2019+ backfill seed
                if seeded is not None:
                    summary_lines.append(f"  SF Bay backfill seed loaded: {seeded} rows")
                st = scrape_norcal.run_daily(conn)
                if st:
                    summary_lines.append(f"  SF Bay scrape: {st}")
            p_sf, n_sf = export_sfbay.write_sfbay_js(conn, DATA_JS_PATH.parent)
            summary_lines.append(f"  data-region-sfbay.js written ({n_sf} trips)")
        except Exception as e:
            summary_lines.append(f"  SF Bay ERROR (non-fatal): {type(e).__name__}: {e}")

        # Staleness alerting — log any landing dark for 4+ hours during operating hours.
        try:
            _hour = datetime.now().hour
            if 6 <= _hour <= 22:
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
                stale = conn.execute("""
                    SELECT landing, MAX(started_at) AS last
                    FROM scrape_log WHERE status='ok'
                    GROUP BY landing
                    HAVING MAX(started_at) < ?
                """, (cutoff,)).fetchall()
                if stale:
                    alert_log = ROOT / "logs" / "staleness_alerts.log"
                    alert_log.parent.mkdir(exist_ok=True)
                    with open(alert_log, "a") as f:
                        f.write(f"{datetime.utcnow().isoformat()}: Stale landings: "
                                f"{[r['landing'] for r in stale]}\n")
                    summary_lines.append(f"  STALENESS ALERT: {[r['landing'] for r in stale]}")
        except Exception as e:
            summary_lines.append(f"  Staleness check ERROR (non-fatal): {e}")

        # Completeness check + alerts. The heartbeat is written first so this
        # run counts as "the job ran".
        mode = "hourly" if hourly else "full"
        exit_code = 2 if core_failures else 0
        if not export_only:
            try:
                completeness.write_run_status(
                    conn, mode, exit_code,
                    f"core landing(s) failed: {', '.join(core_failures)}" if core_failures else "")
                probs = completeness.check(conn, run_status=completeness.load_run_status(conn),
                                           app_json=completeness.APP_JSON)
                # BloodyDecks paddies have their own DB/workflow; their health
                # check reads published state. Only present once that branch merges.
                try:
                    from scraper.paddies import health as paddies_health
                    probs += [completeness.Problem(**vars(p)) for p in paddies_health.check()]
                except ImportError:
                    pass
                except Exception as e:
                    summary_lines.append(f"  BloodyDecks health check ERROR (non-fatal): {e}")
                try:
                    from . import sfbay_health
                    probs += sfbay_health.check(conn)
                except Exception as e:
                    summary_lines.append(f"  SF Bay health check ERROR (non-fatal): {e}")
                completeness.write_report(probs)
                from .alerts import process as process_alerts
                acts = process_alerts(probs)
                summary_lines.append(
                    f"  Completeness: {len(probs)} problem(s)"
                    + (f"; alerted new={acts['new']}" if acts["new"] else "")
                    + (f"; recovered={acts['recovered']}" if acts["recovered"] else ""))
                for p in probs:
                    summary_lines.append(f"    [{p.severity}] {p.detail}")
            except Exception as e:
                summary_lines.append(f"  Completeness check ERROR (non-fatal): {e}")

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

        # Weekly boat photo update — runs on Sundays only.
        if datetime.now().weekday() == 6:
            try:
                from .scrape_boat_photos import update_all_boat_photos
                with db.connect(DB_PATH) as photo_conn:
                    update_all_boat_photos(photo_conn)
                summary_lines.append("  Boat photos: weekly update complete")
            except Exception as e:
                summary_lines.append(f"  Boat photos ERROR (non-fatal): {e}")

    print("Daily run summary:")
    for line in summary_lines:
        print(line)
    if core_failures:
        print(f"EXIT 2: core landing scrape failed after retries: {', '.join(core_failures)}")
        # CI sets SD_SOFT_EXIT=1 so a failed landing doesn't skip the commit
        # step for everything else that was scraped; alerts still fire.
        import os
        return 0 if os.environ.get("SD_SOFT_EXIT") == "1" else 2
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

    try:
        return run(args.date, args.export_only, hourly=args.hourly)
    except Exception as e:
        logging.getLogger(__name__).exception("run crashed")
        try:
            with db.connect(DB_PATH) as c:
                completeness.write_run_status(c, "hourly" if args.hourly else "full", 1,
                                              f"crashed: {type(e).__name__}: {e}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
