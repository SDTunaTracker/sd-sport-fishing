"""Decide whether the Daily Scrape workflow needs its full pipeline.

GitHub's hourly cron fires only a few times a day, and rarely in the 14:00 UTC
"full" slot, so the workflow also runs full mode whenever offshore data is
stale. Stale means any of:

  * no 60-Mile Bank row in ocean_temps within SST_MAX_AGE_DAYS (the old check);
  * web/sst_grid.json missing, unreadable, or its "date" older than
    SST_MAX_AGE_DAYS (the Charts offshore SST layer, written by the workflow's
    "Fetch SST grid" step). The buoy row can be fresh while this grid is not,
    which left the grid 6 days old on 2026-11-26;
  * web/currents_grid.json holding real data (refTime set) older than
    CURRENTS_MAX_AGE_HOURS. The placeholder written before Copernicus
    credentials exist (refTime null) is ignored: full mode can't fill it.

Usage (prints 1 for stale, 0 for fresh):
    python -m src.run_mode
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "tracker.db"
SST_GRID = ROOT / "web" / "sst_grid.json"
CURRENTS_GRID = ROOT / "web" / "currents_grid.json"

SST_MAX_AGE_DAYS = 5          # MUR on CoastWatch ERDDAP lags 2–4 days
CURRENTS_MAX_AGE_HOURS = 48


def _iso_date(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def stale_reasons(db_path: Path = DB_PATH, sst_grid: Path = SST_GRID,
                  currents_grid: Path = CURRENTS_GRID,
                  today: date | None = None, now: datetime | None = None) -> list[str]:
    """Reasons the offshore data is stale; empty list means fresh."""
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    cutoff = today - timedelta(days=SST_MAX_AGE_DAYS)
    reasons: list[str] = []

    latest = None
    try:
        c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        r = c.execute("SELECT MAX(date) FROM ocean_temps WHERE location='60-Mile Bank'").fetchone()
        latest = _iso_date(r[0]) if r else None
        c.close()
    except Exception:
        pass
    if not latest or latest < cutoff:
        reasons.append(f"ocean_temps 60-Mile Bank {latest or 'missing'}")

    grid_date = None
    try:
        grid_date = _iso_date(json.loads(sst_grid.read_text(encoding="utf-8")).get("date"))
    except Exception:
        pass
    if not grid_date or grid_date < cutoff:
        reasons.append(f"sst_grid.json {grid_date or 'missing'}")

    try:
        cur = json.loads(currents_grid.read_text(encoding="utf-8"))
    except Exception:
        cur = None
    ref = cur.get("refTime") if isinstance(cur, dict) else None
    if ref:
        try:
            ref_dt = datetime.fromisoformat(str(ref).replace("Z", "+00:00"))
            if ref_dt.tzinfo is None:
                ref_dt = ref_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            ref_dt = None
        if ref_dt is None or now - ref_dt > timedelta(hours=CURRENTS_MAX_AGE_HOURS):
            reasons.append(f"currents_grid.json {ref}")
    return reasons


def main() -> None:
    import sys
    reasons = stale_reasons()
    for r in reasons:
        print(f"stale: {r}", file=sys.stderr)
    print(1 if reasons else 0)


if __name__ == "__main__":
    main()
