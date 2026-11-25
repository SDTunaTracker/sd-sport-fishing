"""Backfill SF Bay Area (NorCal) fish counts from norcalfishreports.com.

Polite by design: one page per day, 3-5 s between requests, disk cache
(.cache/norcal/), insert-only for old days, and a hard stop on any block or
notice (SourceBlocked). Re-running is safe: cached days are read from disk and
duplicate rows are ignored.

The owner must OK a run against production data. Default target is a scratch
copy, so run it against tracker.db only after that OK:

    .venv\\Scripts\\python.exe scripts\\backfill_sfbay.py --db scratch.db --start 2026-07-12 --end 2026-07-18
    .venv\\Scripts\\python.exe scripts\\backfill_sfbay.py --db tracker.db --start 2019-01-01 --i-have-owner-ok

--offline parses only what is already cached (no network).
Full history 2019-01-01 -> today is ~2,900 pages, about 3.2 h at 4 s/page.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import scrape_norcal as S  # noqa: E402
from src.dates import pacific_today  # noqa: E402

log = logging.getLogger("backfill_sfbay")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--start", type=date.fromisoformat, default=date(2019, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=None)
    p.add_argument("--dates", nargs="*", type=date.fromisoformat, default=None,
                   help="explicit list of days instead of a range")
    p.add_argument("--offline", action="store_true", help="cache only, no network")
    p.add_argument("--skip-logged", action="store_true",
                   help="skip days already in norcal_fetch_log with status 200 (resume)")
    p.add_argument("--i-have-owner-ok", action="store_true",
                   help="required to write to tracker.db")
    p.add_argument("--max-requests", type=int, default=4000)
    p.add_argument("--merge-from", type=Path, default=None,
                   help="copy norcal_trips/norcal_fetch_log rows from this DB into --db "
                        "(insert-only) and exit; no network")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.db.resolve().name == "tracker.db" and not args.i_have_owner_ok:
        log.error("Refusing to write to tracker.db without --i-have-owner-ok "
                  "(the owner must approve a production backfill).")
        return 2

    if args.merge_from:
        return merge(args.merge_from, args.db)

    days = args.dates or []
    if not days:
        end = args.end or pacific_today()
        d = args.start
        while d <= end:
            days.append(d)
            d += timedelta(days=1)

    conn = sqlite3.connect(args.db, timeout=60)
    S.ensure_schema(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS unknown_species (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                 " species_name TEXT NOT NULL, count INTEGER NOT NULL, date TEXT NOT NULL,"
                 " boat TEXT NOT NULL, landing TEXT NOT NULL)")
    if args.skip_logged:
        done = {r[0] for r in conn.execute("SELECT date FROM norcal_fetch_log WHERE status = 200")}
        days = [d for d in days if d.isoformat() not in done]
    fetcher = S.Fetcher(offline=args.offline)
    totals = {"days": 0, "rows": 0, "inserted": 0, "no_count_days": 0, "cached": 0, "errors": 0}
    try:
        for d in days:
            if fetcher.requests_made >= args.max_requests:
                log.warning("max requests reached (%d); stopping", args.max_requests)
                break
            st = S.scrape_days(conn, [d], fetcher=fetcher)
            for k in totals:
                totals[k] += st.get(k, 0)
            if totals["days"] % 50 == 0 and st["days"]:
                log.info("progress %s: %s (requests=%d)", d, totals, fetcher.requests_made)
    except S.SourceBlocked as e:
        log.error("SOURCE BLOCKED: %s. Stopping. Tell the owner; do not retry or work around it.", e)
        conn.commit()
        conn.close()
        return 3
    conn.commit()
    conn.close()
    log.info("done: %s, network requests=%d", totals, fetcher.requests_made)
    return 0


def merge(src: Path, dst: Path) -> int:
    """Insert-only copy of SF Bay rows from a side DB (where the long backfill
    ran) into dst. Takes seconds, so it fits between hourly CI commits of
    tracker.db. Existing rows in dst always win."""
    conn = sqlite3.connect(dst, timeout=60)
    S.ensure_schema(conn)
    conn.execute("ATTACH DATABASE ? AS src", (str(src),))
    cols = ",".join(S._FIELDS)
    before = conn.execute("SELECT COUNT(*) FROM norcal_trips").fetchone()[0]
    conn.execute(f"INSERT OR IGNORE INTO norcal_trips ({cols}) SELECT {cols} FROM src.norcal_trips")
    conn.execute("INSERT OR IGNORE INTO norcal_fetch_log SELECT * FROM src.norcal_fetch_log"
                 " WHERE COALESCE(error,'') <> 'blocked'")
    after = conn.execute("SELECT COUNT(*) FROM norcal_trips").fetchone()[0]
    conn.commit()
    conn.execute("DETACH DATABASE src")
    conn.close()
    log.info("merged %d new SF Bay rows from %s into %s", after - before, src, dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
